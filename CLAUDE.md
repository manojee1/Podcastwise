# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

There is no build step, linter, or test suite in this repo — it's a plain Python CLI (`pip3 install -r requirements.txt`).

```bash
# Run the CLI (always as a module, never `python3 src/cli.py` or a bare `podcastwise`)
python3 -m src.cli -n 20                  # interactive selector over 20 most recent episodes
python3 -m src.cli -n 20 --batch          # non-interactive (required in non-TTY contexts, e.g. when Claude runs it)
python3 -m src.cli --list                 # list episodes, no processing
python3 -m src.cli --stats                # listening stats
python3 -m src.cli --status               # processing status
python3 -m src.cli --list-models          # available LLM aliases
python3 -m src.cli -n 5 --dry-run         # preview without writing anything
python3 -m src.cli --youtube-watched      # process the "watched on YouTube" playlist instead of Apple Podcasts history

# Optional standalone Flask web UI (separate from the CLI pipeline)
python3 -m src.web.app                    # http://localhost:5000

# One-off Lenny's Podcast bulk-processing script (isolated output dir/state/sheet)
python3 scripts/process_lenny.py --dry-run
```

No automated tests exist. Verify changes by running the CLI against real data (`--dry-run` first) and checking the generated markdown/cache/state files under `~/Documents/PodcastNotes/`.

## Architecture

**Pipeline shape:** `podcast_db.py` (source episodes) → transcript fetch → `summarizer.py` (LLM) → `markdown.py` (write file) → `state.py` (record) → optional `sheets.py` (export). `pipeline.py` orchestrates this for the Apple Podcasts path; `cli.py` is the argparse entry point that wires sources, filters, and the pipeline together.

**Two episode sources, one downstream pipeline:**
- `podcast_db.py` reads Apple Podcasts' own SQLite library (`~/Library/Group Containers/.../MTLibrary.sqlite`, Core Data epoch timestamps) to get listening history.
- `youtube_watched.py` reads a YouTube "watched" playlist instead, building equivalent `Episode` objects (synthetic IDs derived from video ID, no `date_published`) so it can flow through the same pipeline/state/sheets.
- Lenny's Podcast (`lenny.py` + `scripts/process_lenny.py`) is a third, intentionally *isolated* source: it pulls transcripts from a GitHub repo and runs through its own script that overrides `PODCASTWISE_OUTPUT_DIR` and `GOOGLE_SHEET_ID` via env vars *before* importing any `src.*` module — every path-returning function (`get_output_dir`, `get_state_file`, `get_cache_dir`, `get_summary_cache_dir`, `get_sheet_id`) reads `os.getenv()` at call time specifically so this redirection works without touching the main pipeline's state.

**Transcript acquisition is a dispatch chain**, implemented in `youtube.py:fetch_transcript_for_episode()`: check cache → explicit `--youtube-url` override → Stratechery blog (`stratechery.py`, if `is_stratechery(episode)`) → JP Morgan Eye on the Market site (`jpmorgan.py`, if `is_eye_on_the_market(episode)`, falls through to YouTube on failure) → YouTube search as the general fallback. Per-podcast modules (`stratechery.py`, `jpmorgan.py`, `lenny.py`) all build the same `youtube.py:Transcript` dataclass so the rest of the pipeline doesn't need to know the source.

**YouTube matching is confidence-scored, not first-result:** `search_youtube_with_fallback()` tries multiple query variants, `find_best_match()` scores candidates into a `MatchResult` (with `confidence` and `reason`), and `validate_match()` can reject a match outright. Rejections either auto-skip (logging a `[WARN]`) or, in interactive flows, call back into `selector.py:confirm_low_confidence_match()` so a human can approve a low-confidence match. `extract_guest_names()` feeding into this scoring has been a recurring source of subtle bugs (false-positive name extraction, regex case-sensitivity) — see git log for past fixes before changing its patterns.

**Stratechery matching** similarly avoids naive title similarity: `find_matching_post()` requires a minimum content-word overlap (`content_word_overlap()`, template words like "interview"/"ceo"/"founder" excluded) on top of similarity, because Stratechery post titles share a lot of boilerplate structure that fools plain similarity scoring.

**State and caching, all keyed by episode ID, all path-overridable via `PODCASTWISE_OUTPUT_DIR`:**
- `state.py` (`processed.json`) tracks per-episode status (`success`/`no_transcript`/`error`) and `exported_to_sheets`, gating re-processing — `--force` bypasses it, `--retry` re-attempts only `no_transcript` rows. `mark_not_exported()` exists specifically to force a re-export after a summary was corrected post-hoc.
- Raw transcripts and generated summaries are cached as JSON under `.cache/` so re-running summarization (e.g. with a different `--model`) doesn't re-fetch transcripts.
- The global `StateManager` singleton (`get_state_manager()`) recreates itself if `PODCASTWISE_OUTPUT_DIR` changes after first access — this is what lets `scripts/process_lenny.py` redirect state just by setting the env var first.

**Multi-provider summarization (`summarizer.py`):** `MODEL_CONFIG` maps short aliases (`sonnet`, `haiku`, `opus`, `gpt-4o`, etc.) to either the direct Anthropic API or OpenRouter, selected per-call via `--model`/`DEFAULT_MODEL`. Long transcripts are split via `chunk_transcript()` and summarized chunk-by-chunk (`_summarize_chunked`) vs. single-shot (`_summarize_single`); the prompt template that drives extraction (TL;DR, key insights, frameworks, soundbites, takeaways, references) is documented in `PROMPTS.md`.

**Helper scripts** (`scripts/`) are one-off remediation tools for fixing bad transcript matches after the fact — not part of the normal pipeline: `fix_wrong_transcripts.py` clears cache/state/markdown for a mismatched episode, `reprocess_cleared.py` re-runs the pipeline on specific IDs, `force_reexport_fixed.py` deletes stale Sheet rows and resets export state. Use this clear→reprocess→re-export sequence when a wrong transcript was matched and already exported.

**Web UI (`src/web/`)** is a separate, optional Flask app (blueprints under `routes/`, services under `services/`) for browsing/processing through a browser instead of the CLI — it is not on the path of `python3 -m src.cli` and changes to one don't require touching the other, but both ultimately call into the same `src/` pipeline modules.

For full design rationale and the original spec, see `SPEC.md`; for the exact LLM prompts, see `PROMPTS.md`; for model/provider setup, see `MODEL_SETUP.md`.
