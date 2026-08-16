# L&D Weekly Digest

The 10 most relevant articles each week in learning & development, instructional
design, and learning technology. Built Friday, emailed Sunday morning.

**Live:** https://booya1986.github.io/ld-digest/reports/
**This week:** `https://booya1986.github.io/ld-digest/reports/<YYYY-Www>/`

---

## The weekly chain

**Friday 07:05 IL** — `.github/workflows/friday-articles.yml`

| # | Step | What it does | Fails the run? |
|---|---|---|---|
| 1 | `fetch_ld_articles.py` | Reads `scripts/feeds.json`, pulls ~23 RSS/Atom feeds + Hacker News, filters to the L&D beat, scores, dedupes (within the week and against all prior weeks), and guarantees each of the four lanes a share of the candidate pool | Yes, if zero candidates |
| 2 | dedup gate | Skips everything if `reports/<week>/index.html` already exists | — |
| 3 | `discover_articles.py` | Anthropic web search for anything the feeds missed. Findings join the pool as ordinary candidates and get no special standing | No |
| 4 | `extract_content.py` | Pulls the real article body for the top 15 candidates. Firecrawl if `FIRECRAWL_API_KEY` is set, plain fetch otherwise | No |
| 5 | `generate_briefs.py` | One Claude call picks the best 10 and writes Hebrew + English summary, 3 key insights, and why-it-matters for each | No (degrades to headlines) |
| 6 | `review_briefs.py` | **Editorial gate.** A second Claude pass judges each brief against the source text, and rewrites the ones that are generic, unsupported, or unspecific. Up to 2 rounds | No |
| 7 | `build_report.py` | Renders `index.html` + `articles.json` | Yes |
| 8 | `build_og_image.py` | Renders the 1200×630 social card so shared links preview properly | No |
| 9 | `build_index.py` | Regenerates the archive index from the directories that exist | Yes |
| 10 | commit + push | GitHub Pages serves it as static files, no build step | Yes |

**Sunday 07:07 IL** — `.github/workflows/sunday-digest.yml`
Finds the latest week, sends via Gmail SMTP, commits the `.email_sent` dedup marker.

**Continuously (local)** — a launchd agent runs `sync_vault_note.py` every 6 hours,
which turns the published report into an Obsidian note in
`~/Documents/avi-workspace/Researches/L&D Articles/`. The cloud cannot reach the
vault, which is why this one piece is local.

---

## Repository layout

```
scripts/
  feeds.json             curated sources: name, url, tier, lane
  fetch_ld_articles.py   collect, filter, score, dedupe, diversify
  discover_articles.py   web-search top-up (Anthropic server-side search)
  extract_content.py     article body extraction (Firecrawl or direct)
  generate_briefs.py     select 10 + write bilingual briefs
  review_briefs.py       editorial review and rewrite loop
  build_report.py        index.html + articles.json + social meta
  build_og_image.py      og.png (1200x630)
  build_index.py         reports/index.html archive
  send_digest.py         email HTML (library)
  send_digest_smtp.py    email sending
  sync_vault_note.py     Obsidian note (runs locally only)
reports/<YYYY-Www>/
  index.html  articles.json  og.png  .email_sent
```

## Secrets

| Secret | Needed by | Required? |
|---|---|---|
| `ANTHROPIC_API_KEY` | briefs, editorial review, web-search top-up | Yes |
| `GMAIL_APP_PASSWORD` | Sunday email | Yes |
| `FIRECRAWL_API_KEY` | better article extraction | Optional; falls back to direct fetch |

## Adding or removing a source

Edit `scripts/feeds.json`. Each entry needs `name`, `url`, `tier` (1 authoritative,
2 practitioner, 3 general business), and `lane` (`ai_ld`, `id_craft`,
`learning_tech`, `strategy`).

**Verify the URL first.** A feed that 404s or parses zero items is dropped, not kept
hopefully: `python3 -m pytest scripts/ -q` checks the file's shape, and the fetch
step emits a `::warning` for any feed that returns nothing. Low-frequency expert
blogs are deliberately kept even though they are silent most weeks.

## Testing

```bash
python3 -m pytest scripts/ -q                 # 29 unit tests, no network

# Full dry run in CI: builds into a temp dir, uploads an artifact,
# never commits and never emails.
gh workflow run "Friday L&D articles" --repo booya1986/ld-digest -f dry_run=true
```

## Design rules worth keeping

These are inherited from the sibling trending-repos pipeline, where each was
learned by breaking:

1. **`git add` one path at a time, and only when it exists.** A single
   `git add -f a b c` with one path missing stages *nothing*. That is how a
   dedup marker went uncommitted and shipped six copies of one email.
2. **Structured outputs, not "return only JSON."** Truncated JSON silently
   emptied two weeks of briefs in the sibling repo.
3. **The model selects by array index, never by echoing a URL.** Links come
   from fetched data, so a hallucinated link is structurally impossible.
4. **Read the first *text* block, never `content[0]`** — thinking is on by
   default on `claude-opus-5` and a thinking block has no `.text`.
5. **Word-boundary matching for short signal terms.** Naive substring matching
   put `ai` inside *tr**ai**ning* and collapsed the lane balance.
6. **Nothing in the enrichment path may fail the build.** Discovery, extraction,
   review, and the social card all degrade rather than break the digest.
7. **One home for the code.** No mirrored copy of these scripts anywhere else.
