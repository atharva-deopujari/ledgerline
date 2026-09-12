# 03 - Streaming STT choice for the Pipecat finance-planner bot

Researched 2026-09-11 against live docs. Pipecat is at **v1.9.0 (released 2026-09-11, Python >= 3.11)**. Some Pipecat docs still reference deprecation markers like "v0.0.105" from the pre-1.0 numbering; the current API is the `settings=` style described below.

## Decision summary

- **Use Deepgram Nova-3 via `DeepgramSTTService`** with `smart_format=True`, `numerals=True`, `language="en-IN"` (or `"en"`), `interim_results=True`, and `keyterm=[...]` for finance vocabulary (EMI, rupees, lakh, crore, SIP, minimum due).
- Why Deepgram over the accuracy leaders (Speechmatics 1.07% WER, AssemblyAI U3.5-Pro 1.22%): Nova-3 is the **fastest** in Pipecat's own benchmark (247 ms median TTFS, 1.71% WER), has the most mature Pipecat integration, explicit `en-IN` support, the best free tier (**$200 credit, no card, never expires**), and `numerals`/`smart_format` are built in. For a 30-day plan bot, latency + cheap iteration beats a 0.5-point WER gap.
- **Do not use Deepgram Flux for this bot.** Flux has model-integrated turn detection (great) but **no `smart_format`** (only `numerals`), and its "hold on... forty-two hundred" behaviour is unproven for number-heavy pauses. Keep it as a documented fallback to try if turn-taking feels bad.
- **Turn end = Pipecat's turn-strategy layer, not Deepgram endpointing.** Leave `endpointing`/`utterance_end_ms` unset; the Pipecat service does not even consume `UtteranceEnd`/`SpeechStarted` events. Use Silero VAD + `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=1.0-1.2)` for people who pause while recalling numbers; or keep the default Smart Turn v3 analyzer if you accept its known short-utterance bugs.
- **Number words are converted by Deepgram, not by you.** Expect "forty two hundred" -> "4200", "fifteen thousand rupees" -> "15,000 rupees" (VERIFIED for the pattern, UNVERIFIED for rupee-symbol handling), "five lakh" -> most likely "5 lakh" (UNVERIFIED). There is an **open bug** with "a hundred" + percent. Therefore the LLM must read every amount and date back to the user before committing it.
- **Cost for ~200 minutes of dev testing: about $1.00-$1.80**, entirely inside the free $200 credit.

## Comparison table (streaming STT usable from Pipecat, September 2026)

