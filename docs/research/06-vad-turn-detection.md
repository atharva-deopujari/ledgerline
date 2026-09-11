# 06 — VAD and end-of-turn detection in Pipecat

Researched 2026-09-11 against Pipecat **1.9.0** (PyPI, released 2026-09-11; `requires-python >=3.11`). Pipecat's turn-detection API changed materially in 1.0.0 (2026-04-14): several names in the original brief (`DailyParams.vad_analyzer`, `allow_interruptions`, `MinWordsInterruptionStrategy`, `UserIdleProcessor`, `aggregation_timeout`) are **gone**. Everything below uses the current API.

## Decision summary

- **Keep Silero VAD at the default `stop_secs=0.2`. Do not lengthen it.** Pipecat's STT-latency budget is calibrated for 0.2 s and warns if you change it. A long VAD stop is the wrong tool for the "pause mid-number" problem.
- **Use Smart Turn v3.2 (`LocalSmartTurnAnalyzerV3`) as the stop strategy.** It is already the default, bundled in the wheel (8 MB ONNX), runs ~10-60 ms on CPU, supports English/Hindi/Marathi, and its training data is explicitly labelled for mid-utterance fillers ("um", "uh"). When it says INCOMPLETE the turn stays open for up to `SmartTurnParams.stop_secs` (default 3.0 s) of silence. This is the mechanism that solves our failure mode.
- **Let Pipecat, not Deepgram, decide end of turn.** Leave Deepgram `endpointing`/`utterance_end_ms` unset; Pipecat sends `Finalize` on VAD stop and gates the turn on a finalized transcript or a 0.35 s P99 deadline.
- **Gate interruptions with `MinWordsUserTurnStartStrategy(min_words=3)`** so "uh-huh" does not kill the bot mid-explanation.
- **Use `user_idle_timeout` (10 s) + `on_user_turn_idle`** for "are you still there?" — `UserIdleProcessor` no longer exists.
- Build everything through `LLMContextAggregatorPair` / `LLMUserAggregatorParams`; VAD, turn strategies, interruptions and idle detection all live there now.

## 1. SileroVADAnalyzer

```python
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
```

`SileroVADAnalyzer(*, sample_rate: int | None = None, params: VADParams | None = None)`; sample rate must be 8000 or 16000 (transport supplies it if `None`). `VADParams` defaults (verified in `vad_analyzer.py`): `confidence=0.7`, `start_secs=0.2`, `stop_secs=0.2`, `min_volume=0.6`. States: QUIET → STARTING → SPEAKING → STOPPING.

**Where it plugs in:** `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())`. In 1.0.0 the `vad_analyzer`/`turn_analyzer` fields were removed from `TransportParams`/`DailyParams`; "VAD and turn detection are now handled entirely by `LLMUserAggregator`". The aggregator wraps it in a `VADController` and emits `VADUserStartedSpeakingFrame`/`VADUserStoppedSpeakingFrame` (the stop frame carries `stop_secs` and a timestamp used by the stop strategies).

**Model shipping / Docker:** `silero_vad.onnx` is package data (`pipecat.audio.vad.data`, loaded via `importlib_resources`) — no runtime download. `onnxruntime~=1.24.3` is now a *core* dependency and the `silero` extra is an empty list. So `pip install "pipecat-ai[daily,deepgram]"` in the image is the whole "prebake"; the container needs no model-fetch step and no outbound access for models at start.

## 2. Smart Turn (v3.2, `LocalSmartTurnAnalyzerV3`)

```python
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
```

