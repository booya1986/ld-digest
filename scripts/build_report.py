#!/usr/bin/env python3
"""Build the mobile-responsive HTML report from the enriched articles JSON.

Reads the JSON emitted by generate_briefs.py (stdin or --in), and writes:
  - <outdir>/index.html     mobile-friendly report page
  - <outdir>/articles.json  structured data the email and vault note read

Design system: matches Avi's blog and the sibling trending-repos report.
Hebrew RTL by default with an EN toggle.

The .card / .brief-section DOM shape is a contract, not decoration:
sync_vault_note.py parses the published HTML back into an Obsidian note.
"""
import argparse
import html
import json
import os
import sys

SITE_BASE = "https://booya1986.github.io/ld-digest/reports"

LANE_TAGS = {
    "ai_ld":         ("AI בלמידה",        "AI in L&D"),
    "id_craft":      ("עיצוב למידה",      "Learning design"),
    "learning_tech": ("טכנולוגיות למידה", "Learning tech"),
    "strategy":      ("אסטרטגיה",         "Strategy"),
}

BRIEF_LABELS = {
    "Summary":                {"he": "תקציר",             "en": "Summary"},
    "Key insights":           {"he": "תובנות מפתח",       "en": "Key insights"},
    "Why it matters for you": {"he": "למה זה רלוונטי לך", "en": "Why it matters for you"},
}


def _labels(label_en):
    return BRIEF_LABELS.get(label_en, {"he": label_en, "en": label_en})


def wrap_brief_section(label_en, text_he, text_en=None, is_matters=False):
    """A brief-section div with a bilingual label and bilingual body text."""
    if text_en is None:
        text_en = text_he
    labels = _labels(label_en)
    cls = "brief-section brief-section--matters" if is_matters else "brief-section"
    return (
        f'<div class="{cls}">'
        f'<p class="brief-label" data-he="{html.escape(labels["he"])}" '
        f'data-en="{html.escape(labels["en"])}">{html.escape(labels["he"])}</p>'
        f'<p class="brief-text i18n" data-he="{html.escape(text_he)}" '
        f'data-en="{html.escape(text_en)}">{html.escape(text_he)}</p>'
        f'</div>'
    )


def wrap_brief_list(label_en, items_he, items_en=None):
    """Same contract as wrap_brief_section, but the body is a <ul>.

    The bilingual payload rides on the <ul> as newline-joined data-he/data-en
    so the language toggle can rebuild the list, and so sync_vault_note.py can
    recover the bullets without parsing every <li>.
    """
    items_he = [i for i in (items_he or []) if i]
    items_en = [i for i in (items_en or []) if i] or items_he
    if not items_he:
        return ""
    labels = _labels(label_en)
    lis = "".join(f"<li>{html.escape(i)}</li>" for i in items_he)
    return (
        f'<div class="brief-section">'
        f'<p class="brief-label" data-he="{html.escape(labels["he"])}" '
        f'data-en="{html.escape(labels["en"])}">{html.escape(labels["he"])}</p>'
        f'<ul class="brief-list i18n-list" '
        f'data-he="{html.escape(chr(10).join(items_he))}" '
        f'data-en="{html.escape(chr(10).join(items_en))}">{lis}</ul>'
        f'</div>'
    )


