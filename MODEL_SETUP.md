# Model Configuration Guide

Podcastwise supports multiple LLM providers for podcast summarization.

## Available Models

Run `podcastwise --list-models` to see all available options:

```
Anthropic (direct API):
  sonnet       → claude-sonnet-4-20250514
  haiku        → claude-3-5-haiku-20241022
  opus         → claude-opus-4-20250514

OpenRouter:
  or-sonnet    → anthropic/claude-sonnet-4
  or-haiku     → anthropic/claude-3.5-haiku
  or-opus      → anthropic/claude-opus-4
  gpt-4o       → openai/gpt-4o
  gpt-4-turbo  → openai/gpt-4-turbo
  llama-70b    → meta-llama/llama-3-70b-instruct
  deepseek     → deepseek/deepseek-chat
```

## Setup

### Option 1: Anthropic API (Direct)

1. Get an API key from [console.anthropic.com](https://console.anthropic.com)
2. Add to `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```

### Option 2: OpenRouter

OpenRouter lets you use Claude, GPT-4, Llama, and other models with a single API key.

1. Get an API key from [openrouter.ai](https://openrouter.ai)
2. Add to `.env`:
   ```
   OPENROUTER_API_KEY=sk-or-v1-...
   ```

## Usage

### Per-run model selection

Use the `--model` or `-m` flag:

```bash
# Use Haiku (faster, cheaper)
podcastwise -n 5 --batch --model haiku

# Use GPT-4o via OpenRouter
podcastwise -n 5 --batch --model gpt-4o

# Use Claude via OpenRouter
podcastwise -n 5 --batch --model or-sonnet
```

### Set default model

Add to `.env`:
```
DEFAULT_MODEL=haiku
```

Now all runs will use Haiku unless you specify `--model`.

## Model Comparison

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `sonnet` | Medium | High | $$ |
| `haiku` | Fast | Good | $ |
| `opus` | Slow | Highest | $$$$ |
| `gpt-4o` | Fast | High | $$ |
| `deepseek` | Fast | Good | $ |

## Examples

```bash
# Quick batch with Haiku
podcastwise -n 10 --batch --model haiku --no-rate-limit

# High quality with Sonnet (default)
podcastwise -n 5 --batch

# Use OpenRouter's Claude
podcastwise -n 5 --batch --model or-sonnet

# Filter by podcast and date with specific model
podcastwise -p "lex fridman" --from 2026-01-01 --model gpt-4o --batch
```
