#!/usr/bin/env python3
"""Build the weekly L&D Articles note, and install it into Avi's vault.

Split in two, because the vault is a local folder with no git remote and the
cloud cannot reach it:

  RENDER  runs in the Friday workflow (`--emit <path>`) and commits the note
          markdown into the repo as reports/<week>/vault-note.md, so the note
          EXISTS whether or not the Mac is on.
  INSTALL runs on the Mac (`--install-all`) and copies every rendered note the
          vault is missing. It walks all weeks, not just the newest: before
          this, a Mac that was off across a Friday lost that week's note
          permanently, because only the latest week was ever considered.

Source of truth is the committed reports/<week>/articles.json, not the HTML.
The sibling AI News pipeline regexes its own rendered page back apart, which
couples the note to the page's markup; reading the structured data avoids that
entirely.

Idempotent throughout: an existing vault note is never overwritten.

Usage:
  python3 sync_vault_note.py [week]              write one week into the vault
  python3 sync_vault_note.py <week> --emit PATH  render to PATH, no vault touch
  python3 sync_vault_note.py --install-all       backfill every missing week
"""
import datetime
import json
import os
import re
import sys

# Default to the repo this script lives in, which is correct on the Mac clone
# and on a CI runner alike. A Mac-path default made the Friday `--emit` step
# read a directory that does not exist on a runner.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.environ.get("LD_SITE_CLONE", _REPO_ROOT)
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
        # weekly-digest, not report: this is the value the folder's map-of-content
        # dataview filters on, matching the sibling Trending Repos convention.
        "type: weekly-digest",
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


NOTE_SUFFIX = "L&D Articles"
INDEX_NOTE = "📌 L&D Articles — מפת תוכן.md"
INDEX_START = "<!-- INDEX:START -->"
INDEX_END = "<!-- INDEX:END -->"


def render_note(week):
    """The note markdown for a week, or None when the report has no articles.

    Touches nothing outside the reports directory, so it is safe to run in CI
    where no vault exists.
    """
    data = load_articles(week)
    if not data.get("articles"):
        print(f"No articles in {week} report; nothing to render.")
        return None
    return build_note(week, data)


def all_weeks():
    return sorted(
        d for d in os.listdir(REPORTS_DIR)
        if os.path.isdir(os.path.join(REPORTS_DIR, d)) and re.fullmatch(r"\d{4}-W\d+", d)
    )


def note_path_for(week):
    return os.path.join(VAULT_DIR, f"{week} {NOTE_SUFFIX}.md")


def install_all():
    """Backfill every week the vault is missing a note for.

    Prefers the note rendered in the cloud (reports/<week>/vault-note.md) and
    falls back to rendering locally, so weeks published before the cloud render
    existed are still recoverable.
    """
    os.makedirs(VAULT_DIR, exist_ok=True)
    weeks = all_weeks()
    written = 0
    for week in weeks:
        target = note_path_for(week)
        if os.path.exists(target):
            continue
        cloud = os.path.join(REPORTS_DIR, week, "vault-note.md")
        if os.path.exists(cloud):
            content, origin = open(cloud, encoding="utf-8").read(), "cloud"
        else:
            content, origin = render_note(week), "rendered locally"
        if not content or not content.strip():
            print(f"{week}: nothing to write, skipping")
            continue
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"{week}: note written ({origin}) -> {target}")
        written += 1
    print(f"install-all: {written} note(s) written, {len(weeks)} week(s) checked")
    update_index()
    return 0



def _friday_of(week):
    """The Friday a week's report was built, derived from the ISO week itself."""
    try:
        year, num = week.split("-W")
        return datetime.date.fromisocalendar(int(year), int(num), 5).isoformat()
    except ValueError:
        return ""


def installed_weeks():
    """Weeks that have both a published report and a note in the vault.

    Derived from the reports directory and probed one path at a time, NOT by
    listing the vault. Under launchd, macOS TCC lets this process stat a known
    file under ~/Documents but denies enumerating the directory, so os.listdir
    on the vault raises PermissionError while os.path.exists on a file inside
    it succeeds. Observed 2026-08-22.
    """
    return [w for w in reversed(all_weeks()) if os.path.exists(note_path_for(w))]


def render_index(weeks):
    """The generated table of contents for the vault folder.

    Plain markdown with wikilinks rather than a dataview query, so it reads
    correctly in preview, in source mode, and anywhere the note is exported or
    opened outside Obsidian.
    """
    lines = [INDEX_START,
             "<!-- נוצר אוטומטית על ידי sync_vault_note.py. אין לערוך ידנית. -->",
             ""]
    if not weeks:
        lines.append("_עוד אין דוחות._")
    else:
        lines.append("| שבוע | תאריך | פתק | דוח מלא |")
        lines.append("|---|---|---|---|")
        for week in weeks:
            lines.append(f"| `{week}` | {_friday_of(week)} "
                         f"| [[{week} {NOTE_SUFFIX}]] "
                         f"| [פתח]({BASE_URL}/{week}/) |")
        lines.append("")
        lines.append(f"_{len(weeks)} דוחות._")
    lines.append(INDEX_END)
    return "\n".join(lines)


def update_index():
    """Refresh the generated block inside the folder's index note.

    Marker scoped: the note carries hand-written documentation above the table
    which has to survive.
    """
    path = os.path.join(VAULT_DIR, INDEX_NOTE)
    table = render_index(installed_weeks())
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        print(f"index note not found at {path}, skipping")
        return
    if INDEX_START in text and INDEX_END in text:
        text = (text[:text.index(INDEX_START)] + table
                + text[text.index(INDEX_END) + len(INDEX_END):])
    else:
        text = text.rstrip("\n") + "\n\n## 📝 כל הדוחות\n\n" + table + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"index updated: {path}")


def main():
    args = sys.argv[1:]
    if "--install-all" in args:
        return install_all()

    emit = None
    if "--emit" in args:
        i = args.index("--emit")
        try:
            emit = args[i + 1]
        except IndexError:
            print("--emit needs a path", file=sys.stderr)
            return 2
        del args[i:i + 2]

    week = args[0] if args else latest_week()

    if emit:
        content = render_note(week)
        if not content or not content.strip():
            print(f"Refusing to emit an empty note for {week}.", file=sys.stderr)
            return 1
        os.makedirs(os.path.dirname(os.path.abspath(emit)) or ".", exist_ok=True)
        with open(emit, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Note rendered: {emit} ({len(content)} chars)")
        return 0

    target = note_path_for(week)
    if os.path.exists(target):
        print(f"Vault note already exists for {week}, skipping.")
        return 0
    content = render_note(week)
    if not content:
        return 0
    os.makedirs(VAULT_DIR, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"note written: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
