"""Only whole articles reach the digest: extraction drops partial text instead
of cutting it, the brief writer only sees complete candidates, and a brief
that describes its source as cut is dropped."""
from extract_content import MAX_CHARS, MIN_CHARS, incomplete_reason
from generate_briefs import complete_pool, mentions_truncation

BODY = "A real sentence about learning design and practice. " * 60


def test_whole_article_passes():
    assert incomplete_reason(BODY) == ""


def test_short_text_is_not_an_article():
    assert incomplete_reason("x" * (MIN_CHARS - 1))


def test_over_the_limit_is_dropped_not_cut():
    assert incomplete_reason("y" * (MAX_CHARS + 1))


def test_paywall_tail_is_incomplete():
    assert incomplete_reason(BODY + "\nSubscribe to continue reading this article.")


def test_pool_keeps_only_complete_articles():
    items = [
        {"title": "a", "full_text": BODY},
        {"title": "b", "summary": "feed blurb only"},
        {"title": "c", "full_text": "  "},
        {"title": "d", "full_text": BODY},
    ]
    assert [i["title"] for i in complete_pool(items)] == ["a", "d"]


def test_pool_skips_whole_article_that_overflows_budget():
    items = [{"title": "big", "full_text": "z" * 900}, {"title": "small", "full_text": "z" * 50}]
    pool = complete_pool(items, budget=500)
    assert [i["title"] for i in pool] == ["small"]
    assert len(pool[0]["full_text"]) == 50


def test_truncation_note_in_brief_is_caught():
    # The W41 Tulsiani brief that started this.
    assert mentions_truncation({"summary_he": "ההצעה שלו... (הטקסט שנאסף נקטע בתחילת תיאור השכבה.)"})
    assert mentions_truncation({"summary_en": "(The retrieved text cuts off at the start.)"})
    assert not mentions_truncation({"summary_en": "He argues for two layers of capability.",
                                    "insights_en": ["Cut rework by half by defining measures first."]})
