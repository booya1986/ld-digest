#!/usr/bin/env python3
"""Tests for fetch_ld_articles.py. Run: python3 -m pytest scripts/ -q"""
import datetime
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch_ld_articles as f  # noqa: E402

NOW = datetime.datetime(2026, 8, 16, 12, 0, tzinfo=datetime.timezone.utc)


def _item(title, summary="", **kw):
    base = {"title": title, "summary": summary, "url": "https://x.test/a",
            "source": "T", "tier": 2, "feed_lane": "strategy", "points": 0}
    base.update(kw)
    return base


# --- feed parsing ----------------------------------------------------------

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Instructional design in 2026</title><link>https://a.test/1</link>
<pubDate>Fri, 14 Aug 2026 09:00:00 +0000</pubDate>
<description>&lt;p&gt;A look at learning design.&lt;/p&gt;</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Learning analytics that work</title>
<link rel="alternate" href="https://b.test/2"/>
<published>2026-08-13T10:00:00Z</published>
<summary>Measuring training impact.</summary></entry></feed>"""


def test_parses_rss():
    items = f.parse_feed(RSS, "Src", tier=1, lane="id_craft")
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "Instructional design in 2026"
    assert it["url"] == "https://a.test/1"
    assert it["tier"] == 1 and it["feed_lane"] == "id_craft"
    assert "learning design" in it["summary"].lower()   # tags stripped
    assert it["published_dt"].year == 2026


def test_parses_atom_link_href():
    items = f.parse_feed(ATOM, "Src")
    assert len(items) == 1
    assert items[0]["url"] == "https://b.test/2"
    assert items[0]["published_dt"].month == 8


def test_unparseable_feed_returns_empty_not_raises():
    assert f.parse_feed("<html>not a feed</html>", "Src") == []


def test_tolerates_undefined_html_entities():
    """Several real L&D feeds ship &nbsp; / &rsquo; in titles. Strict XML
    defines five entities, so a naive parse loses the whole source."""
    xml = ("""<?xml version="1.0"?><rss version="2.0"><channel><item>"""
           """<title>L&amp;D&nbsp;trends&rsquo;26</title><link>https://c.test/3</link>"""
           """<pubDate>Fri, 14 Aug 2026 09:00:00 +0000</pubDate></item></channel></rss>""")
    items = f.parse_feed(xml, "Src")
    assert len(items) == 1
    assert "trends" in items[0]["title"]


# --- dates and recency -----------------------------------------------------

@pytest.mark.parametrize("raw,year", [
    ("Fri, 14 Aug 2026 09:00:00 +0000", 2026),   # RFC-822
    ("2026-08-13T10:00:00Z", 2026),              # ISO-8601
])
def test_parse_date_formats(raw, year):
    assert f.parse_date(raw).year == year


def test_parse_date_garbage_is_none():
    assert f.parse_date("last tuesday") is None
    assert f.parse_date("") is None


def test_recency_window():
    fresh = _item("x", published_dt=NOW - datetime.timedelta(days=3))
    stale = _item("x", published_dt=NOW - datetime.timedelta(days=20))
    assert f.is_recent(fresh, NOW)
    assert not f.is_recent(stale, NOW)


def test_undated_item_is_not_assumed_fresh():
    assert not f.is_recent(_item("x", published_dt=None), NOW)


# --- topic filter ----------------------------------------------------------

def test_on_beat_strong_signal():
    assert f.is_on_beat(_item("A new model for instructional design"))


def test_off_beat_generic_business():
    assert not f.is_on_beat(_item("Quarterly earnings beat expectations"))


def test_anti_signal_drops_k12():
    assert not f.is_on_beat(
        _item("K-12 classroom instructional design for high school teachers"))


def test_anti_signal_penalises_score():
    on = f.article_score(_item("Corporate training and learning analytics"), NOW)
    off = f.article_score(
        _item("Corporate training and learning analytics for K-12 school district"), NOW)
    assert off < on


# --- signal matching (regression) ------------------------------------------

def test_short_tokens_need_word_boundaries():
    """`ai` must not match inside 'training', `hr` inside 'through',
    `roi` inside 'android'. This bug put 13 of 21 articles in one lane."""
    text = "training programs delivered through android devices"
    assert f._hits(text, f._compile_terms(("ai", "hr", "roi"))) == 0


