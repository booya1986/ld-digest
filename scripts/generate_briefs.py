#!/usr/bin/env python3
"""Pick the week's 10 best L&D articles and write bilingual briefs for each.

Usage: generate_briefs.py <in.json> <out.json>

One Claude call selects from the fetched candidates and writes Hebrew + English
copy for each pick. If ANTHROPIC_API_KEY is not set (or the call fails) it
degrades to the top-scoring headlines, so the report always has content and the
pipeline never fails on this step.

Three deliberate choices, all carried over from the trending-repos pipeline
where each was learned the hard way:
  * Structured outputs (output_config.format) instead of "return only JSON".
    The model cannot emit unparseable output, so the truncated-JSON failure
    that silently emptied the briefs for two weeks cannot recur here.
  * The model selects by INDEX, never by echoing a URL. Links come from the
    fetched data, so an article can never point at a hallucinated address.
  * Read the first *text* block, never content[0] — thinking is on by default
    on this model and the first block has no .text.
"""
import json
import os
import sys

MODEL = "claude-opus-5"
CANDIDATES = 30                # how many articles the model chooses from
WANTED = 10                    # how many make the digest
# Thinking is on by default on claude-opus-5 and shares this budget with the
# response text, so leave real headroom: 10 articles x 8 bilingual fields is a
# large structured payload.
MAX_TOKENS = 32000

LANES = ("ai_ld", "id_craft", "learning_tech", "strategy")

SYSTEM_PROMPT = """\
You are the editor of Avi Levi's weekly learning & development digest.

Avi has 17 years in L&D and leads learning solution architecture at a large \
bank, where he manages a small team and also lectures on digital learning \
development. His axis is AI + performance + data, not the classic modality \
debate. The thesis he works from: the unit sells courses, but the organization \
needs performance. He favors performance consulting over order-taking (needs \
analysis, ISPI, LTEM over Kirkpatrick-only), learning analytics and skills \
data, and AI as an instructional-design force multiplier. He is building \
AI-native ways of producing learning, and he teaches other L&D professionals \
to do the same.

Rules:
- Pick the {wanted} most valuable articles of the week, ranked by how much they \
matter to a senior L&D practitioner. Rank on substance: how significant the \
idea is, how well evidenced it is, and how much it changes what someone \
building learning can actually do.
- Aim to cover all four lanes (ai_ld, id_craft, learning_tech, strategy), but \
never promote a weak article just to fill a lane. Substance wins over balance.
- Prefer articles with a concrete idea, method, finding, or data over vendor \
marketing, listicles, and course-catalog roundups.
- Never pick two articles covering the same story. Choose the better source.
- Ground every claim in the title and summary you are given. Never invent \
findings, numbers, or claims the source does not support. If the supplied \
summary is thin, write less rather than filling the gap with assumption.
- Do not use em-dashes anywhere. Use colons, commas, or parentheses instead.
- Hebrew must read naturally, not as translated English. Keep product, company, \
and methodology names in Latin script inside the Hebrew text.

Per article write:
- summary: 2 to 3 sentences on what the article actually says.
- insights: exactly 3 short, concrete takeaways. Each one a standalone point a \
reader could act on or quote. Not a restatement of the summary.
- matters: 1 to 2 sentences on why this specifically matters to Avi, given his \
role and interests above."""

_STR = {"type": "string"}

ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "index": {
            "type": "integer",
            "description": "Index of the chosen candidate, from the list given.",
        },
        "lane": {"type": "string", "enum": list(LANES)},
        "headline_he": _STR,
        "headline_en": _STR,
        "summary_he": _STR,
        "summary_en": _STR,
        "insights_he": {"type": "array", "items": _STR},
        "insights_en": {"type": "array", "items": _STR},
        "matters_he": _STR,
        "matters_en": _STR,
    },
    "required": [
        "index", "lane", "headline_he", "headline_en",
        "summary_he", "summary_en", "insights_he", "insights_en",
        "matters_he", "matters_en",
    ],
    "additionalProperties": False,
}

BRIEFS_SCHEMA = {
    "type": "object",
    "properties": {"articles": {"type": "array", "items": ARTICLE_SCHEMA}},
    "required": ["articles"],
    "additionalProperties": False,
}


FULL_TEXT_CHARS = 4000   # per article, inside the candidate list


