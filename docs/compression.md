# LLM Compression

Mnemo Phase 2 introduces **per-turn LLM compression** as a post-dedup
step inside `memory(action="capture")`. The goal is roughly **3x token
reduction at >=0.9 fact retention** so memory recall quality stays
intact while storage + retrieval costs drop.

## When compression runs

Compression fires automatically when ALL of the following are true:

1. `memory(action="capture", text=...)` is called.
2. The dedup probe did NOT short-circuit (no near-duplicate exists).
3. `COMPRESSION_ENABLED=true` (the default).
4. At least one LLM provider env key is set
   (`GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` /
   `XAI_API_KEY`), OR `COMPRESSION_PROVIDER` explicitly names one.

If any of these is false, the row stores the raw text with
`compressed=false` and the pipeline gracefully skips. No exception is
raised; future rows can still compress once you configure a provider.

## What is preserved

The compression prompt explicitly instructs the model to retain:

- Concrete facts (numbers, dates, prices)
- Decisions ("we picked X because Y")
- Preferences ("I always want Z")
- Names (people, products, places)
- File paths + URLs
- Code identifiers (function / variable / class names)
- Quoted phrases

Filler text (greetings, hedging, repeated context, transitional phrases)
is dropped.

## What is stripped

- Filler / transitional words ("so", "well", "you know")
- Repeated context within the same turn
- Hedging that does not change meaning
- Pleasantries

## Graceful skip

When the LLM call fails (SDK exception, empty response, rate limit, env
missing), compression silently degrades to a raw store. The row is still
captured -- you never lose data because the compression provider is
flaky. Counts:

- `tokens_in` always reflects the original text.
- `tokens_out == tokens_in` on graceful skip (no rewrite happened).
- `compressed == False` on graceful skip.

Set `LOG_LEVEL=DEBUG` to see when compression skipped and why.

## Manual re-compression

For rows captured before `COMPRESSION_ENABLED` was true (e.g. Phase 1
data carried through Phase 2 upgrade), call:

```
memory(action="compress", memory_id="<id>")
```

This reruns the LLM compression pipeline on the existing row, updating
`content` + `text_raw` + `compressed` + `compression_provider` +
`updated_at`. Already-compressed rows return `status=already_compressed`
without burning an LLM call.

## Disable compression

```
COMPRESSION_ENABLED=false
```

When disabled, capture stores the raw text always. Useful when:

- You want byte-exact transcripts for audit
- You are debugging a memory recall regression and want to rule out
  compression as a variable
- You want to avoid LLM API costs for high-volume captures

## Per-provider override

```
COMPRESSION_PROVIDER=openai
COMPRESSION_MODEL=gpt-5-mini
```

When set, these win over the auto-detected provider priority
(Gemini > OpenAI > Anthropic > xAI from `llm.detect_provider`). Use this
when you want compression on a different provider than the LLM you use
for graph extraction or importance scoring.

## Provider priority

Default order (matches `llm.detect_provider`):

1. Gemini (`GEMINI_API_KEY` or `GOOGLE_API_KEY`)
2. OpenAI (`OPENAI_API_KEY`)
3. Anthropic (`ANTHROPIC_API_KEY`)
4. xAI (`XAI_API_KEY`)

Free-tier-friendly default: Gemini Flash gives you reasonable
compression quality at zero cost up to the free quota.

## How it works (under the hood)

```
capture(text)
  -> dedup probe
  -> compress(text)
       -> tiktoken.encode(text) -> tokens_in
       -> llm.call_llm(COMPRESSION_PROMPT.format(text=text),
                       provider=resolved, model=resolved,
                       temperature=0.0,
                       max_tokens=tokens_in // 2)
       -> tiktoken.encode(result) -> tokens_out
       -> {text, text_raw, compressed=True, provider, tokens_in, tokens_out}
  -> db.add_with_context_type(content=result.text,
                              text_raw=result.text_raw,
                              compressed=True,
                              compression_provider=...)
```

`tiktoken cl100k_base` is the tokenizer (matches OpenAI + Anthropic
estimates closely enough for the 3x metric). The prompt asks for "<= 1/3
of the original tokens" so a moderate compression ratio is the explicit
target -- the model is not asked to be maximally terse, just to drop
filler.
