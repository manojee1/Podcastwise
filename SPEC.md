# Podcastwise: Podcast Tracking & Summarization System

## Overview

A CLI tool that extracts podcast listening history from Apple Podcasts on macOS (plus a YouTube "watched" playlist as a second episode source), finds transcripts — via YouTube, or directly from the Stratechery blog, the JP Morgan Eye on the Market site, or Lenny's Podcast's GitHub transcript archive, depending on the show — and generates structured markdown summaries using an LLM (Claude, or other providers via OpenRouter).

---

## Goals

1. **Track** — Pull podcast episodes listened to since Jan 1, 2025 from Apple Podcasts (includes iCloud-synced episodes from iPhone/iPad)
2. **Select** — Present an interactive list for user to choose which episodes to summarize (shows partial listens marked as such)
3. **Transcribe** — Find transcripts via YouTube (mark as "not found" if unavailable, retry on next run)
4. **Summarize** — Use Claude API to extract structured insights from transcripts
5. **Output** — Generate individual markdown files with consistent structure

---

## User Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│  1. User runs: podcastwise                                      │
├─────────────────────────────────────────────────────────────────┤
│  2. Tool reads Apple Podcasts database                          │
│     → Displays list of episodes since Jan 1, 2025               │
│     → Most recent first                                         │
│     → Partial listens marked as such                            │
├─────────────────────────────────────────────────────────────────┤
│  3. User selects episodes to summarize (checkbox UI)            │
├─────────────────────────────────────────────────────────────────┤
│  4. For each selected episode:                                  │
│     a. Check if already summarized → skip (unless --force)      │
│     b. Search YouTube for full episode video                    │
│     c. If found → extract transcript → summarize → generate md  │
│     d. If not found → mark as "transcript not found", skip      │
│        (will retry on next run)                                 │
├─────────────────────────────────────────────────────────────────┤
│  5. Output: ~/Documents/PodcastNotes/{date}_{podcast}_{ep}.md   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Sources

### Apple Podcasts Database

**Location:** `~/Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite`

**Note:** This database includes episodes synced via iCloud from iPhone/iPad.

**Key Tables (to explore):**
- `ZMTEPISODE` — Episode metadata (title, duration, play date, play progress)
- `ZMTPODCAST` — Podcast/show metadata (name, author, feed URL)

**Key Fields Needed:**
- Episode title
- Podcast name
- Date played
- Duration
- Play progress (to determine partial vs complete listen)

### YouTube Watched Playlist

An alternate episode source (`src/youtube_watched.py`): videos from a YouTube "Podcasts" playlist (default `YOUTUBE_WATCHED_PLAYLIST_URL`), for long-form interviews watched directly on YouTube rather than in Apple Podcasts. Episodes are merged into the default episode list (sorted together with Apple Podcasts history by date) and flow through the same pipeline, state file, and Google Sheet. Matched to their transcript by video ID directly — no search/matching needed. `--youtube-watched` runs against just this source.

### Per-Podcast Transcript Sources

Some shows have a higher-quality transcript source than YouTube and are special-cased ahead of the general YouTube search:

- **Stratechery** (`src/stratechery.py`) — fetches the matching blog post from the Stratechery archive (requires session cookies). Matching uses title similarity *and* a minimum content-word-overlap gate, since Stratechery post titles share a lot of boilerplate ("Interview with X CEO A" vs. "...CEO B") that fools plain similarity scoring.
- **JP Morgan Eye on the Market** (`src/jpmorgan.py`) — fetches the article transcript from the JP Morgan Asset Management site. Falls through to YouTube search if the article fetch fails.
- **Lenny's Podcast** (`src/lenny.py`) — fetches pre-existing transcripts from the `ChatPRD/lennys-podcast-transcripts` GitHub repo. Also used standalone via `scripts/process_lenny.py` to bulk-process the whole archive into an isolated output directory and Sheet.

### Transcript Acquisition Order

For a given episode, `fetch_transcript_for_episode()` (`src/youtube.py`) tries, in order:

1. **Cache** — previously-fetched transcript for this episode ID, if present
2. **Explicit YouTube URL** — `--youtube-url` override, or a known URL carried on the episode (e.g. from the watched playlist)
3. **Stratechery / JP Morgan** — if the episode matches one of these shows
4. **YouTube search** — multiple query variants tried, candidates scored for confidence (`find_best_match`); a low-confidence or guest-mismatched candidate (`validate_match`) is either auto-rejected (`--batch`, logged as `[WARN]`) or shown to the user for an accept/reject prompt (interactive mode)
5. **Not Found** — if nothing matches, mark episode as "transcript not found" and skip (will retry on next run via `--retry`)

