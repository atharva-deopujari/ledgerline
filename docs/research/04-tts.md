# 04 — Streaming TTS choice for Pipecat

Researched 2026-09-11 against live docs. Pipecat `1.9.0` (released 2026-09-11, Python >=3.11). Items not confirmed from a primary source are marked **UNVERIFIED**.

## Decision summary

- **Primary: Cartesia `sonic-3.6` via `CartesiaTTSService` (WebSocket).** Best measured TTFB of the hosted options (128–188 ms p50 in two independent benchmarks), word timestamps (so interrupted turns commit only spoken words to the LLM context), `calm` is one of Cartesia's six "primary" emotions **(corrected via context7: neutral, calm, angry, content, sad, scared)**, and the free tier (20K credits ≈ 27 min/month, no card) covers a hobby demo.
- **Runner-up: ElevenLabs `eleven_flash_v2_5` via `ElevenLabsTTSService`.** Also WebSocket + word timestamps in Pipecat, ~75 ms vendor TTFB (264–288 ms measured). Weaker on our exact use case: Flash v2.5 does *not* normalize numbers by default and `apply_text_normalization="on"` is enterprise-only for Flash, so "₹4,200" is risky. Free tier 10K credits (Flash = 0.5 credit/char → ~20K chars ≈ ~20 min), non-commercial, attribution.
- **Budget fallback: Deepgram Aura-2 (`DeepgramTTSService`, WebSocket).** $200 free credit, no card → ~6.6M chars (thousands of minutes). But Pipecat docs list no word timestamps for it, so interruption context is coarser. Keep TTS swappable behind an env var.
- **Do not use:** OpenAI `gpt-4o-mini-tts` (HTTP, no word timestamps, no free tier, slow/high-variance), PlayHT (API shut down 2025-12-31; Pipecat service deprecated since 0.0.88), Rime (huge free tier but 337 ms p50 with 381 ms IQR in Coval's benchmark).
- **Text normalization:** do it at two layers — (1) system prompt tells the LLM to write "4,200 rupees" / "fifteenth September", never "₹" or "Rs."; (2) a global Pipecat `text_transforms` regex rewrites any leaked "₹"/"Rs." before synthesis. Keep `TextAggregationMode.SENTENCE` (default) so the regex sees whole sentences.
- **Voice:** Cartesia-recommended agent voices — **Daniel** (`47c38ca4-5f35-497b-b1a3-415245fb35e1`, en-US male) or **Skylar** (`db6b0ed5-d5d3-463d-ae85-518a07d3c2b4`, en-US female) with `GenerationConfig(emotion="calm", speed=0.95)`.

## Comparison table

Latency: "vendor" = marketing claim (model-only, excludes network); "measured" = Coval continuous benchmark (May 2026, via Gradium) or Vapi Humanness Index (p50, includes network). Minutes assume ~750 chars/min of speech.

| Provider / model | TTFB vendor → measured | Pipecat class (WS?) | Word timestamps | Numbers / ₹ / dates | Price | Free tier (card?) | Free minutes/mo |
|---|---|---|---|---|---|---|---|
| **Cartesia sonic-3.6** | 82–90 ms → 128 ms (Vapi, 3.5), 188 ms (Coval, 3) | `CartesiaTTSService` (WS) | Yes | Locale-aware normalizer (`normalization: auto`); docs: pass `$19.99`, `1,234,567`, `04/20/2025` as written. ₹ not documented → **UNVERIFIED** | ~1 credit/char; 100K credits $5/mo; overage rate not published | 20K credits, **no card**, non-commercial, 2 concurrent | ~27 (Cartesia's own figure) |
| **ElevenLabs eleven_flash_v2_5** | 75 ms → 226 ms (Vapi, Flash v2), 288 ms (Coval) | `ElevenLabsTTSService` (WS) | Yes (alignment) | Flash: "numbers aren't normalized by default"; `$1,000,000` read as "one thousand thousand dollars". `on` = enterprise only | 0.5 credit/char; Starter $6/30K credits | 10K credits, no card (**UNVERIFIED** official), attribution, non-commercial | ~20 (Flash) / ~10 (v2) |
| ElevenLabs eleven_v3_conversational | 280 ms vendor | same class, `model=` | Yes | v3 normalizes better | 1 credit/char (UNVERIFIED) | as above | ~10 |
| **Deepgram Aura-2** | sub-200 / ~90 ms tuned → 313 ms (Coval) | `DeepgramTTSService` (WS) `voice=aura-2-*-en` | Not documented | Tested on `$5.7M`, `€14.30`, dates; 92% "good". English-centric; ₹ **UNVERIFIED** | $0.030 / 1K chars | $200 credit, **no card** | ~8,800 (one-time credit) |
| Deepgram Flux TTS | — | `DeepgramFluxTTSService` (WS, TOKEN default) | Not documented | — | free until 2026-09-12, then $0.045/1K | same $200 | — |
| OpenAI gpt-4o-mini-tts | variable; tts-1-hd 2,295 ms (Coval) | `OpenAITTSService` (HTTP stream) | No | Steerable via `instructions` | $0.60/1M input chars + $12/1M audio tokens ≈ $0.015/min | none (prepaid, card) | 0 |
| Rime mistv2 / mistv3 | 150–200 ms vendor → 337 ms p50, IQR 381 ms | `RimeTTSService` (WS) | Yes | Speed/pause tags; normalization **UNVERIFIED** | $0.03/1K (Mist), $0.05/1K (Coda) | 3,000 free min (page also says ~800 min), no card | 800–3,000 |
| Google Chirp 3 HD | "low" (no number) | `GoogleTTSService` (WS) | Not documented | Google normalizer; no SSML on WS class | $30/1M chars (**UNVERIFIED** third-party) | 1M chars/mo Chirp 3 (**UNVERIFIED**); billing account/card needed | ~1,300 |
| Azure Neural | not published | `AzureTTSService` (WS) | Yes | SSML `<say-as>` available | $16/1M; HD $22/1M (**UNVERIFIED** third-party) | F0 500K chars/mo; Azure account (card typical, **UNVERIFIED**) | ~660 |
| PlayHT | — | deprecated 0.0.88 | — | — | API shut down 2025-12-31 | — | — |
| Others in Pipecat 1.9 | Inworld, MiniMax, Hume, Speechify, Fish, Groq, LMNT, Neuphonic, Kokoro (local), Piper (local) | see supported-services | varies | not researched | — | — | — |

## Deep-dive: Cartesia (recommended)

### Install and construct

```bash
uv add "pipecat-ai[cartesia,daily,deepgram,openai,silero]"
```

```python
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.tts_service import TextAggregationMode
from pipecat.transcriptions.language import Language

tts = CartesiaTTSService(
    api_key=os.getenv("CARTESIA_API_KEY"),
    # sample_rate=None -> inherits pipeline rate; Cartesia accepts 8k/16k/22.05k/24k/44.1k/48k
    encoding="pcm_s16le",            # default
    container="raw",                 # default
    text_aggregation_mode=TextAggregationMode.SENTENCE,   # default
    settings=CartesiaTTSService.Settings(
        model="sonic-3.6",           # set EXPLICITLY: context7's Pipecat docs state Settings.model defaults
                                     # to "sonic-3.5" (corrected via context7). Use the dated snapshot
                                     # "sonic-3.6-2026-08-27" to pin.
        voice="47c38ca4-5f35-497b-b1a3-415245fb35e1",     # Daniel, en-US
        language=Language.EN,
        generation_config=GenerationConfig(speed=0.95, emotion="calm"),  # speed 0.6–1.5, volume 0.5–2.0
    ),
    text_transforms=[("*", normalize_currency)],           # see below
)
```

Full `__init__` (from `src/pipecat/services/cartesia/tts.py`, main): `api_key`, `voice_id` (deprecated 0.0.105), `cartesia_version` (deprecated 1.8.0 — do not set), `url="wss://api.cartesia.ai/tts/websocket"`, `model` (deprecated), `sample_rate`, `encoding="pcm_s16le"`, `container="raw"`, `max_buffer_delay_ms`, `params` (deprecated), `extra_headers`, `settings`, `text_aggregation_mode`, `aggregate_sentences` (deprecated). `Settings` fields: `model`, `voice`, `language`, `generation_config`, `pronunciation_dict_id`. Word timestamps are always on (Pipecat handles Cartesia's `timestamps` messages via `add_word_timestamps`). WebSocket idles out after 5 min and auto-reconnects. Helpers for transforms: `CartesiaTTSService.SPELL(text)`, `EMOTION_TAG(emotion)`, `PAUSE_TAG(seconds)`, `VOLUME_TAG(v)`, `SPEED_TAG(s)`, which emit Cartesia's `<spell>`, `<emotion value=""/>`, `<break time=""/>`, `<volume ratio=""/>`, `<speed ratio=""/>` tags (Sonic-3+).

Pipecat does **not** expose Cartesia's newer request fields `locale`, `accent`, `normalization` (added Aug 2026) — **confirmed via context7**: `CartesiaTTSService.Settings` is exactly `model`, `voice`, `language`, `generation_config`, `pronunciation_dict_id`. Cartesia's API itself does accept `normalization` as `auto` (default) / `off` / a locale code such as `en-IN` ("read dates and numbers the Indian English way") — so the capability exists API-side but is unreachable through Pipecat's Settings today. `language="en"` gives US conventions by default.

### Free tier and the Pro question

Confirmed on cartesia.ai/pricing: **Free $0 — 20K credits/month, "~27 minutes TTS", 2 concurrent TTS requests, no credit card, no commercial license, no cloning.** docs.cartesia.ai/pricing: TTS is "approximately 1 credit per character" (slight variance from preprocessing). 20,000 chars / ~750 chars-per-minute ≈ 27 min, matching Cartesia's number.

**Pro is $5/month** (or $48/year ≈ $4/mo, which is the "$4" figure you saw): 100K credits ≈ 133 min, 3 concurrent, commercial license, instant cloning, card required. Overages can be enabled so requests keep succeeding past the allotment.

Verdict: 27 min is thin for a 30-day planner. A 4-minute session × 5 dev iterations a day burns the month in one afternoon. Recommend: build on Free, wire `TTS_PROVIDER=cartesia|deepgram|elevenlabs` so Deepgram's $200 credit is a one-line fallback, and buy one month of Pro ($5) the week you record the demo — it also removes the "non-commercial" ambiguity for a public release.

### Text normalization for ₹ / Rs. / dates

Cartesia's guidance (prompting-tips, Sonic 3): "Pass numbers, currency, dates, and common acronyms in conventional written form" (`1,234,567`, `$19.99`, `04/20/2025`, `7:00 PM`) and "Do not strip punctuation or force casing. Heavy preprocessing may hurt output quality." The rupee sign is not in their examples and I found no test of `₹` reading in the `en` locale — treat it as **UNVERIFIED** and defensively normalize.

Pipecat's hook is `text_transforms` (preferred; `text_filters`/`MarkdownTextFilter` still work but docs say filters "will be deprecated"). Signature: `list[tuple[AggregationType | str, Callable[[str, str], Awaitable[str]]]]`; `"*"` applies to all aggregations; or call `tts.add_text_transformer(fn, "*")`. Transforms run after sentence aggregation and before `run_tts`; with word-timestamp services they also change the text committed to context (fine here — "4,200 rupees" in history is harmless).

```python
import re
_RUPEE = re.compile(r"(?:₹|Rs\.?|INR)\s?([\d,]+(?:\.\d+)?)\s*(lakh|crore)?", re.I)

async def normalize_currency(text: str, agg_type: str) -> str:
    def rep(m):
        amt, unit = m.group(1), m.group(2)
        return f"{amt} {unit} rupees" if unit else f"{amt} rupees"
    text = _RUPEE.sub(rep, text)
    return text.replace("₹", " rupees ")   # any stray symbol
```

Recommended approach: (1) **system prompt** — "Write money as digits followed by the word rupees, e.g. 4,200 rupees or 1.5 lakh rupees. Never use the ₹ symbol, Rs., or INR. Write dates as '15th September', never 15/09 or 2026-09-15. Write percentages as '12 percent'." (ElevenLabs' own normalization guide recommends exactly this LLM-side strategy.) (2) The transform above as a safety net. (3) Leave Cartesia's normalizer on (`auto`) for plain numbers; do not spell digits out yourself — Cartesia reads `1,234,567` natively and heavy preprocessing hurts quality. (4) Use `SPELL()` only for things like UPI IDs or account numbers.

### Sentence aggregation

`TTSService` (base) aggregates LLM tokens before each TTS request. `TextAggregationMode.SENTENCE` (default) uses `SimpleTextAggregator`, which buffers character-by-character and calls `pipecat.utils.string.match_endofsentence` (NLTK punkt with punctuation checks and number/email handling, so `4,200` or `1.5` do not split). Docstring: adds "~200–300 ms per sentence" but produces natural prosody. `TextAggregationMode.TOKEN` streams tokens straight to Cartesia (Cartesia's `continue=true` contexts handle it) for lower latency at some quality risk — and it would break the sentence-level regex above, since "₹" and "4,200" may arrive in different chunks.

Tunables: `text_aggregation_mode`; Cartesia-only `max_buffer_delay_ms` (Pipecat forces 0 in SENTENCE mode, leaves Cartesia's default 3000 in TOKEN mode); custom aggregators via `LLMTextProcessor(text_aggregator=PatternPairAggregator())` placed `llm -> llm_text_processor -> tts`, with `skip_aggregator_types=[...]` to silence e.g. JSON plan blocks; `push_text_frames`, `append_trailing_space`. Recommendation: keep SENTENCE, and bundle NLTK data (`NLTK_DATA` env) so the first turn does not download punkt.

### Voice

Cartesia's Sonic 3.6 docs list five "stable, pleasant, yet also realistic" agent voices: Skylar `db6b0ed5-d5d3-463d-ae85-518a07d3c2b4` (en-US F), Daniel `47c38ca4-5f35-497b-b1a3-415245fb35e1` (en-US M), Jacqueline `9626c31c-bec5-4cca-baa8-f8ba9e84c8bc` (en-US F), Gemma `62ae83ad-4f6a-430b-af41-a9bede9286ca` (en-GB F), Archie `ef191366-f52f-447a-a398-ed8c0f2943a1` (en-GB M). For a calm money coach speaking to an Indian user, Daniel or Gemma with `emotion="calm"` (one of the six primary emotions: `neutral, calm, angry, content, sad, scared`; Cartesia also documents a ~57-value full emotion list, English-only). Cartesia's India page claims Indian-English voices and Hinglish support in 3.6; specific Indian-English voice IDs must be copied from play.cartesia.ai — **UNVERIFIED**.

## Deep-dive: ElevenLabs (runner-up)

```python
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
tts = ElevenLabsTTSService(
    api_key=os.getenv("ELEVENLABS_API_KEY"),
    settings=ElevenLabsTTSService.Settings(
        model="eleven_flash_v2_5",      # default; ~75 ms vendor TTFB, 32 languages, 0.5 credit/char
        voice="21m00Tcm4TlvDq8ikWAM",   # Rachel (docs example)
        stability=0.6, similarity_boost=0.75, speed=0.95,   # speed 0.7–1.2 on WS
        apply_text_normalization="auto",
    ),
)
```

`__init__`: `api_key`, `url="wss://api.elevenlabs.io"`, `sample_rate`, `auto_mode` (None → on in SENTENCE mode, off in TOKEN), `enable_ssml_parsing`, `enable_logging`, `pronunciation_dictionary_locators` (deprecated 1.6.0 → use `text_transforms`), `settings`, `text_aggregation_mode`. Word timestamps come from ElevenLabs alignment data. Why not primary: Flash skips number normalization "to maintain low latency" and `on` is enterprise-only; measured TTFB was 264–302 ms in two benchmarks; free tier is 10K credits with attribution and no commercial rights.

## Gotchas

- Cartesia sunsets `sonic-2`, `sonic-turbo` and older `sonic-3` snapshots after **2026-10-20** — stay on `sonic-3.6`.
- Do not pass `cartesia_version`; Pipecat 1.8+ pins the API version and overriding "can break request and response handling".
- Free-tier concurrency is **2** TTS requests — one bot is fine, two simultaneous demo rooms are not.
- `voice_id=`/`model=` constructor kwargs are deprecated since 0.0.105; use `Settings`. Older tutorials will show the old form.
- Services without word timestamps (Deepgram, OpenAI, Google) fall back to pushing the full sentence's `TTSTextFrame` after synthesis; on interruption the context may contain words the user never heard.
- Emotion tags "only work when the emotion is consistent with the transcript" — `calm` on a reassuring budget summary is fine; do not flip emotion mid-generation.
- `<speed>`/`<volume>` inline tags need whole-value buffering — another reason to stay in SENTENCE mode.
- Cartesia's `en` normalizer uses US date conventions (`MM/DD/YYYY`); have the LLM write dates in words. Indian-format `en-IN` normalization **does exist** in Cartesia's API (`normalization: "en-IN"`) but is **not exposed through Pipecat's `Settings`** — both halves now VERIFIED via context7 (previously marked UNVERIFIED).
- Third-party blogs mention "Sonic 4"; Cartesia's own docs and changelog list `sonic-3.6` (2026-08-27) as latest. Ignore the blog.
- Deepgram Flux TTS stops being free on 2026-09-12 (tomorrow); Aura-2 pricing is unaffected.

## Sources

- Pipecat Cartesia service docs — https://docs.pipecat.ai/server/services/tts/cartesia
- Pipecat Cartesia source (main) — https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/cartesia/tts.py
- Pipecat TTSService base (text_transforms, aggregation) — https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/tts_service.py
- Pipecat learn: text-to-speech (transforms, filters deprecation, timestamps) — https://github.com/pipecat-ai/docs/blob/main/pipecat/learn/text-to-speech.mdx
- Pipecat interruptions (what ends up in context) — https://docs.pipecat.ai/pipecat/fundamentals/interruptions
- Pipecat ElevenLabs docs / source — https://docs.pipecat.ai/server/services/tts/elevenlabs , https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/elevenlabs/tts.py
- Pipecat Deepgram / OpenAI / Rime / Google / Azure TTS docs — https://docs.pipecat.ai/server/services/tts/{deepgram,openai,rime,google,azure}
- Pipecat supported services — https://docs.pipecat.ai/server/services/supported-services
- Pipecat PlayHT deprecation — https://reference-server.pipecat.ai/en/latest/api/pipecat.services.playht.tts.html
- pipecat-ai on PyPI (1.9.0) — https://pypi.org/project/pipecat-ai/
- Cartesia pricing — https://cartesia.ai/pricing ; credits — https://docs.cartesia.ai/pricing
- Cartesia Sonic 3.6 model page (voice IDs) — https://docs.cartesia.ai/build-with-cartesia/tts-models/latest
- Cartesia WebSocket TTS API (normalization, generation_config) — https://docs.cartesia.ai/api-reference/tts/tts
- Cartesia prompting tips — https://docs.cartesia.ai/build-with-cartesia/sonic-3/prompting-tips
- Cartesia SSML tags — https://docs.cartesia.ai/build-with-cartesia/sonic-3/ssml-tags
- Cartesia volume/speed/emotion — https://docs.cartesia.ai/build-with-cartesia/sonic-3/volume-speed-emotion
- Cartesia 2026 changelog — https://docs.cartesia.ai/changelog/2026
- Cartesia India page — https://www.cartesia.ai/india
- ElevenLabs models (latency, Flash normalization note) — https://elevenlabs.io/docs/overview/models
- ElevenLabs normalization guide — https://elevenlabs.io/docs/best-practices/prompting/normalization
- ElevenLabs pricing — https://elevenlabs.io/pricing
- Deepgram pricing — https://deepgram.com/pricing ; Aura-2 launch — https://deepgram.com/learn/introducing-aura-2-enterprise-text-to-speech ; prompting — https://developers.deepgram.com/docs/text-to-speech-prompting
- OpenAI API pricing — https://developers.openai.com/api/docs/pricing
- Rime pricing — https://www.rime.ai/pricing
- Azure Speech pricing — https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/
- Google TTS pricing (page truncated; figures from third parties) — https://cloud.google.com/text-to-speech/pricing , https://texttolab.com/blog/google-cloud-tts-pricing
- Measured latency: Vapi Humanness Index — https://humannessindex.vapi.ai/models/cartesia-sonic-3-5 ; Coval data via Gradium (vendor-authored) — https://gradium.ai/content/tts-latency-benchmark-2026 ; invideo analysis — https://invideo.io/blog/cartesia-sonic-ai-voice/ ; Dograh TTFB roundup — https://www.dograh.com/feeds/blog/tts-time-first-byte

## Context7 cross-check (2026-09-11)

Every concrete claim below was re-queried against context7 MCP documentation, which is treated as authoritative and current. Nothing in the body above was deleted; corrections are marked inline as **(corrected via context7)**.

### Libraries consulted

| Library | Context7 ID | Version / notes |
|---|---|---|
| Pipecat docs | `/pipecat-ai/docs` | no pinned version; 6,869 snippets, High reputation, benchmark 78.01 |
| Pipecat source/API | `/pipecat-ai/pipecat` | no pinned version; 3,072 snippets, benchmark 70.71 |
| Cartesia docs | `/websites/cartesia_ai` | no pinned version; 4,125 snippets, benchmark 82.37 (API version header default `2026-08-14`) |
| Cartesia Python SDK | `/cartesia-ai/cartesia-python` | no pinned version; 758 snippets (not queried; docs site was sufficient) |
| ElevenLabs docs | `/websites/elevenlabs_io` | no pinned version; 5,777 snippets, benchmark 79.56 |
| Deepgram API docs | `/websites/developers_deepgram` | no pinned version; 5,909 snippets, benchmark 82.53 |

### Claims table

| # | Claim in report | Verdict | Evidence |
|---|---|---|---|
| 1 | `CartesiaTTSService.Settings.model` default is `sonic-3.6` in Pipecat 1.9.0 | CONTRADICTED → noted inline | Pipecat API reference: "**model** (str) - Optional - TTS model identifier. **Defaults to 'sonic-3.5'**." Both the `learn/text-to-speech.mdx` and `api-reference` examples use `sonic-3.5` / `sonic-3`. Resolution: report body kept, code comment changed to *set `model` explicitly* rather than rely on a default. |
| 2 | `Settings` fields are exactly `model`, `voice`, `language`, `generation_config`, `pronunciation_dict_id` | VERIFIED | Pipecat `CartesiaTTSService.Settings` lists precisely those five. |
| 3 | `GenerationConfig(speed=…, volume=…)` ranges are 0.6–1.5 and 0.5–2.0 | VERIFIED (twice) | Pipecat: "volume ... Valid range: [0.5, 2.0]", "speed ... Valid range: [0.6, 1.5]". Cartesia AsyncAPI: same, both default 1.0. |
| 4 | `emotion="calm"` is a valid primary emotion | VERIFIED | Cartesia: "**Primary**: neutral, calm, angry, content, sad, scared". |
| 5 | Cartesia has **five** primary emotions | CONTRADICTED → corrected inline | The primary list has **six** members (neutral, calm, angry, content, sad, scared). The full list runs to ~57 values; Pipecat's own doc says "a wide range of over 60 emotion strings". Report now reads "six". |
| 6 | Emotion tags are English-only / "only work when consistent with the transcript" | VERIFIED (first half) | "Emotion tags are supported only for English." The consistency guidance itself was NOT COVERED. |
| 7 | Constructor signature (`voice_id`, `cartesia_version`, `url`, `model`, `sample_rate`, `encoding`, `container`, `max_buffer_delay_ms`, `params`, `extra_headers`, `settings`, `text_aggregation_mode`, `aggregate_sentences`) | VERIFIED verbatim | Pipecat API md reproduces exactly that signature, with `url='wss://api.cartesia.ai/tts/websocket'`, `encoding='pcm_s16le'`, `container='raw'`, and the note "several parameters are deprecated in favor of the `settings` object". |
| 8 | Cartesia word timestamps are always on in Pipecat | VERIFIED | "Word timestamps automatically enabled for precise context updates." |
| 9 | Word timestamps available on Cartesia / ElevenLabs / Rime / Azure; not on Deepgram TTS | VERIFIED | "Services such as Cartesia, ElevenLabs, and Rime offer word-level timestamps"; Azure "provides lower latency and word-level timestamps"; `DeepgramTTSService.Settings` exposes only `model`, `voice`, `language` — no timestamp support documented. (Also: `RimeNonJsonTTSService` is deprecated and does **not** support word timestamps — worth knowing if you fall back to Rime.) |
| 10 | Voice IDs: Skylar `db6b0ed5-…`, Daniel `47c38ca4-…`, Jacqueline `9626c31c-…`, Gemma `62ae83ad-…`, Archie `ef191366-…` | VERIFIED, all five exact | Cartesia `tts-models/latest` reproduces the identical list with identical UUIDs and locales. "Choosing a Voice" independently names Daniel/Archie/Parker/Jameson/Corey and Skylar/Gemma/Jacqueline/Emma/Lauren as top agent voices. |
| 11 | `sonic-2`, `sonic-turbo` and older `sonic-3` snapshots sunset after 2026-10-20 | VERIFIED, exact date | Cartesia changelog (July 2026): "Sonic-2, Sonic-turbo, and Sonic-3-2025-10-27 will be sunsetted after October 20, 2026." A sunset table confirms the same three rows. Requests to a retired model return `error_code: "model_sunsetted"`. |
| 12 | `sonic-3.6-2026-08-27` is a real dated snapshot | VERIFIED | Referenced by Cartesia's own `voice_model_mismatch` error message: "Switch to one of these compatible models: sonic-3.5-2026-05-04, **sonic-3.6-2026-08-27**." |
| 13 | Cartesia "TTS is approximately 1 credit per character" | VERIFIED | docs.cartesia.ai/pricing: "Standard TTS costs approximately 1 credit per character. The exact number of credits can vary slightly due to transcript pre-processing." Also: "Credits are only used by successful requests; errors will not consume credits" (a detail the report omits, and a small argument in its favour for dev iteration). |
| 14 | Free tier = 20K credits/month, ~27 min, no card, non-commercial | PARTIALLY VERIFIED | Concurrency confirmed exactly — "Plan Free \| TTS Concurrent Requests **2** \| STT **8**". The credit allotment itself is NOT COVERED: docs.cartesia.ai/pricing defers with "See cartesia.ai/pricing for current plans and included credits." The 20K/27 min/$5 Pro figures stand on the report's own reading of the pricing page. |
| 15 | Cartesia normalization is locale-aware with `auto` default | VERIFIED and **expanded** | "`auto` (default) — Cartesia decides how dates, times, and numbers are read; `off` — skip the normalizer; **a locale code such as `en-IN`** — read dates and numbers the Indian English way." A documented request example pairs `model_id: "sonic-3.6"` with `locale: "hi-IN"` and `normalization: "en-IN"` on Hinglish text — direct support for the report's India use case, if it can reach the field. |
| 16 | Pipecat does not expose `locale` / `accent` / `normalization` | VERIFIED → upgraded from UNVERIFIED inline | Pipecat `Settings` has only the five fields in claim 2. |
| 17 | ₹ handling by Cartesia is undocumented | VERIFIED (still undocumented) | No rupee-symbol guidance anywhere in the indexed Cartesia corpus. Defensive normalization stays justified. |
| 18 | `<spell>`, `<speed ratio>`, `<volume ratio>` SSML tags, Sonic-3+ | VERIFIED | "Use the speed tag with a ratio between 0.6 and 1.5 ... available on sonic-3 and later"; `<spell>` examples match the report ("a space inside the tag forces a longer pause between characters"). |
| 19 | `text_transforms` is the preferred hook; `text_filters` "will be deprecated" | VERIFIED | Pipecat `learn/text-to-speech.mdx`: "Note that text filters are being deprecated in favor of other methods", alongside the `add_text_transformer(fn, "*")` API and a `replace_text([...])` helper used as `CartesiaTTSService(text_transforms=[("*", transform)])`. |
| 20 | `TextAggregationMode.SENTENCE` is the default | VERIFIED with a caveat | ElevenLabs notes: "Sentence aggregation is the default mode for text processing." **But** the Bland TTS doc describes passing `SENTENCE` as "overriding the default token streaming behavior" — so the default is per-service, not global. Passing it explicitly (as the report's snippet does) is the right call. |
| 21 | `LLMTextProcessor(text_aggregator=PatternPairAggregator())` placed `llm -> llm_text_processor -> tts` | VERIFIED verbatim | context7 reproduces the same pattern with the same pipeline-ordering comment. |
| 22 | `~200–300 ms per sentence` added by sentence aggregation; NLTK punkt / `match_endofsentence` internals | NOT COVERED | Not in context7's indexed Pipecat corpus; left as sourced from the docstring. |
| 23 | ElevenLabs `Settings` = model, voice, language, stability, similarity_boost, style, use_speaker_boost, speed, apply_text_normalization | VERIFIED, including ranges | "speed ... **WebSocket: 0.7–1.2.** HTTP: 0.25–4.0", "apply_text_normalization (Literal) - ... \"auto\", \"on\", or \"off\"". Report's `speed=0.95` and "speed 0.7–1.2 on WS" are exact. The report's snippet omits `style` and `use_speaker_boost`, which do exist. |
| 24 | `pronunciation_dictionary_locators` deprecated in 1.6.0 → use `text_transforms` | VERIFIED, with the reason | "deprecated as of version 1.6.0 and ... scheduled for removal in version 2.0.0 ... use the `text_transforms` parameter with `replace_text` instead, as **dictionary substitutions can interfere with alignment-based word-completion tracking**." |
| 25 | `auto_mode` reduces latency, on in SENTENCE mode | VERIFIED (behaviour) | "The `auto_mode` feature can reduce latency by disabling server-side chunk scheduling, which is recommended when sending complete sentences." The `None → on in SENTENCE, off in TOKEN` default logic itself is NOT COVERED. |
| 26 | Flash v2.5 does not normalize numbers by default; `apply_text_normalization="on"` is **enterprise-only** for v2.5 | VERIFIED, near-verbatim | "To maintain ultra-low latency, Flash v2.5 disables text normalization for numbers, dates, and currencies by default. **Enterprise customers can enable normalization for v2.5** by setting the `apply_text_normalization` parameter to 'on'. Alternatively, Multilingual v2 handles number normalization natively, or developers can **pre-normalize text using an LLM** prior to TTS generation." The last clause independently endorses the report's system-prompt strategy. |
| 27 | `eleven_flash_v2_5`: ~75 ms, 32 languages, 0.5 credit/char | VERIFIED | "Eleven Flash v2.5 (ultra-low latency of ~75ms, 32 languages, 40,000 character limit, and **50% lower price per character**)". The 40K character-per-request limit is a detail the report omits. |
| 28 | `eleven_v3_conversational` ~280 ms | VERIFIED | "Eleven v3 Conversational (expressive realtime synthesis with ~280ms latency and audio tags)". |
| 29 | Rachel voice `21m00Tcm4TlvDq8ikWAM` | VERIFIED | Same voice ID in Pipecat's ElevenLabs example. |
| 30 | ElevenLabs free tier = 10K credits, attribution, non-commercial | NOT COVERED | The `/v1/user/subscription` example response shows a `starter` tier with `character_limit: 10000`, but that is a sample payload, not the free-plan policy. Pricing-page claims stand on the report's own sourcing. |
| 31 | Deepgram Aura-2 via `DeepgramTTSService`, voices `aura-2-*-en` | VERIFIED | Deepgram examples use `aura-2-thalia-en`, `aura-2-andromeda-en`. Two useful uncovered-in-report limits: **2,000 characters per request** and a **2,400 characters/minute throughput cap** for Aura models. |
| 32 | Aura-2 at $0.030/1K chars; Flux TTS free until 2026-09-12 then $0.045/1K; $200 credit | NOT COVERED | context7 indexes developers.deepgram.com, not deepgram.com/pricing. Left as-is. |
| 33 | PlayHT API shut down 2025-12-31; Pipecat service deprecated since 0.0.88 | NOT COVERED | No PlayHT material surfaced. Related deprecations context7 *does* confirm, which supports the report's general picture: `XTTSService` deprecated in 1.7.0 (removal in 2.0.0), `RimeNonJsonTTSService` deprecated, Sarvam/Google `InputParams` deprecated as of 0.0.105. |
| 34 | All measured-latency numbers (Coval, Vapi Humanness Index, Gradium, Dograh), free-tier minutes, and per-character pricing for OpenAI / Rime / Google / Azure | NOT COVERED | Benchmark and pricing data are outside context7's indexed corpus. Unchanged. |

### Corrections applied

1. **Primary-emotion count.** Decision summary: "five 'primary' emotions" → "six" **(corrected via context7)**, with the list spelled out. The Voice section now reads "one of the six primary emotions" and notes the ~57-value full list is English-only.
2. **Cartesia model default.** The construction snippet no longer implies `sonic-3.6` is the Pipecat default; the comment now instructs setting `model` explicitly, since context7's Pipecat docs give `sonic-3.5` as `Settings.model`'s default **(corrected via context7)**. The recommendation to run `sonic-3.6` is unchanged and remains correct — it is simply not the fallback.
3. **`normalization` / `en-IN` upgraded from UNVERIFIED.** Both halves are now confirmed: Pipecat's `Settings` genuinely does not expose `locale`/`accent`/`normalization`, and Cartesia's API genuinely does accept `normalization: "en-IN"` for Indian-English date/number reading. The relevant paragraph and the matching gotcha were rewritten to say so.

### Disagreements left standing (report's sourcing is more current)

- **`sonic-3.6` as Pipecat's default model (claim 1).** context7's Pipecat snapshot says `sonic-3.5`; the report read the 1.9.0 source on 2026-09-11 and says `sonic-3.6`. Rather than pick a winner, the code now sets `model` explicitly, which is correct under either. The `sonic-3.6-2026-08-27` snapshot is independently confirmed to exist in Cartesia's own docs, so the model itself is real and current.
- **Cartesia free-tier size, ElevenLabs free tier, and all per-character / per-minute pricing** live on vendor pricing pages that context7 does not index. Unchanged.
- **All measured latency benchmarks and the PlayHT shutdown** are NOT COVERED by context7 and stand on the report's own citations.