def render_cards(articles):
    cards = []
    for i, a in enumerate(articles, 1):
        url = html.escape(a.get("url", ""))
        source = html.escape(a.get("source", ""))
        published = html.escape((a.get("published") or "")[:10])
        head_he = a.get("headline_he") or a.get("headline_en") or ""
        head_en = a.get("headline_en") or head_he
        lane_he, lane_en = LANE_TAGS.get(a.get("lane", "strategy"), LANE_TAGS["strategy"])

        body = ""
        if a.get("summary_he") or a.get("summary_en"):
            body += wrap_brief_section(
                "Summary", a.get("summary_he") or "", a.get("summary_en") or "")
        body += wrap_brief_list(
            "Key insights", a.get("insights_he"), a.get("insights_en"))
        if a.get("matters_he") or a.get("matters_en"):
            body += wrap_brief_section(
                "Why it matters for you",
                a.get("matters_he") or "", a.get("matters_en") or "", is_matters=True)
        if not body:
            body = f'<p class="desc">{html.escape(a.get("summary_en") or "")}</p>'

        cards.append(f"""
    <article class="card">
      <div class="card__rank">#{i}</div>
      <div class="card__body">

        <div class="card__header">
          <div class="card__title-block">
            <p class="card__eyebrow">{source}</p>
            <h2 class="card__title">
              <a href="{url}" target="_blank" rel="noopener"
                 class="i18n" data-he="{html.escape(head_he)}"
                 data-en="{html.escape(head_en)}">{html.escape(head_he)}</a>
            </h2>
          </div>
        </div>

        <div class="card__meta">
          <span class="meta-item"><span class="meta-icon">&#128197;</span> {published}</span>
        </div>

        <div class="card__tags">
          <span class="tag i18n" data-he="{html.escape(lane_he)}"
                data-en="{html.escape(lane_en)}">{html.escape(lane_he)}</span>
        </div>

        <div class="card__content">{body}</div>

        <a class="card__cta" href="{url}" target="_blank" rel="noopener">
          <span class="i18n" data-he="קרא את הכתבה המלאה" data-en="Read the full article">קרא את הכתבה המלאה</span>
          <span class="cta-arrow">&#8592;</span>
        </a>

      </div>
    </article>""")
    return "\n".join(cards)


def render_html(data):
    week = data.get("week", "")
    generated_for = data.get("generated_for", "")
    articles = data.get("articles", [])
    cards_html = render_cards(articles)
    week_display = html.escape(week)
    count = len(articles)

    # Social preview. WhatsApp, Slack, LinkedIn, and X all read og:*; without
    # it a shared link renders as a bare grey box. The URLs must be absolute.
    page_url = f"{SITE_BASE}/{week}/"
    og_image = f"{SITE_BASE}/{week}/og.png"
    og_title = f"עיכול L&D שבועי — {week}"
    lead = ""
    if articles:
        lead = (articles[0].get("headline_he") or articles[0].get("headline_en") or "")
    og_desc = f"{count} הכתבות המובילות בלמידה, פיתוח והדרכה"
    if lead:
        og_desc += f". פותח ב: {lead}"
    og_desc = og_desc[:200]

    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1b1b1b">
<title>עיכול L&amp;D שבועי {week_display}</title>
<meta name="description" content="{html.escape(og_desc)}">
<link rel="canonical" href="{html.escape(page_url)}">

<meta property="og:type" content="article">
<meta property="og:site_name" content="עיכול L&amp;D שבועי">
<meta property="og:locale" content="he_IL">
<meta property="og:url" content="{html.escape(page_url)}">
<meta property="og:title" content="{html.escape(og_title)}">
<meta property="og:description" content="{html.escape(og_desc)}">
<meta property="og:image" content="{html.escape(og_image)}">
<meta property="og:image:secure_url" content="{html.escape(og_image)}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{html.escape(og_title)}">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(og_title)}">
<meta name="twitter:description" content="{html.escape(og_desc)}">
<meta name="twitter:image" content="{html.escape(og_image)}">