| Provider / model | Pipecat class (import) | Median TTFS / WER (Pipecat bench) | Interim results | Endpointing / turn config | Number formatting | Keyword boosting | Streaming price /min | Free tier, card? |
|---|---|---|---|---|---|---|---|---|
| **Deepgram Nova-3** (`nova-3-general`) | `DeepgramSTTService` (`pipecat.services.deepgram.stt`) | **247 ms** / 1.71% | Yes (`interim_results=True` default) | `endpointing` ms, `utterance_end_ms`; Pipecat sends `Finalize` on VAD stop | `smart_format`, `numerals` (`en`, `en-IN` supported; not Hindi) | `keyterm` (Nova-3: <=500 tokens; Flux: up to 100 terms **(corrected via context7)**, +$0.0013/min), legacy `keywords` | $0.0077 regular; **$0.0048 promo** (mono). Multi $0.0092/$0.0058 | **$200, no card, never expires** |
| Deepgram Flux (`flux-general-en`) | `DeepgramFluxSTTService` (`pipecat.services.deepgram.flux.stt`) | Not in published bench | Yes (`Update`, `EagerEndOfTurn` as interim) | Model-native: `eot_threshold` 0.7, `eager_eot_threshold`, `eot_timeout_ms` 5000; auto-sets `ExternalUserTurnStrategies` | `numerals` only (set at connect time); **no `smart_format`** | `keyterm` | $0.0077 regular; $0.0065 promo | Same $200 |
| AssemblyAI Universal-Streaming / U3.5-Pro | `AssemblyAISTTService` (`pipecat.services.assemblyai.stt`) | 282 ms / **1.22%** (U3.5-Pro) | Yes, continuous partials (~3 s cadence) | `vad_force_turn_endpoint=True` (Pipecat VAD) or model-native (`min_turn_silence` 400 ms, `max_turn_silence` 1280 ms) | `format_turns` (ITN for dates/times/numbers) | `keyterms_prompt` | $0.0025 (Universal-Streaming); $0.0075 (U3.5-Pro); **billed on socket time, not audio** | $50, no card; 5 new streams/min |
| Speechmatics (Enhanced) | `SpeechmaticsSTTService` (`pipecat.services.speechmatics.stt`) | 495 ms / **1.07%** (best WER) | Partials + finals | `turn_detection_mode` EXTERNAL / ADAPTIVE / SMART_TURN; `end_of_utterance_silence_trigger`, `max_delay` | Built-in formatting (UNVERIFIED depth) | `additional_vocab` | **UNVERIFIED**: third-party quotes $1.04/hr std, $1.35/hr enhanced (~$0.017-0.023/min); pricing page unclear | $100, no card; 2 concurrent RT sessions |
| Gladia Solaria-1 | `GladiaSTTService` (`pipecat.services.gladia.stt`) | Not in published bench; vendor claims <300 ms | Yes | `endpointing` (s), `maximum_duration_without_endpointing` 5 s, `enable_vad` | UNVERIFIED | `custom_vocabulary` | $0.0125 (Starter $0.75/hr); Growth ~$0.0042 | EUR 50 credit; **card via Stripe** (UNVERIFIED whether required before use) |
| OpenAI realtime (`gpt-realtime-whisper`, `gpt-live-transcribe`, `gpt-transcribe`) | `OpenAIRealtimeSTTService` (`pipecat.services.openai.stt`); `OpenAISTTService` is segmented HTTP, no interims | 637 ms / 3.06% (gpt-4o-transcribe) | Yes, via delta events | Server VAD (`turn_detection` dict) or local VAD | LLM-style, no explicit numeral toggle; `prompt` only on some models | `prompt` | **$0.017** live models; $0.0045-0.006 for segmented `gpt-transcribe`/`gpt-4o-transcribe` | Pay-as-you-go, card needed |
| Google Cloud STT v2 (`latest_long`, Chirp 3) / Gemini live | `GoogleSTTService` (`pipecat.services.google.stt`); `GeminiSTTService` (`gemini-3.5-transcribe-live`) | Gemini live: 458 ms / 2.24% | Yes (`enable_interim_results`) | External VAD; 5-min stream limit, auto-reconnect at 4 min | Auto punctuation; ITN UNVERIFIED | `adaptation_phrases` (Gemini) | ~$0.016 std streaming (volume discounts) | $300 trial (card) + 60 free min/month |
| Others Pipecat supports | AWS Transcribe, Azure, Cartesia, ElevenLabs, Soniox, Sarvam, Gnani, Groq/Whisper, NVIDIA, Mistral, Fal, xAI, etc. | -- | -- | -- | -- | -- | -- | Not evaluated; Sarvam/Gnani are Indian-language specialists worth a glance if Hindi code-switching becomes a requirement |

Latency/WER numbers are from the open `pipecat-ai/stt-benchmark` (22 services, 1,000 samples, "Time To Final Segment" measured from end of speech; semantic WER ignores punctuation/formatting). Indian-English-specific accuracy is **UNVERIFIED for every vendor** -- none publish an en-IN WER; Deepgram markets "global English" and offers an `en-IN` code, AssemblyAI markets "Global English and all its accents".

## Deep dive: Deepgram Nova-3 in Pipecat 1.9

### Install and construct

```bash
pip install "pipecat-ai[deepgram,daily,silero,openai,cartesia]"
```

```python
from pipecat.services.deepgram.stt import DeepgramSTTService

stt = DeepgramSTTService(
    api_key=os.getenv("DEEPGRAM_API_KEY"),
    # constructor-only: base_url="", encoding="linear16", channels=1,
    # multichannel=False, sample_rate=None (pipeline rate), tag=None,
    # mip_opt_out=None, addons=None, ttfs_p99_latency=DEEPGRAM_TTFS_P99
    settings=DeepgramSTTService.Settings(
        model="nova-3-general",      # default
        language="en-IN",            # default Language.EN. NOTE (context7): en-IN is enumerated for Nova-2/Nova
                                     # in models-languages-overview; the Nova-3 English variant list is NOT
                                     # covered there. Confirm en-IN on Nova-3 before relying on it.
        smart_format=True,           # default False -- turn ON (implies punctuate)
        numerals=True,               # default False -- turn ON
        punctuate=True,              # default True
        interim_results=True,        # default True; required for utterance_end_ms
        keyterm=["EMI", "rupees", "lakh", "crore", "SIP", "minimum due",
                 "credit card", "salary", "rent", "UPI"],
        # endpointing=None, utterance_end_ms=None  -> leave unset (see below)
        # keywords=None (legacy boosting; use keyterm on Nova-3)
        # profanity_filter, diarize, detect_entities, redact, replace, search, version
    ),
)
```

