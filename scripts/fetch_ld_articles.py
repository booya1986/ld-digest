#!/usr/bin/env python3
"""Collect the past week's L&D / instructional-design / learning-tech articles.

Emits JSON on stdout with the shape generate_briefs.py expects:

    {"week", "since", "generated_for", "count", "warnings", "items": [...]}

Design notes (carried over from the trending-repos news fetcher, which this is
a fork of):
  * Feeds only, no API keys. Every source in feeds.json was probed live and
    confirmed to parse and return items. Dead feeds are removed rather than
    kept as decoration that silently returns nothing.
  * Hacker News supplies the community signal that editorial L&D feeds miss,
    via the free Algolia endpoint (no key).
  * Nothing here may be fatal. A source that 403s, changes markup, or hangs
    records a warning and the run continues on the others.
  * Lane floors exist because one category always outruns the others on raw
    signal. Without them, AI-in-L&D think-pieces crowd out learning science.
"""
import datetime
import html as _html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

WINDOW_DAYS = 7
MAX_ITEMS = 30          # candidates handed to the brief writer
MAX_PER_SOURCE = 6      # keeps a high-volume feed from swamping the pool
POOL_FLOOR_PER_LANE = 4  # keep at least this many of each lane in the pool
TIMEOUT = 25

FEEDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feeds.json")

LANES = ("ai_ld", "id_craft", "learning_tech", "strategy")

# What counts as this digest's beat: corporate/workplace learning and the craft
# and technology around it. A headline naming one of these is almost always
# on-topic, so they carry the most weight.
STRONG_SIGNALS = (
    "instructional design", "instructional designer", "learning experience",
    "learning design", "l&d", "learning and development", "corporate training",
    "corporate learning", "workplace learning", "learning technology",
    "learning technologies", "learning analytics", "learning science",
    "learning ecosystem", "learning culture", "training program",
    "lms", "lxp", "learning management system", "learning platform",
    "performance support", "instructional video", "e-learning", "elearning",
    "scorm", "xapi", "cmi5", "learning record store",
    "upskilling", "reskilling", "skills taxonomy", "skills-based",
    "talent development", "employee training", "onboarding program",
    "ai tutor", "adaptive learning", "learning agent", "training data literacy",
    "kirkpatrick", "ltem", "addie", "bloom's taxonomy", "andragogy",
    "chief learning officer", "learning leader",
)

SIGNALS = (
    "training", "learner", "learning", "curriculum", "course", "courseware",
    "assessment", "evaluation", "competency", "capability", "coaching",
    "mentoring", "enablement", "microlearning", "authoring", "simulation",
    "knowledge transfer", "retention", "workforce", "talent", "hr",
    "development program", "facilitation", "instructor", "classroom",
    "certification", "pedagogy", "cognitive load", "spaced repetition",
    "retrieval practice", "feedback", "motivation", "engagement",
    "ai", "genai", "generative ai", "llm", "chatgpt", "copilot", "agent",
    "automation", "personalization", "roi", "measurement", "data",
)

# Off-beat for a corporate/workplace L&D digest. This is not an academia or
# K-12 brief, and it is not a general HR-compliance brief.
ANTI_SIGNALS = (
    "k-12", "k12", "kindergarten", "elementary school", "high school",
    "university admission", "college admission", "student loan", "tuition",
    "sat exam", "school district", "teacher union", "campus",
    "crypto", "bitcoin", "blockchain", "nft", "sports", "election",
    "horoscope", "recipe", "dating app", "webinar registration",
    "discount code", "black friday", "coupon",
)

# Lane classification. Checked in order; first lane with a hit wins. The feed's
# own lane is the fallback, which is what carries the single-topic expert blogs.
LANE_SIGNALS = {
    "ai_ld": (
        "ai", "genai", "generative", "llm", "chatgpt", "claude", "gpt",
        "copilot", "agent", "agentic", "automation", "machine learning",
        "prompt", "synthetic", "ai tutor",
    ),
    "learning_tech": (
        "lms", "lxp", "platform", "software", "tool", "authoring", "scorm",
        "xapi", "cmi5", "learning record store", "analytics", "dashboard",
        "integration", "vendor", "product launch", "storyline", "articulate",
        "rise", "captivate", "video", "vr", "ar", "simulation",
    ),
    "id_craft": (
        "instructional design", "learning design", "learning science",
        "cognitive", "pedagogy", "andragogy", "curriculum", "assessment",
        "evaluation", "kirkpatrick", "ltem", "addie", "bloom", "storyboard",
        "microlearning", "spaced", "retrieval", "scenario", "practice",
        "learning experience", "accessibility",
    ),
    "strategy": (
        "strategy", "business", "roi", "executive", "leadership", "budget",
        "workforce", "skills", "talent", "culture", "organization",
        "transformation", "cfo", "ceo", "chief learning officer", "market",
        "report", "survey", "benchmark", "future of work", "hiring",
    ),
}

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