<link rel="icon" href="data:image/svg+xml,&lt;svg xmlns=&quot;http://www.w3.org/2000/svg&quot; viewBox=&quot;0 0 100 100&quot;&gt;&lt;text y=&quot;.9em&quot; font-size=&quot;90&quot;&gt;&#128218;&lt;/text&gt;&lt;/svg&gt;">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Hebrew:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #1b1b1b;
    --bg-elevated: #232323;
    --fg: #c5c1b9;
    --fg-strong: #dcdad5;
    --fg-muted: #a09d96;
    --fg-subtle: #96928c;
    --accent: #22c55e;
    --accent-glow: rgba(34,197,94,0.6);
    --accent-soft: rgba(34,197,94,0.12);
    --accent-softer: rgba(34,197,94,0.04);
    --accent-border: rgba(34,197,94,0.12);
    --accent-border-hover: rgba(34,197,94,0.3);
    --shadow-glow-md: 0 0 15px rgba(34,197,94,0.3), 0 0 40px rgba(34,197,94,0.1);
    --text-glow: 0 0 8px rgba(34,197,94,0.6), 0 0 20px rgba(34,197,94,0.3);
    --font-sans: 'Noto Sans Hebrew', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
    --radius-pill: 999px;
    --transition: 0.3s cubic-bezier(0.4,0,0.2,1);
    --transition-fast: 0.15s cubic-bezier(0.4,0,0.2,1);
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ -webkit-text-size-adjust: 100%; }}

  body {{
    background: var(--bg);
    color: var(--fg);
    font-family: var(--font-sans);
    font-size: clamp(1rem, 2vw, 1.0625rem);
    line-height: 1.7;
    padding-top: env(safe-area-inset-top);
    padding-bottom: env(safe-area-inset-bottom);
    overflow-x: hidden;
  }}

  /* ── GRID BACKGROUND ── */
  body::before {{
    content: '';
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    background-image:
      linear-gradient(rgba(34,197,94,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(34,197,94,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, black 40%, transparent 100%);
    -webkit-mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, black 40%, transparent 100%);
  }}

  .wrap {{
    position: relative;
    z-index: 1;
    max-width: 720px;
    margin: 0 auto;
    padding: 24px 16px 80px;
  }}

  /* ── TOP BAR ── */
  .top-bar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    gap: 10px;
  }}
  .lang-btn, .share-btn {{
    background: var(--accent-softer);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-pill);
    color: var(--accent);
    font-family: var(--font-sans);
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.5px;
    padding: 7px 16px;
    cursor: pointer;
    transition: all var(--transition-fast);
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 44px;
    -webkit-tap-highlight-color: transparent;
  }}
  .lang-btn:hover, .share-btn:hover {{
    background: var(--accent-soft);
    border-color: var(--accent);
    box-shadow: 0 0 10px var(--accent-glow);
  }}
  .share-btn svg {{ width: 16px; height: 16px; stroke: var(--accent); }}
  .share-copied {{
    font-size: 0.72rem;
    color: var(--accent);
    margin-top: 4px;
    text-align: center;
    opacity: 0;
    transition: opacity 0.3s;
  }}
  .share-copied.show {{ opacity: 1; }}

  /* ── HEADER ── */
  .site-header {{ margin-bottom: 28px; }}
  .header-eyebrow {{
    font-size: 0.8rem;
    font-weight: 500;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent);
    text-shadow: var(--text-glow);
    margin-bottom: 6px;
  }}
  .header-title {{
    font-size: clamp(1.6rem, 4vw, 2.2rem);
    font-weight: 700;
    color: var(--fg-strong);
    line-height: 1.3;
    text-shadow: 0 0 30px rgba(34,197,94,0.1);
    margin-bottom: 4px;
  }}
  .header-sub {{
    font-size: 0.875rem;
    color: var(--fg-muted);
    font-weight: 300;
  }}

  /* ── CARDS ── */
  .card {{
    position: relative;
    background: var(--accent-softer);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-lg);
    margin-bottom: 16px;
    transition: border-color var(--transition), background var(--transition), box-shadow var(--transition);
  }}
  .card:hover {{
    border-color: var(--accent-border-hover);
    background: rgba(34,197,94,0.07);
    box-shadow: var(--shadow-glow-md), 0 12px 32px rgba(0,0,0,0.25);
  }}

  .card__rank {{
    position: absolute;
    top: -1px;
    right: 20px;
    background: var(--accent);
    color: #0a1a0f;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.5px;
    padding: 3px 10px;
    border-radius: 0 0 var(--radius-sm) var(--radius-sm);
  }}
  [dir="ltr"] .card__rank {{ right: auto; left: 20px; }}

  .card__body {{ padding: 28px 20px 20px; }}

  .card__header {{
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 10px;
  }}
  .card__title-block {{ flex: 1; min-width: 0; }}
  .card__eyebrow {{
    font-size: 0.78rem;
    font-weight: 500;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--accent);
    text-shadow: var(--text-glow);
    margin-bottom: 4px;
  }}
  .card__title {{
    font-size: 1.1rem;
    font-weight: 600;
    line-height: 1.35;
  }}
  .card__title a {{
    color: var(--fg-strong);
    text-decoration: none;
    transition: color var(--transition-fast);
    word-break: break-word;
  }}
  .card__title a:hover {{ color: var(--accent); }}

  .card__meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    font-size: 0.78rem;
    color: var(--fg-subtle);
    margin-bottom: 10px;
  }}
  .meta-icon {{ opacity: 0.5; }}

  .card__tags {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 16px;
  }}
  .tag {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: var(--radius-pill);
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    color: var(--accent);
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.3px;
    white-space: nowrap;
    transition: all var(--transition-fast);
  }}
  .tag:hover {{
    background: rgba(34,197,94,0.16);
    border-color: var(--accent);
    box-shadow: 0 0 10px var(--accent-glow);
  }}

  /* ── BRIEF SECTIONS ── */
  .card__content {{ display: flex; flex-direction: column; gap: 0; }}

  .brief-section {{
    padding: 10px 0;
    border-top: 1px solid var(--accent-border);
  }}
  .brief-section:first-child {{ border-top: none; padding-top: 0; }}

  .brief-label {{
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--accent);
    text-shadow: var(--text-glow);
    margin-bottom: 4px;
  }}
  .brief-text {{
    font-size: 0.9375rem;
    color: var(--fg-muted);
    font-weight: 300;
    line-height: 1.7;
  }}

  .brief-list {{
    font-size: 0.9375rem;
    color: var(--fg-muted);
    font-weight: 300;
    line-height: 1.65;
    padding-right: 18px;
    margin-top: 2px;
  }}
  [dir="ltr"] .brief-list {{ padding-right: 0; padding-left: 18px; }}
  .brief-list li {{ margin-bottom: 5px; }}
  .brief-list li::marker {{ color: var(--accent); }}

  /* "Why it matters" gets a highlight treatment */
  .brief-section--matters {{
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-md);
    padding: 10px 14px;
    margin-top: 8px;
  }}
  .brief-section--matters .brief-label {{ margin-bottom: 3px; }}
  .brief-section--matters .brief-text {{
    color: var(--fg-strong);
    font-weight: 400;
  }}

  .desc {{ font-size: 0.9375rem; color: var(--fg-muted); font-weight: 300; line-height: 1.7; }}

  /* ── CARD CTA ── */
  .card__cta {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-top: 14px;
    padding: 9px 18px;
    border-radius: var(--radius-pill);
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    color: var(--accent);
    font-size: 0.82rem;
    font-weight: 600;
    text-decoration: none;
    transition: all var(--transition-fast);
    min-height: 42px;
  }}
  .card__cta:hover {{
    background: var(--accent);
    color: #0a1a0f;
    border-color: var(--accent);
    box-shadow: 0 0 14px var(--accent-glow);
  }}
  /* RTL reading flow: a "leads to" arrow points left. Flip it for LTR. */
  .cta-arrow {{ font-size: 1rem; line-height: 1; }}
  [dir="ltr"] .cta-arrow {{ transform: scaleX(-1); display: inline-block; }}

  /* ── SECTION HEADINGS ── */
  .section-eyebrow {{
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent);
    text-shadow: var(--text-glow);
    margin-bottom: 4px;
  }}
  .section-sub {{
    font-size: 0.78rem;
    color: var(--fg-subtle);
    margin-bottom: 14px;
  }}

  /* ── FOOTER ── */
  .site-footer {{
    margin-top: 40px;
    font-size: 0.78rem;
    color: var(--fg-subtle);
    text-align: center;
    border-top: 1px solid var(--accent-border);
    padding-top: 20px;
  }}
  a {{ color: var(--accent); }}

  /* ── MOBILE SAFETY ── */
  img, video {{ max-width: 100%; }}
  @media (max-width: 480px) {{
    .card__body {{ padding: 28px 14px 16px; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <div class="top-bar">
    <button class="lang-btn" id="langToggle" onclick="toggleLang()">EN</button>
    <button class="share-btn" id="shareBtn" onclick="shareReport()" aria-label="Share">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
        <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
      </svg>
      <span class="i18n" data-he="שתף" data-en="Share">שתף</span>
    </button>
  </div>

  <header class="site-header">
    <p class="header-eyebrow i18n" data-he="עיכול L&amp;D שבועי" data-en="Weekly L&amp;D Digest">עיכול L&amp;D שבועי</p>
    <h1 class="header-title i18n" data-he="&#128218; למידה, פיתוח והדרכה" data-en="&#128218; Learning &amp; Development">&#128218; למידה, פיתוח והדרכה</h1>
    <p class="header-sub">{week_display} &middot; {html.escape(generated_for)}</p>
  </header>

  <p class="section-eyebrow i18n" data-he="&#128218; {count} הכתבות המובילות" data-en="&#128218; Top {count} Articles">&#128218; {count} הכתבות המובילות</p>
  <p class="section-sub i18n" data-he="מה שכדאי לקרוא השבוע בלמידה, בעיצוב הדרכה ובטכנולוגיות למידה" data-en="This week's best reading in L&amp;D, instructional design, and learning technology">מה שכדאי לקרוא השבוע בלמידה, בעיצוב הדרכה ובטכנולוגיות למידה</p>

  <main id="articleList">
{cards_html}
  </main>

  <footer class="site-footer">
    <span class="i18n" data-he="עיכול אוטומטי שבועי &middot; מקורות: בלוגים ומגזינים מובילים בתחום הלמידה" data-en="Auto-generated weekly digest &middot; Sources: leading L&amp;D blogs and publications">עיכול אוטומטי שבועי &middot; מקורות: בלוגים ומגזינים מובילים בתחום הלמידה</span>
    <p class="share-copied" id="shareCopied">&#128279; <span class="i18n" data-he="הקישור הועתק!" data-en="Link copied!">הקישור הועתק!</span></p>
  </footer>

</div>

<script>
// ── LANGUAGE TOGGLE ──
var currentLang = 'he';
function toggleLang() {{
  currentLang = currentLang === 'he' ? 'en' : 'he';
  var isHe = currentLang === 'he';
  document.documentElement.lang = currentLang;
  document.documentElement.dir = isHe ? 'rtl' : 'ltr';
  document.getElementById('langToggle').textContent = isHe ? 'EN' : 'עב';
  document.querySelectorAll('.i18n').forEach(function(el) {{
    var v = el.dataset[currentLang];
    if (v !== undefined) el.innerHTML = v;
  }});
  // Bulleted lists carry their items as newline-joined data attributes.
  document.querySelectorAll('.i18n-list').forEach(function(el) {{
    var v = el.dataset[currentLang];
    if (v === undefined) return;
    el.innerHTML = v.split('\\n').filter(Boolean).map(function(item) {{
      var li = document.createElement('li');
      li.textContent = item;
      return li.outerHTML;
    }}).join('');
  }});
  document.querySelectorAll('.brief-label').forEach(function(el) {{
    var he = el.dataset.he, en = el.dataset.en;
    if (he && en) el.textContent = isHe ? he : en;
  }});
}}

// ── SHARE ──
function shareReport() {{
  var title = currentLang === 'he'
    ? 'עיכול L&D שבועי – {week_display}'
    : 'Weekly L&D Digest – {week_display}';
  var url = window.location.href;
  if (navigator.share) {{
    navigator.share({{ title: title, url: url }}).catch(function(){{}});
  }} else {{
    navigator.clipboard.writeText(url).then(function() {{
      var el = document.getElementById('shareCopied');
      el.classList.add('show');
      setTimeout(function() {{ el.classList.remove('show'); }}, 2500);
    }}).catch(function() {{
      prompt('Copy this link:', url);
    }});
  }}
}}
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default="-")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    if args.infile == "-":
        data = json.load(sys.stdin)
    else:
        data = json.load(open(args.infile, encoding="utf-8"))

    os.makedirs(args.outdir, exist_ok=True)

    with open(os.path.join(args.outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_html(data))

    # Structured data next to the page: the email and the vault note read this
    # instead of re-parsing text out of the HTML.
    payload = {
        "week": data.get("week", ""),
        "generated_for": data.get("generated_for", ""),
        "count": len(data.get("articles", [])),
        "articles": data.get("articles", []),
        "warnings": data.get("warnings", []),
    }
    with open(os.path.join(args.outdir, "articles.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"wrote {args.outdir}/index.html ({payload['count']} articles)")


if __name__ == "__main__":
    main()
