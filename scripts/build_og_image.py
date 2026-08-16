#!/usr/bin/env python3
"""Render the week's social-share card to reports/<week>/og.png (1200x630).

Usage: build_og_image.py <reports/WEEK-dir>

WhatsApp, Slack, LinkedIn, and X all preview a shared link from its og:image.
Without one the link renders as a bare grey box, which reads as broken.

Rendered by screenshotting an HTML card rather than drawing with an imaging
library: Hebrew needs RTL bidi handling and proper text shaping, which a
browser does correctly and PIL does not. Same approach as Avi's workshop
landing-page tooling.

Non-fatal: if Playwright or Chromium is unavailable the page still ships, just
without a per-week card.
"""
import json
import os
import sys

W, H = 1200, 630


def card_html(week, count, headlines):
    import html as _h
    items = "".join(
        f'<li><span class="dot"></span><span class="txt">{_h.escape(h)}</span></li>'
        for h in headlines[:3]
    )
    label = week.replace("-", " ").replace("W", "שבוע ")
    return f"""<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Hebrew:wght@300;400;600;700&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ margin:0; padding:0; background:#1b1b1b; }}
  /* Everything lives inside a fixed-size card that is screenshotted directly.
     Sizing the viewport instead lets an absolutely-positioned decoration widen
     the layout box, which pushes RTL text off the right edge. */
  .card {{ position:relative; width:{W}px; height:{H}px; overflow:hidden;
           background:#1b1b1b; color:#c5c1b9;
           font-family:'Noto Sans Hebrew',sans-serif; }}
  .bg-grid {{ position:absolute; inset:0;
    background-image:
      linear-gradient(rgba(34,197,94,0.05) 1px, transparent 1px),
      linear-gradient(90deg, rgba(34,197,94,0.05) 1px, transparent 1px);
    background-size:48px 48px;
    mask-image:radial-gradient(ellipse 80% 70% at 70% 0%, black 35%, transparent 100%);
    -webkit-mask-image:radial-gradient(ellipse 80% 70% at 70% 0%, black 35%, transparent 100%); }}
  .bg-blob {{ position:absolute; top:-150px; left:-150px;
    width:540px; height:540px; border-radius:50%;
    background:radial-gradient(circle, rgba(34,197,94,0.18) 0%, transparent 68%); }}
  .wrap {{ position:absolute; inset:0; z-index:2; padding:58px 68px;
           display:flex; flex-direction:column; }}
  .eyebrow {{ font-size:21px; font-weight:600; letter-spacing:4px; color:#22c55e;
              text-transform:uppercase; margin-bottom:16px; }}
  h1 {{ font-size:62px; font-weight:700; color:#f3f2ef; line-height:1.16;
        letter-spacing:-1px; margin-bottom:12px; }}
  .sub {{ font-size:26px; color:#a09d96; font-weight:300; margin-bottom:30px; }}
  ul {{ list-style:none; display:flex; flex-direction:column; gap:12px; }}
  li {{ font-size:22px; color:#c5c1b9; font-weight:300; display:flex;
        align-items:center; gap:12px; }}
  li span.txt {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .dot {{ width:8px; height:8px; border-radius:50%; background:#22c55e;
          flex-shrink:0; box-shadow:0 0 10px rgba(34,197,94,0.85); }}
  .foot {{ margin-top:auto; display:flex; align-items:center; gap:14px;
           font-size:20px; color:#96928c; }}
  .pill {{ background:rgba(34,197,94,0.14); border:1px solid rgba(34,197,94,0.35);
           color:#22c55e; border-radius:999px; padding:6px 20px;
           font-size:19px; font-weight:600; white-space:nowrap; }}
</style></head><body>
<div class="card">
  <div class="bg-grid"></div>
  <div class="bg-blob"></div>
  <div class="wrap">
    <div class="eyebrow">Weekly L&amp;D Digest</div>
    <h1>&#128218; למידה, פיתוח והדרכה</h1>
    <div class="sub">{count} הכתבות שכדאי לקרוא השבוע</div>
    <ul>{items}</ul>
    <div class="foot"><span class="pill">{label}</span><span>תקציר, תובנות מפתח וקישור למקור</span></div>
  </div>
</div></body></html>"""


def main():
    if len(sys.argv) < 2:
        print("usage: build_og_image.py <reports/WEEK-dir>", file=sys.stderr)
        sys.exit(2)
    outdir = sys.argv[1]

    meta_path = os.path.join(outdir, "articles.json")
    if not os.path.exists(meta_path):
        print(f"no articles.json in {outdir}; skipping OG image", file=sys.stderr)
        return
    data = json.load(open(meta_path, encoding="utf-8"))
    articles = data.get("articles", [])
    week = data.get("week", "")
    headlines = [a.get("headline_he") or a.get("headline_en") or "" for a in articles]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed; skipping OG image", file=sys.stderr)
        return

    out = os.path.join(outdir, "og.png")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": W, "height": H},
                                    device_scale_factor=1)
            page.set_content(card_html(week, len(articles), headlines),
                             wait_until="networkidle")
            # Without this the screenshot can land before the webfont swaps in,
            # and Hebrew renders in a fallback face.
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(600)
            # Screenshot the card element, not the viewport: this guarantees
            # exactly 1200x630 with nothing clipped at the edges.
            page.locator(".card").screenshot(path=out, type="png")
            browser.close()
    except Exception as e:
        print(f"OG image failed ({type(e).__name__}: {e}); page ships without it",
              file=sys.stderr)
        return

    size = os.path.getsize(out)
    print(f"wrote {out} ({size:,} bytes)")
    # WhatsApp is the strictest common consumer and gets unreliable past ~300KB.
    if size > 300_000:
        print(f"::warning title=og::og.png is {size:,} bytes; "
              f"WhatsApp previews get unreliable above ~300KB", file=sys.stderr)


if __name__ == "__main__":
    main()
