#!/usr/bin/env python3
"""Pull the real article text for the strongest candidates.

Usage: extract_content.py <in.json> <out.json>

The digest promises a summary and three key insights per article. Those are
only as good as the text they are drawn from, and an RSS <description> is often
two truncated sentences. This step replaces the feed blurb with the article
body wherever it can get one.

Two paths, in order:
  1. FIRECRAWL_API_KEY set: Firecrawl's scrape endpoint, which returns clean
     markdown and gets past the bot blocks several L&D publishers run.
  2. No key: a plain fetch plus a conservative HTML-to-text pass. Free, works
     on most sites, gives up quietly on the ones that block it.

Non-fatal throughout: any article that cannot be extracted keeps its feed
summary and the digest is built as before. Only the top candidates are
extracted, since the brief writer picks from the full pool but only the
strongest are realistic picks and every fetch costs time (and a Firecrawl
credit).
"""
import json
import os
import re
import sys
import urllib.request

EXTRACT_LIMIT = 15      # candidates to extract, highest-scoring first
MAX_CHARS = 6000        # per article, enough for a grounded brief
TIMEOUT = 30

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_DROP_BLOCKS = re.compile(
    r"<(script|style|nav|header|footer|aside|form|noscript|svg|iframe)\b[^>]*>.*?</\1>",
    re.S | re.I,
)
_MAIN = re.compile(r"<(article|main)\b[^>]*>(.*?)</\1>", re.S | re.I)
_BLOCK_END = re.compile(r"</(p|div|li|h[1-6]|br|tr)\s*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def _clean_html(html):
    """Conservative HTML to text. Prefers <article>/<main> when present, since
    that is where publishers put the body, and falls back to the whole page."""
    html = _DROP_BLOCKS.sub(" ", html)
    m = _MAIN.search(html)
    if m and len(m.group(2)) > 500:
        html = m.group(2)
    html = _BLOCK_END.sub("\n", html)
    text = _TAG.sub(" ", html)
    import html as _h
    text = _h.unescape(text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t\xa0]+", " ", line).strip()
        # Drop nav crumbs and one-word menu items; keep real sentences.
        if len(line) > 40:
            lines.append(line)
    return "\n".join(lines).strip()


def _fetch_plain(url):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            return ""
        raw = resp.read(3_000_000)
    return _clean_html(raw.decode("utf-8", "ignore"))


def _fetch_firecrawl(url, api_key):
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v2/scrape",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8", "ignore"))
    data = body.get("data") or body
    return (data.get("markdown") or "").strip()


def extract_one(url, api_key):
    """Firecrawl when configured, plain fetch otherwise. Firecrawl failures
    fall through to the plain path rather than losing the article."""
    if api_key:
        try:
            text = _fetch_firecrawl(url, api_key)
            if len(text) > 400:
                return text, "firecrawl"
        except Exception as e:
            print(f"  firecrawl failed ({type(e).__name__}), trying direct", file=sys.stderr)
    text = _fetch_plain(url)
    return text, "direct"


def extract(infile, outfile):
    data = json.load(open(infile, encoding="utf-8"))
    warnings = list(data.get("warnings") or [])
    items = data.get("items", [])
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()

    if not api_key:
        print("FIRECRAWL_API_KEY not set; using direct fetch only", file=sys.stderr)

    targets = sorted(items, key=lambda i: i.get("score", 0), reverse=True)[:EXTRACT_LIMIT]
    if len(items) > EXTRACT_LIMIT:
        # Never let a coverage cap look like full coverage on the run summary.
        print(
            f"extracting top {EXTRACT_LIMIT} of {len(items)} candidates; "
            f"the rest keep their feed summary",
            file=sys.stderr,
        )

    ok, via = 0, {}
    for i, item in enumerate(targets, 1):
        url = item.get("url", "")
        print(f"  [{i}/{len(targets)}] {url[:80]}", file=sys.stderr)
        try:
            text, how = extract_one(url, api_key)
        except Exception as e:
            print(f"    extract failed: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if len(text) < 400:
            continue                      # paywall, JS-only page, or a block
        item["full_text"] = text[:MAX_CHARS]
        item["extracted_via"] = how
        ok += 1
        via[how] = via.get(how, 0) + 1

    print(f"extracted {ok}/{len(targets)} articles {via}", file=sys.stderr)
    if ok < len(targets) // 2:
        warnings.append(
            f"full text extracted for only {ok}/{len(targets)} articles; "
            f"briefs for the rest rely on feed summaries"
        )

    data["items"] = items
    data["warnings"] = warnings
    json.dump(data, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def main():
    if len(sys.argv) < 3:
        print("usage: extract_content.py <in.json> <out.json>", file=sys.stderr)
        sys.exit(2)
    extract(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
