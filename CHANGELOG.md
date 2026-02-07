# Podcastwise Changes - February 5, 2026

## 1. Google Sheets Export - Column Updates
**Files:** `src/sheets.py`

- Removed "Who Should Listen" column
- Removed "Topics" column
- Added "TL;DR" column from `summary.tldr`
- Added "Category" column - single category per episode (mapped from existing categories)
- Updated formatting:
  - Key Insights: bulleted list
  - Frameworks: bulleted list (was pipe-separated)
  - Soundbites: bulleted list with full quotes (was truncated at 100 chars)

**Category mapping:** Tech, Entertainment, News/Politics, Finance/Economics/Investing, Health, Humor, History, Other

---

## 2. Speed Improvements
**Files:** `src/summarizer.py`

Reduced conservative rate limiting delays:
| Setting | Before | After |
|---------|--------|-------|
| `MIN_DELAY_SECONDS` | 2 | 0.5 |
| `MAX_DELAY_SECONDS` | 30 | 5 |
| Delay formula | `tokens/5000` | `tokens/20000` |

Result: ~4x faster processing while staying within API limits.

---

## 3. Multi-Provider Model Support
**Files:** `src/summarizer.py`, `src/pipeline.py`, `src/cli.py`, `requirements.txt`

Added support for multiple LLM providers with model switching:

**New CLI options:**
```bash
podcastwise --list-models              # Show available models
podcastwise --model haiku              # Use specific model
podcastwise --model gpt-4o             # Use OpenRouter model
```

**Available models:**
- **Anthropic (direct):** `sonnet`, `haiku`, `opus`
- **OpenRouter:** `or-sonnet`, `or-haiku`, `or-opus`, `gpt-4o`, `gpt-4-turbo`, `llama-70b`, `deepseek`

**Environment variables:**
```
ANTHROPIC_API_KEY=sk-ant-...      # For direct Anthropic
OPENROUTER_API_KEY=sk-or-v1-...   # For OpenRouter
DEFAULT_MODEL=sonnet              # Set default model
```

**New dependency:** `openai>=1.0.0` (for OpenRouter compatibility)

---

## 4. YouTube Cookie Authentication
**Files:** `src/youtube.py`, `src/cli.py`

Added cookie-based authentication to bypass YouTube IP blocks when fetching transcripts.

**New CLI options:**
```bash
podcastwise --refresh-cookies           # Extract cookies from browser
podcastwise --refresh-cookies --browser safari
podcastwise --set-cookies /path/to/cookies.txt  # Import manual export
```

**How it works:**
- Cookies are extracted from browser using yt-dlp
- Stored in `~/Documents/PodcastNotes/.cache/transcripts/youtube_cookies.txt`
- Automatically used for transcript requests if present
- Delete the file to revert to regular (unauthenticated) requests

**Manual cookie export (for macOS):**
1. Install browser extension: "Get cookies.txt LOCALLY"
2. Go to youtube.com while logged in
3. Export cookies via extension
4. Run: `podcastwise --set-cookies /path/to/cookies.txt`

**Environment variable:**
```
YOUTUBE_COOKIE_BROWSER=chrome   # Default browser for extraction
```

---

## 5. New Documentation Files

- `MODEL_SETUP.md` - Guide for configuring LLM providers and models
- `CHANGELOG_2026-02-05.md` - This file

---

## Summary of New CLI Options

| Option | Description |
|--------|-------------|
| `--model`, `-m` | Select LLM model (sonnet, haiku, gpt-4o, etc.) |
| `--list-models` | List all available models |
| `--refresh-cookies` | Extract YouTube cookies from browser |
| `--set-cookies FILE` | Import manually exported cookies |
| `--browser` | Specify browser for cookie extraction |

---

## Files Modified

- `src/sheets.py` - Column updates, formatting changes
- `src/summarizer.py` - Rate limiting, multi-provider support
- `src/pipeline.py` - Model parameter passthrough
- `src/cli.py` - New CLI options (model, cookies)
- `src/youtube.py` - Cookie authentication
- `requirements.txt` - Added openai dependency
- `MODEL_SETUP.md` - New documentation
