# Podcastwise

A CLI tool that extracts your podcast listening history from Apple Podcasts, fetches transcripts from YouTube, and generates structured AI summaries. Summaries can be saved as markdown files and exported to Google Sheets.

## Features

- **Apple Podcasts Integration**: Reads your listening history directly from the Apple Podcasts database
- **YouTube Transcript Fetching**: Automatically finds and downloads transcripts from YouTube
- **AI Summarization**: Generates structured summaries using Claude, GPT-4, or other LLMs
- **Multiple Output Formats**: Markdown files with YAML frontmatter + Google Sheets export
- **Interactive Selection**: Choose which episodes to summarize with a TUI interface
- **Smart Caching**: Transcripts and summaries are cached to avoid redundant API calls
- **Batch Processing**: Process multiple episodes automatically with rate limiting

## Installation

### 1. Clone or Download

```bash
cd ~/Documents
git clone <repo-url> Podcastwise
cd Podcastwise
```

### 2. Install Dependencies

```bash
pip3 install -r requirements.txt
```

### 3. Configure Environment

Create a `.env` file with your API keys:

```bash
# Required: Anthropic API key for Claude
ANTHROPIC_API_KEY=sk-ant-api03-...

# Optional: OpenRouter API key (for GPT-4, Llama, etc.)
OPENROUTER_API_KEY=sk-or-...

# Optional: Default model (sonnet, haiku, opus, gpt-4o, etc.)
DEFAULT_MODEL=sonnet

# Optional: Output directory (defaults to ~/Documents/PodcastNotes)
PODCASTWISE_OUTPUT_DIR=~/Documents/PodcastNotes
```

Get your API keys:
- Anthropic: https://console.anthropic.com/
- OpenRouter: https://openrouter.ai/keys

## Usage

### Interactive Mode (Recommended)

```bash
python3 -m src.cli -n 50
```

This shows your 50 most recent episodes with an interactive selector:
- **↑/↓** — Navigate through episodes
- **Space** — Select/deselect an episode
- **Ctrl+A** — Select all
- **Ctrl+R** — Clear all selections
- **Enter** — Confirm and start processing

### Common Commands

```bash
# Interactive selection from 50 most recent episodes
python3 -m src.cli -n 50

# Filter by podcast name
python3 -m src.cli -p "stratechery" -n 20

# Only fully listened episodes (>= 90%)
python3 -m src.cli --complete-only -n 30

# Filter by date range
python3 -m src.cli --from 2025-01-01 --to 2025-01-31

# Preview without making changes
python3 -m src.cli -n 20 --dry-run

# Batch mode (no prompts, processes all filtered episodes)
python3 -m src.cli -p "odd lots" -n 5 --batch

# Re-process already summarized episodes
python3 -m src.cli -n 10 --force

# Retry episodes previously marked as "no transcript"
python3 -m src.cli --retry
```

### Information Commands

```bash
# List all episodes (no processing)
python3 -m src.cli --list

# Show listening statistics
python3 -m src.cli --stats

# Show processing status
python3 -m src.cli --status

# List available AI models
python3 -m src.cli --list-models
```

### Model Selection

Choose which AI model to use for summarization:

```bash
# Use Claude Haiku (faster, cheaper)
python3 -m src.cli -n 10 -m haiku

# Use GPT-4o via OpenRouter
python3 -m src.cli -n 10 -m gpt-4o

# Use Claude Opus (most capable)
python3 -m src.cli -n 10 -m opus
```

**Available Models:**

| Shorthand | Model | Provider |
|-----------|-------|----------|
| `sonnet` | Claude Sonnet 4 | Anthropic |
| `haiku` | Claude 3.5 Haiku | Anthropic |
| `opus` | Claude Opus 4 | Anthropic |
| `gpt-4o` | GPT-4o | OpenRouter |
| `gpt-4-turbo` | GPT-4 Turbo | OpenRouter |
| `llama-70b` | Llama 3 70B | OpenRouter |
| `deepseek` | DeepSeek Chat | OpenRouter |

## Google Sheets Export

Export your summaries to a Google Sheet for easy browsing and sharing.

