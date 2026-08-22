#!/usr/bin/env python3
"""Build the weekly L&D digest email.

This module owns the HTML; send_digest_smtp.py owns the sending, so the cloud
send and any local send produce a byte-identical message.

The TL;DR is read from the committed reports/<week>/articles.json rather than
parsed out of prose, so there is no text-shaped contract to break.
"""
import json
import os
import re

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")
# Recipients live in send_digest_smtp.py (DIGEST_TO, comma separated).
# This module is only used as a library for build_html/read_top_articles.
BASE_URL = "https://booya1986.github.io/ld-digest/reports"
TLDR_COUNT = 4


def latest_week():
    weeks = sorted(
        d for d in os.listdir(REPORTS_DIR)
        if os.path.isdir(os.path.join(REPORTS_DIR, d)) and re.fullmatch(r"\d{4}-W\d+", d)
    )
    if not weeks:
        raise RuntimeError("No report folders found in reports/")
    return weeks[-1]


def week_label(week):
    return week.replace("-", " ").replace("W", "שבוע ")


def read_top_articles(week, limit=TLDR_COUNT):
    """Top headlines for the email TL;DR, from the report's structured data."""
    path = os.path.join(REPORTS_DIR, week, "articles.json")
    if not os.path.exists(path):
        return []
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (ValueError, OSError):
        return []
    out = []
    for a in (data.get("articles") or [])[:limit]:
        headline = a.get("headline_he") or a.get("headline_en") or ""
        summary = a.get("summary_he") or a.get("summary_en") or ""
        # One clause is enough for a scannable TL;DR line.
        first = summary.split(".")[0].strip()
        if len(first) > 150:
            first = first[:147].rstrip() + "..."
        out.append((headline, first, a.get("source", "")))
    return out


def build_html(week, top_articles):
    report_url = f"{BASE_URL}/{week}/"
    rows = ""
    for i, (headline, blurb, source) in enumerate(top_articles):
        border = "border-bottom:1px solid #2d2d2d;" if i < len(top_articles) - 1 else ""
        tail = f" &mdash; {blurb}" if blurb else ""
        rows += f'''<tr><td style="padding:9px 0;{border}">
        <p style="margin:0;font-size:14px;color:#f3f4f6;font-family:Arial,sans-serif;line-height:1.5;">
          <strong style="color:#22c55e;">{headline}</strong>{tail}
        </p>
        <p style="margin:3px 0 0;font-size:11px;color:#6b7280;font-family:Arial,sans-serif;">{source}</p>
        </td></tr>'''

    label = week_label(week)
    return f"""<!DOCTYPE html><html lang="he" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:Arial,sans-serif;direction:rtl;">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f0f0f0" style="padding:24px 12px;">
<tr><td align="center">
<table width="100%" style="max-width:520px;" cellpadding="0" cellspacing="0">
  <tr><td style="background:#1b1b1b;border-radius:12px 12px 0 0;padding:24px 28px 18px;border-bottom:3px solid #22c55e;">
    <p style="margin:0 0 6px;font-size:11px;color:#22c55e;letter-spacing:2px;font-family:Arial,sans-serif;">WEEKLY L&amp;D DIGEST</p>
    <h1 style="margin:0 0 4px;font-size:22px;color:#f9fafb;font-family:Arial,sans-serif;">&#128218; למידה, פיתוח והדרכה</h1>
    <p style="margin:0;font-size:13px;color:#9ca3af;font-family:Arial,sans-serif;">{label} &middot; 10 הכתבות שכדאי לקרוא השבוע</p>
  </td></tr>
  <tr><td style="background:#1b1b1b;padding:20px 28px 16px;">
    <p style="margin:0 0 14px;font-size:11px;font-weight:bold;color:#22c55e;letter-spacing:2px;font-family:Arial,sans-serif;">TL;DR &mdash; ההיילייטס של השבוע</p>
    <table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
    <p style="margin:14px 0 0;font-size:12px;color:#6b7280;font-family:Arial,sans-serif;">+ עוד כתבות בדוח המלא, עם תקציר ותובנות מפתח לכל אחת</p>
  </td></tr>
  <tr><td style="background:#1b1b1b;padding:20px 28px 24px;">
    <a href="{report_url}" style="display:block;background:#22c55e;color:#0a1a0f;padding:16px 0;border-radius:50px;text-decoration:none;font-weight:bold;font-size:16px;text-align:center;font-family:Arial,sans-serif;">&#128241; קרא את הדוח המלא</a>
  </td></tr>
  <tr><td style="background:#111111;border-radius:0 0 12px 12px;padding:14px 28px;border-top:1px solid #2d2d2d;">
    <p style="margin:0;font-size:11px;color:#6b7280;text-align:center;font-family:Arial,sans-serif;">נשלח אוטומטית כל יום ראשון &middot; <a href="{BASE_URL}/" style="color:#4b5563;text-decoration:none;">כל הדוחות</a></p>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>"""


def build_subject(week):
    return f"📚 דוח L&D שבועי מוכן – {week_label(week)}"


PLAIN_BODY = "10 הכתבות המובילות בעולם הלמידה והפיתוח השבוע. פתח לקרוא."
