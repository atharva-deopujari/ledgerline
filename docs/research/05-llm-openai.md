# 05 — LLM: OpenAI gpt-5.6-luna inside Pipecat

Researched 2026-09-11 against live OpenAI docs, Pipecat v1.9.0 source (released 2026-09-11), and public issue trackers. Anything not confirmed from a primary source is marked **UNVERIFIED**.

## Decision summary

- **Model id:** `gpt-5.6-luna`. Cheapest tier of the GPT-5.6 family (Sol / Terra / Luna). $0.20 in / $0.02 cached / $1.20 out per 1M tokens after the 30 Jul 2026 price cut. 1,050,000-token context, 128k max output, knowledge cutoff 16 Feb 2026.
- **Luna reasons by default** (`reasoning.effort` default `medium`). For voice we must set effort to **`none`**: measured TTFT drops from ~1.9 s (medium) to ~0.65–0.9 s (none).
- **Hard constraint:** on `/v1/chat/completions`, gpt-5.6 models reject function tools unless `reasoning_effort="none"` (400 error, fires even when you never set the param). This is documented behaviour and applies **from GPT-5.4 onward, not just gpt-5.6** (corrected via context7): "starting with GPT-5.4, Chat Completions does not support tool calling with reasoning_effort values other than none." Pipecat's `OpenAILLMService` uses Chat Completions, so with it we MUST pass `extra={"reasoning_effort": "none"}`.
- **Recommended service:** `OpenAIResponsesLLMService` (Responses API, WebSocket, in `pipecat-ai[openai]`). It auto-sends `reasoning: {"effort": "none"}` for gpt-5.x when you leave `reasoning` unset, supports `ReasoningConfig`, uses `previous_response_id` for incremental context, and passes `strict` through to tool schemas. Fallback: `OpenAILLMService` with `extra={"reasoning_effort": "none"}`.
- **Do not set `temperature`/`top_p`** on luna: GPT-5.x reasoning-family models reject sampling params (Azure/Foundry error `'top_p' is not supported with this model`). Leave them `NOT_GIVEN` (Pipecat's default). `verbosity="low"` is the right knob for short spoken output.
- **Function calling:** streaming tool-call deltas are assembled by Pipecat; use `FunctionSchema` (explicit enums) or direct functions; keep tool descriptions short; ask for `parallel_tool_calls=False` (via `extra`) so the finance planner records one fact per turn.
- **Cost of the test plan:** ~1.35M input + ~55k output tokens per pass ≈ **$0.35** (≈ $0.70 if every turn triggers a tool call + follow-up). Under $1 either way; caching cuts input further.
- **Fallback model if luna misbehaves:** `gpt-4.1-mini` (non-reasoning, temperature works, 0.9 s TTFT, 2× the price). `gpt-4o-mini` is cheaper but has a 2023 cutoff and is de-facto legacy; `gpt-5-mini` snapshot is scheduled for API shutdown 11 Dec 2026.

## 1. The GPT-5.6 family

Launched 10 Jul 2026 in three durable tiers: **Sol** (flagship), **Terra** (balanced), **Luna** (fast/cheap). API ids are `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`; there is also a `gpt-5.6-luna-pro` on OpenRouter and Sol has a `reasoning.mode: pro`. The luna model card shows a single alias, no dated snapshot. The bare `gpt-5.6` alias routes to Sol (added via context7). Fast mode is requested with `service_tier="fast"` (or `"priority"`; both opt in, and the response reports `"priority"`) at 2× standard price (luna fast: $0.40 / $0.04 / $2.40) — the canonical value in the current Fast mode guide is `"fast"` (corrected via context7).

| | Luna | Terra | Sol |
|---|---|---|---|
| Input / cached / output per 1M | $0.20 / $0.02 / $1.20 | $2.00 / $0.20 / $12.00 | $4.00 / $0.40 / $20.00 |
| Context / max output | 1,050,000 / 128,000 | 1,050,000 / 128,000 (corrected via context7) | 1,050,000 / 128,000 (corrected via context7) |
| Knowledge cutoff | 16 Feb 2026 | 16 Feb 2026 (corrected via context7) | 16 Feb 2026 (corrected via context7) |

Luna specifics (model card): modalities text+image in, text out; endpoints Chat Completions, Responses, Batch (no Realtime/Assistants); features streaming, structured outputs, function calling, prompt caching. Prices were $1 / $6 at launch; cut 80 % on 30 Jul 2026. Two billing riders the original draft missed (added via context7): prompts over **272K input tokens are billed at 2× the input rate and 1.5× the output rate for the whole request**, and **cache writes cost 1.25× the uncached input rate**. Neither bites our ~3k-token contexts, but the cache-write surcharge slightly worsens the "$0.10–0.15 with caching" figure in §8.

**Rate limits for luna** (from the model card): Tier 1 (after $5 paid) 500 RPM / 500,000 TPM; Tier 2 ($50 paid) 5,000 RPM / 2,000,000 TPM. Usage caps: Tier 1 $100/month, Tier 2 $500/month. A single voice session at ~3k tokens/turn and one turn every ~10 s is ~20k TPM, so Tier 1 comfortably handles 10+ concurrent test sessions.

## 2. Reasoning, verbosity, sampling params

- **Reasons by default.** Model card: "Reasoning.effort supports: none, low, medium (default), high, xhigh, and max." `minimal` is in the generic reasoning guide list but not in luna's list — treat `minimal` as **UNVERIFIED for luna**; use `none`.
- **Parameter names:** Chat Completions `reasoning_effort: "none"`; Responses `reasoning: {"effort": "none"}`.
- **TTFT impact (Artificial Analysis, OpenAI endpoint, P50, 10k-token prompt):** non-reasoning 0.65–0.90 s; low 1.72 s; medium 1.93 s; high 16.98 s; xhigh 43 s; max 168 s. Output speed ~110 tok/s. For a voice turn the difference between `none` and the default `medium` is roughly +1.1 s before the first word, which is the whole latency budget. Use `none`. OpenAI's own voice-prompting guide says to start at `low` for Realtime agents; for a chained STT→LLM→TTS stack with tool calls, `none` is the pragmatic choice and is what Pipecat's Responses service defaults to.
- **Verbosity:** `verbosity: "low" | "medium" | "high"` (default `medium`) exists on Chat Completions and as `text.verbosity` on Responses; the GPT-5.6 prompting guide explicitly highlights it. Use `low`.
- **Temperature / top_p:** the luna model card lists no sampling params. GPT-5.x reasoning-family models reject them ("Unsupported parameter: 'top_p' is not supported with this model", reproduced on Azure Foundry for gpt-5.6-luna). One community report claims "only the default (1) value is supported" — **UNVERIFIED whether temperature is accepted when effort is `none`**. Safe rule: never send them. Pipecat only sends fields you set, so just omit.

## 3. Chat Completions vs Responses API in Pipecat

- `pipecat.services.openai.llm.OpenAILLMService` → **Chat Completions** (`self._client.chat.completions.create(**params)`, streaming with `stream_options.include_usage`).
- `pipecat.services.openai.responses.llm.OpenAIResponsesLLMService` → **Responses API over WebSocket** (`wss://api.openai.com/v1/responses`, PR #4141 made WS the default); `OpenAIResponsesHttpLLMService` is the HTTP variant. Both ship in `pipecat-ai[openai]` and work with the universal `LLMContext` / `LLMContextAggregatorPair`. Examples: `examples/function-calling/function-calling-openai-responses*.py`.
- **Why it matters:** OpenAI now returns `400 Function tools with reasoning_effort are not supported for gpt-5.6-luna in /v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to 'none'.` This fires even with no `reasoning_effort` in the request because the default is `medium` (confirmed in LibreChat #14355, LiteLLM #33221, Vane #1173, Pipecat #4043 for gpt-5.4). OpenAI Support (7 Sep 2026) says Responses is the supported path.
- **Recommendation:** use `OpenAIResponsesLLMService`. Reasons: (1) it is the endpoint OpenAI supports for tools + GPT-5.6; (2) its `_maybe_disable_reasoning()` sends `effort="none"` automatically for gpt-5.x when `reasoning` is unset, so you cannot forget; (3) `previous_response_id` sends only the incremental context on a persistent socket (lower latency and fewer input tokens; `store=False` so nothing is kept server-side 30 days); (4) `strict` propagates to tool schemas. Keep `OpenAILLMService` + `extra={"reasoning_effort": "none", "verbosity": "low"}` as a one-line fallback if the WS service misbehaves (it is newer code).

## 4. Pipecat OpenAILLMService details (v1.9.0)

- Import: `from pipecat.services.openai.llm import OpenAILLMService`. Install: `pipecat-ai[openai]`.
- **`params=OpenAILLMService.InputParams(...)` is deprecated since v0.0.105.** Use `settings=OpenAILLMService.Settings(...)`; `model` moved into `Settings` (default `"gpt-4.1"`).
- Constructor: `api_key`, `base_url`, `organization`, `project`, `default_headers`, `service_tier`, `params` (deprecated), `settings`, `retry_timeout_secs=5.0`, `retry_on_timeout=False`.
- `Settings` fields: `model`, `system_instruction`, `temperature`, `top_p`, `max_tokens` (deprecated upstream), `max_completion_tokens`, `frequency_penalty`, `presence_penalty`, `seed`, `top_k`, `extra: dict`. All default `NOT_GIVEN` so nothing is sent unless set.
- `reasoning_effort`, `verbosity`, `parallel_tool_calls`, `prompt_cache_key` are **not first-class**; pass them in `extra`. `build_chat_completion_params()` does `params.update(self._settings.extra)` last, so `extra` overrides everything.
- Runtime changes: `LLMUpdateSettingsFrame(delta=OpenAILLMService.Settings(...))` (uninterruptible).

```python
llm = OpenAILLMService(
    api_key=os.environ["OPENAI_API_KEY"],
    settings=OpenAILLMService.Settings(
        model="gpt-5.6-luna",
        max_completion_tokens=200,
        extra={"reasoning_effort": "none", "verbosity": "low", "parallel_tool_calls": False},
    ),
)
```

Responses equivalent (preferred):

```python
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
llm = OpenAIResponsesLLMService(
    api_key=os.environ["OPENAI_API_KEY"],
    settings=OpenAIResponsesLLMService.Settings(
        model="gpt-5.6-luna",
        max_completion_tokens=200,          # mapped to max_output_tokens
        reasoning=OpenAIResponsesLLMService.ReasoningConfig(effort="none"),  # explicit; auto if omitted
        extra={"text": {"verbosity": "low"}, "parallel_tool_calls": False},   # UNVERIFIED key shape for verbosity
    ),
)
```

**Streaming tool calls:** the Chat Completions service accumulates `tool_call.function.name` and `tool_call.function.arguments` string fragments per `tool_call.index`, captures `tool_call.id`, and after the stream ends wraps them as `FunctionCallFromLLM` and calls `run_function_calls()`. Multiple calls in one turn run with `run_in_parallel=True` and `group_parallel_tools=True` (one LLM re-run after all results). `parallel_tool_calls` is not set by Pipecat; OpenAI's default is `true`, so pass `False` via `extra` if you want exactly zero or one call per turn.

## 5. Function-calling quality on luna

- OpenAI's launch material claims luna "selects tools more accurately on the first call, constructing valid arguments without the retry cycles GPT-4o often required." Independent reports on argument hallucination are scarce; the bugs filed against luna are API-surface issues (the reasoning_effort/tools 400; an intermittent 500 on image-only function outputs in Responses). Treat tool quality as **good but unmeasured for our domain — UNVERIFIED**; the project's eval harness should log tool-call success.
- The GPT-5.6 prompting guide's message: shorter prompts and **"keep tool descriptions concise and precise"**; leaner prompts scored 10–15 % better with 40–66 % fewer tokens. Expose only task-relevant tools (< 20).
- OpenAI function-calling guide: "We recommend always enabling strict mode" (`strict: true`, `additionalProperties: false`, all properties `required`, optional = `type: ["number","null"]`). "Don't make the model fill arguments you already know." Put when/when-not-to-call rules in the system prompt.
- **Pipecat strict support:** `FunctionSchema(name, description, properties, required, handler=)` has no `strict` field in v1.9.0; the Responses adapter forwards `d.get("strict", None)` so it is `None`. To get strict mode, pass raw OpenAI tool dicts through `ToolsSchema(custom_tools={AdapterType.OPENAI: [...]})` — **UNVERIFIED that the Responses adapter reads the same key**; test once, otherwise accept non-strict and validate arguments in Python (which we must do anyway).
- Direct functions (async def with `params: FunctionCallParams` + typed args + Google docstring) are the preferred pattern but do not emit JSON enums yet; use `FunctionSchema` for `enum` fields such as expense category.

## 6. Voice prompt engineering with luna

OpenAI's voice-prompting guide (written for Realtime, largely applicable to chained pipelines) and the Pipecat examples converge on:

- Tone line + format ban, verbatim from Pipecat's example: *"You are a helpful assistant in a voice conversation. Your responses will be spoken aloud, so avoid emojis, bullet points, or other formatting that can't be spoken."*
- "Keep responses to 2–3 sentences per turn"; "Do not include lists or markdown in voice responses."
- "When collecting required values, ask for only the next missing item. Do not ask for multiple values in the same turn."
- "For numeric identifiers, read the value back digit by digit… Is that right?" — adapt to money: repeat the amount in words before recording it.
- "Only say an action was completed after the tool call succeeds… If the tool fails, explain briefly, avoid raw errors, give a clear next step."
- Preamble before a tool call ("I'll note that down.") masks latency; Pipecat can speak it via `on_function_calls_started` + `TTSSpeakFrame`.

**Making all numbers come from tools:** state it as an outcome rule (GPT-5.6 responds better to outcomes than procedures): "You never compute, add, subtract, or estimate. Every number you say must appear verbatim in the most recent tool result. If you need a total or a daily budget, call `compute_plan` and read back its fields." Reinforce structurally: return totals as pre-formatted strings from the tool (e.g. `"daily_budget_spoken": "one thousand two hundred rupees"`), give tools names like `record_income` / `record_expense` / `get_summary`, and set `parallel_tool_calls=False` so the model records one fact, hears the result, then asks the next question. Combine with `verbosity="low"` and `max_completion_tokens≈200`.

## 7. Alternatives if luna misbehaves

| Model | In / cached / out ($/1M) | TTFT (OpenAI, P50) | Temp OK? | Status |
|---|---|---|---|---|
| gpt-5.6-luna (effort none) | 0.20 / 0.02 / 1.20 | 0.65–0.90 s | No (omit) | Current; 1.05M ctx; cutoff Feb 2026 |
| gpt-5.4-mini (effort none default) | 0.75 / 0.075 / 4.50 | UNVERIFIED | No | Current; 400k ctx; cutoff Aug 2025 |
| gpt-4.1-mini | 0.40 / 0.10 / 1.60 | 0.90 s | Yes | Current in API (retired from ChatGPT Feb 2026); no reasoning; 1M ctx |
| gpt-4o-mini | 0.15 / 0.075 / 0.60 | 0.91 s, 150 tok/s | Yes | Current in API but 128k ctx, cutoff Oct 2023; AA flags as deprecated |
| gpt-5-mini | 0.25 / 0.025 / 2.00 | 77 s at high; none UNVERIFIED | No | `gpt-5-mini-2025-08-07` shuts down 11 Dec 2026 → avoid |

Order of fallback: `gpt-4.1-mini` first (same Pipecat code, delete the `reasoning`/`extra` lines, temperature usable), then `gpt-5.4-mini`. Note `gpt-4.1-nano` is scheduled for shutdown 23 Oct 2026 with luna as the named replacement.

## 8. Cost estimate for the test plan

Assumptions: 30 conversations × 15 turns, ~3,000 tokens of context per LLM call, ~120 output tokens per call (a short sentence + tool-call JSON).

- Input: 30 × 15 × 3,000 = 1.35M tokens × $0.20 = **$0.27**
- Output: 30 × 15 × 120 = 54k tokens × $1.20 = **$0.065**
- **≈ $0.34 per full pass.** If every turn is tool-call → result → second completion, double it: **≈ $0.70**.
- Prompt caching: system prompt + tools + history prefix is identical across the two calls of a turn and mostly identical turn to turn; at $0.02 cached, realistic input cost falls to roughly $0.10–0.15. Responses WS + `previous_response_id` also avoids re-sending the prefix at all.
- Same plan on gpt-4.1-mini ≈ $0.63–1.25; on gpt-4o-mini ≈ $0.24–0.48. All negligible against Daily/STT/TTS minutes.

## Gotchas

1. **The 400 that looks like a Pipecat bug** ("Function tools with reasoning_effort are not supported… in /v1/chat/completions") is an OpenAI constraint. Fix: Responses service, or `extra={"reasoning_effort": "none"}` on `OpenAILLMService`.
2. **`params=InputParams(...)` is deprecated**; write `settings=...Settings(...)` and put `model` inside `Settings`.
3. Do not set `temperature`/`top_p` on any gpt-5.x model; leave defaults.
4. `max_tokens` is deprecated upstream; use `max_completion_tokens` (Responses service maps it to `max_output_tokens`).
5. Pipecat's default `model` is `gpt-4.1`; forgetting `model="gpt-5.6-luna"` silently runs a different model.
6. Pipecat `FunctionSchema` has no `strict`; validate tool args in Python.
7. Effort `none` plus tools means the model gets no thinking time; keep tool schemas simple (flat numbers, enums) and let Python own all arithmetic.
8. Reasoning effort `medium` (default) alone adds ~1 s TTFT; `high`+ is unusable for voice.
9. The Responses WS service is new (v1.8/1.9); keep the Chat Completions fallback wired behind an env flag.
10. Fast mode (`service_tier="priority"`) doubles price; not needed at Tier 1 volumes.

## Sources

- Luna model card: https://developers.openai.com/api/docs/models/gpt-5.6-luna
- Pricing: https://developers.openai.com/api/docs/pricing
- Rate limits / tiers: https://developers.openai.com/api/docs/guides/rate-limits
- Reasoning guide: https://developers.openai.com/api/docs/guides/reasoning
- Function calling guide (strict, parallel_tool_calls, best practices): https://developers.openai.com/api/docs/guides/function-calling
- Chat Completions reference (reasoning_effort, verbosity, service_tier): https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create
- Voice agents guide: https://developers.openai.com/api/docs/guides/voice-agents ; voice prompting: https://developers.openai.com/api/docs/guides/voice-prompting
- Deprecations: https://developers.openai.com/api/docs/deprecations
- GPT-5.6 launch: https://openai.com/index/gpt-5-6/ ; price drop 30 Jul 2026: https://community.openai.com/t/announcing-a-major-price-drop-for-5-6-terra-and-luna-and-fast-mode-for-5-6-sol/1388484
- gpt-5.6 + tools 400 on Chat Completions: https://community.openai.com/t/gpt-5-6-chat-completion-reasoning-effort-bug-behavior-change/1386454 ; https://github.com/danny-avila/LibreChat/issues/14355 ; https://github.com/BerriAI/litellm/issues/33221 ; https://github.com/itzcrazykns/vane/issues/1173
- Luna rejects temperature/top_p: https://learn.microsoft.com/en-sg/answers/questions/5989904/gpt-5-6-luna-thread-runs-fail-because-parameters-t
- Latency benchmarks: https://artificialanalysis.ai/models/gpt-5-6-luna-non-reasoning/providers (+ -low, -medium, -high variants) ; https://artificialanalysis.ai/models/gpt-4-1-mini/providers ; https://artificialanalysis.ai/models/gpt-4o-mini/providers
- GPT-5.6 prompting guide coverage: https://decrypt.co/373439/openai-new-gpt-5-6-prompt-guide-chatgpt
- Pipecat OpenAILLMService docs: https://docs.pipecat.ai/api-reference/server/services/llm/openai ; Responses service: https://docs.pipecat.ai/api-reference/server/services/llm/openai-responses ; settings pattern: https://docs.pipecat.ai/pipecat/fundamentals/service-settings ; function calling: https://docs.pipecat.ai/pipecat/learn/function-calling
- Pipecat source (main, v1.9.0): src/pipecat/services/openai/base_llm.py, src/pipecat/services/openai/responses/llm.py, src/pipecat/adapters/services/open_ai_adapter.py, open_ai_responses_adapter.py, adapters/schemas/function_schema.py; examples/function-calling/function-calling-direct.py, function-calling-openai-responses.py
- Pipecat issue on the same 400 (gpt-5.4): https://github.com/pipecat-ai/pipecat/issues/4043
- Alternative model cards: https://developers.openai.com/api/docs/models/gpt-5.4-mini ; https://developers.openai.com/api/docs/models/gpt-5-mini ; https://developers.openai.com/api/docs/models/gpt-4o-mini

---

## Context7 cross-check (2026-09-11)

Every concrete claim above was re-queried against context7 MCP documentation, which the user treats as authoritative and current.

### Libraries consulted

| Library | Context7 id | Notes |
|---|---|---|
| OpenAI API (platform docs + API reference) | `/websites/developers_openai_api` | 7,786 snippets, High reputation, benchmark 80.06. No version pinning offered; served as "current". |
| OpenAI Python SDK | `/openai/openai-python` | 594 snippets, benchmark 84.34. Versions available: v1.68.0, v1_105_0, v2.8.1, v2.11.0. |
| OpenAI Python SDK (deepwiki mirror) | `/websites/deepwiki_openai_openai-python` | 1,075 snippets; not needed once the platform docs answered. |
| Pipecat docs | `/pipecat-ai/docs` | 6,869 snippets, High reputation, benchmark 78.01. No version pinning; snippets sourced from `github.com/pipecat-ai/docs` main. |
| Pipecat source | `/pipecat-ai/pipecat` | 3,072 snippets; alternate. |
| Pipecat API reference | `/websites/reference-server_pipecat_ai_en` | 2,654 snippets; alternate. |

### Claims table

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | GPT-5.6 family is Sol / Terra / Luna, ids `gpt-5.6-sol` / `-terra` / `-luna` | VERIFIED | Separate model-card pages exist for all three; `beta.responses.create` types `model` as `Literal["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", ...]`. |
| 2 | Bare `gpt-5.6` alias | VERIFIED (new) | "GPT-5.6 Sol is the frontier model in the GPT-5.6 family… with the gpt-5.6 alias routing directly to it." |
| 3 | Luna is the cheapest/lowest tier | VERIFIED | "GPT-5.6 Luna is designed for cost-sensitive, high-volume workloads and roughly corresponds to the nano model tier used in earlier GPT-5 families." Terra "roughly corresponding to the mini model tier". |
| 4 | Luna $0.20 in / $0.02 cached / $1.20 out per 1M | VERIFIED | "GPT-5.6 Luna pricing is $0.20 per 1M input tokens, $0.02 per 1M cached input tokens, and $1.20 per 1M output tokens." |
| 5 | Sol $4.00 / $0.40 / $20.00 | VERIFIED | Pricing page: "gpt-5.6-sol cost $4.00 for short context input, $0.40 for cached input, $5.00 for cache writes, and $20.00 for output per 1M tokens". |
| 6 | Terra $2.00 / $0.20 / $12.00 | NOT COVERED | The pricing snippet returned only Sol and Luna numbers. Left in the body unchanged. |
| 7 | Long-context and cache-write surcharges | CONTRADICTED (incomplete) → corrected inline | "Prompts exceeding 272K input tokens are billed at 2x the input rate and 1.5x the output rate for the complete request. Additionally, cache writes are charged at 1.25x the uncached input token rate." The draft's flat $0.20/$0.02 model omitted both. |
| 8 | Luna 1,050,000 context, 128,000 max output, cutoff 16 Feb 2026 | VERIFIED | Luna model card, verbatim. |
| 9 | Terra / Sol context and cutoff "UNVERIFIED" | CONTRADICTED → corrected inline | Both cards state 1,050,000 / 128,000 / 16 Feb 2026. Bedrock guide corroborates: "GPT-5.4 and GPT-5.5 support a 272,000-token context window, whereas GPT-5.6 Sol, Terra, and Luna support up to 1,050,000 tokens." |
| 10 | Luna reasoning effort values: `none, low, medium (default), high, xhigh, max` | VERIFIED | Luna card verbatim; Terra and Sol identical. |
| 11 | `minimal` is in the generic reasoning list but not luna's | VERIFIED | API-level allowed values are `"none", "minimal", "low", "medium", "high", "xhigh", "max"`; the luna/terra/sol model cards omit `minimal`. The draft's distinction is exactly right. |
| 12 | Default effort is `medium` | VERIFIED | "medium (default)" on all three cards; reasoning guide adds "Defaults vary by model; for example, gpt-5.5 defaults to medium". |
| 13 | `none` effort exists | VERIFIED | Listed on every card and in the Chat Completions `reasoning_effort` enum. |
| 14 | Param names: CC `reasoning_effort`, Responses `reasoning.effort` | VERIFIED | `chat.completions.create` takes `reasoning_effort`; `responses.create` takes `reasoning={"effort": ...}`. |
| 15 | `verbosity` exists; `text.verbosity` on Responses; default `medium`; use `low` | VERIFIED (value); default NOT COVERED | Deployment checklist: `text: { verbosity: "low" }` on `responses.create`, "Configure text verbosity to low when compact answers and faster response times with fewer tokens are needed." The `medium` default was not stated in any returned snippet. |
| 16 | GPT-5.x reasoning models reject `temperature` / `top_p` | NOT COVERED | No OpenAI doc returned says this. The Responses **response object** still exposes `temperature` and `top_p` fields, and the generic completions reference documents both without a reasoning-model carve-out. The draft's source (Azure AI Foundry error) is more specific than anything context7 carries; body left unchanged. Treat "never send them" as a safe-by-construction rule, not a documented one. |
| 17 | Chat Completions rejects function tools unless effort is `none` | VERIFIED, and broader than stated → corrected inline | Migration guide: "starting with GPT-5.4, Chat Completions does not support tool calling with reasoning_effort values other than none." The draft scoped this to gpt-5.6 only. |
| 18 | Responses API has a WebSocket mode at `/v1/responses` | VERIFIED | "The Responses API supports a WebSocket mode for long-running, tool-call-heavy workflows over a persistent connection to /v1/responses." |
| 19 | `previous_response_id` sends only incremental context on the socket | VERIFIED | "Each turn can be continued by sending only new input items alongside previous_response_id"; a connection-local cache keeps recent responses in memory for low-latency continuation. |
| 20 | `store=False` works with the WS path | VERIFIED; "30-day server retention" NOT COVERED | "WebSocket mode is compatible with Zero Data Retention (ZDR) and store=false." Migration guide: "Responses are stored by default… both can be disabled by setting store: false." No 30-day figure appeared. |
| 21 | New failure mode the draft missed | ADDED (new) | WS mode can return `previous_response_not_found` (400) after a connection cache reset; recovery is to resend with `previous_response_id: null` plus full input. There is also a `client.responses.compact()` endpoint for compacting a long window. See "Corrections applied". |
| 22 | Fast mode via `service_tier="priority"` | PARTIALLY CONTRADICTED → corrected inline | Current docs: "setting 'fast' or 'priority' opts in to Fast mode at the request level (reflected as 'priority' in the response)". `"fast"` is the canonical value in the Fast mode guide; the full enum is `auto, default, flex, fast, priority`. |
| 23 | 2× price for Fast mode (luna $0.40/$0.04/$2.40) | NOT COVERED | The Fast mode guide snippet shows usage, not pricing. |
| 24 | Prompt caching cuts input cost; cached rate $0.02 | VERIFIED (rate) / REFINED | Caching "is automatically evaluated for prompts of 1,024 tokens or longer"; cache hits bill "at the discounted cached-input rate". But GPT-5.6+ also supports **explicit** caching (`prompt_cache_options.mode: "explicit"`, `prompt_cache_breakpoint`), and `prompt_cache_retention` is deprecated in favour of `prompt_cache_options.ttl`. Track `cached_tokens` and `cache_write_tokens` in `input_tokens_details`. |
| 25 | `prompt_cache_key` exists | VERIFIED | A first-class param on `responses.create`; "Replaces `user`". Docs advise ~15 requests/minute per key. |
| 26 | Rate limits: Tier 1 500 RPM / 500k TPM, Tier 2 5,000 RPM / 2M TPM, $100 / $500 caps | NOT COVERED | No tier table returned. Left unchanged. |
| 27 | TTFT numbers (0.65–0.9 s none, 1.93 s medium, 16.98 s high, …) | NOT COVERED | Artificial Analysis benchmarks; OpenAI docs carry no latency figures. Left unchanged. |
| 28 | OpenAI's voice guidance says start at `low` for Realtime agents | VERIFIED | Realtime models prompting guide: "It is recommended to start with a 'low' setting for most production voice agents and adjust based on task complexity, latency requirements, and the cost of failure." Note this is scoped to `gpt-realtime-2`, not to chained pipelines — the draft's framing is accurate. |
| 29 | OpenAI publishes a chained STT→LLM→TTS voice-agent pattern | VERIFIED | Voice agents guide ships a `VoicePipeline` / `SingleAgentVoiceWorkflow` chained example using `model="gpt-5.6"` with `@function_tool`. |
| 30 | Function-calling: "always enable strict mode", `additionalProperties: false`, all props required, optional = nullable type | VERIFIED | "Setting strict to true ensures function calls reliably adhere to the function schema rather than relying on best-effort adherence… requires that additionalProperties is set to false for each object in parameters, and all fields in properties are marked as required. Optional fields can be accommodated by including null as a type option." |
| 31 | "Don't make the model fill arguments you already know"; keep tools < 20 | VERIFIED | "handling parameters in application code rather than relying on the model when values are already known… keep the number of initially available functions under 20 per turn, and consider fine-tuning or tool search for larger toolsets." |
| 32 | `parallel_tool_calls=False` gives zero or one call per turn; OpenAI default is true | VERIFIED | "Setting parallel_tool_calls to false ensures the model calls zero or one tool per turn." Parallel calling is supported "on supported models beginning with GPT-5". |
| 33 | "Keep tool descriptions concise and precise"; leaner prompts score 10–15 % better | NOT COVERED | The prompting-guide statistics come from a third-party write-up; not in context7's OpenAI corpus. Left unchanged. |
| 34 | `gpt-5-mini` snapshot shuts down 11 Dec 2026 | VERIFIED | Deprecations: "Select GPT-5 and o3 model snapshots (including gpt-5-2025-08-07, o3-2025-04-16, and their respective pro and mini variants) are scheduled for shutdown on December 11, 2026, with recommended replacements in the gpt-5.6 model series." |
| 35 | `gpt-4.1-nano` shuts down 23 Oct 2026, luna named as replacement | NOT COVERED (suggestive only) | No gpt-4.1 deprecation entry was returned. The `models.retrieve` reference example does show `"shutdown_date": "2026-10-23"`, consistent with the date but not proof of the model. Left unchanged, flagged. |
| 36 | gpt-5.4-mini / gpt-4.1-mini / gpt-4o-mini prices, context, cutoffs, availability | NOT COVERED | The pricing snippet covered only the GPT-5.6 tier. SDK/platform docs do not enumerate these. Fallback table left unchanged — re-verify against the live pricing page before relying on it. |
| 37 | Pipecat: `params=InputParams(...)` deprecated since v0.0.105; use `settings=Settings(...)`; `model` moves inside `Settings` | VERIFIED | "As of version 0.0.105, the InputParams and params pattern is deprecated in favor of the Settings and settings pattern"; the migration snippet shows `model` moving from constructor arg into `Settings`. |
| 38 | Import `from pipecat.services.openai.llm import OpenAILLMService` | VERIFIED | Exact import in the OpenAI LLM service reference. |
| 39 | `Settings` carries `model`, `temperature`, `max_completion_tokens`, `frequency_penalty`, `system_instruction`, `extra` | VERIFIED (for the fields shown) | Example: `Settings(model="gpt-4.1", temperature=0.7, max_completion_tokens=1000, frequency_penalty=0.5)`; "OpenAI LLM supports `max_completion_tokens`". `top_p`, `presence_penalty`, `seed`, `top_k`, `max_tokens`-deprecation were NOT COVERED individually — they come from the draft's source read, which is more granular. |
| 40 | `extra: dict` passes provider-specific params not in `Settings` | VERIFIED | "Initialize an LLM service with provider-specific parameters using the `extra` dictionary within the `Settings` object. This allows for options not directly supported by the Pipecat Settings dataclass." Example: `extra={"logprobs": True, "top_logprobs": 5}`. |
| 41 | Pipecat's default model is `gpt-4.1` | NOT COVERED | Every doc example passes `model=` explicitly (`"gpt-4.1"`, `"gpt-4o"`); no snippet states the default. The gotcha ("always set `model`") stands regardless. |
| 42 | `LLMUpdateSettingsFrame(delta=...Settings(...))` for runtime changes | VERIFIED | Shown for the OpenAI Realtime service with the same `delta=Settings(...)` shape. |
| 43 | `OpenAIResponsesLLMService` is WebSocket-based and lives at `pipecat.services.openai.responses.llm`; HTTP variant is `OpenAIResponsesHttpLLMService` | VERIFIED | Both imports appear verbatim; "Initializes the WebSocket-based OpenAI LLM service for real-time interactions." |
| 44 | `OpenAIResponsesLLMService.ReasoningConfig(effort="none")` | NOT COVERED | The docs show a reasoning config only for the **Realtime** service: `from pipecat.services.openai.realtime.events import SessionProperties, Reasoning` → `Reasoning(effort="high")`. No `ReasoningConfig` on the Responses service appeared. The draft read it from v1.9.0 source, which is more specific than context7's docs corpus; body left unchanged but **verify the class name against the installed package before writing code**. |
| 45 | `_maybe_disable_reasoning()` auto-sends `effort="none"` for gpt-5.x | NOT COVERED | Source-level detail, absent from the docs corpus. Left unchanged, unverified. |
| 46 | `max_completion_tokens` maps to `max_output_tokens` on Responses | NOT COVERED (plausible) | `beta.responses.create` documents `max_output_tokens` ("Minimum value is 16"); the Pipecat mapping itself was not in a returned snippet. |
| 47 | Pipecat `FunctionSchema` has no `strict` field | VERIFIED (by absence, consistently) | The documented signature is `FunctionSchema(name, description, properties, required, handler)` with no `strict`. Docs also confirm the draft's reason for preferring it: the `enum` is "the kind of explicit control a direct function can't yet express." |
| 48 | Raw OpenAI tool dicts via `ToolsSchema(custom_tools={AdapterType.OPENAI: [...]})` | VERIFIED (mechanism), still UNVERIFIED for the Responses adapter | "When a provider has tools that do not fit Pipecat's standard schema, define them using `ToolsSchema.custom_tools`… `custom_tools` is currently supported for OpenAI-family adapters and Gemini." Whether the *Responses* adapter reads `strict` from those dicts is still untested. |
| 49 | Direct functions = `async def` + `params: FunctionCallParams` + typed args + Google docstring; no enums | VERIFIED | Exact pattern in the function-calling guide, with Google-style `Args:` docstring; enums are named as the thing `FunctionSchema` gives you that direct functions do not. |
| 50 | Multiple calls run with `run_in_parallel=True` and `group_parallel_tools=True` | VERIFIED | "`run_in_parallel` determines if tool calls execute concurrently or sequentially, with the default being parallel execution. `group_parallel_tools` dictates whether the LLM responds once after all tool calls in a batch are finished (when `True`)." Constructor option `run_in_parallel=True  # (default: True)`. |
| 51 | `parallel_tool_calls` is not set by Pipecat; pass via `extra` | VERIFIED (by absence) | It appears in no Pipecat `Settings` field list; the `extra` escape hatch is the documented mechanism. |

Tally: 26 VERIFIED, 3 CONTRADICTED/partially contradicted (all corrected inline), 1 refined, 1 added, 20 NOT COVERED.

### Corrections applied

1. **§Decision summary and §3** — the Chat-Completions-rejects-tools constraint was scoped to gpt-5.6; context7 says it begins at **GPT-5.4**. Rewritten and marked "(corrected via context7)". This strengthens the recommendation to use `OpenAIResponsesLLMService`.
2. **§1 table** — Terra and Sol context window, max output and knowledge cutoff were marked UNVERIFIED. They are documented as **1,050,000 / 128,000 / 16 Feb 2026**, identical to Luna. Filled in and marked.
3. **§1 prose** — Fast mode: `service_tier="fast"` is the canonical current value (`"priority"` also opts in and is what the response reports). Corrected and marked; the full enum `auto | default | flex | fast | priority` added.
4. **§1 prose** — added the bare **`gpt-5.6` alias routes to Sol**, which the draft did not mention (a real footgun: `model="gpt-5.6"` silently buys the $4/$20 flagship instead of luna).
5. **§1 prose** — added the two billing riders the draft omitted: **>272K input tokens bills at 2× input / 1.5× output for the whole request**, and **cache writes cost 1.25× the uncached input rate**. Neither affects our ~3k-token turns, but the cache-write surcharge makes §8's "$0.10–0.15 with caching" slightly optimistic.

### Disagreements left standing (report is more specific than context7)

- **temperature / top_p rejection on GPT-5.x** (claim 16). Context7's OpenAI corpus documents both params generically and the Responses object still exposes them; it carries no reasoning-family carve-out. The report's evidence is a reproduced Azure AI Foundry error. Body unchanged — omitting the params costs nothing and is the safe default either way.
- **Pipecat `ReasoningConfig` and `_maybe_disable_reasoning()`** (claims 44–45). Read from v1.9.0 source; context7's Pipecat docs corpus only documents a `Reasoning(effort=...)` for the Realtime service. Body unchanged, but confirm the exact class name against the installed package before committing code.
- **Model availability, pricing and deprecation dates for the fallback table** (claims 6, 23, 26, 35, 36). SDK and platform docs in context7 do not enumerate per-model pricing beyond Sol and Luna, nor the rate-limit tiers. These remain sourced from the live pricing and deprecations pages as of 2026-09-11.

### New information worth acting on (not in the original draft)

- **WebSocket `previous_response_not_found`**: after a connection cache reset the socket returns `400 / previous_response_not_found`. Recovery is to resend the turn with `previous_response_id: null` **plus the full input context**. Any `previous_response_id` strategy needs this fallback path — otherwise a reconnect drops the whole conversation.
- **`client.responses.compact(model=..., input=...)`**: an HTTP endpoint that compacts a long input window; the compacted output can be fed straight into a new WS `response.create`. Useful if a session ever outgrows its window.
- **Explicit prompt caching on GPT-5.6+**: `prompt_cache_options.mode: "explicit"` plus `prompt_cache_breakpoint` at reusable boundaries, bypassing implicit breakpoints. `prompt_cache_retention` is deprecated in favour of `prompt_cache_options.ttl`. Implicit caching only kicks in at ≥1,024 tokens; keep per-key traffic near ~15 req/min and partition above that.
- **`tool_search` and tool namespaces**: for toolsets past the ~20 soft ceiling, OpenAI now ships `{"type": "tool_search"}` with `{"type": "namespace", ...}` groupings and `defer_loading: true` per tool. Not needed at our seven tools, but it is the documented escape hatch.
