# Podcastwise Prompts

This document contains the prompts used for generating podcast summaries.

---

## Main Extraction Prompt

Used for each transcript (or each chunk if the transcript is very long).

```
You are an expert podcast analyst. Your task is to extract structured insights from a podcast transcript.

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

{
  "tldr": "A 2-3 sentence summary capturing the main topic and key conclusion. What would you tell someone who asks 'what was this episode about?'",

  "who_should_listen": "One sentence describing the ideal audience. Example: 'Anyone interested in AI safety' or 'Founders raising their first round'",

  "key_insights": [
    "3-7 key insights or 'aha moments' from the episode. Novel ideas, counterintuitive findings, or things that shift thinking."
  ],

  "frameworks": [
    {
      "name": "Name of the framework, model, or concept",
      "description": "Brief explanation of how it works"
    }
  ],

  "soundbites": [
    {
      "quote": "A memorable, quotable statement from the episode (2-4 sentences max)",
      "speaker": "Name of who said it"
    }
  ],

  "takeaways": [
    "Actionable items the listener can actually DO after listening. Be specific and practical."
  ],

  "references": {
    "books": ["Book Title by Author"],
    "people": ["Person Name - brief context of why mentioned"],
    "tools": ["Tool/Product Name - what it does"],
    "links": ["Any URLs or resources mentioned"]
  },

  "categories": ["Select 1-3 from: Tech, Finance, News, Health, Humor, Science, Business, Relationships. You may add ONE new category if none fit well."]
}

Important guidelines:
- Extract 2-7 soundbites that are memorable and quotable
- For frameworks, only include explicitly named concepts or models discussed
- Be specific in takeaways - avoid generic advice
- If no books/people/tools were mentioned, use empty arrays
- Keep the tldr concise but informative
- Categories should reflect the PRIMARY topics, not tangential mentions

Return ONLY the JSON object, no additional text.
```

---

## Synthesis Prompt (for Long Episodes)

Used when a transcript is too long and needs to be processed in chunks. This prompt combines the individual chunk summaries into one cohesive summary.

**When is this used?**
- Transcripts longer than ~500,000 characters are split into chunks
- Each chunk is summarized using the main extraction prompt
- Then this synthesis prompt combines them

```
You are synthesizing summaries from a long podcast episode that was processed in chunks.

<podcast_info>
Podcast: {podcast_name}
Episode: {episode_title}
</podcast_info>

Here are the summaries from each chunk:

{chunk_summaries}

Synthesize these into a single cohesive summary. Combine insights, remove duplicates, and create a unified view.

Return a JSON object with these keys:
{
  "tldr": "2-3 sentence overall summary",
  "who_should_listen": "One sentence on ideal audience",
  "key_insights": ["Combined list of unique insights, max 7"],
  "frameworks": [{"name": "...", "description": "..."}],
  "soundbites": [{"quote": "...", "speaker": "..."}],
  "takeaways": ["Combined actionable items"],
  "references": {"books": [], "people": [], "tools": [], "links": []},
  "categories": ["1-3 categories"]
}

Return ONLY the JSON object.
```

---

## Variables

| Variable | Description |
|----------|-------------|
| `{podcast_name}` | Name of the podcast (e.g., "Odd Lots") |
| `{episode_title}` | Title of the episode |
| `{host}` | Host name(s) |
| `{duration}` | Episode duration (e.g., "1h 30m") |
| `{transcript}` | Full transcript text |
| `{chunk_summaries}` | Combined JSON summaries from each chunk |

---

## Output Structure

The prompts generate a JSON object that maps to this markdown structure:

| JSON Field | Markdown Section |
|------------|------------------|
| `tldr` | ## TL;DR |
| `who_should_listen` | ## Who Should Listen |
| `key_insights` | ## Key Insights (bullet list) |
| `frameworks` | ## Frameworks & Models (with descriptions) |
| `soundbites` | ## Soundbites (blockquotes) |
| `takeaways` | ## Key Takeaways / Action Items (checkboxes) |
| `references` | ## References Mentioned (books, people, tools, links) |
| `categories` | YAML frontmatter |

---

## Customization

To modify the prompts, edit `src/summarizer.py`:
- `EXTRACTION_PROMPT` — Main prompt (line ~35)
- `SYNTHESIS_PROMPT` — Chunking synthesis prompt (line ~165)

Common modifications:
- Change number of insights (currently 3-7)
- Change number of soundbites (currently 2-7)
- Add new extraction fields
- Modify category list
- Adjust tone/style instructions