- **What it does:** an ~8 M-parameter Whisper-Tiny-backbone classifier that, on each VAD stop, looks at the last ≤8 s of the user's turn (16 kHz mono, plus `pre_speech_ms=500` of lead-in) and predicts COMPLETE vs INCOMPLETE from prosody and semantics, not just silence.
- **Model:** `smart-turn-v3.2-cpu.onnx` (int8, 8 MB) is bundled in the wheel (`pipecat.audio.turn.smart_turn.data`) and used when `smart_turn_model_path` is `None`. Constructor: `LocalSmartTurnAnalyzerV3(*, smart_turn_model_path=None, cpu_count=1, params: SmartTurnParams | None)`. The `local-smart-turn` extra (torch/coremltools) is **not** needed for the V3 ONNX path.
- **Speed:** Daily reports 12 ms best-case, 9-57 ms across CPUs for the 8 MB model, "under 100 ms on most cloud instances", ~65-70 ms on Pipecat Cloud.
- **Languages:** 23, including English, Hindi and Marathi.
- **Accuracy:** v3.1 English 94.7 % (8 MB); v3.2 (2026-01-07) cut errors on short utterances ("yes", "okay") by 40 % and added background-noise robustness.
- **Enable:** it is the *default* stop strategy since 0.0.102 — `UserTurnStrategies.stop` defaults to `[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]`. Set it explicitly only to tune `SmartTurnParams`.
- **How it combines with Silero (from `turn_analyzer_user_turn_stop_strategy.py`):** VAD stop (0.2 s) → `analyze_end_of_turn()`. If COMPLETE, the strategy waits for text and either a `TranscriptionFrame(finalized=True)` or the STT P99 deadline, whichever first. If INCOMPLETE, nothing fires; audio keeps buffering, and if the user resumes, the pending conclusion is discarded. Only after `SmartTurnParams.stop_secs` (default **3.0 s**) of continuous silence does `append_audio` force COMPLETE.
- **Does it fix "my EMI is... um... forty-two hundred"?** This is exactly the case it is designed for: the v3.2 training set carries `midfiller` and `endfiller` labels (filled pauses, trailing off), and an INCOMPLETE verdict holds the turn open for up to 3 s. A plain long `stop_secs` would instead add that latency to *every* turn and would break Pipecat's latency calibration (see §3). **Verdict: use Smart Turn; do not substitute a longer VAD stop.** The non-ML fallback, `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)`, is a fixed wait after every pause — slower for complete sentences and still cut off at 0.6 s for thoughtful pauses.

## 3. Deepgram endpointing vs Pipecat

Verified `DeepgramSTTService` defaults: `model="nova-3-general"`, `interim_results=True`, `punctuate=True`, `endpointing=None`, `utterance_end_ms=None`, `smart_format=False`, `numerals=False`, `ttfs_p99_latency=DEEPGRAM_TTFS_P99` = **0.35 s**. With `endpointing=None` Deepgram applies its own server default (10 ms), so `speech_final` transcripts arrive quickly — that is fine, because **Deepgram does not end the turn**. The service does not consume `UtteranceEnd`/`SpeechStarted` events; it only (a) emits `TranscriptionFrame`/`InterimTranscriptionFrame` and (b) sends `Finalize` when it sees `VADUserStoppedSpeakingFrame`, so the final transcript lands fast.

**Who decides:** the aggregator's stop strategy. Deadline logic: "the end of the user's speech plus the STT service's `ttfs_p99_latency`" — anchored to `vad_stop.timestamp - stop_secs`, so VAD, Smart Turn inference and the STT wait **do not stack**. Built-in P99 values were measured with `stop_secs=0.2`; if you change it Pipecat logs a warning telling you to re-run `pipecat-ai/stt-benchmark` and pass a measured `ttfs_p99_latency`. If `stop_secs >= 0.35` the STT wait collapses to 0 and you fall back to the 5 s `user_turn_stop_timeout` — a real latency regression.

**Recommendation:** leave `endpointing` and `utterance_end_ms` unset, keep `interim_results=True` (the strategy uses an interim after a finalized transcript to un-finalize, guarding against aggressive STT endpoints). Enable `smart_format=True` (or `numerals=True`) so "forty-two hundred" arrives as digits — verify the formatting of amounts like "forty-two hundred" vs "4,200" in testing.