**Note:** Raw transcripts are cached locally after fetching to enable re-summarization without re-fetching.

---

## Output Format

### File Naming
```
{YYYY-MM-DD}_{podcast-slug}_{episode-slug}.md
```
Example: `2025-01-15_huberman-lab_sleep-optimization.md`

### File Structure

```markdown
---
podcast: "{Podcast Name}"
episode: "{Episode Title}"
guest: "{Guest Name(s)}"
host: "{Host Name}"
date_listened: YYYY-MM-DD
date_published: YYYY-MM-DD
duration: "{Xh Ym}"
category: [{Category1}, {Category2}]
youtube_url: "{URL if found}"
---

# {Episode Title}

## TL;DR
{2-3 sentence summary}

## Who Should Listen
{Target audience for this episode}

## Key Insights
- {Insight 1}
- {Insight 2}
- {Insight 3}

## Frameworks & Models
### {Framework Name}
{Description}

## Soundbites
> "{Quote 1}" — {Speaker}

> "{Quote 2}" — {Speaker}

## Key Takeaways / Action Items
- [ ] {Actionable item 1}
- [ ] {Actionable item 2}

## References Mentioned
### Books
- {Book Title} by {Author}

### People
- {Person} — {Context}

### Tools / Products
- {Tool} — {What it does}

### Links
- [{Title}]({URL})

## Personal Notes
{Empty section for user to fill in}
```

---

## Technical Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Database Access | `sqlite3` (built-in) |
| YouTube Search | `yt-dlp` |
| YouTube Transcripts | `youtube-transcript-api` |
| LLM | Claude API (`anthropic` SDK), other providers via OpenRouter (`openai` SDK) |
| Blog/Article Scraping | `requests` + `beautifulsoup4` (Stratechery, JP Morgan) |
| CLI Interface | `rich` + `inquirer` or `textual` |
| Web UI | `flask` (optional, `src/web/`) |
| Config | `.env` file for API keys |
| State Tracking | JSON file for processed episodes |
| Export | Google Sheets (`gspread`, `google-auth`) |

---

## Configuration

### Environment Variables
```
ANTHROPIC_API_KEY=sk-ant-...          # Get from console.anthropic.com
PODCASTWISE_OUTPUT_DIR=~/Documents/PodcastNotes
OPENROUTER_API_KEY=sk-or-v1-...       # Optional: GPT-4, Llama, Gemini, etc. via OpenRouter
DEFAULT_MODEL=sonnet                  # Optional: default model alias
GOOGLE_SHEETS_CREDENTIALS=~/path/to/credentials.json   # Optional: Sheets export
GOOGLE_SHEET_ID=...                   # Optional: Sheets export
YOUTUBE_WATCHED_PLAYLIST_URL=...      # Optional: override the watched-playlist source
YOUTUBE_COOKIE_BROWSER=chrome         # Optional: default browser for cookie extraction
```

### Categories

