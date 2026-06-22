# Podcastwise Changelog

Newest entries first.

---

## 2026-06-21 — YouTube-watched playlist; low-confidence match confirmation
**Files:** `src/youtube_watched.py`, `src/cli.py`, `src/pipeline.py`, `src/selector.py`, `src/youtube.py`, `src/podcast_db.py`, `src/summarizer.py`, `scripts/process_lenny.py`

- Added `src/youtube_watched.py` — a "Podcasts watched on YouTube" playlist source. Episodes are matched directly by video ID (no search/matching needed) and merged into the default episode list alongside Apple Podcasts history (sorted together by date).
- `--youtube-watched` CLI flag still works standalone for previewing/limiting to just the playlist.
- Added an interactive low-confidence match confirmation: when a YouTube candidate is found but `validate_match()` rejects it (confidence below threshold, or expected guest names missing from the title), the user is shown the candidate and prompted `Use this video for the transcript? [y/N]` instead of the match being auto-rejected. Only active outside `--batch` mode; batch mode still auto-rejects and logs a `[WARN]`.
- Added `Episode.youtube_url` field so a known YouTube URL (e.g. from the watched-playlist source) can bypass search entirely.
- Added `gemini-flash-3` → `google/gemini-3-flash-preview` to `MODEL_CONFIG` (OpenRouter).
- Added `scripts/process_lenny.py` — bulk-processes all Lenny's Podcast transcripts from GitHub into an isolated `~/Documents/PodcastNotes/LennysPodcasts/` output dir and a dedicated Google Sheet, without touching the main pipeline's state.

---

## 2026-03-04 — Org-abbreviation prefix blocking guest extraction
**Files:** `src/youtube.py`

Titles like `"A16Z's David George on How Private and Public Markets..."` weren't getting guest names extracted because Pattern 3 ("Name on Topic") requires the title to start with a capitalized name, and `"A16Z's"` blocked the match. Now strips leading all-caps org-abbreviation prefixes (e.g. `A16Z's`, `NPR's`, `IBM's`) before running extraction patterns. Mixed-case prefixes like `McKinsey's` are intentionally left alone to avoid false positives.

---

## 2026-02-26 — Repeat-guest "Vol./Pt." title handling
**Files:** `src/youtube.py`

Titles like `"Gary Oldman, Vol. III"` were failing to match:
- `build_search_query()` now strips `, Vol. III` / `, Pt. 2` / `, Part 1` suffixes before building the search query (the volume indicator was poisoning search results).
- `extract_guest_names()` gained a Pattern 0 to pull the guest name out of `"Name, Vol. N"` titles, so the guest-match confidence bonus still applies.

---

## 2026-02-21 — Lenny's Podcast source; deterministic episode IDs
**Files:** `src/lenny.py`

Added `src/lenny.py` — fetches and parses transcripts from the `ChatPRD/lennys-podcast-transcripts` GitHub repo, building `Episode`/`Transcript` objects compatible with the existing summarizer and markdown writer.

`_make_episode_id()` originally used Python's built-in `hash()`, which is randomized per-process (`PYTHONHASHSEED`), so the same episode got a different ID on every run — causing duplicate state entries and re-processing already-done episodes. Switched to a SHA-256-based ID so it's stable across processes.

---

## 2026-02-20 — Guest-name extraction bug fixes
**Files:** `src/youtube.py`, `scripts/reprocess_cleared.py`

Five extraction failures in `extract_guest_names()` were letting topically-similar-but-wrong videos pass the 0.5 confidence threshold:
- Capital `"With"` not matched (`\bwith` → `\b[Ww]ith`)
- `"co-founder"` role not matched (added `Founder` + `re.IGNORECASE` to the role pattern)
- `"| Guest Name"` at the end of a title not matched (added pipe-end Pattern 4)
- `"Name & Name on Topic"` not matched (extended Pattern 3 to consume `&` before `" on "`)
- Short last names (≤5 chars) causing false positives in `name_appears_in_text`

Also fixed: em dash (`—`, U+2014) wasn't recognized as a delimiter in Pattern 1 (only en dash `–`, U+2013, was), causing `"Name — Topic"` titles (e.g. Dwarkesh Podcast episodes) to fail extraction.

Cleared and reprocessed 5 affected episodes; added `PHASE4_IDS` to `reprocess_cleared.py` for traceability.

---

## 2026-02-19 — Transcript-matching fixes, web UI, JP Morgan support
**Files:** `src/stratechery.py`, `src/youtube.py`, `src/state.py`, `src/jpmorgan.py`, `src/web/`, `scripts/fix_wrong_transcripts.py`, `scripts/reprocess_cleared.py`, `scripts/force_reexport_fixed.py`, `src/cli.py`, `src/sheets.py`, `src/markdown.py`, `src/summarizer.py`