def _candidate_list(items):
    """Give the model the article body where extract_content.py got one, and
    the feed blurb otherwise. Key insights drawn from a two-line RSS summary
    are thin; drawn from the real text they are specific."""
    lines = []
    for i, it in enumerate(items):
        points = it.get("points") or 0
        traction = f" [{points} HN points]" if points else ""
        full = (it.get("full_text") or "").strip()
        if full:
            body = f"   full text:\n{full[:FULL_TEXT_CHARS]}"
        else:
            body = f"   summary only (full text unavailable):\n   {(it.get('summary') or '')[:400]}"
        lines.append(
            f"{i}. {it['title']}\n"
            f"   source: {it.get('source', '')}{traction} | lane: {it.get('lane', '')}"
            f" | {(it.get('published') or '')[:10]}\n"
            f"{body}"
        )
    return "\n".join(lines)


def _response_text(message):
    """First text block. Never content[0] — thinking is on by default on
    claude-opus-5 and a thinking block has no .text (the bug that killed the
    briefs step in the sibling pipeline for two weeks)."""
    for block in message.content:
        if block.type == "text":
            return block.text
    return ""


def _fallback(items):
    """No API key, or the call failed: ship headlines rather than nothing."""
    out = []
    for it in items[:WANTED]:
        out.append({
            "headline_he": it["title"],
            "headline_en": it["title"],
            "summary_he": "",
            "summary_en": (it.get("summary") or "")[:300],
            "insights_he": [],
            "insights_en": [],
            "matters_he": "",
            "matters_en": "",
            "lane": it.get("lane", "strategy"),
            "url": it["url"],
            "source": it.get("source", ""),
            "published": it.get("published", ""),
        })
    return out


def _trim(seq, n=3):
    """Exactly-N array lengths cannot be expressed in a supported JSON Schema
    constraint, so the count is asked for in the prompt and enforced here."""
    return [s for s in (seq or []) if s][:n]


def generate(infile, outfile):
    data = json.load(open(infile, encoding="utf-8"))
    items = data.get("items", [])
    warnings = list(data.get("warnings") or [])

    if not items:
        warnings.append("no articles to brief")
        data["articles"] = []
        data["warnings"] = warnings
        json.dump(data, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return

    pool = items[:CANDIDATES]
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        print("ANTHROPIC_API_KEY not set; using headline-only digest", file=sys.stderr)
        warnings.append("briefs written without Claude (no ANTHROPIC_API_KEY)")
        articles = _fallback(pool)
    else:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            prompt = (
                f"Here are this week's candidate L&D articles.\n\n"
                f"{_candidate_list(pool)}\n\n"
                f"Choose the {WANTED} most valuable and write the digest entries."
            )
            message = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT.format(wanted=WANTED),
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": BRIEFS_SCHEMA}},
            )
            if message.stop_reason == "max_tokens":
                warnings.append("briefs hit max_tokens; digest may be short")
            parsed = json.loads(_response_text(message))

            articles, seen = [], set()
            for entry in parsed.get("articles", []):
                idx = entry.get("index")
                if not isinstance(idx, int) or not 0 <= idx < len(pool):
                    continue          # model named a candidate that doesn't exist
                if idx in seen:
                    continue          # same article picked twice
                seen.add(idx)
                src = pool[idx]
                articles.append({
                    "headline_he": entry["headline_he"],
                    "headline_en": entry["headline_en"],
                    "summary_he": entry["summary_he"],
                    "summary_en": entry["summary_en"],
                    "insights_he": _trim(entry.get("insights_he")),
                    "insights_en": _trim(entry.get("insights_en")),
                    "matters_he": entry["matters_he"],
                    "matters_en": entry["matters_en"],
                    "lane": entry.get("lane", src.get("lane", "strategy")),
                    "url": src["url"],
                    "source": src.get("source", ""),
                    "published": src.get("published", ""),
                })
            if not articles:
                raise ValueError("model returned no usable articles")

            covered = {a["lane"] for a in articles}
            missing = [l for l in LANES if l not in covered]
            if missing:
                warnings.append(f"no article this week in lane(s): {', '.join(missing)}")
            print(f"briefs: {len(articles)} of {len(pool)} candidates", file=sys.stderr)
        except Exception as e:
            print(f"brief generation failed: {type(e).__name__}: {e}", file=sys.stderr)
            warnings.append(f"briefs failed ({type(e).__name__}); used headlines only")
            articles = _fallback(pool)

    data["articles"] = articles
    data["warnings"] = warnings
    json.dump(data, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def main():
    if len(sys.argv) < 3:
        print("usage: generate_briefs.py <in.json> <out.json>", file=sys.stderr)
        sys.exit(2)
    generate(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
