"""
LLM-based podcast summarization using Claude API or OpenRouter.

Extracts structured insights from podcast transcripts.
Supports multiple providers: Anthropic (direct) and OpenRouter.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional, Literal
from pathlib import Path

from dotenv import load_dotenv

from .podcast_db import Episode
from .youtube import Transcript


# Load environment variables
load_dotenv()

# --- Provider and Model Configuration ---

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENROUTER = "openrouter"

# Model aliases mapped to (provider, model_id)
MODEL_CONFIG = {
    # Anthropic models
    "sonnet": (PROVIDER_ANTHROPIC, "claude-sonnet-4-20250514"),
    "haiku": (PROVIDER_ANTHROPIC, "claude-3-5-haiku-20241022"),
    "opus": (PROVIDER_ANTHROPIC, "claude-opus-4-20250514"),
    # OpenRouter models (Claude)
    "or-sonnet": (PROVIDER_OPENROUTER, "anthropic/claude-sonnet-4"),
    "or-haiku": (PROVIDER_OPENROUTER, "anthropic/claude-3.5-haiku"),
    "or-opus": (PROVIDER_OPENROUTER, "anthropic/claude-opus-4"),
    # OpenRouter models (Other providers)
    "gpt-4o": (PROVIDER_OPENROUTER, "openai/gpt-4o"),
    "gpt-4-turbo": (PROVIDER_OPENROUTER, "openai/gpt-4-turbo"),
    "llama-70b": (PROVIDER_OPENROUTER, "meta-llama/llama-3-70b-instruct"),
    "deepseek": (PROVIDER_OPENROUTER, "deepseek/deepseek-chat"),
}

# Default model
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "sonnet")

def get_available_models() -> list[str]:
    """Return list of available model aliases."""
    return list(MODEL_CONFIG.keys())


def get_model_info(model_alias: str) -> tuple[str, str]:
    """
    Get provider and model ID for a given alias.

    Args:
        model_alias: Short name like 'sonnet', 'haiku', 'gpt-4o'

    Returns:
        Tuple of (provider, model_id)
    """
    if model_alias not in MODEL_CONFIG:
        raise ValueError(
            f"Unknown model: {model_alias}\n"
            f"Available models: {', '.join(MODEL_CONFIG.keys())}"
        )
    return MODEL_CONFIG[model_alias]


# --- Rate Limiting Settings ---

RATE_LIMIT_ENABLED = True  # Default: rate limiting on
TOKENS_PER_MINUTE = 30000  # Anthropic's default limit
CHARS_PER_TOKEN = 4  # Approximate
SAFETY_MARGIN = 0.8  # Use 80% of limit to be safe
MIN_DELAY_SECONDS = 0.5  # Minimum delay between requests
MAX_DELAY_SECONDS = 5  # Maximum delay if transcript is very long

# Track last request time for rate limiting
_last_request_time = 0
_tokens_used_this_minute = 0
_minute_start_time = 0

# Default categories (LLM can extend)
DEFAULT_CATEGORIES = [
    "Tech",
    "Finance",
    "News",
    "Health",
    "Humor",
    "Science",
    "Business",
    "Relationships",
]

# Max tokens for Claude context (leaving room for response)
MAX_TRANSCRIPT_TOKENS = 150000  # ~600K chars, Claude can handle 200K tokens


# --- Client Creation ---

def _create_anthropic_client():
    """Create Anthropic client."""
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set.\n"
            "Add to .env: ANTHROPIC_API_KEY=sk-ant-..."
        )
    return anthropic.Anthropic(api_key=api_key)


def _create_openrouter_client():
    """Create OpenRouter client (OpenAI-compatible)."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "OpenAI SDK not installed. Run:\n"
            "pip install openai"
        )
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY not set.\n"
            "Add to .env: OPENROUTER_API_KEY=sk-or-..."
        )
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


