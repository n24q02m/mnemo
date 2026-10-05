# LLM Compression

**Per-turn LLM compression** runs as a post-dedup step inside
`memory(action="capture")`. The goal is roughly **3x token
reduction at >=0.9 fact retention** so memory recall quality stays
intact while storage + retrieval costs drop.

## When compression runs

Compression fires automatically when ALL of the following are true:

1. `memory(action="capture", text=...)` is called.
2. The dedup probe did NOT short-circuit (no near-duplicate exists).
3. `COMPRESSION_ENABLED=true` (the default).
4. The chat cell (`[models.chat]`) is configured (OpenRouter default
   pre-wired via `hull config init`; any OpenAI-spec endpoint works).

If any of these is false, the row stores the raw text with
`compressed=false` and the pipeline gracefully skips. No exception is
raised; future rows can still compress once the cell is configured.

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

For rows captured before `COMPRESSION_ENABLED` was true (e.g. older
data carried through an upgrade), call:

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

## Model override

The model comes from the `[models.chat]` cell in the instance config
(`base_url` + `api_key` + `model`; OpenRouter default). Point the cell at
a different OpenAI-compatible endpoint or model to change the compression
provider -- config, not code. There are no per-provider env keys and no
auto-detect order; the historical `COMPRESSION_PROVIDER` /
`COMPRESSION_MODEL` env overrides and the `llm.detect_provider` priority
(Gemini > OpenAI > Anthropic > xAI) were removed in the 2026-09 de-host.

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
