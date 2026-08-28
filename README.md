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

**Sunday 07:30 IL** — `.github/workflows/sunday-digest.yml`
Finds the latest week, sends via Gmail SMTP to everyone in the `DIGEST_TO` repo
variable, commits the `.email_sent` dedup marker.

Triggered by a claude.ai routine that pushes `.send-trigger` at 07:25 IL.
GitHub's own cron cannot promise a time (41 minutes late on 2026-08-23, absent
on 2026-08-16), and a push starts a workflow immediately. GitHub's cron is now
only a late backup, starting after 07:30 in both Israeli timezones.

**The vault note.** The vault is a plain local folder with no git remote, so CI
cannot write into it. The note is therefore *rendered* in the Friday run
(`sync_vault_note.py --emit`) and committed as `reports/<week>/vault-note.md`,
which means it exists whether or not the Mac is on. A launchd agent
(`com.avilevi.ld-vault-note`) then copies into
`~/Documents/avi-workspace/Researches/L&D Articles/` every week the vault is
missing, via `--install-all`.

Two failures produced that design, both on 2026-08-21 (W34):

* The agent ran on `StartInterval` alone and `launchctl print` showed
  `runs = 2` across two days. A `StartInterval` timer does not catch up on a
  Mac that sits in deep-idle sleep, which is the same reason
  `StartCalendarInterval` had been abandoned earlier. The plist now carries
  both, plus an hourly backstop and a retry re-arm.
* The script only ever considered the **latest** week, so a Mac that was off
  across a Friday did not delay that week's note, it lost it: the next week's
  run would find a newer report and skip the gap permanently. `--install-all`
  walks every week.

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
  sync_vault_note.py     Obsidian note: --emit renders in CI, --install-all copies locally
reports/<YYYY-Www>/
  index.html  articles.json  og.png  vault-note.md  .email_sent
```

## Secrets

| Secret | Needed by | Required? |
|---|---|---|
| `ANTHROPIC_API_KEY` | briefs, editorial review, web-search top-up | Yes |
| `GMAIL_APP_PASSWORD` | Sunday email | Yes |
| `FIRECRAWL_API_KEY` | better article extraction | Optional; falls back to direct fetch |

## Variables

| Variable | Meaning |
|---|---|
| `DIGEST_TO` | Comma separated recipient list for the Sunday email. Unset means Avi alone. Held as a repo variable so changing the audience is not a code change |

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
python3 -m pytest scripts/ -q                 # unit tests, no network

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

## Reports

<!-- REPORTS:START -->
<!-- Generated by scripts/build_index.py on every build. Do not edit by hand. -->

| Week | Date | Report | Articles | Emailed |
|---|---|---|---|---|
| `2026-W35` | 2026-08-28 | [open](https://booya1986.github.io/ld-digest/reports/2026-W35/) | 10 |  |
| `2026-W34` | 2026-08-21 | [open](https://booya1986.github.io/ld-digest/reports/2026-W34/) | 10 | ✅ |
| `2026-W33` | 2026-08-16 | [open](https://booya1986.github.io/ld-digest/reports/2026-W33/) | 10 | ✅ |

_3 reports._
<!-- REPORTS:END -->