**Flux (`DeepgramFluxSTTService`)** does its own turn detection (`eot_threshold`, `eot_timeout_ms`), requests `ExternalUserTurnStrategies`, and is English-only (`flux-general-en`). Not recommended here: we lose Smart Turn, lose Hindi/Marathi, and issue #4279 shows a Flux `eot_timeout_ms` longer than `user_turn_stop_timeout` silently drops late transcripts.

## 4. User aggregator timeouts

`LLMUserAggregatorParams` (in `pipecat.processors.aggregators.llm_response_universal`), verified fields: `vad_analyzer=None`, `user_turn_strategies=None` (→ defaults), `user_turn_stop_timeout=5.0` (safety net: forces end of turn if no stop strategy fires, emits `on_user_turn_stop_timeout`; reset by any transcription/VAD activity; never fires while the user is speaking), `user_idle_timeout=0` (off), `audio_idle_timeout=1.0` (force speech stop if audio frames stop, e.g. mic muted), `user_mute_strategies=[]`. `aggregation_timeout` does not appear in the current params — the "wait for late transcripts after VAD stop" role is now the P99 deadline inside the stop strategy (`wait_for_transcript=True`, plus a late-transcript path that fires immediately if the P99 timer already expired). Events: `on_user_turn_started/stopped`, `on_user_turn_stop_timeout`, `on_user_turn_idle`, `on_user_turn_message_added`, `on_user_mute_started/stopped`.

## 5. Interruption tuning

`allow_interruptions` and `interruption_strategies` were **removed from `PipelineParams` in 1.0.0**; interruptions are always on and controlled by start strategies (`pipecat.turns.user_start`): `VADUserTurnStartStrategy(enable_interruptions=True)`, `TranscriptionUserTurnStartStrategy(use_interim=True, enable_interruptions=True)`, `MinWordsUserTurnStartStrategy(min_words, use_interim=True)`. Default start list is `[VAD, Transcription]` — any speech interrupts. The official `turn-management-interruption-config.py` example uses `UserTurnStrategies(start=[MinWordsUserTurnStartStrategy(min_words=3)])`; the word threshold "only applies when the bot is actively speaking", so backchannels ("yeah", "mm-hmm", "okay okay") no longer cancel the plan explanation, while a real 3+ word interjection still does. Trade-off: turn start now waits for an interim transcript rather than VAD, adding a few hundred ms before the bot stops talking. `user_mute_strategies` exist for hard-muting during specific bot phases if needed.

## 6. Idle detection

`UserIdleProcessor` was removed in 1.0.0. Use `LLMUserAggregatorParams(user_idle_timeout=N)` and `@user_aggregator.event_handler("on_user_turn_idle")`. The timer starts on `BotStoppedSpeakingFrame`, resets when either side speaks, is suppressed during function calls and active user turns, and re-fires each cycle (the official example escalates: nudge, nudge, goodbye + `EndWorkerFrame()`). Adjustable at runtime via `UserIdleTimeoutUpdateFrame(timeout=...)`. **Worth including** — it is ~15 lines and demonstrates turn awareness — but use **10 s**, not the docs' 5 s: our users think before answering money questions, and the first nudge should be a soft "take your time" appended as a developer message with `run_llm=True`.

## Recommended config

```python
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair, LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService

stt = DeepgramSTTService(
    api_key=os.environ["DEEPGRAM_API_KEY"],
    settings=DeepgramSTTService.Settings(   # spelling confirmed (corrected via context7)
        model="nova-3-general", smart_format=True, interim_results=True,
        # endpointing / utterance_end_ms intentionally unset
    ),
)

user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
    context,
    user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(
            params=VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.2, min_volume=0.6)
        ),
        user_turn_strategies=UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=3)],
            stop=[TurnAnalyzerUserTurnStopStrategy(
                turn_analyzer=LocalSmartTurnAnalyzerV3(
                    params=SmartTurnParams(stop_secs=3.0, pre_speech_ms=500, max_duration_secs=8)
                ),
            )],
        ),
        user_turn_stop_timeout=6.0,
        user_idle_timeout=10.0,
    ),
)
```