Notes:
- `live_options=LiveOptions(...)` still exists but is **deprecated** (docs say "since 0.0.105, removed in 2.0.0"); use `Settings`. Settings can be updated at runtime via `STTUpdateSettingsFrame(delta=DeepgramSTTService.Settings(...))`.
- `keyterm` is a Nova-3/Flux feature: plain terms, no `word:weight` syntax, repeated as query params, max 500 tokens per request, recommended 20-50 terms. Billed as an add-on at $0.0013/min streaming.
- `smart_format` formats dates, times, currency, phone numbers and turns on punctuation automatically. Deepgram notes streaming smart-format **may hold an incomplete entity for up to 3 s of silence**; Pipecat mitigates this by sending a `Finalize` message when the pipeline VAD fires `VADUserStoppedSpeakingFrame`, and marks the resulting transcript `finalized` (`from_finalize`), which the turn strategies use to short-circuit their STT wait.
- `vad_events`: not exposed in `Settings`, and the Pipecat service **does not handle `SpeechStarted` or `UtteranceEnd` messages at all** -- it only consumes `Results` (final/interim). So Deepgram's `endpointing` and `utterance_end_ms` have no effect on Pipecat turn-taking with Nova-3; they only change when `speech_final` flips in the raw response.

### How Pipecat decides the user's turn ended (v1.9)

Turn boundaries are owned by `LLMContextAggregatorPair(... user_params=LLMUserAggregatorParams(...))`, not by the STT service.

- **Start strategies (default):** `[VADUserTurnStartStrategy(), TranscriptionUserTurnStartStrategy()]` -- Silero VAD onset, with an STT-transcript fallback.
- **Stop strategies (default):** `[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]` -- Smart Turn v3 runs on the audio after VAD silence and decides if the utterance is semantically complete.
- **Alternative:** `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)` -- pure silence timer after VAD stop. Both strategies have `wait_for_transcript=True`, meaning after firing they wait for a `finalized` `TranscriptionFrame` or fall back to the service's `ttfs_p99_latency` deadline.
- **Safety net:** `user_turn_stop_timeout=5.0` s in `LLMUserAggregatorParams`; if nothing else stops the turn, this does.
- **Silero VADParams defaults:** `confidence=0.7`, `start_secs=0.2`, `stop_secs=0.2`, `min_volume=0.6`. Docs explicitly say do **not** tune `stop_secs` to change wait time; tune the stop strategy.

So for Nova-3 the answer to "STT endpointing vs VAD vs both" is: **VAD (Silero) + Pipecat stop strategy; Deepgram endpointing is irrelevant.** Only Flux, AssemblyAI (with `vad_force_turn_endpoint=False`) and Speechmatics ADAPTIVE mode move turn detection into the STT vendor (via `ExternalUserTurnStrategies`).

Recommended for users who pause mid-sentence while recalling numbers ("my EMI is... uh... forty-two hundred, on the... fifth"):

```python
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.turns.user_start import VADUserTurnStartStrategy, TranscriptionUserTurnStartStrategy
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy

user_params = LLMUserAggregatorParams(
    vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
    user_turn_strategies=UserTurnStrategies(
        start=[VADUserTurnStartStrategy(), TranscriptionUserTurnStartStrategy()],
        stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=1.1)],
    ),
    user_turn_stop_timeout=4.0,
)
```