**Transcript matching fixes:**
- `stratechery.py`: added a `content_word_overlap()` gate to `find_matching_post()` to stop false matches between structurally similar titles (e.g. "Interview with X CEO A" matching "Interview with Y CEO B"), with a template-word exclusion list (`earnings`, `notes`, `update`, etc.). Increased `max_pages` 15 → 20 to cover the ~440-post archive. Added module-level `_cached_posts` so the archive is only fetched once per batch run.
- `youtube.py`: fixed `extract_guest_names()` — removed a `re.IGNORECASE` bug that was capturing entire sentences as "guest names". Added role-based Pattern 2a (`CEO`/`Founder` + Name).
- `state.py`: added `mark_not_exported()` to reset the `exported_to_sheets` flag so corrected summaries can be re-exported.

**New helper scripts** (one-off remediation, not part of the normal pipeline):
- `scripts/fix_wrong_transcripts.py` — clears cache/state/markdown for mismatched episodes
- `scripts/reprocess_cleared.py` — re-processes specific episode IDs through the pipeline
- `scripts/force_reexport_fixed.py` — deletes stale sheet rows, resets state, re-exports

**Other additions:**
- `src/web/` — standalone Flask web UI for browsing/processing through a browser
- `src/jpmorgan.py` — JP Morgan Eye on the Market transcript support
- Various improvements to exports, retry logic, cleanup, and sheet sync across `cli.py`, `sheets.py`, `markdown.py`, `summarizer.py`

---

## 2026-02-11 — Sheet sync, cleanup, retry, manual URL override
**Files:** `src/cli.py`, `src/pipeline.py`, `src/sheets.py`, `src/state.py`, `src/summarizer.py`, `src/youtube.py`, `requirements.txt`

- Added `--sync-export-state` to sync local state with the Google Sheet
- Added `--cleanup-sheets` to remove duplicate rows from sheets
- Added `--retry-episodes` to retry failed transcript fetches
- Added `--youtube-url` for a manual YouTube URL override
- Added Guests and Date Created columns to sheet exports
- Extract guests from soundbites for backward compatibility
- Track `exported_to_sheets` state to prevent duplicate exports
- Auto-sync now always runs after processing, not just on success

---

## 2026-02-05 — Sheets columns, speed, multi-provider models, cookie auth

### Google Sheets Export — Column Updates
**Files:** `src/sheets.py`

- Removed "Who Should Listen" column
- Removed "Topics" column
- Added "TL;DR" column from `summary.tldr`
- Added "Category" column — single category per episode (mapped from existing categories)
- Updated formatting:
  - Key Insights: bulleted list
  - Frameworks: bulleted list (was pipe-separated)
  - Soundbites: bulleted list with full quotes (was truncated at 100 chars)

**Category mapping:** Tech, Entertainment, News/Politics, Finance/Economics/Investing, Health, Humor, History, Other

### Speed Improvements
**Files:** `src/summarizer.py`

Reduced conservative rate limiting delays:
| Setting | Before | After |
|---------|--------|-------|
| `MIN_DELAY_SECONDS` | 2 | 0.5 |
| `MAX_DELAY_SECONDS` | 30 | 5 |
| Delay formula | `tokens/5000` | `tokens/20000` |

Result: ~4x faster processing while staying within API limits.

### Multi-Provider Model Support
**Files:** `src/summarizer.py`, `src/pipeline.py`, `src/cli.py`, `requirements.txt`

Added support for multiple LLM providers with model switching:

```bash
podcastwise --list-models              # Show available models
podcastwise --model haiku              # Use specific model
podcastwise --model gpt-4o             # Use OpenRouter model
```

- **Anthropic (direct):** `sonnet`, `haiku`, `opus`
- **OpenRouter:** `or-sonnet`, `or-haiku`, `or-opus`, `gpt-4o`, `gpt-4-turbo`, `llama-70b`, `deepseek`

New env vars: `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `DEFAULT_MODEL`. New dependency: `openai>=1.0.0`.

### YouTube Cookie Authentication
**Files:** `src/youtube.py`, `src/cli.py`

Added cookie-based authentication to bypass YouTube IP blocks when fetching transcripts.

```bash
podcastwise --refresh-cookies           # Extract cookies from browser
podcastwise --refresh-cookies --browser safari
podcastwise --set-cookies /path/to/cookies.txt  # Import manual export
```

Cookies are extracted from the browser via `yt-dlp`, stored in `~/Documents/PodcastNotes/.cache/transcripts/youtube_cookies.txt`, and used automatically for transcript requests if present. Delete the file to revert to unauthenticated requests. Manual export also supported (browser extension → `--set-cookies`). New env var: `YOUTUBE_COOKIE_BROWSER`.

### New Documentation Files
- `MODEL_SETUP.md` — guide for configuring LLM providers and models