Tune in testing, in this order: (1) `SmartTurnParams.stop_secs` 2.5-4.0 s — the max hold for an INCOMPLETE pause; (2) `min_words` 2 vs 3; (3) `user_idle_timeout` 8-12 s; (4) `VADParams.confidence`/`min_volume` only for noisy mics; (5) if `on_user_turn_stop_timeout` ever fires in logs, Deepgram finals are late — measure with stt-benchmark and set `ttfs_p99_latency`.

## Gotchas

- `PipelineTask` is deprecated for `PipelineWorker` (`pipecat.pipeline.worker`); `PipelineParams` no longer has `allow_interruptions`.
- Changing VAD `stop_secs` from 0.2 triggers a warning and, above 0.35 s, zeroes the STT wait budget — pauses then leak into `user_turn_stop_timeout` (5 s).
- Smart Turn's `stop_secs` (3.0, silence cap after INCOMPLETE) is a different knob from VAD `stop_secs` (0.2). Do not confuse them.
- Both ONNX models ship in the wheel; the `silero` extra is empty and `local-smart-turn` is only for torch/CoreML analyzers — do not install it in Docker.
- `on_user_turn_idle` fires repeatedly; count retries in the handler.
- `DeepgramSTTService.Settings` is the correct spelling and `ttfs_p99_latency` is a real constructor kwarg
  *(corrected via context7 — both were flagged UNVERIFIED above)*.
- Number formatting: `smart_format`/`numerals` behaviour on "forty-two hundred" and dates ("the fifth") is UNVERIFIED — test and, if needed, normalise in the LLM prompt.

## Sources

- PyPI pipecat-ai (1.9.0, extras): https://pypi.org/project/pipecat-ai/
- Release v1.0.0 (removals): https://github.com/pipecat-ai/pipecat/releases/tag/v1.0.0
- User turn strategies: https://docs.pipecat.ai/api-reference/server/utilities/turn-management/user-turn-strategies
- Silero VAD docs: https://docs.pipecat.ai/server/utilities/audio/silero-vad-analyzer
- VADParams source: https://reference-server.pipecat.ai/en/stable/_modules/pipecat/audio/vad/vad_analyzer.html
- Silero source (bundled model): https://reference-server.pipecat.ai/en/latest/_modules/pipecat/audio/vad/silero.html
- Smart Turn overview: https://docs.pipecat.ai/api-reference/server/utilities/turn-detection/smart-turn-overview
- LocalSmartTurnAnalyzerV3: https://reference-server.pipecat.ai/en/stable/api/pipecat.audio.turn.smart_turn.local_smart_turn_v3.html
- SmartTurnParams / BaseSmartTurn: https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/audio/turn/smart_turn/base_smart_turn.py
- TurnAnalyzerUserTurnStopStrategy source: https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/turns/user_stop/turn_analyzer_user_turn_stop_strategy.py
- SpeechTimeoutUserTurnStopStrategy: https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/turns/user_stop/speech_timeout_user_turn_stop_strategy.py
- UserTurnController: https://reference-server.pipecat.ai/en/stable/_modules/pipecat/turns/user_turn_controller.html
- LLMUserAggregatorParams: https://reference-server.pipecat.ai/en/stable/api/pipecat.processors.aggregators.llm_response_universal.html
- STT latency tuning: https://docs.pipecat.ai/pipecat/fundamentals/stt-latency-tuning
- stt_latency constants: https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/stt_latency.py
- Deepgram STT service: https://docs.pipecat.ai/api-reference/server/services/stt/deepgram and https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/deepgram/stt.py
- Deepgram endpointing default: https://developers.deepgram.com/docs/endpointing
- Issue #4279 (late STT dropped): https://github.com/pipecat-ai/pipecat/issues/4279
- Detecting idle users: https://docs.pipecat.ai/pipecat/fundamentals/detecting-user-idle
- Examples: https://github.com/pipecat-ai/pipecat/tree/main/examples/turn-management
- PipelineWorker/PipelineParams: https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/pipeline/worker.py
- pyproject (onnxruntime core, bundled .onnx): https://raw.githubusercontent.com/pipecat-ai/pipecat/main/pyproject.toml
- Smart Turn v3 / v3.1 / v3.2 blogs: https://www.daily.co/blog/announcing-smart-turn-v3-with-cpu-inference-in-just-12ms/ , https://www.daily.co/blog/improved-accuracy-in-smart-turn-v3-1/ , https://www.daily.co/blog/smart-turn-v3-2-handling-noisy-environments-and-short-responses/
- Smart Turn repo / data (midfiller labels): https://github.com/pipecat-ai/smart-turn , https://huggingface.co/datasets/pipecat-ai/smart-turn-data-v3.2-train


