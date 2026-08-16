#!/usr/bin/env python3
"""Editorial quality gate: judge each brief, rewrite the weak ones, repeat.

Usage: review_briefs.py <briefs.json> <out.json>

A brief that is grammatical but generic ("AI is changing L&D", "organizations
should measure impact") passes every mechanical check and is still worthless to
read. This step puts a second model in the reviewer's chair with the source
text in hand, and sends anything that fails back to be rewritten.

The loop:
  1. Review all articles against explicit criteria. Each gets pass or revise,
     plus the specific problem and the specific fix.
  2. Rewrite only the articles that failed, with the critique and the source
     text supplied.
  3. Re-review the rewrites. Stop when everything passes or after MAX_ROUNDS.

Deliberate choices:
  * The reviewer sees the source text, so "not supported by the article" is a
    verdict it can actually reach. A reviewer without the source can only judge
    style, which is the failure mode this step exists to catch.
  * Articles are addressed by index into the article list, never by title, so a
    rewrite can never be attached to the wrong article.
  * Non-fatal. A failed review keeps the original briefs and records a warning.
"""
import json
import os
import sys

MODEL = "claude-opus-5"
MAX_TOKENS = 32000
MAX_ROUNDS = 2
SOURCE_CHARS = 3500
# Below this share passing, the digest is weak enough to be worth shouting about
# on the run summary even after the rewrite rounds.
ACCEPTABLE_PASS_RATE = 0.7

REVIEW_SYSTEM = """\
You are a demanding editor reviewing a weekly L&D digest before it is sent to \
one reader: a senior learning leader with 17 years in the field who runs an \
L&D unit at a large bank. He is not a beginner. He does not need to be told \
that AI is changing learning, that measurement matters, or that learners are \
busy. His time is the scarce resource.

You are given, per article, the source text and the drafted brief. Judge the \
brief only. Be strict: your job is to catch briefs that read fine and say \
nothing.

Mark an article "revise" if ANY of these is true:
- The summary could have been written from the headline alone, without reading \
the article.
- Any insight is a generic truism, a restatement of the summary, or advice this \
reader already knows. "Organizations should align learning to business goals" \
is a truism. "Teams that defined success measures before building cut rework by \
half" is an insight.
- Any claim, number, or finding is not supported by the source text. This is \
the most serious failure: flag it even if everything else is strong.
- The "why it matters" says something that would be equally true for any L&D \
professional, rather than connecting to this reader's specific situation \
(AI-native content production, performance over course delivery, learning \
analytics, leading a team, teaching other L&D practitioners).
- The Hebrew reads as literal translated English rather than natural Hebrew.
- There are fewer than 3 insights, or the text contains em-dashes.

Otherwise mark it "pass".

For each article, state the problem concretely and say exactly what a rewrite \
should do differently. Do not write the replacement text yourself. Do not be \
generous: a digest of ten adequate briefs is worse than one with six sharp \
ones and four flagged for rework."""

REWRITE_SYSTEM = """\
You are rewriting rejected entries in a weekly L&D digest, for a senior \
learning leader with 17 years in the field who runs an L&D unit at a large bank \
and is building AI-native ways of producing learning. He favours performance \
consulting over course delivery, and cares about learning analytics and skills \
data.

You are given the source text, the rejected draft, and an editor's critique of \
exactly what is wrong. Fix what the critique identifies. Keep what was working.

Rules:
- Ground every claim in the supplied source text. If the source does not support \
a point, cut the point. Never invent a number, finding, or claim.
- Insights must be specific and standalone: something the reader could quote or \
act on. Not a restatement of the summary, not a truism.
- "Why it matters" must connect to this reader's specific situation, not to L&D \
professionals in general.
- Hebrew must read as natural Hebrew, not translated English. Keep product, \
company, and methodology names in Latin script.
- Exactly 3 insights. No em-dashes anywhere: use colons, commas, or parentheses.
- If the source text genuinely does not support a worthwhile brief, write the \
most honest short version you can rather than padding it."""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["pass", "revise"]},
                    "problem": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["index", "verdict", "problem", "fix"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reviews"],
    "additionalProperties": False,
}

_STR = {"type": "string"}
REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "summary_he": _STR,
                    "summary_en": _STR,
                    "insights_he": {"type": "array", "items": _STR},
                    "insights_en": {"type": "array", "items": _STR},
                    "matters_he": _STR,
                    "matters_en": _STR,
                },
                "required": [
                    "index", "summary_he", "summary_en",
                    "insights_he", "insights_en", "matters_he", "matters_en",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["articles"],
    "additionalProperties": False,
}


def _text(message):
    for block in message.content:
        if block.type == "text":
            return block.text
    return ""


def _source_for(article, by_url):
    """The article body the brief was written from, so the reviewer can check
    claims rather than only judging style."""
    item = by_url.get(article.get("url"))
    if not item:
        return "(source text unavailable)"
    return (item.get("full_text") or item.get("summary") or "(source text unavailable)")[:SOURCE_CHARS]