Rationale: Smart Turn v3 is the smarter default, but two open issues (#3643 short "Yes"/"Sure" hanging 5 s on phone-quality audio; #3988 deadlock when STT delays finalizing short utterances) make a deterministic ~1.1 s silence timer the safer choice for a demo where the user says short confirmations ("yes", "correct", "3,200"). Try Smart Turn v3 as a stretch option and A/B it. Whichever you use, the system prompt should tell the LLM that a turn may arrive mid-thought and to ask "did you finish?" rather than assume.

### How number words come out

Verified from Deepgram docs:
- `numerals=True`: "nine hundred" -> "900"; "june twenty eighth" -> "june 28th"; digit strings stay space-separated ("5 5 5 2 1 2..."). With punctuation on, converted numbers **drop thousands separators** in the `numerals`-only path ("999,999" -> "999999").
- `smart_format=True`: "eight thirty seven pm on wednesday" -> "8:37 PM on Wednesday"; formats currency, dates, times, phone numbers. This is the one you want for "on the fifth" and "3,200".

Expected but **UNVERIFIED by direct test** (do a 5-minute test call on day one and paste results here):
- "forty two hundred" -> "4200" or "4,200" (likely; Deepgram's ITN handles compound hundreds).
- "fifteen thousand rupees" -> "15,000 rupees" (likely; whether it emits "Rs." or the rupee symbol is unknown -- smart_format currency examples are USD-centric).
- "five lakh" -> "5 lakh" (likely; there is no evidence Deepgram expands lakh/crore to 500,000 / 10,000,000, so the LLM must know 1 lakh = 100,000 and 1 crore = 10,000,000).
- "credit card minimum due is three thousand two hundred" -> "3,200".

Known issue (open since 2025-03-29, GitHub discussion #1168): with `smart_format=true`, "a hundred and ten percent" -> "a 10%". Deepgram confirmed it as an edge case with "a hundred" followed by a percentage; the workaround is unformatted output. Percentages are rare in this bot but "a hundred" is not, so watch for it.

Implication for the LLM layer: **every amount and date must be echoed back** ("Got it -- EMI of 4,200 rupees on the 5th, correct?") before being written to the plan. Consider also passing interim + final transcripts to the LLM as-is and letting gpt-5.6-luna resolve "forty two hundred" if Deepgram leaves it as words; it handles both.

### Cost for ~200 minutes of dev testing

| Item | Rate | 200 min |
|---|---|---|
| Nova-3 mono streaming (promo, Sept 2026) | $0.0048/min | $0.96 |
| Nova-3 mono streaming (regular) | $0.0077/min | $1.54 |
| Keyterm prompting add-on | $0.0013/min | $0.26 |
| Smart formatting / numerals | included | $0 |
| **Total** | | **$1.22 (promo) - $1.80 (regular)** |

All of it is covered by the $200 sign-up credit (no credit card). For comparison, 200 min would be ~$0.50 on AssemblyAI Universal-Streaming (but socket-time billing inflates idle dev sessions), ~$3.40 on OpenAI `gpt-live-transcribe`, ~$3.20 on Google standard streaming.

## Gotchas

1. **Deepgram `endpointing`/`utterance_end_ms` do nothing for Pipecat turn-taking with Nova-3.** The service ignores `UtteranceEnd`. Don't waste time tuning them; tune `SpeechTimeoutUserTurnStopStrategy.user_speech_timeout` or the Smart Turn analyzer.
2. **Smart-format holds entities up to 3 s.** Numbers at the end of an utterance can arrive late unless the VAD-triggered `Finalize` fires. If you disable VAD you will see 1-3 s of extra latency on number-terminated sentences.
3. **Default stop strategy is Smart Turn v3, with open bugs (#3643, #3988) on short utterances.** Symptom: "yes" takes 5 s (the `user_turn_stop_timeout` safety net). Use the silence-timer strategy or lower `user_turn_stop_timeout` to ~3-4 s.
4. **Race: STT final arriving after the turn already closed (#4279, Flux).** The turn is silently skipped. Mostly a Flux/`eot_timeout_ms` issue, but keep `wait_for_transcript=True` (the default) and don't set `user_turn_stop_timeout` below the STT's realistic finalization time.
5. **Flux lacks `smart_format`.** Only `numerals`, and it must be set at connection time. Not suitable when "on the fifth" and currency need formatting.
6. **`numerals` alone strips thousand separators** when punctuation is on ("999999"). Always pair it with `smart_format=True`.
7. **Legacy `keywords` boosting is not the same as `keyterm`.** Nova-3 uses `keyterm` (plain terms, no weights). Keyterm costs an extra $0.0013/min and counts toward a 500-token cap.
8. **Language code choice.** `en-IN` is listed for Nova-3, but there is no published evidence it beats plain `en` on Indian speakers. Test both; both support smart_format/numerals. `multi` (code-switching to Hindi) disables numerals for the Hindi portions.
9. **Lakh/crore are not expanded.** Treat them as vocabulary (add to `keyterm`) and have the LLM normalize to rupees.
10. **AssemblyAI bills on WebSocket open time**, not audio sent. Idle dev sessions cost money; irrelevant for Deepgram which bills on audio.
11. **Pipecat's 1.x API renamed things.** Old snippets with `LiveOptions`, `InputParams`, `vad_events=True` in Deepgram constructors are pre-1.0 and still parse but are deprecated; write against `Settings`.
12. **Indian-English accuracy is unmeasured by every vendor.** Budget 30 minutes to record 20 test phrases (amounts, dates, "EMI", "lakh") and compute a rough error rate before locking the vendor.

## Sources

- Pipecat Deepgram STT docs: https://docs.pipecat.ai/server/services/stt/deepgram
- Pipecat Deepgram STT source (reference): https://reference-server.pipecat.ai/en/latest/_modules/pipecat/services/deepgram/stt.html
- Pipecat User Turn Strategies: https://docs.pipecat.ai/api-reference/server/utilities/turn-management/user-turn-strategies
- Pipecat Silero VAD analyzer: https://docs.pipecat.ai/server/utilities/audio/silero-vad-analyzer
- Pipecat supported services list: https://docs.pipecat.ai/server/services/supported-services
- Pipecat AssemblyAI STT: https://docs.pipecat.ai/server/services/stt/assemblyai
- Pipecat OpenAI STT: https://docs.pipecat.ai/server/services/stt/openai
- Pipecat Speechmatics STT: https://docs.pipecat.ai/server/services/stt/speechmatics
- Pipecat Gladia STT: https://docs.pipecat.ai/server/services/stt/gladia
- Pipecat Google STT: https://docs.pipecat.ai/server/services/stt/google
- Pipecat STT benchmark (TTFS/WER): https://github.com/pipecat-ai/stt-benchmark
- Pipecat releases (v1.9.0): https://github.com/pipecat-ai/pipecat/releases and https://pypi.org/project/pipecat-ai/
- Pipecat issues: #525 https://github.com/pipecat-ai/pipecat/issues/525 , #3643 https://github.com/pipecat-ai/pipecat/issues/3643 , #3988 https://github.com/pipecat-ai/pipecat/issues/3988 , #4279 https://github.com/pipecat-ai/pipecat/issues/4279
- Deepgram pricing: https://deepgram.com/pricing
- Deepgram Numerals: https://developers.deepgram.com/docs/numerals
- Deepgram Smart Format: https://developers.deepgram.com/docs/smart-format
- Deepgram Keyterm prompting: https://developers.deepgram.com/docs/keyterm
- Deepgram end-of-speech detection (endpointing, UtteranceEnd): https://developers.deepgram.com/docs/understanding-end-of-speech-detection
- Deepgram models & languages (en-IN): https://developers.deepgram.com/docs/models-languages-overview
- Deepgram Flux configuration: https://developers.deepgram.com/docs/flux/configuration and https://developers.deepgram.com/docs/flux/quickstart
- Deepgram + Pipecat Flux guide: https://deepgram.com/learn/build-voice-agent-pipecat-deepgram-flux-stt-tts
- Deepgram smart_format "a hundred" bug: https://github.com/orgs/deepgram/discussions/1168
- AssemblyAI pricing: https://www.assemblyai.com/pricing
- AssemblyAI Universal-Streaming API reference: https://www.assemblyai.com/docs/api-reference/streaming-api/universal-streaming/universal-streaming
- OpenAI pricing: https://developers.openai.com/api/docs/pricing
- Google STT pricing: https://cloud.google.com/speech-to-text/pricing (page truncated; per-minute figures cross-checked via third-party summaries -- UNVERIFIED)
- Speechmatics pricing: https://www.speechmatics.com/pricing (real-time rate not legible on page; third-party $1.04/$1.35 per hour figures UNVERIFIED)
- Gladia pricing: https://www.gladia.io/pricing

## Context7 cross-check (2026-09-11)

Every concrete claim below was re-queried against context7 MCP documentation, which is treated as authoritative and current. Nothing in the body above was deleted; corrections are marked inline as **(corrected via context7)**.

### Libraries consulted

| Library | Context7 ID | Version / notes |
|---|---|---|
| Pipecat docs | `/pipecat-ai/docs` | no pinned version; 6,869 snippets, High reputation, benchmark 78.01 |
| Pipecat source/API | `/pipecat-ai/pipecat` | no pinned version; 3,072 snippets, benchmark 70.71 |
| Deepgram API docs | `/websites/developers_deepgram` | no pinned version; 5,909 snippets, benchmark 82.53 |
| Deepgram Python SDK | `/deepgram/deepgram-python-sdk` | versions list shows `v5.3.0` (not queried; API docs were sufficient) |

### Claims table

| # | Claim in report | Verdict | Evidence |
|---|---|---|---|
| 1 | `DeepgramSTTService.Settings` default model is `nova-3-general` | VERIFIED | "**model** (str) - Optional - Deepgram model to use (default: \"nova-3-general\")" |
| 2 | `smart_format` default `False` | VERIFIED | "**smart_format** (bool) - Optional - Apply smart formatting to transcripts (default: False)" |
| 3 | `numerals` default `False` | VERIFIED | "**numerals** (bool) - Optional - Convert spoken numbers to numerals (default: False)" |
| 4 | `punctuate` default `True`, `interim_results` default `True` | VERIFIED | "**punctuate** ... (default: True)", "**interim_results** ... (default: True)" |
| 5 | `endpointing` and `utterance_end_ms` exist in `Settings` | VERIFIED | "**endpointing** (int \| bool) ... **utterance_end_ms** (int) - Optional - Silence duration in ms before an utterance-end event" |
| 6 | `keyterm` and legacy `keywords` both in `Settings` | VERIFIED | Both listed in `DeepgramSTTService.Settings` |
| 7 | Other listed fields (`profanity_filter`, `diarize`, `detect_entities`, `redact`, `replace`, `search`) | VERIFIED | All present; note `profanity_filter` default is **True**, which the report did not state |
| 8 | `live_options=LiveOptions(...)` deprecated in favour of `settings=` | PARTIALLY VERIFIED | context7 shows both forms live side by side (`learn/speech-to-text.mdx` still teaches `LiveOptions`; `fundamentals/service-settings.mdx` teaches `settings=`). The explicit "deprecated since 0.0.105, removed in 2.0.0" marker was NOT COVERED for Deepgram, though context7 confirms the identical 0.0.105 `InputParams`/`params` → `Settings` migration for Cartesia STT, Sarvam TTS and Google TTS. Report's recommendation (write against `Settings`) stands. |
| 9 | Pipecat sends `Finalize` to Deepgram on VAD user-stopped-speaking | VERIFIED | "The service optimizes transcript delivery by sending a finalize request to Deepgram when the pipeline's VAD detects that the user has stopped speaking." |
| 10 | Pipecat's Deepgram service does not handle `UtteranceEnd` / `SpeechStarted`, so `endpointing`/`utterance_end_ms` don't drive Pipecat turn-taking | NOT COVERED (not contradicted) | context7 documents the params and the Finalize behaviour but says nothing about `UtteranceEnd` consumption. It does corroborate the architecture: "Adjusting responsiveness should be handled within the chosen stop strategy rather than low-level VAD settings", and "Closing a turn requires both a transcript from the STT service and the fulfillment of the specific strategy's end-of-turn criteria." |
| 11 | `numerals=True` turns "nine hundred" into "900" | VERIFIED | "the cardinal number \"nine hundred\" would appear in your transcript as \"900\", and the ordinal number \"nine hundredth\" would appear ... as \"900th\"" |
| 12 | `smart_format=true` implies punctuation and formats dates/times/currency/phone numbers | VERIFIED | Twilio integration doc: "smart_format=True # punctuation, capitalization, formatted numbers/dates"; self-hosted doc: entity-detector "detects and formats entities such as dates, times, currency amounts, phone numbers, emails, and URLs" |
| 13 | `smart_format` may hold an incomplete entity for up to 3 s of silence; `Finalize` short-circuits it | VERIFIED | "Finalize the transcript after **3 seconds of silence**"; "Send a `Finalize` message to end transcription earlier than the 3-second threshold"; also a `no_delay` parameter the report does not mention |
| 14 | `smart_format=true` implies numerals | VERIFIED | "When `smart_format=true`, numerals will automatically be applied for all supported languages." |
| 15 | "a hundred and ten percent" → "a 10%" bug (GitHub discussion #1168) | NOT COVERED | No such issue in context7 docs; leave the report's GitHub-sourced finding as-is |
| 16 | `keyterm` is plain terms with no `word:weight` syntax | VERIFIED | "`keyterm` accepts plain terms only. Unlike the legacy `keywords` feature, it does not support weights or intensifiers. Appending one ... is silently ignored" |
| 17 | `keyterm` capped at 500 tokens per request | VERIFIED (for Nova-3) | "Key Terms are limited to 500 tokens per request" |
| 18 | Same 500-token cap applies to **Flux** | CONTRADICTED → corrected inline | Flux Configure message: "**keyterms** (array of strings) - Optional - ... **Up to 100 terms.** This array replaces the entire list, not merges." |
| 19 | `keyterm` costs +$0.0013/min; Nova-3 $0.0077 regular / $0.0048 promo per minute | NOT COVERED | context7 carries developers.deepgram.com, not the pricing page. Pricing claims left as-is. |
| 20 | $200 free credit, no card, never expires | NOT COVERED | Same reason. |
| 21 | Flux supports `numerals` only, set at connection time, no mid-stream toggle | VERIFIED | "On Flux, set `numerals` as a query parameter when you open the connection. Flux does not support toggling `numerals` mid-stream through the `Configure` message." A `Configure` with `features.numerals` "returns an UNPARSABLE_CLIENT_MESSAGE error and closes the connection." |
| 22 | Flux has **no** `smart_format` | VERIFIED (by absence + structure) | The documented Flux `Configure` schema exposes only `thresholds`, `keyterms`, `language_hints`; `smart_format` appears only on `/v1/listen`. Numerals doc treats numerals as the Flux formatting approach. |
| 23 | Flux `eot_threshold` 0.7 default, `eager_eot_threshold`, `eot_timeout_ms` 5000 | VERIFIED (ranges) / PARTIAL (defaults) | "eot_threshold ... Range: 0.5 to 1.0", "eager_eot_threshold ... Range: 0.3 to 0.9. Must be ≤ eot_threshold", "eot_timeout_ms ... Range: 500 to 60000". The example `ConfigureSuccess` echoes `eot_threshold: 0.7`; exact defaults not stated as defaults. |
| 24 | `en-IN` is a listed Nova-3 language variant | NOT CONFIRMED → caveat added inline | context7's `models-languages-overview` / `models-overview` tables enumerate `en-IN` for **Nova-2** and legacy **Nova** ("English: `en`, `en-US`, `en-AU`, `en-GB`, `en-NZ`, `en-IN`"). The Nova-3 material returned (model doc + five 2025-2026 language-expansion changelogs covering Hindi, Gujarati, Chinese, Marathi, Tamil, Telugu, etc.) never enumerates English sub-variants. Not contradicted, but not corroborated either — test it. |
| 25 | `multi` (code-switching) disables numerals for Hindi | VERIFIED (for Flux multi; consistent for Nova-3 multi) | "Flux Multilingual ... Numeral formatting is not currently supported for Hindi or Japanese." Nova-3 multi does support keyterm prompting (500 tokens), per the 2025-11-26 and 2025-12-10 changelogs. |
| 26 | Pipecat 1.9.0 released 2026-09-11; benchmark TTFS/WER figures (247 ms / 1.71%, 1.22%, 1.07%, etc.) | NOT COVERED | context7 indexes no release dates or `pipecat-ai/stt-benchmark` data. All latency/WER numbers, AssemblyAI/Speechmatics/Gladia/Google pricing, free-tier sizes, and GitHub issue numbers (#525, #3643, #3988, #4279) stand on the report's own sourcing. |

### Corrections applied

1. **Flux keyterm cap.** Comparison table: `keyterm` cap split into "Nova-3: <=500 tokens; Flux: up to 100 terms" **(corrected via context7)**. Gotcha 7's 500-token statement remains correct for Nova-3.
2. **`en-IN` on Nova-3.** Added an inline caveat in the `DeepgramSTTService.Settings` snippet: context7 enumerates `en-IN` only for Nova-2/Nova, so the Nova-3 claim is unconfirmed and must be tested. This reinforces, rather than replaces, Gotcha 8.

### Disagreements left standing (report's sourcing is more current)

- **`LiveOptions` deprecation (claim 8).** context7's Pipecat `learn/speech-to-text.mdx` still presents `LiveOptions` as a first-class configuration path with a `nova-2` example. The report cites the 1.9.0 reference server marking it deprecated. The report's guidance is kept; context7's snapshot appears to lag.
- **All pricing, free-tier, benchmark-latency and GitHub-issue claims** are outside context7's indexed corpus (docs sites only) and are left untouched.