---

## Context7 cross-check (2026-09-11)

**Library used:** `/pipecat-ai/docs` (Context7; "Pipecat", 6869 snippets, source reputation High, benchmark
78.01). Context7 exposed **no version-pinned variant** — the corpus tracks `github.com/pipecat-ai/docs` `main`
and is therefore *unversioned*. Internal version markers ("default since 0.0.102", "deprecated since version
1.5.0", `migration-1.0.mdx`, `LocalSmartTurnAnalyzerV3`, `WorkerRunner`) put it in the post-1.0 era and
consistent with 1.9.0. `/pipecat-ai/pipecat` and `/websites/pipecat_ai` were rejected as lower-coverage
mirrors.

This report's turn-detection claims were read from source; context7 is used here as a second, independent
confirmation, and it agreed on every load-bearing default.

| # | Claim (section) | Status | Context7 evidence |
| --- | --- | --- | --- |
| 1 | `SileroVADAnalyzer(sample_rate, params)`, sample rate 8000 or 16000 (§1) | VERIFIED | `services/vad/silero-vad-analyzer`: "Audio sample rate in Hz. Must be 8000 or 16000" |
| 2 | `VADParams` defaults `confidence=0.7, start_secs=0.2, stop_secs=0.2, min_volume=0.6` (§1) | VERIFIED | Same page, all four defaults stated verbatim; corroborated a second time on the `krisp-viva-vad-analyzer` page |
| 3 | VAD plugs into `LLMUserAggregatorParams(vad_analyzer=...)`, not `TransportParams`/`DailyParams` (§1) | VERIFIED | `learn/speech-input` and `migration-1.0` both wire it exclusively through `LLMUserAggregatorParams`; no transport-level `vad_analyzer` appears anywhere in the corpus |
| 4 | Smart Turn v3 is the **default** stop strategy since 0.0.102 (§2) | VERIFIED | `turn-detection/smart-turn-overview` "Default Strategy": "As of version 0.0.102, the TurnAnalyzerUserTurnStopStrategy combined with LocalSmartTurnAnalyzerV3 is the default user turn stop strategy" |
| 5 | Default `UserTurnStrategies` = start `[VAD, Transcription]`, stop `[TurnAnalyzer(LocalSmartTurnAnalyzerV3())]` (§2, §5) | VERIFIED | `turn-management/user-turn-strategies` "Define Default User Turn Strategies" — the exact literal, commented "equivalent to the default behavior" |
| 6 | Import paths `pipecat.audio.turn.smart_turn.local_smart_turn_v3`, `pipecat.turns.user_stop`, `pipecat.turns.user_turn_strategies` (§2) | VERIFIED | Identical imports in `user-turn-strategies` and `migration-1.0` |
| 7 | `SmartTurnParams` exposes `stop_secs`, `pre_speech_ms`, `max_duration_secs`; `max_duration_secs` defaults to 8 (§2) | VERIFIED | `smart-turn-overview` "Configuration": "max_duration_secs to set the maximum segment duration, which defaults to 8 seconds" |
| 8 | `SmartTurnParams.stop_secs` default is **3.0 s** (§2, §Recommended config) | NOT COVERED | Docs describe `stop_secs` as "the duration of silence required to trigger an end-of-turn" but state no numeric default. Source-read value retained |
| 9 | `pre_speech_ms=500` default (§2) | NOT COVERED | Parameter confirmed to exist; no default given |
| 10 | v3.2 model bundled in the wheel, no runtime download; `local-smart-turn` extra not needed for the ONNX path (§2, gotchas) | NOT COVERED | Prose docs do not discuss packaging or extras contents |
| 11 | Smart Turn latency / language-count / accuracy figures (§2) | NOT COVERED | These are Daily blog claims; context7's doc corpus carries no benchmark numbers |
| 12 | `LocalSmartTurnAnalyzerV3()` takes no required args (§2, config) | VERIFIED | Every context7 example instantiates it bare: `TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())` |
| 13 | `DeepgramSTTService.Settings(...)` is the right spelling (§Recommended config — was flagged UNVERIFIED) | VERIFIED → corrected inline | `fundamentals/service-settings`: `DeepgramSTTService(api_key=..., settings=DeepgramSTTService.Settings(model="nova-3", language="en", smart_format=True))` |
| 14 | `ttfs_p99_latency` is a real `DeepgramSTTService` kwarg (§3) | VERIFIED | `services/stt/deepgram` parameter table: "**ttfs_p99_latency** (float) - Optional - P99 latency from speech end to final transcript in seconds" |
| 15 | `ttfs_p99_latency` default = **0.35 s** for Deepgram (§3) | NOT COVERED | Parameter documented without a default value; `stt_latency.py` remains the only source |
| 16 | Deepgram defaults `model="nova-3-general"`, `endpointing=None`, `utterance_end_ms=None`, `smart_format=False`, `numerals=False` (§3) | NOT COVERED | The constructor table documents `encoding`, `channels`, `multichannel`, `sample_rate`, `callback`, `tag`, `mip_opt_out`, `addons`, `ttfs_p99_latency` — the transcription options now live behind `settings=` and no defaults are published. Note the doc *example* uses `model="nova-3"` rather than `"nova-3-general"`; that is an example value, not a stated default, so it is not treated as a contradiction |
| 17 | `MinWordsUserTurnStartStrategy(min_words=3)` gates interruptions (§Decision summary, §5) | VERIFIED | `turn-management/user-turn-strategies` and `fundamentals/interruptions` both show `MinWordsUserTurnStartStrategy(min_words=3)` |
| 18 | The word threshold "only applies when the bot is actively speaking" (§5) | VERIFIED | `user-turn-strategies`: "When the bot is not speaking, the strategy defaults to triggering after a single word. The word count threshold only applies while the bot is actively speaking" |
| 19 | Strategy params `min_words`, `use_interim`, `enable_interruptions` (§5) | VERIFIED | Same page's parameter table, all three |
| 20 | `allow_interruptions`/`interruption_strategies` removed from `PipelineParams` in 1.0.0; interruptions always on (§5, gotchas) | VERIFIED | `migration-1.0` "Turn Management": "The legacy allow_interruptions parameter … has been removed" |
| 21 | `LLMUserAggregatorParams.user_turn_stop_timeout` default **5.0** (§4) | VERIFIED | `user-turn-strategies`: "Default: 5.0. Safety-net timeout … If a user turn starts but no stop strategy triggers within this duration, the turn is automatically ended" |
| 22 | `LLMUserAggregatorParams` carries `vad_analyzer`, `user_turn_strategies`, `user_mute_strategies`, `user_idle_timeout` (§4) | VERIFIED | `migration-1.0` shows all five fields on one constructor call |
| 23 | `audio_idle_timeout=1.0` default (§4) | NOT COVERED | Field never appears in the corpus |
| 24 | `user_idle_timeout=0` means off (§4) | NOT COVERED | Docs only ever show positive values (`5.0`, `8.0`); the "0 disables" semantics are unstated |
| 25 | `on_user_turn_idle` timer starts when the bot stops speaking, cancelled when either side speaks (§6) | VERIFIED | `turn-management/turn-events`: "The idle timer starts when the bot finishes speaking and is cancelled when the user or bot starts speaking again" |
| 26 | `UserIdleProcessor` removed; idle handled on the aggregator (§Decision summary, §6) | VERIFIED (by absence + positive evidence) | `UserIdleProcessor` returns no hits; `fundamentals/detecting-user-idle` — the page that would document it — uses `LLMUserAggregatorParams(user_idle_timeout=...)` exclusively |
| 27 | The docs' idle example uses 5 s (report recommends 10 s instead) (§6) | VERIFIED | `detecting-user-idle`: `user_idle_timeout=5.0,  # Detect idle after 5 seconds`. `migration-1.0` uses 8.0. Our 10 s is a deliberate deviation, not an error |
| 28 | `aggregation_timeout` no longer exists on the user params (§4, header) | VERIFIED (by absence) | Zero hits across the corpus; every current example uses `user_turn_stop_timeout` |
| 29 | Events `on_user_turn_started/stopped`, `on_user_turn_stop_timeout`, `on_user_turn_idle` (§4) | VERIFIED (partial) | `turn-management/turn-events` documents `on_user_turn_idle` in full; the sibling events are on the same page but were not individually quoted |
| 30 | STT-latency warning when `stop_secs` ≠ 0.2; `stop_secs >= 0.35` zeroes the STT wait (§3, gotchas) | NOT COVERED | `fundamentals/stt-latency-tuning` did not surface for any query; retained on source authority |
| 31 | `DeepgramFluxSTTService` does its own EOT and requests `ExternalUserTurnStrategies` (§3) | NOT COVERED | No Flux snippets surfaced |

**Tally:** 17 VERIFIED · 0 CONTRADICTED · 14 NOT COVERED.

### Corrections applied

1. **§Recommended config** — removed the `# UNVERIFIED exact Settings class spelling` marker on
   `DeepgramSTTService.Settings(...)`. Context7 confirms the nested-`Settings` spelling on
   `fundamentals/service-settings`. Marked *(corrected via context7)*.
2. **§Gotchas** — added a line recording that both `DeepgramSTTService.Settings` and the `ttfs_p99_latency`
   kwarg are now doc-confirmed, since the body previously hedged on them.

### New facts context7 adds (not previously in this report)

- **Disabling interruptions does not drop the user's speech.** `fundamentals/interruptions`: with
  interruptions off, "user speech during the bot's turn is queued for processing after the bot finishes
  speaking rather than cancelling the current output." Relevant if we ever hard-disable barge-in for the
  plan-explanation phase instead of relying on `min_words`.
- **A model-based backchannel filter exists as a first-class strategy**:
  `KrispVivaIPUserTurnStartStrategy(threshold=0.5)` (with `TranscriptionUserTurnStartStrategy()` as fallback)
  is documented as the ML alternative to `min_words` for distinguishing genuine interruptions from
  backchannels. It needs the Krisp VIVA SDK and a `.kef` model file, so it is heavier than our chosen
  `min_words=3` — but it is the escalation path if 3 words proves to be the wrong threshold in testing.
- **`KrispVivaVadAnalyzer`** is an alternative VAD accepting the same `VADParams`, at 8k/16k/32k/44.1k/48k.
  Not needed — Silero is bundled and free — but noted as the drop-in if mic noise defeats Silero.

### Disagreements

**None.** Every claim context7 covered, it confirmed. The 14 NOT COVERED rows are all numeric defaults
(`SmartTurnParams.stop_secs=3.0`, `pre_speech_ms=500`, `ttfs_p99_latency=0.35`, `audio_idle_timeout=1.0`,
the Deepgram option defaults) plus packaging and benchmark facts that the prose docs simply do not publish.
These stay source-verified against the 1.9.0 sdist and are unchanged. The one nominal difference —
`model="nova-3"` in a context7 example vs `"nova-3-general"` as this report's stated default — is an example
value, not a documented default, and is not treated as a contradiction.