**Example:** [Podcast Summaries Sheet](https://docs.google.com/spreadsheets/d/1cBK3nWIyzMWAepBTQSNnR-LrhNy8X4-230MzRcpbdMA/edit?gid=1445827789#gid=1445827789)

### Setup

1. Create a Google Cloud project and enable the Sheets API
2. Create a service account and download the JSON credentials
3. Share your Google Sheet with the service account email
4. Add to `.env`:

```bash
GOOGLE_SHEETS_CREDENTIALS=~/path/to/credentials.json
GOOGLE_SHEET_ID=your-spreadsheet-id
```

### Export Commands

```bash
# Export all summaries to Google Sheets
python3 -m src.cli --export-sheets

# Auto-export after summarizing
python3 -m src.cli -n 10 --auto-sync
```

The sheet will have a "Summary" tab with columns:
- Podcast Name
- Episode Title
- Date Listened
- Duration
- TL;DR
- Category
- Key Insights
- Frameworks
- Soundbites

## Output Format

### Markdown Files

Summaries are saved to `~/Documents/PodcastNotes/`:

```
~/Documents/PodcastNotes/
├── 2025-01-31_odd-lots_jeff-currie-on-metals.md
├── 2025-01-30_stratechery_meta-earnings.md
└── ...
```

Each file contains:
- **YAML frontmatter** (metadata for Obsidian/etc.)
- **TL;DR** — One-paragraph summary
- **Who Should Listen** — Target audience
- **Key Insights** — Main points with context
- **Frameworks & Models** — Mental models discussed
- **Soundbites** — Quotable moments with speaker attribution
- **Takeaways** — Action items and conclusions
- **References** — Books, people, tools, links mentioned
- **Personal Notes** — Empty section for your annotations

### Cached Data

Transcripts and state are cached to avoid re-fetching:

```
~/Documents/PodcastNotes/
├── .cache/
│   ├── transcripts/    # Raw YouTube transcripts (JSON)
│   └── summaries/      # Generated summaries (JSON)
└── .state/
    └── processed.json  # Tracks which episodes are done
```

## Cookie Management

### YouTube Cookies

If you encounter YouTube rate limits or IP blocks:

```bash
# Extract cookies from Chrome
python3 -m src.cli --refresh-cookies

# Use a different browser
python3 -m src.cli --refresh-cookies --browser firefox

# Import from manually exported file
python3 -m src.cli --set-cookies ~/cookies.txt
```

## Troubleshooting

### "No transcript found" for an episode

- The episode may not be on YouTube
- Try `--retry` flag to re-attempt failed episodes
- Some podcasts don't post full episodes to YouTube

### Re-process a specific episode

```bash
python3 -m src.cli -p "podcast name" -n 5 --force
```

### API rate limits

The tool uses exponential backoff. If you hit limits:
- Wait a few minutes and try again
- Use `--no-rate-limit` only if you're sure (may cause errors)
- Consider using a faster/cheaper model like `haiku`

### Google Sheets rate limit (429 error)

The tool batches writes to avoid hitting the 60 writes/minute limit. If you still see errors:
- Wait a minute and run `--export-sheets` again
- Duplicates are automatically skipped

## Quick Start Example

```bash
# 1. Navigate to Podcastwise
cd ~/Documents/Podcastwise

# 2. Run with 20 most recent episodes
python3 -m src.cli -n 20

# 3. Select episodes with Space, press Enter

# 4. Wait for processing

# 5. View summaries
open ~/Documents/PodcastNotes/

# 6. Export to Google Sheets
python3 -m src.cli --export-sheets
```

## Project Structure

```
Podcastwise/
├── src/
│   ├── cli.py          # Command-line interface
│   ├── podcast_db.py   # Apple Podcasts database reader
│   ├── youtube.py      # YouTube transcript fetcher
│   ├── summarizer.py   # AI summarization (Claude/GPT)
│   ├── markdown.py     # Markdown file generation
│   ├── sheets.py       # Google Sheets export
│   ├── pipeline.py     # Processing pipeline
│   ├── processor.py    # Batch processing
│   └── state.py        # State management
├── requirements.txt
├── .env.example
└── README.md
```

## License

MIT