Fixed list (LLM can extend if content doesn't fit):
- Tech
- Finance
- News
- Health
- Humor
- Science
- Business
- Relationships
- *(LLM may add others as needed)*

### User Preferences (future)
- Custom extraction prompts
- Podcasts to always skip

---

## Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| YouTube video not found | Mark as "transcript not found", skip, retry next run |
| Transcript too long for Claude | Chunk into segments, summarize each, then synthesize |
| Episode already summarized | Skip unless `--force` flag |
| API rate limits | Exponential backoff, queue remaining |
| Partial listen | Include in list, marked as "partial" |
| Non-English podcast | Claude can summarize if transcript available |
| Uncertain YouTube match (below confidence threshold, or expected guest missing from title) | Interactive: prompt user to accept/reject the candidate. `--batch`: auto-reject, log `[WARN]` |
| Per-podcast source fetch fails (Stratechery cookies expired, JP Morgan article missing) | Fall through to general YouTube search |

---

## Implementation Phases

### Phase 1: Data Extraction ✅
- [x] Connect to Apple Podcasts SQLite database
- [x] Query for episodes played since Jan 1, 2025 (includes iCloud-synced)
- [x] Extract: episode title, podcast name, date played, duration, play progress
- [x] Identify partial listens vs completed episodes
- [x] Display results in terminal (basic list)

### Phase 2: Interactive Selection UI ✅
- [x] Build CLI interface with checkboxes
- [x] Show episodes sorted by date (most recent first)
- [x] Display: date, podcast name, episode title, duration, partial/complete status
- [x] Allow multi-select
- [x] Add "select all" / "deselect all" options (Ctrl+A / Ctrl+R)
- [x] Add filtering: --limit, --podcast, --complete-only

### Phase 3: YouTube Transcript Pipeline ✅
- [x] Search YouTube for episode matches
- [x] Handle title variations (fuzzy matching)
- [x] Extract transcript via `youtube-transcript-api`
- [x] Cache raw transcripts locally (keep permanently for re-summarization)
- [x] Mark episodes as "transcript not found" if no YouTube match
- [x] --retry flag to retry previously not-found episodes

### Phase 4: LLM Summarization ✅
- [x] Design extraction prompt for Claude
- [x] Handle long transcripts (chunking strategy)
- [x] Parse Claude response into structured data
- [x] Implement category classification (fixed list + LLM extension)

### Phase 5: Markdown Generation ✅
- [x] Generate frontmatter from metadata
- [x] Format each section
- [x] Write to output directory (`~/Documents/PodcastNotes/`)
- [x] Handle filename conflicts (append number)

### Phase 6: State Management & Polish ✅
- [x] Track processed episodes in JSON state file
- [x] Skip already-summarized episodes by default
- [x] `--force` flag to re-summarize existing
- [x] Progress bars for long operations
- [x] `--dry-run` to preview without API calls
- [x] `--batch` mode for non-interactive processing
- [x] `--status` command to show processing status

### Phase 7: Multi-Source Transcripts ✅
- [x] Stratechery blog source with content-word-overlap match gating (`src/stratechery.py`)
- [x] JP Morgan Eye on the Market source, falls through to YouTube on failure (`src/jpmorgan.py`)
- [x] Lenny's Podcast GitHub transcript archive (`src/lenny.py`, `scripts/process_lenny.py`)
- [x] YouTube-watched playlist as a second episode source, merged into the default list (`src/youtube_watched.py`)
- [x] Confidence-scored YouTube matching (`find_best_match`/`validate_match`) with interactive low-confidence accept/reject prompt

### Phase 8: Multi-Provider LLM & Cookie Auth ✅
- [x] Model alias system supporting Anthropic direct API and OpenRouter (GPT-4, Llama, DeepSeek, Gemini, etc.)
- [x] `--model`/`DEFAULT_MODEL` selection, `--list-models`
- [x] YouTube cookie extraction/import to bypass IP blocks (`--refresh-cookies`, `--set-cookies`)

### Phase 9: Google Sheets Export ✅
- [x] Export summaries to a Google Sheet, per-year tabs
- [x] Duplicate detection/cleanup, `--sync-export-state`, `--auto-sync`
- [x] Retry failed transcript fetches (`--retry`/`--retry-episodes`)

### Phase 10: Web UI ✅
- [x] Standalone Flask app (`src/web/`) for browsing/processing through a browser, reusing the same pipeline modules

---

## Future Enhancements (Out of Scope for v1)

- Whisper fallback for episodes without YouTube transcripts
- Search across all summaries
- Obsidian/Notion integration
- Auto-run on new episode played
- Export to Readwise/other tools

---

## Decisions Made

| Question | Decision |
|----------|----------|
| iCloud sync? | Yes — macOS DB includes iCloud-synced episodes from iPhone/iPad |
| Whisper fallback? | No (v1) — mark as "not found", retry next run |
| Categories? | Fixed list (Tech, Finance, News, Health, Humor, Science, Business, Relationships) + LLM can extend |
| Keep transcripts? | Yes — cache raw transcripts permanently for re-summarization |
| Partial listens? | Include in list, marked as "partial" |
| Re-summarize? | Skip by default, use `--force` flag to re-process |
| Multiple transcript sources? | Yes — cache, explicit URL override, Stratechery, JP Morgan, then YouTube search, tried in priority order; per-podcast sources fall through to YouTube on failure |

---

## Success Criteria

- [ ] Can extract 100% of played episodes from Apple Podcasts DB
- [ ] Finds YouTube transcript for >70% of episodes
- [ ] Generates coherent, useful summaries
- [ ] Markdown files are readable and consistently formatted