def _render(article, idx, by_url):
    return f"""### Article {idx}
SOURCE TEXT:
{_source_for(article, by_url)}

DRAFTED BRIEF:
headline (he): {article.get('headline_he', '')}
summary (he): {article.get('summary_he', '')}
summary (en): {article.get('summary_en', '')}
insights (he): {json.dumps(article.get('insights_he', []), ensure_ascii=False)}
insights (en): {json.dumps(article.get('insights_en', []), ensure_ascii=False)}
why it matters (he): {article.get('matters_he', '')}
why it matters (en): {article.get('matters_en', '')}
"""


def review(client, articles, indices, by_url):
    body = "\n".join(_render(articles[i], i, by_url) for i in indices)
    # Streamed for the same reason as generate_briefs: the SDK rejects a
    # non-streaming request this large before it ever leaves the process.
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=REVIEW_SYSTEM,
        messages=[{"role": "user", "content":
                   f"Review these {len(indices)} digest entries.\n\n{body}"}],
        output_config={"format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
    ) as stream:
        msg = stream.get_final_message()
    out = {}
    for r in json.loads(_text(msg)).get("reviews", []):
        i = r.get("index")
        if isinstance(i, int) and i in indices:
            out[i] = r
    return out


def rewrite(client, articles, reviews, by_url):
    parts = []
    for i, r in sorted(reviews.items()):
        parts.append(
            f"{_render(articles[i], i, by_url)}\n"
            f"EDITOR'S PROBLEM: {r['problem']}\n"
            f"EDITOR'S REQUIRED FIX: {r['fix']}\n"
        )
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=REWRITE_SYSTEM,
        messages=[{"role": "user", "content":
                   "Rewrite these rejected entries.\n\n" + "\n".join(parts)}],
        output_config={"format": {"type": "json_schema", "schema": REWRITE_SCHEMA}},
    ) as stream:
        msg = stream.get_final_message()
    applied = []
    for entry in json.loads(_text(msg)).get("articles", []):
        i = entry.get("index")
        if not isinstance(i, int) or i not in reviews:
            continue          # rewrite aimed at an article that wasn't rejected
        a = articles[i]
        a["summary_he"] = entry["summary_he"]
        a["summary_en"] = entry["summary_en"]
        a["insights_he"] = [s for s in entry.get("insights_he") or [] if s][:3]
        a["insights_en"] = [s for s in entry.get("insights_en") or [] if s][:3]
        a["matters_he"] = entry["matters_he"]
        a["matters_en"] = entry["matters_en"]
        a["revised"] = True
        applied.append(i)
    return applied


def run(infile, outfile):
    data = json.load(open(infile, encoding="utf-8"))
    articles = data.get("articles", [])
    warnings = list(data.get("warnings") or [])
    by_url = {i.get("url"): i for i in data.get("items", [])}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not articles:
        if not api_key:
            warnings.append("editorial review skipped (no ANTHROPIC_API_KEY)")
        data["warnings"] = warnings
        json.dump(data, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        pending = list(range(len(articles)))
        history = []
        for rnd in range(1, MAX_ROUNDS + 1):
            reviews = review(client, articles, pending, by_url)
            if not reviews:
                warnings.append(f"editorial review round {rnd} returned no verdicts")
                break
            failed = {i: r for i, r in reviews.items() if r["verdict"] == "revise"}
            passed = len(reviews) - len(failed)
            print(f"review round {rnd}: {passed} pass, {len(failed)} revise",
                  file=sys.stderr)
            for i, r in sorted(failed.items()):
                print(f"  #{i+1} {articles[i].get('headline_en','')[:55]}: "
                      f"{r['problem'][:110]}", file=sys.stderr)
            history.append({"round": rnd, "reviewed": len(reviews),
                            "passed": passed, "revised": sorted(failed)})
            if not failed:
                break
            if rnd == MAX_ROUNDS:
                warnings.append(
                    f"{len(failed)} article(s) still below the editorial bar after "
                    f"{MAX_ROUNDS} rounds; shipped as-is")
                break
            applied = rewrite(client, articles, failed, by_url)
            print(f"  rewrote {len(applied)} article(s)", file=sys.stderr)
            if not applied:
                warnings.append("rewrite produced no usable revisions; shipped as-is")
                break
            pending = applied      # only re-review what actually changed

        if history:
            final = history[-1]
            rate = final["passed"] / max(1, final["reviewed"])
            if rate < ACCEPTABLE_PASS_RATE:
                warnings.append(
                    f"editorial pass rate {final['passed']}/{final['reviewed']} "
                    f"in the final round: this week's source material may be thin")
        data["review"] = history
    except Exception as e:
        print(f"editorial review failed: {type(e).__name__}: {e}", file=sys.stderr)
        warnings.append(f"editorial review failed ({type(e).__name__}); briefs unchanged")

    data["articles"] = articles
    data["warnings"] = warnings
    json.dump(data, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def main():
    if len(sys.argv) < 3:
        print("usage: review_briefs.py <in.json> <out.json>", file=sys.stderr)
        sys.exit(2)
    run(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