def test_long_terms_still_match_suffixes():
    """'instructional design' must match 'Instructional Designers'."""
    text = "6 ai portfolio projects for instructional designers"
    assert f._hits(text, f._compile_terms(("instructional design",))) == 1


def test_lane_classification_uses_content_not_feed():
    """A general-business feed carrying an ID piece lands in id_craft."""
    it = _item("Rethinking instructional design and learning science",
               feed_lane="strategy")
    assert f.classify_lane(it) == "id_craft"


def test_lane_falls_back_to_feed_when_content_is_silent():
    assert f.classify_lane(_item("A short note", feed_lane="id_craft")) == "id_craft"


def test_ai_lane_needs_a_real_ai_word():
    """Regression: the word 'training' alone must not imply the AI lane."""
    assert f.classify_lane(_item("Designing better training programs")) != "ai_ld"


# --- dedupe ----------------------------------------------------------------

def test_dedupe_exact_url():
    a = _item("One title here", url="https://x.test/p?utm=1", _score=5.0)
    b = _item("Totally different words", url="https://x.test/p", _score=1.0)
    assert len(f.dedupe([a, b])) == 1


def test_dedupe_title_overlap_keeps_higher_score():
    a = _item("AI reshapes corporate learning programs",
              url="https://a.test/1", _score=9.0)
    b = _item("AI reshapes corporate learning programs, say analysts",
              url="https://b.test/2", _score=2.0)
    kept = f.dedupe([a, b])
    assert len(kept) == 1
    assert kept[0]["_score"] == 9.0


def test_dedupe_keeps_genuinely_different_stories():
    a = _item("Learning analytics adoption rises", url="https://a.test/1", _score=5.0)
    b = _item("Instructional design salaries report", url="https://b.test/2", _score=4.0)
    assert len(f.dedupe([a, b])) == 2


# --- ranking and diversity -------------------------------------------------

def test_recency_beats_staleness_all_else_equal():
    new = _item("corporate training", published_dt=NOW - datetime.timedelta(days=1))
    old = _item("corporate training", published_dt=NOW - datetime.timedelta(days=6))
    assert f.article_score(new, NOW) > f.article_score(old, NOW)


def test_tier_breaks_ties():
    hi = _item("corporate training", tier=1, published_dt=NOW)
    lo = _item("corporate training", tier=3, published_dt=NOW)
    assert f.article_score(hi, NOW) > f.article_score(lo, NOW)


def test_diversify_gives_every_lane_a_share():
    ranked = []
    for i in range(30):
        it = _item(f"t{i}", _score=100 - i)
        it["lane"] = "ai_ld"          # one lane dominates on raw score
        ranked.append(it)
    for i in range(3):
        it = _item(f"id{i}", _score=1 - i)
        it["lane"] = "id_craft"       # weak but present
        ranked.append(it)
    picked = f.diversify(ranked, limit=10, floor=2)
    lanes = {p["lane"] for p in picked}
    assert "id_craft" in lanes
    assert len(picked) == 10


def test_diversify_respects_limit():
    ranked = []
    for i in range(50):
        it = _item(f"t{i}", _score=float(i))
        it["lane"] = f.LANES[i % 4]
        ranked.append(it)
    assert len(f.diversify(ranked, limit=12, floor=2)) == 12


# --- cross-week dedup ------------------------------------------------------

def test_previously_seen_reads_prior_weeks(tmp_path):
    week = tmp_path / "2026-W30"
    week.mkdir()
    (week / "articles.json").write_text(json.dumps(
        {"articles": [{"url": "https://old.test/a/"}]}), encoding="utf-8")
    (tmp_path / "notaweek").mkdir()
    seen = f.previously_seen(str(tmp_path))
    assert "https://old.test/a" in seen


def test_previously_seen_missing_dir_is_empty():
    assert f.previously_seen("/nonexistent/path/xyz") == set()


# --- config ----------------------------------------------------------------

def test_feeds_file_is_valid_and_covers_every_lane():
    feeds, queries = f.load_feeds()
    assert len(feeds) >= 15
    assert queries
    for feed in feeds:
        assert feed["url"].startswith("http")
        assert feed["lane"] in f.LANES
        assert feed["tier"] in (1, 2, 3)
    assert {feed["lane"] for feed in feeds} == set(f.LANES)


def test_feed_urls_are_unique():
    feeds, _ = f.load_feeds()
    urls = [x["url"] for x in feeds]
    assert len(urls) == len(set(urls))
