# Podcastwise: Podcast Tracking & Summarization System

## Overview

A CLI tool that extracts podcast listening history from Apple Podcasts on macOS, finds transcripts, and generates structured markdown summaries using an LLM.

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

### Transcript Sources

1. **YouTube** — Search `{podcast name} {episode title}`, extract captions
2. **Not Found** — If no YouTube video/transcript available, mark episode as "transcript not found" and skip (will retry on next run)

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
| LLM | Claude API (`anthropic` SDK) |
| CLI Interface | `rich` + `inquirer` or `textual` |
| Config | `.env` file for API keys |
| State Tracking | JSON file for processed episodes |

---

## Configuration

### Environment Variables
```
ANTHROPIC_API_KEY=sk-ant-...  # Get from console.anthropic.com
PODCASTWISE_OUTPUT_DIR=~/Documents/PodcastNotes
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

---

## Future Enhancements (Out of Scope for v1)

- Whisper fallback for episodes without YouTube transcripts
- Web UI for browsing summaries
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

---

## Success Criteria

- [ ] Can extract 100% of played episodes from Apple Podcasts DB
- [ ] Finds YouTube transcript for >70% of episodes
- [ ] Generates coherent, useful summaries
- [ ] Markdown files are readable and consistently formatted