# --- signal matching -------------------------------------------------------
#
# Naive substring matching is a trap here, and an expensive one: bare "ai"
# matches tr-AI-ning, "hr" matches t-HR-ough, "roi" matches and-ROI-d. That is
# how a first run put 13 of 21 articles in the ai_ld lane and left id_craft
# empty. Short tokens therefore need a boundary on BOTH sides.
#
# Longer terms need the opposite: a trailing boundary would make
# "instructional design" miss "instructional designers", and "training" miss
# "trainings". So they anchor on the left and tolerate a word suffix.
_STRICT_MAX_LEN = 4


def _compile_terms(terms):
    """(compiled pattern, weight) pairs. Multi-word terms are more specific,
    so they count double when deciding which lane an article belongs to."""
    out = []
    for t in terms:
        left = r"(?<![a-z0-9])"
        right = r"(?![a-z0-9])" if len(t) <= _STRICT_MAX_LEN else ""
        out.append((re.compile(left + re.escape(t) + right), 2 if " " in t else 1))
    return tuple(out)


def _hits(text, patterns):
    """How many distinct terms appear."""
    return sum(1 for p, _ in patterns if p.search(text))


def _weighted_hits(text, patterns):
    """Same, but specific multi-word terms pull harder."""
    return sum(w for p, w in patterns if p.search(text))


_P_STRONG = _compile_terms(STRONG_SIGNALS)
_P_SIGNALS = _compile_terms(SIGNALS)
_P_ANTI = _compile_terms(ANTI_SIGNALS)
_P_LANE = {lane: _compile_terms(terms) for lane, terms in LANE_SIGNALS.items()}


def iso_week_string(d):
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def load_feeds(path=FEEDS_FILE):
    cfg = json.load(open(path, encoding="utf-8"))
    return cfg.get("feeds", []), cfg.get("hn_queries", [])


def _get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def _clean(text):
    """Strip tags and entities out of a feed summary."""
    if not text:
        return ""
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


_NAMED_ENTITY = re.compile(r"&(?!(?:amp|lt|gt|quot|apos)\b)([A-Za-z][A-Za-z0-9]{1,31});")


def _tolerant_fromstring(xml_text):
    """Parse a feed, surviving the undefined HTML entities some publishers emit.

    Strict XML only defines five entities. Several real L&D feeds ship
    &nbsp; / &mdash; / &rsquo; in titles, which makes ElementTree throw
    'undefined entity' and would otherwise cost us the whole source.
    """
    xml_text = xml_text.strip()
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError:
        pass
    repaired = _NAMED_ENTITY.sub(lambda m: _html.unescape(f"&{m.group(1)};"), xml_text)
    return ET.fromstring(repaired)