def _call_llm(prompt: str, model_alias: str) -> str:
    """
    Call the LLM with the given prompt using the specified model.

    Args:
        prompt: The prompt to send
        model_alias: Model alias from MODEL_CONFIG

    Returns:
        Response text from the model
    """
    provider, model_id = get_model_info(model_alias)

    if provider == PROVIDER_ANTHROPIC:
        client = _create_anthropic_client()
        message = client.messages.create(
            model=model_id,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    elif provider == PROVIDER_OPENROUTER:
        client = _create_openrouter_client()
        response = client.chat.completions.create(
            model=model_id,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    else:
        raise ValueError(f"Unknown provider: {provider}")


def set_rate_limiting(enabled: bool) -> None:
    """Enable or disable rate limiting."""
    global RATE_LIMIT_ENABLED
    RATE_LIMIT_ENABLED = enabled


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text length."""
    return len(text) // CHARS_PER_TOKEN


def _apply_rate_limit(estimated_tokens: int) -> None:
    """
    Apply rate limiting delay if needed.

    Tracks token usage and adds delays to stay under API limits.
    """
    global _last_request_time, _tokens_used_this_minute, _minute_start_time

    if not RATE_LIMIT_ENABLED:
        return

    current_time = time.time()

    # Reset counter if a minute has passed
    if current_time - _minute_start_time >= 60:
        _tokens_used_this_minute = 0
        _minute_start_time = current_time

    # Calculate safe token limit
    safe_limit = int(TOKENS_PER_MINUTE * SAFETY_MARGIN)

    # If this request would exceed the limit, wait for the minute to reset
    if _tokens_used_this_minute + estimated_tokens > safe_limit:
        wait_time = 60 - (current_time - _minute_start_time) + 1
        if wait_time > 0:
            time.sleep(wait_time)
            _tokens_used_this_minute = 0
            _minute_start_time = time.time()

    # Calculate delay based on transcript size
    # Longer transcripts = longer delay to spread out requests
    delay = min(
        MAX_DELAY_SECONDS,
        max(MIN_DELAY_SECONDS, estimated_tokens / 20000)  # ~1 sec per 20K tokens
    )

    # Ensure minimum time between requests
    time_since_last = current_time - _last_request_time
    if time_since_last < delay:
        time.sleep(delay - time_since_last)

    # Update tracking
    _tokens_used_this_minute += estimated_tokens
    _last_request_time = time.time()


@dataclass
class PodcastSummary:
    """Structured summary of a podcast episode."""
    tldr: str
    who_should_listen: str
    key_insights: list[str]
    frameworks: list[dict]  # [{name, description}, ...]
    soundbites: list[dict]  # [{quote, speaker}, ...]
    takeaways: list[str]
    references: dict  # {books: [], people: [], tools: [], links: []}
    categories: list[str]

    def to_dict(self) -> dict:
        return {
            "tldr": self.tldr,
            "who_should_listen": self.who_should_listen,
            "key_insights": self.key_insights,
            "frameworks": self.frameworks,
            "soundbites": self.soundbites,
            "takeaways": self.takeaways,
            "references": self.references,
            "categories": self.categories,
        }


EXTRACTION_PROMPT = """You are an expert podcast analyst. Your task is to extract structured insights from a podcast transcript.

<podcast_info>
Podcast: {podcast_name}
Episode: {episode_title}
Host: {host}
Duration: {duration}
</podcast_info>

<transcript>
{transcript}
</transcript>

Analyze this transcript and extract the following information. Return your response as a JSON object with these exact keys:

{{
  "tldr": "A 2-3 sentence summary capturing the main topic and key conclusion. What would you tell someone who asks 'what was this episode about?'",

  "who_should_listen": "One sentence describing the ideal audience. Example: 'Anyone interested in AI safety' or 'Founders raising their first round'",

  "key_insights": [
    "3-7 key insights or 'aha moments' from the episode. Novel ideas, counterintuitive findings, or things that shift thinking."
  ],

  "frameworks": [
    {{
      "name": "Name of the framework, model, or concept",
      "description": "Brief explanation of how it works"
    }}
  ],

  "soundbites": [
    {{
      "quote": "A memorable, quotable statement from the episode (2-4 sentences max)",
      "speaker": "Name of who said it"
    }}
  ],

  "takeaways": [
    "Actionable items the listener can actually DO after listening. Be specific and practical."
  ],

  "references": {{
    "books": ["Book Title by Author"],
    "people": ["Person Name - brief context of why mentioned"],
    "tools": ["Tool/Product Name - what it does"],
    "links": ["Any URLs or resources mentioned"]
  }},

  "categories": ["Select 1-3 from: Tech, Finance, News, Health, Humor, Science, Business, Relationships. You may add ONE new category if none fit well."]
}}

Important guidelines:
- Extract 2-7 soundbites that are memorable and quotable
- For frameworks, only include explicitly named concepts or models discussed
- Be specific in takeaways - avoid generic advice
- If no books/people/tools were mentioned, use empty arrays
- Keep the tldr concise but informative
- Categories should reflect the PRIMARY topics, not tangential mentions

Return ONLY the JSON object, no additional text."""


def chunk_transcript(text: str, max_chars: int = 500000) -> list[str]:
    """
    Split transcript into chunks if too long.

    Tries to split at sentence boundaries.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current_chunk = ""

    # Split by sentences (roughly)
    sentences = text.replace('. ', '.|').replace('? ', '?|').replace('! ', '!|').split('|')

    for sentence in sentences:
        if len(current_chunk) + len(sentence) > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk += " " + sentence

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def summarize_transcript(
    episode: Episode,
    transcript: Transcript,
    model: Optional[str] = None,
    rate_limit: bool = True,
) -> PodcastSummary:
    """
    Generate a structured summary from a podcast transcript.

    Args:
        episode: Episode metadata
        transcript: Transcript object with full text
        model: Model alias (e.g., 'sonnet', 'haiku', 'gpt-4o'). Defaults to DEFAULT_MODEL.
        rate_limit: Whether to apply rate limiting (default True)

    Returns:
        PodcastSummary object
    """
    model = model or DEFAULT_MODEL

    # Validate model
    get_model_info(model)  # Raises if invalid

    # Set rate limiting
    set_rate_limiting(rate_limit)

    # Check if transcript needs chunking
    chunks = chunk_transcript(transcript.text)

    if len(chunks) == 1:
        # Single chunk - process directly
        return _summarize_single(episode, transcript.text, model)
    else:
        # Multiple chunks - summarize each, then synthesize
        return _summarize_chunked(episode, chunks, model)


def _summarize_single(
    episode: Episode,
    text: str,
    model: str,
) -> PodcastSummary:
    """Summarize a single transcript chunk."""

    prompt = EXTRACTION_PROMPT.format(
        podcast_name=episode.podcast_name,
        episode_title=episode.title,
        host=episode.podcast_author or "Unknown",
        duration=episode.duration_formatted,
        transcript=text,
    )

    # Apply rate limiting based on estimated tokens
    estimated_tokens = _estimate_tokens(prompt)
    _apply_rate_limit(estimated_tokens)

    # Call LLM
    response_text = _call_llm(prompt, model)

    # Clean up response if needed (sometimes has markdown code blocks)
    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
    response_text = response_text.strip()

    data = json.loads(response_text)

    return PodcastSummary(
        tldr=data.get("tldr", ""),
        who_should_listen=data.get("who_should_listen", ""),
        key_insights=data.get("key_insights", []),
        frameworks=data.get("frameworks", []),
        soundbites=data.get("soundbites", []),
        takeaways=data.get("takeaways", []),
        references=data.get("references", {"books": [], "people": [], "tools": [], "links": []}),
        categories=data.get("categories", []),
    )


SYNTHESIS_PROMPT = """You are synthesizing summaries from a long podcast episode that was processed in chunks.

<podcast_info>
Podcast: {podcast_name}
Episode: {episode_title}
</podcast_info>

Here are the summaries from each chunk:

{chunk_summaries}

Synthesize these into a single cohesive summary. Combine insights, remove duplicates, and create a unified view.

Return a JSON object with these keys:
{{
  "tldr": "2-3 sentence overall summary",
  "who_should_listen": "One sentence on ideal audience",
  "key_insights": ["Combined list of unique insights, max 7"],
  "frameworks": [{{"name": "...", "description": "..."}}],
  "soundbites": [{{"quote": "...", "speaker": "..."}}],
  "takeaways": ["Combined actionable items"],
  "references": {{"books": [], "people": [], "tools": [], "links": []}},
  "categories": ["1-3 categories"]
}}

Return ONLY the JSON object."""


def _summarize_chunked(
    episode: Episode,
    chunks: list[str],
    model: str,
) -> PodcastSummary:
    """Summarize multiple chunks and synthesize."""

    # Summarize each chunk
    chunk_summaries = []
    for i, chunk in enumerate(chunks):
        prompt = EXTRACTION_PROMPT.format(
            podcast_name=episode.podcast_name,
            episode_title=f"{episode.title} (Part {i+1}/{len(chunks)})",
            host=episode.podcast_author or "Unknown",
            duration=episode.duration_formatted,
            transcript=chunk,
        )

        # Apply rate limiting for each chunk
        estimated_tokens = _estimate_tokens(prompt)
        _apply_rate_limit(estimated_tokens)

        # Call LLM
        response_text = _call_llm(prompt, model)
        chunk_summaries.append(f"=== Part {i+1} ===\n{response_text}")

    # Synthesize
    synthesis_prompt = SYNTHESIS_PROMPT.format(
        podcast_name=episode.podcast_name,
        episode_title=episode.title,
        chunk_summaries="\n\n".join(chunk_summaries),
    )

    # Apply rate limiting for synthesis
    estimated_tokens = _estimate_tokens(synthesis_prompt)
    _apply_rate_limit(estimated_tokens)

    # Call LLM for synthesis
    response_text = _call_llm(synthesis_prompt, model)

    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
    response_text = response_text.strip()

    data = json.loads(response_text)

    return PodcastSummary(
        tldr=data.get("tldr", ""),
        who_should_listen=data.get("who_should_listen", ""),
        key_insights=data.get("key_insights", []),
        frameworks=data.get("frameworks", []),
        soundbites=data.get("soundbites", []),
        takeaways=data.get("takeaways", []),
        references=data.get("references", {"books": [], "people": [], "tools": [], "links": []}),
        categories=data.get("categories", []),
    )


if __name__ == "__main__":
    # Test with a cached transcript
    from .podcast_db import get_episodes_since
    from .youtube import Transcript, CACHE_DIR

    print("Testing summarization...")

    # Check for API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nError: ANTHROPIC_API_KEY not set.")
        print("Create a .env file with: ANTHROPIC_API_KEY=sk-ant-...")
        exit(1)

    # Find a cached transcript
    cache_files = list(CACHE_DIR.glob("*.json"))
    if not cache_files:
        print("No cached transcripts found. Run --fetch-transcripts first.")
        exit(1)

    # Load first cached transcript
    with open(cache_files[0]) as f:
        data = json.load(f)

    episode_id = data["episode_id"]

    # Find matching episode
    episodes = get_episodes_since()
    episode = next((ep for ep in episodes if ep.id == episode_id), None)

    if not episode:
        print(f"Episode {episode_id} not found in database.")
        exit(1)

    transcript = Transcript(
        episode_id=data["episode_id"],
        video_id=data["video_id"],
        video_url=data["video_url"],
        text=data["text"],
        segments=data["segments"],
    )

    print(f"\nSummarizing: {episode.title[:60]}...")
    print(f"Transcript length: {len(transcript.text)} chars")

    summary = summarize_transcript(episode, transcript)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"\nTL;DR: {summary.tldr}")
    print(f"\nWho Should Listen: {summary.who_should_listen}")
    print(f"\nCategories: {', '.join(summary.categories)}")
    print(f"\nKey Insights ({len(summary.key_insights)}):")
    for insight in summary.key_insights:
        print(f"  - {insight}")
    print(f"\nSoundbites ({len(summary.soundbites)}):")
    for sb in summary.soundbites[:3]:
        print(f"  \"{sb['quote'][:80]}...\" — {sb['speaker']}")
