#!/usr/bin/env python3
"""Web-search top-up: catch notable L&D articles the curated feeds missed.

Usage: discover_articles.py <in.json> <out.json>

Additive and non-fatal by design. Findings are appended to the candidate pool
as ordinary tier-2 items and then flow through the same scoring, dedupe, and
selection as everything else: they get no special standing. If the call fails,
returns nothing, or there is no API key, the input is copied through unchanged
and the digest is built from feeds alone.

Uses the Anthropic server-side web search tool, so it needs no scraping vendor
beyond the ANTHROPIC_API_KEY the pipeline already has. Note that the
web_search_20260209 variant has dynamic filtering built in: do NOT also declare
a code_execution tool, which would create a second execution environment.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_ld_articles import _norm_url, classify_lane, is_on_beat  # noqa: E402

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
MAX_SEARCHES = 6
WANTED = 12
MAX_CONTINUATIONS = 4

SYSTEM_PROMPT = """\
You find recent, substantive articles about corporate learning and development \
for a senior L&D practitioner's weekly digest.

In scope: instructional design and learning design, learning science, AI applied \
to workplace learning, learning technology (LMS/LXP, authoring, learning \
analytics, xAPI), and L&D strategy (skills, workforce capability, measurement, \
the business case for learning).

Out of scope: K-12 and higher education, MOOC and course-catalog roundups, \
certification marketing, vendor press releases with no substance, and anything \
published more than 7 days ago.

Search the web for what was published in the last 7 days, then return the most \
substantive findings. Rules:
- Only return articles you actually found in search results. Never invent a \
title, a URL, or a publication.
- The url must be exactly the URL from the search result, copied verbatim.
- Prefer a concrete idea, method, finding, or dataset over opinion.
- Skip anything you cannot date to the last 7 days.
- summary: 1 to 2 sentences, in English, grounded in what the search result \
actually showed. Do not speculate about content you did not see.
- Return fewer results rather than padding with weak or off-topic ones. \
Returning nothing is an acceptable answer."""

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "source": {"type": "string"},
                    "published": {
                        "type": "string",
                        "description": "ISO date (YYYY-MM-DD) the article was published.",
                    },
                    "summary": {"type": "string"},
                },
                "required": ["title", "url", "source", "published", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["articles"],
    "additionalProperties": False,
}


def _response_text(message):
    """First text block — never content[0], which is a thinking block."""
    for block in message.content:
        if block.type == "text":
            return block.text
    return ""


def _parse_date(raw):
    try:
        d = datetime.date.fromisoformat((raw or "")[:10])
    except ValueError:
        return None
    return datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)


def search(since, warnings):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        warnings.append("web-search top-up skipped (no ANTHROPIC_API_KEY)")
        return []

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    prompt = (
        f"Today is {datetime.date.today().isoformat()}. Find up to {WANTED} "
        f"notable L&D, instructional design, and learning technology articles "
        f"published since {since}. Cover a spread across the field rather than "
        f"several articles on one story."
    )
    messages = [{"role": "user", "content": prompt}]

    for _ in range(MAX_CONTINUATIONS):
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": MAX_SEARCHES,
            }],
            output_config={"format": {"type": "json_schema", "schema": FINDINGS_SCHEMA}},
        )
        # A long server-tool turn can stop with pause_turn; re-send to resume.
        # Without this the answer is silently truncated, with no error raised.
        if message.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": message.content})
            continue
        if message.stop_reason == "max_tokens":
            warnings.append("web-search top-up hit max_tokens")
        return json.loads(_response_text(message)).get("articles", [])

    warnings.append("web-search top-up still paused after retries; skipped")
    return []


def discover(infile, outfile):
    data = json.load(open(infile, encoding="utf-8"))
    warnings = list(data.get("warnings") or [])
    items = data.get("items", [])
    since = data.get("since") or ""

    try:
        found = search(since, warnings)
    except Exception as e:
        print(f"web-search top-up failed: {type(e).__name__}: {e}", file=sys.stderr)
        warnings.append(f"web-search top-up failed ({type(e).__name__})")
        found = []

    seen = {_norm_url(i.get("url")) for i in items}
    cutoff = _parse_date(since)
    added = 0

    for f in found:
        url = (f.get("url") or "").strip()
        if not url.startswith("http") or _norm_url(url) in seen:
            continue
        published = _parse_date(f.get("published"))
        if cutoff and published and published < cutoff:
            continue        # older than the window the model was asked for
        item = {
            "title": (f.get("title") or "").strip(),
            "url": url,
            "source": (f.get("source") or "Web").strip(),
            "published": published.isoformat() if published else "",
            "summary": (f.get("summary") or "").strip(),
            "points": 0,
            "tier": 2,
            "feed_lane": "strategy",
            "discovered": True,
        }
        if not item["title"]:
            continue
        # Same topic gate as the feeds: discovery gets no free pass.
        if not is_on_beat(item):
            continue
        item["lane"] = classify_lane(item)
        item["score"] = 0.0
        items.append(item)
        seen.add(_norm_url(url))
        added += 1

    if added:
        print(f"web search added {added} candidates", file=sys.stderr)
    else:
        warnings.append("web-search top-up added no new candidates")

    data["items"] = items
    data["count"] = len(items)
    data["warnings"] = warnings
    json.dump(data, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def main():
    if len(sys.argv) < 3:
        print("usage: discover_articles.py <in.json> <out.json>", file=sys.stderr)
        sys.exit(2)
    discover(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