def parse_date(raw):
    """RFC-822 (RSS) or ISO-8601 (Atom) to an aware UTC datetime, or None."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _text(node):
    return (node.text or "").strip() if node is not None else ""


def parse_feed(xml_text, source, tier=2, lane="strategy"):
    """Read RSS <item>s or Atom <entry>s into a common item shape."""
    try:
        root = _tolerant_fromstring(xml_text)
    except ET.ParseError:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = []

    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = _text(node.find("title")) or _text(node.find("atom:title", ns))
        link = _text(node.find("link")) or _text(node.find("atom:link", ns))
        if not link:
            for ln in list(node.findall("link")) + list(node.findall("atom:link", ns)):
                href = ln.get("href")
                if href and ln.get("rel", "alternate") == "alternate":
                    link = href
                    break
        raw_date = (
            _text(node.find("pubDate"))
            or _text(node.find("published"))
            or _text(node.find("updated"))
            or _text(node.find("atom:published", ns))
            or _text(node.find("atom:updated", ns))
        )
        summary = (
            _text(node.find("description"))
            or _text(node.find("summary"))
            or _text(node.find("atom:summary", ns))
            or _text(node.find("content"))
            or _text(node.find("atom:content", ns))
        )
        if not title or not link:
            continue
        items.append({
            "title": _clean(title),
            "url": link.strip(),
            "source": source,
            "tier": tier,
            "feed_lane": lane,
            "published": raw_date,
            "published_dt": parse_date(raw_date),
            "summary": _clean(summary)[:800],
            "points": 0,
        })
    return items


def is_recent(item, now=None, window_days=WINDOW_DAYS):
    """Within the window. An item with no parseable date is not assumed fresh."""
    dt = item.get("published_dt")
    if dt is None:
        return False
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age = (now - dt).total_seconds() / 86400.0
    return -1 <= age <= window_days


def _item_text(item):
    return f"{item.get('title', '')} {item.get('summary', '')}".lower()


def classify_lane(item):
    """Content first, the feed's own lane as fallback.

    General-business feeds (HBR, Sloan, HR Dive) carry occasional L&D pieces
    that belong in whichever lane the content is about, not in the feed's.
    """
    text = _item_text(item)
    best, best_hits = None, 0
    for lane in LANES:
        hits = _weighted_hits(text, _P_LANE[lane])
        if hits > best_hits:
            best, best_hits = lane, hits
    return best or item.get("feed_lane") or "strategy"


def article_score(item, now=None):
    """Rank candidates: on-beat first, then fresh, then authority, then traction.

    Adapted from the Source Ledger's model (tier + recency + corroboration)
    rather than the repo pipeline's star-velocity, which has no analogue here.
    """
    text = _item_text(item)
    score = 0.0
    score += 3.0 * _hits(text, _P_STRONG)
    score += 1.0 * _hits(text, _P_SIGNALS)
    score -= 5.0 * _hits(text, _P_ANTI)
    score += {1: 2.0, 2: 1.5, 3: 0.5}.get(item.get("tier", 2), 0.0)
    dt = item.get("published_dt")
    if dt is not None:
        now = now or datetime.datetime.now(datetime.timezone.utc)
        age = max((now - dt).total_seconds() / 86400.0, 0.0)
        score += max(0.0, 4.0 - age * 0.5)      # today beats last Monday
    points = item.get("points") or 0
    if points:
        score += min(points / 100.0, 5.0)       # HN traction, capped
    return score


def is_on_beat(item):
    """Keep workplace L&D content, drop the rest of the business/tech cycle."""
    text = _item_text(item)
    if _hits(text, _P_ANTI):
        return False
    if _hits(text, _P_STRONG):
        return True
    return _hits(text, _P_SIGNALS) >= 3


_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with",
    "is", "are", "its", "it", "as", "at", "by", "from", "new", "now", "says",
    "this", "that", "will", "has", "have", "you", "your", "how", "why",
    "what", "when", "can", "should", "about", "not", "but", "we", "our",
}


def _title_key(title):
    return frozenset(w for w in _WORD.findall(title.lower())
                     if w not in _STOP and len(w) > 2)


def _norm_url(url):
    return (url or "").split("?")[0].rstrip("/").lower()


def dedupe(items, overlap=0.6):
    """Collapse the same story reported by several outlets.

    Exact URL match, or titles sharing enough distinctive words. The
    higher-scoring copy survives, so the version from the more authoritative
    source (or the one that reached HN) is the one that goes forward.
    """
    kept = []
    seen_urls = set()
    for item in sorted(items, key=lambda i: i.get("_score", 0), reverse=True):
        url = _norm_url(item.get("url"))
        if url and url in seen_urls:
            continue
        key = _title_key(item.get("title", ""))
        dup = False
        for other in kept:
            other_key = other["_key"]
            if not key or not other_key:
                continue
            shared = len(key & other_key)
            if shared / max(1, min(len(key), len(other_key))) >= overlap:
                dup = True
                break
        if dup:
            continue
        item["_key"] = key
        kept.append(item)
        if url:
            seen_urls.add(url)
    return kept


def previously_seen(reports_dir=None):
    """URLs already published in an earlier week, so we never repeat an article.

    Reads the committed articles.json of each prior report. Only directories
    named like an ISO week are considered, matching the repo pipeline's
    `^\\d{4}-W\\d{2}` guard.
    """
    reports_dir = reports_dir or os.environ.get("LD_REPORTS_DIR", "")
    seen = set()
    if not reports_dir or not os.path.isdir(reports_dir):
        return seen
    for name in os.listdir(reports_dir):
        if not re.fullmatch(r"\d{4}-W\d{2}", name):
            continue
        path = os.path.join(reports_dir, name, "articles.json")
        if not os.path.exists(path):
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for a in data.get("articles", []) or []:
            u = _norm_url(a.get("url"))
            if u:
                seen.add(u)
    return seen


def fetch_hacker_news(since_ts, queries, min_points=40, limit=20):
    """L&D stories the HN crowd actually upvoted this week. No key needed."""
    out = []
    for q in queries:
        url = (
            "https://hn.algolia.com/api/v1/search_by_date?tags=story"
            f"&hitsPerPage={limit}&query={urllib.parse.quote(q)}"
            f"&numericFilters=created_at_i>{since_ts},points>{min_points}"
        )
        data = json.loads(_get(url))
        for hit in data.get("hits", []):
            link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            out.append({
                "title": _clean(hit.get("title") or ""),
                "url": link,
                "source": "Hacker News",
                "tier": 2,
                "feed_lane": "learning_tech",
                "published": hit.get("created_at") or "",
                "published_dt": parse_date(hit.get("created_at") or ""),
                "summary": "",
                "points": hit.get("points") or 0,
            })
    return [i for i in out if i["title"]]


def diversify(ranked, limit=MAX_ITEMS, floor=POOL_FLOOR_PER_LANE):
    """Top-N by score, but guarantee each lane a share of the pool.

    Without this, the highest-volume lane fills the candidate list and the
    brief writer never even sees the other three.
    """
    by_lane = {lane: [i for i in ranked if i["lane"] == lane] for lane in LANES}
    picked, picked_ids = [], set()

    for lane in LANES:
        for item in by_lane[lane][:floor]:
            if id(item) not in picked_ids:
                picked.append(item)
                picked_ids.add(id(item))

    for item in ranked:
        if len(picked) >= limit:
            break
        if id(item) not in picked_ids:
            picked.append(item)
            picked_ids.add(id(item))

    picked.sort(key=lambda i: i["_score"], reverse=True)
    return picked[:limit]


def collect(now=None, warnings=None, reports_dir=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    warnings = warnings if warnings is not None else []
    feeds, hn_queries = load_feeds()
    collected = []

    for feed in feeds:
        name, url = feed["name"], feed["url"]
        try:
            items = parse_feed(_get(url), name, feed.get("tier", 2), feed.get("lane", "strategy"))
        except Exception as e:
            warnings.append(f"feed failed for '{name}': {type(e).__name__}: {e}")
            continue
        if not items:
            warnings.append(f"feed '{name}' parsed 0 items (format change?)")
            continue
        fresh = [i for i in items if is_recent(i, now)]
        collected.extend(fresh[:MAX_PER_SOURCE])

    try:
        since_ts = int((now - datetime.timedelta(days=WINDOW_DAYS)).timestamp())
        collected.extend(fetch_hacker_news(since_ts, hn_queries))
    except Exception as e:
        warnings.append(f"hacker news failed: {type(e).__name__}: {e}")

    on_beat = [i for i in collected if is_on_beat(i)]
    if collected and not on_beat:
        warnings.append(
            f"{len(collected)} items fetched but none passed the L&D topic filter"
        )

    seen = previously_seen(reports_dir)
    if seen:
        before = len(on_beat)
        on_beat = [i for i in on_beat if _norm_url(i.get("url")) not in seen]
        if before != len(on_beat):
            warnings.append(f"dropped {before - len(on_beat)} articles already sent in an earlier week")

    for item in on_beat:
        item["lane"] = classify_lane(item)
        item["_score"] = article_score(item, now)

    ranked = sorted(dedupe(on_beat), key=lambda i: i["_score"], reverse=True)
    return diversify(ranked), warnings


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date()
    items, warnings = collect(now, [])

    if len(items) < 10:
        warnings.append(f"only {len(items)} articles survived filtering (wanted 10+)")

    clean_items = []
    for i in items:
        clean_items.append({
            "title": i["title"],
            "url": i["url"],
            "source": i["source"],
            "lane": i.get("lane", "strategy"),
            "published": (i["published_dt"].isoformat() if i.get("published_dt") else ""),
            "summary": i.get("summary", ""),
            "points": i.get("points", 0),
            "score": round(i.get("_score", 0), 2),
        })

    feeds, _ = load_feeds()
    out = {
        "week": iso_week_string(today),
        "since": (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat(),
        "generated_for": today.isoformat(),
        "count": len(clean_items),
        "sources_tried": len(feeds) + 1,
        "warnings": warnings,
        "items": clean_items,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
