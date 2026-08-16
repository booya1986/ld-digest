#!/usr/bin/env python3
"""Write the weekly L&D Articles note into Avi's Obsidian vault.

The cloud workflow cannot reach the vault, so it only commits the report into
the git repo. This script runs locally (launchd, via vault_note_only.sh) and
turns the published report into an Obsidian note.

Source of truth is the committed reports/<week>/articles.json, not the HTML.
The sibling trending-repos pipeline regexes its own rendered page back apart,
which couples the note to the page's markup; reading the structured data
avoids that entirely.

Idempotent: exits early if the week's note already exists.
Usage: python3 sync_vault_note.py [week]
"""
import datetime
import json
import os
import re
import sys

SITE_DIR = os.environ.get(
    "LD_SITE_CLONE",
    os.path.expanduser("~/Library/Application Support/ld-digest/ld-site"),
)
VAULT_DIR = os.path.expanduser("~/Documents/avi-workspace/Researches/L&D Articles")
REPORTS_DIR = os.path.join(SITE_DIR, "reports")
BASE_URL = "https://booya1986.github.io/ld-digest/reports"

LANE_HE = {
    "ai_ld": "AI בלמידה",
    "id_craft": "עיצוב למידה",
    "learning_tech": "טכנולוגיות למידה",
    "strategy": "אסטרטגיה",
}


def latest_week():
    weeks = sorted(
        d for d in os.listdir(REPORTS_DIR)
        if os.path.isdir(os.path.join(REPORTS_DIR, d)) and re.fullmatch(r"\d{4}-W\d{2}", d)
    )
    if not weeks:
        raise SystemExit("No report week folders found.")
    return weeks[-1]


def load_articles(week):
    path = os.path.join(REPORTS_DIR, week, "articles.json")
    if not os.path.exists(path):
        raise SystemExit(f"No articles.json for {week} (has the report been pulled?)")
    return json.load(open(path, encoding="utf-8"))


def build_note(week, data):
    articles = data.get("articles", [])
    created = data.get("generated_for") or datetime.date.today().isoformat()

    # Every field here is required by the vault schema. Jarvis's nightly ingest
    # skips or misclassifies notes with incomplete frontmatter.
    lines = [
        "---",
        "description: דוח שבועי - הכתבות המובילות בלמידה, פיתוח והדרכה",
        "type: report",
        "category: research",
        "lang: he",
        "status: active",
        "tags: [ld, instructional-design, learning-tech, weekly-digest, research]",
        "text-to-speech: no",
        f"created: {created}",
        f"week: {week}",
        "---",
        "",
        f"# 📚 עיכול L&D שבועי — {week}",
        "",
        f"דוח שבועי: {len(articles)} הכתבות הרלוונטיות ביותר בלמידה, פיתוח והדרכה לשבוע "
        f"{week.split('-W')[-1]}.",
        "",
        f"[📱 הדוח המלא]({BASE_URL}/{week}/)",
        "",
        "---",
        "",
    ]

    for a in articles:
        headline = a.get("headline_he") or a.get("headline_en") or ""
        url = a.get("url", "")
        source = a.get("source", "")
        published = (a.get("published") or "")[:10]
        lane = LANE_HE.get(a.get("lane", "strategy"), "")

        lines.append(f"## [{headline}]({url})")
        meta = " · ".join(x for x in (source, published, lane) if x)
        lines.append(f"_{meta}_")
        lines.append("")

        if a.get("summary_he"):
            lines.append(f"**תקציר:** {a['summary_he']}")
            lines.append("")
        if a.get("summary_en"):
            lines.append(f"_{a['summary_en']}_")
            lines.append("")

        insights_he = a.get("insights_he") or []
        if insights_he:
            lines.append("**תובנות מפתח:**")
            lines.extend(f"- {i}" for i in insights_he)
            lines.append("")

        if a.get("matters_he"):
            lines.append(f"**למה זה רלוונטי לך:** {a['matters_he']}")
            lines.append("")
        if a.get("matters_en"):
            lines.append(f"_{a['matters_en']}_")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    week = sys.argv[1] if len(sys.argv) > 1 else latest_week()
    os.makedirs(VAULT_DIR, exist_ok=True)
    note_path = os.path.join(VAULT_DIR, f"{week} L&D Articles.md")

    if os.path.exists(note_path):
        print(f"Vault note already exists for {week}, skipping.")
        return

    data = load_articles(week)
    if not data.get("articles"):
        print(f"No articles in {week} report; not writing an empty note.")
        return

    with open(note_path, "w", encoding="utf-8") as f:
        f.write(build_note(week, data))
    print(f"note written: {note_path}")


if __name__ == "__main__":
    main()
