# 11 — Testing and evaluation strategy (minimal but rigorous)

Researched 2026-09-11. Everything below was checked against current docs/source; where a claim could not be verified it is marked **(unverified)**.

## Decision summary

- **Three layers, three tools, no eval SaaS.** (1) pytest unit tests on the plan engine and tool handlers with `Decimal`; (2) a ~150-line text-only conversation harness that calls OpenAI directly with the *same* tool schemas and handler functions the Pipecat bot uses; (3) Pipecat's own `pipecat eval` (v1.4+) in text mode as the integration check that the real pipeline wiring works. Audio is a manual smoke checklist.
- **Bypass Pipecat for the conversation harness.** Pipecat Evals' simulated scenarios "cannot inject hidden facts or mid-conversation corrections" (docs), and corrections/conflicts are the heart of this brief. A direct OpenAI loop gives us that plus response caching for CI.
- **Rule checks first, judge second.** Deterministic transcript checks (numbers traceable to tool results, one question per turn, forbidden phrases) gate the run; the LLM judge only scores what rules cannot (usefulness, clarity, handling of corrections). Judge = binary pass/fail per criterion, different model family or at least a different tier from the agent, position-free (single-transcript grading), majority-of-3 on flaky criteria.
- **Report pass rates, not pass/fail.** gpt-5.6-luna is a reasoning model; `temperature` is only accepted at `reasoning_effort: none` (community-reported, not in official docs) and `seed` is "best effort" at most. Each scenario runs N=5; the report shows k/5.
- **Don't add DeepEval / promptfoo / Braintrust / OpenAI Evals.** OpenAI Evals goes read-only 31 Oct 2026 and shuts down 30 Nov 2026. The others solve dataset UI and dashboards we don't need; ~200 lines of pytest + one judge call is easier to defend live.
- **Cost:** a full eval run (12 scenarios × 5 runs, Luna agent + Luna simulated user + Terra judge) is roughly **$2–3**. Unit tests and cached CI replays are free.

## 1. Test pyramid

### (a) Unit tests — plan engine, state, tool handlers
- `Decimal` everywhere in money fields; assert exact equality, never `approx`. Pydantic `condecimal`/`Decimal` fields with a validator rejecting floats.
- Parametrize over YAML fixtures: input `FinancialState` → expected plan (per-day balance, ordered payments, shortfall, actions). Cases: surplus, exact-zero, shortfall, income after due date, two incomes, optional-expense trimming order, duplicate loan names, missing due date, negative/zero amounts.
- Property tests (hypothesis, ~20 lines): sum of plan outflows ≤ available cash unless `shortfall > 0`; day-by-day balance never silently goes negative without a flagged shortfall; correcting an amount and recomputing equals building from the corrected state.
- Tool handlers: `record_income`, `record_expense`, `record_debt`, `correct_field`, `flag_conflict`, `mark_unknown`, `build_plan`. Test that a correction *replaces* not appends; that two different values for the same item produce a `conflicts[]` entry and no plan until resolved; that `build_plan` refuses when required fields are `unknown`.

### (b) Text-only conversation harness — recommendation: bypass Pipecat
Two options were evaluated:
1. **Pipecat pipeline with text injection.** Possible (feed `TextFrame`/`TranscriptionFrame` into the user aggregator), and Pipecat 1.4+ formalises it as Pipecat Evals: add `"eval": lambda: WebsocketServerParams(audio_in_enabled=True, audio_out_enabled=True)` (from `pipecat.transports.websocket.server`) to `transport_params` **(corrected via context7 — the quickstart uses `WebsocketServerParams`, not an `EvalTransportParams` type)**, run `uv run bot.py -t eval`, then `pipecat eval run scenario.yaml` connects an RTVI client over `ws://localhost:7860` (the `--bot-url` default). Text mode skips STT and TTS. Scripted turns support `event: function_call` with `calls:` (subset argument match), `text_contains`, `eval:` (judge), `within_ms`. Output: `.eval.log` per scenario, `results.jsonl` for suites, exit 0/1.
2. **Direct OpenAI loop** with the same `tools=[...]` JSON schemas and the same Python handler functions, a `FinancialState` instance, and a transcript log.

**Recommend (2) as primary, (1) as a thin integration layer.** Reasons: (2) needs no running bot or websocket, runs in plain pytest, can be response-cached, and supports our own simulated user with hidden facts and corrections — which Pipecat's simulated scenarios explicitly do not. Keep 3–4 Pipecat scripted scenarios in text mode to prove that aggregator → LLM → tool → card-emitting processor wiring is intact in the deployed bot. The only real risk of (2) is drift between the harness loop and Pipecat's context aggregation (e.g., how tool results are appended); mitigate by importing the tool schemas and handlers from one module and never redefining them in tests.

### (c) LLM-simulated user
A second Luna call with a persona prompt holding **hidden facts** the agent must extract (e.g., `salary=42,000 on the 1st; rent=15,000 due 5th; card min=3,200 due 12th; EMI=8,500 due 20th; groceries≈6,000; OTT 1,200`), plus two scripted behaviours: a **correction** ("sorry, rent is fifteen five, not fifteen") triggered at a given turn, and a **conflict** (says card minimum is 3,200 early and 2,300 later without acknowledging). The simulator answers only what is asked, one fact per turn, and ends with "yes, I understand" only after the agent has explained the plan. Cap at 16 turns. Log the hidden facts alongside the final state so the equality check is mechanical.

### (d) Rule-based transcript checks (deterministic, no LLM)
- **Forbidden phrases** (regex, case-insensitive): "approved", "you are eligible", "take a loan", "personal loan", "settlement offer", "I have paid", "I've transferred", "guaranteed".
- **Number provenance**: every currency number in assistant text must appear in some tool result or user utterance up to that turn (normalise "15,500", "15500", "fifteen thousand five hundred"). This is the "no invented numbers" rule made testable.
- **One question per turn**: count `?` and interrogative openers; >1 fails.
- **No markdown / TTS-unfriendly output**: no `*`, `#`, `-` bullets, no digits with more than one comma group (TTS reads "1,50,000" badly), no URLs.
- **Final-state equality**: `state == persona.hidden_facts` after corrections applied; `conflicts` resolved before `build_plan` is called; `build_plan` called exactly once (or zero when info is missing and the agent says so).
- **Guess detection**: if `state.unknown` non-empty, the plan explanation must include a hedge from an allow-list ("assuming", "if", "once you confirm").

### (e) LLM-as-judge rubric
Binary criteria, one transcript per call, JSON output with a quoted evidence span per verdict (Hamel Husain: "A binary decision forces everyone to consider what truly matters"). Judge model: gpt-5.6-terra (different tier from the Luna agent; self-preference bias is 10–25% in the literature when judge and agent share a family, so flag this as a residual risk). Criteria: (1) asked a useful *next* question given known state; (2) acknowledged and applied the correction without re-asking known facts; (3) explained shortfall/surplus in plain words with the actual numbers; (4) checked understanding (asked the user to restate or confirm, not just "does that make sense?"); (5) did not present a guess as fact. Calibrate on ~30 hand-labelled transcripts; report true-positive and true-negative rates separately, not raw agreement.

### (f) Real voice smoke checklist (manual, ~5 minutes, once per prompt version)
Say "forty-two hundred", "fifteen five", "twelve-fifty" and check the card; interrupt mid-sentence; go silent 6s; correct an amount and watch every card update; ask "did you pay it?" and confirm the agent denies taking action; listen for markdown or digit-salad in TTS; note end-to-end latency to first audio. Record transcript + state snapshot JSON for any failure (see §5).

## 2. Pipecat's own test utilities

`pipecat.tests.utils` (source verified) provides:
- `run_test(processor, *, frames_to_send, expected_down_frames=None, expected_up_frames=None, ignore_start=True, send_end_frame=True, observers=None, pipeline_params=None, start_timeout=1.0, enable_rtvi=False)` → `(down_frames, up_frames)`. Builds `Pipeline([source QueuedFrameProcessor, processor, sink QueuedFrameProcessor])`, queues each frame, sends `EndFrame` by default, then asserts `len(received) == len(expected)` and `isinstance(real, expected)` **in order**. Extra or missing frames fail.
- `SleepFrame(sleep=0.2)` — consumed by `run_test` via `asyncio.sleep`, not pushed through the pipeline; use it to separate system frames from data frames.
- `QueuedFrameProcessor`, `HeartbeatsObserver`.

**Verdict:** ideal for our one custom `FrameProcessor` (the card emitter that turns state deltas into RTVI server messages / `TextFrame`s for the client). Not useful for LLM behaviour. Pipecat Evals (§1b) covers the LLM-in-pipeline case.

## 3. Determinism, repetition, caching, cost

- **Sampling controls.** gpt-5.6-luna supports reasoning effort `none…max` (official; the enumerated set is `none, minimal, low, medium, high, xhigh, max` — **(corrected via context7)** — support varies by model). GPT-5-family models return `400 Unsupported value: 'temperature'… Only the default (1) value is supported` unless reasoning is `none` (OpenAI community thread; **not in official docs**). `seed`/`system_fingerprint` is documented as "best effort" for Chat Completions; I could not verify it does anything for 5.6 **(unverified)**. **(corrected via context7: `seed` is additionally flagged `Deprecated, Beta` in the current Chat Completions reference — do not build the harness around it.)** Decision: run the agent at `reasoning_effort: low` (voice latency), accept non-determinism, and measure it.
- **N runs.** Each scenario runs N=5 by default (`EVAL_RUNS=5`), 1 in fast mode. Report k/5 and treat <4/5 as regression. "The Coin Flip Judge?" (Yagubyan, Apr 2026) found pairwise judge verdicts flip 13.6% on average and 11 trials are needed for 95% agreement with a 50-trial reference — we cannot afford that, so we report small-N honestly (§6).
- **Caching.** A 40-line wrapper hashes `(model, messages, tools, effort)` → JSON on disk under `tests/conversation/cassettes/`. CI runs with `EVAL_MODE=replay` (free, deterministic, catches code regressions in handlers/rules); `make eval` runs `record` (live). Cache misses in replay mode fail loudly.
- **Cost estimate** (Luna $0.20/$1.20 per 1M in/out; Terra $2/$12; cached input 10%): one 14-turn scenario ≈ 30k agent input tokens (mostly cached system prompt) + 1.5k output ≈ $0.008; simulated user ≈ $0.006; judge on Terra ≈ 4k in + 0.6k out ≈ $0.015. **≈ $0.03/run → 12 scenarios × 5 runs ≈ $1.80**, plus 3 judge repeats on flaky criteria ≈ $2.50 ceiling.

## 4. Regression workflow

- Scenarios are YAML in `tests/conversation/scenarios/` (example below). Prompts live in `prompts/system_v1.md`, `system_v2.md`; the harness takes `--prompt-version`.
- `make eval` → `python -m evals.run --prompt v2 --runs 5 --out docs/eval-results/2026-09-14_v2.md`. The markdown report has: per-scenario table (rule-check pass k/N, judge criteria k/N, tool-call correctness, tokens, $), a diff column against a `--baseline` report, and a "new failures / fixed" section. `results.jsonl` sits beside it for machine diffing.
- `make eval-compare BASE=v1 HEAD=v2` runs both prompts on the same cassette-seeded simulated users (same persona seeds) and prints side by side.
- `make test` = unit + replayed conversation tests, no network. `make eval-pipecat` = `uv run bot.py -t eval &` then `pipecat eval suite evals/suite.yaml` (text mode, judge pointed at OpenAI via `factory:` instead of the Ollama default).

## 5. Failure → fix → evidence

**Capture.** The bot already emits every tool call and state delta for cards; add a `SessionRecorder` observer that writes `sessions/<id>.json` = `{transcript: [{role, text, ts}], tool_calls: [{name, args, result, ts}], state_snapshots: [...], prompt_version}`. A `scripts/session_to_fixture.py` turns it into a scenario YAML: persona facts from final state, user turns as the scripted path, and the observed bad behaviour as a new rule or judge criterion.

**Plausible example (domain-specific).** Voice smoke test: user says "rent is forty-two hundred". Deepgram smart formatting has a documented edge case where "a hundred and ten percent" became "a 10%" (GitHub discussion #1168); "forty two hundred" is the same class of risk, arriving as "42 100" or "4200" depending on formatting. In the failing session the model called `record_expense(name="rent", amount=42)`, the card showed ₹42, and the plan reported a large surplus. **Fix:** (i) handler-level plausibility guard — amounts under 100 for rent/EMI/salary return `needs_confirmation` instead of writing state; (ii) prompt rule: "repeat any amount back in words before recording it"; (iii) new fixture `stt_numeral_4200.yaml` whose user turn is the literal STT output "rent is 42 100", asserting the agent asks for confirmation and no `record_expense` fires with `amount < 100`. **Evidence:** report shows `v1: 0/5 → v2: 5/5` on the new fixture and no drops elsewhere. Second candidate: "asked two questions in one turn" caught by the rule check on 3/5 runs of `missing_due_date.yaml`; fix = explicit one-question rule with an example in the prompt; evidence = 3/5 → 5/5.

## 6. Where this can be wrong

- **Judge validity.** Norman, Rivera & Hughes (Jun 2026, 21 judges, ~541k judgments) found production judges have test-retest reliability >0.95 yet position bias >0.10 and 33–41 point kappa deflation vs exact-match — judges can be *consistent and wrong*. Our binary single-transcript design removes position bias but not leniency or verbosity bias (the agent that talks more may score "explained clearly" more often). Mitigation is a 30-transcript human calibration set; that is small, and the labeller is me, so criteria drift is likely.
- **Simulated user unrealism.** The persona answers cleanly, one fact per turn, in fluent English. Real users ramble, give ranges ("about ten, fifteen thousand"), and change subject. Pass rates from the harness are an upper bound.
- **STT is outside the text harness.** Numerals, Indian-English accents, code-switching, and barge-in are only covered by the manual checklist and Pipecat's audio mode, which we run rarely because of the TTS free tier. The most likely production failures are exactly here.
- **Small N.** 5 runs per scenario gives a 95% CI of roughly ±35 points on a pass rate; 4/5 vs 5/5 is not a significant difference. Version comparisons are indicative, not proof.
- **Same vendor for agent, simulator, judge.** Even across tiers, shared training may make the judge blind to shared failure modes. A cross-vendor judge spot-check on 10 transcripts is the cheap fix if time allows.
- **Harness ≠ pipeline.** The direct OpenAI loop may diverge from Pipecat's aggregator behaviour (interruptions, partial tool results). Pipecat Evals text runs reduce but do not eliminate this.

## 7. Frameworks

- **OpenAI Evals API** — deprecated: read-only 31 Oct 2026, shutdown 30 Nov 2026. No.
- **Pipecat Evals** — yes, as integration layer (first-party, YAML, text mode, `results.jsonl`, exit codes). Not as the primary harness because simulated scenarios can't script corrections or hidden facts, and the default judge is local Ollama `gemma4:12b`.
- **LiveKit agents testing** — not our stack, but its design (text mode "most cost-effective and deterministic", `.judge(llm, intent=...)`, `mock_tools`) validates the text-first approach.
- **DeepEval** (`ConversationSimulator`, `ConversationalTestCase`, pytest-native) and **promptfoo** (`promptfoo:simulated-user`, `maxTurns`) both do what §1c does; they add dependencies and opinionated metrics we would spend the walkthrough explaining. **Braintrust/Langfuse datasets** are dashboards for teams; a markdown report in git is enough here. **Coval/Hamming/Cekura** are paid voice-simulation SaaS; Coval has a Pipecat integration but needs a websocket-exposed agent and budget. Not for a take-home.
- **Recommendation:** pytest + `hypothesis` + PyYAML + the OpenAI SDK. ~200 lines of harness, ~60 of rule checks, ~40 of judge, ~60 of report.

## Proposed test directory layout

```
prompts/                     system_v1.md, system_v2.md
src/agent/tools.py           tool schemas + handlers (imported by bot AND harness)
src/agent/plan_engine.py     pure functions, Decimal
tests/
  unit/
    test_plan_engine.py      parametrized over fixtures/plans/*.yaml + hypothesis
    test_tool_handlers.py    corrections, conflicts, unknowns
    test_card_processor.py   pipecat.tests.utils.run_test on the custom FrameProcessor
    fixtures/plans/*.yaml
  conversation/
    harness.py               OpenAI loop + real handlers + transcript/state log
    sim_user.py              persona with hidden facts, correction, conflict
    checks.py                rule-based transcript checks
    judge.py                 rubric -> {criterion: pass|fail, evidence}
    cache.py                 record/replay cassettes
    scenarios/*.yaml
    cassettes/               committed JSON, replay in CI
    test_scenarios.py        parametrized over scenarios × EVAL_RUNS
  voice/SMOKE_CHECKLIST.md
evals/                       Pipecat Evals: scripted/*.yaml, suite.yaml (text mode)
scripts/session_to_fixture.py, eval_report.py
docs/eval-results/YYYY-MM-DD_<prompt>.md + results.jsonl
Makefile: test | eval | eval-compare | eval-pipecat
```

## Example scenario fixture

```yaml
name: correction_and_conflict_shortfall
tags: [correction, conflict, shortfall]
persona:
  description: "Priya, 29, salaried, calm, answers one thing at a time, Indian English."
  hidden_facts:
    incomes:  [{name: salary, amount: "42000", day: 1}]
    expenses: [{name: rent, amount: "15500", day: 5, essential: true},
               {name: groceries, amount: "6000", essential: true},
               {name: streaming, amount: "1200", essential: false}]
    debts:    [{name: credit card minimum, amount: "3200", day: 12},
               {name: bike EMI, amount: "8500", day: 20},
               {name: personal loan EMI, amount: "12000", day: 25}]
  scripted_behaviours:
    - turn: 4  # after rent was first given as 15000
      say: "Sorry, rent is fifteen five, not fifteen."
    - turn: 7
      say: "The card minimum is twenty-three hundred."   # conflicts with 3200 said earlier
  ends_when: "agent has explained the plan and asked me to confirm understanding"
max_turns: 16
expect:
  final_state_equals_hidden_facts: true      # after correction; conflict resolved by asking
  tool_calls:
    correct_field: {min: 1}
    flag_conflict: {min: 1}
    build_plan: {exactly: 1}
  plan:
    shortfall: "4400"                        # 42000 - (15500+6000+3200+8500+12000) = -3200 ... see fixture math
  rules: [no_forbidden_phrases, numbers_traceable, one_question_per_turn, no_markdown, hedge_when_unknown]
  judge: [useful_next_question, applied_correction, explained_shortfall, checked_understanding, no_guess_as_fact]
runs: 5
pass_threshold: 4
```
(The `plan.shortfall` value is computed by the plan engine fixture, not typed by hand; the harness fails if the two disagree.)

## Example judge rubric (excerpt of `judge.py` prompt)

```
You are grading ONE transcript of a voice assistant that helps a person plan 30 days of finances.
Answer each criterion PASS or FAIL. Quote the exact assistant sentence that justifies your verdict.
Do not reward length. Do not reward politeness. A missing behaviour is FAIL, not "partial".

1 useful_next_question: At every turn where information was still missing, the assistant's
  question targeted a fact that changes the plan (an amount, a date, whether an expense is
  essential). FAIL if it asked something already answered or asked two things at once.
2 applied_correction: When the user corrected a number, the assistant acknowledged the new
  value and did not use the old one again. FAIL if any later sentence uses the old value.
3 explained_shortfall: The final explanation states the shortfall or surplus with the actual
  number and names which payment(s) cannot be covered. FAIL if vague ("tight month").
4 checked_understanding: The assistant asked the user to say back or confirm a specific part
  of the plan. FAIL for a bare "does that make sense?".
5 no_guess_as_fact: Any number the user did not give is marked as an assumption. FAIL if an
  assumed number is stated flatly.
Return JSON: {"1": {"verdict": "PASS|FAIL", "evidence": "..."}, ...}
```

## Sources

- Pipecat Evals overview, quickstart, scripted/simulated scenarios, suites: https://docs.pipecat.ai/pipecat/evals/overview · https://docs.pipecat.ai/pipecat/evals/quickstart · https://docs.pipecat.ai/pipecat/evals/scripted-scenarios · https://docs.pipecat.ai/pipecat/evals/simulated-scenarios · https://docs.pipecat.ai/pipecat/evals/suites
- Pipecat 1.4.0 release announcement (Evals) and releases: https://x.com/pipecat_ai/status/2067278219779129851 · https://github.com/pipecat-ai/pipecat/releases
- `pipecat.tests.utils` source and API docs: https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/tests/utils.py · https://pipecat-docs.readthedocs.io/en/stable/api/pipecat.tests.utils.html · PR #1048 https://github.com/pipecat-ai/pipecat/pull/1048
- `pipecat.evals.transport` reference: https://reference-server.pipecat.ai/en/stable/_modules/pipecat/evals/transport.html
- Pipecat + Coval: https://docs.pipecat.ai/pipecat/evals/platforms/coval
- gpt-5.6-luna model page and pricing: https://developers.openai.com/api/docs/models/gpt-5.6-luna · https://developers.openai.com/api/docs/pricing · https://simonwillison.net/2026/Jul/9/gpt-5-6/
- OpenAI reasoning guide (no temperature/seed statement): https://developers.openai.com/api/docs/guides/reasoning
- GPT-5 temperature restriction (community): https://community.openai.com/t/gpt-5-models-temperature/1337957 · litellm issue https://github.com/BerriAI/litellm/issues/17005
- Seed / system_fingerprint "best effort": https://cookbook.openai.com/examples/reproducible_outputs_with_the_seed_parameter
- OpenAI Evals deprecation notice: https://developers.openai.com/api/docs/guides/evals
- LiveKit agents testing (text mode, `.judge`, `mock_tools`): https://docs.livekit.io/agents/start/testing/
- Hamel Husain, "Creating a LLM-as-a-Judge that drives business results": https://hamel.dev/blog/posts/llm-judge/
- Norman, Rivera, Hughes, "Reliability without Validity" (Jun 2026): https://arxiv.org/abs/2606.19544
- Yagubyan, "The Coin Flip Judge?" (Apr 2026): https://arxiv.org/abs/2606.13685
- Self-preference bias in LLM judges: https://arxiv.org/abs/2410.21819 · position/verbosity bias survey: https://arxiv.org/abs/2410.02736
- Deepgram numerals / smart_format edge case: https://developers.deepgram.com/docs/numerals · https://github.com/orgs/deepgram/discussions/1168
- promptfoo simulated user: https://www.promptfoo.dev/docs/providers/simulated-user/ · DeepEval ConversationSimulator: https://deepeval.com/docs/conversation-simulator
- Langfuse datasets/experiments: https://langfuse.com/docs/evaluation/experiments/datasets
- Vapi test suites: https://docs.vapi.ai/test/test-suites · Coval vs Hamming vs Cekura comparisons: https://www.coval.ai/blog/hamming-vs-cekura · https://hamming.ai/resources/hamming-vs-coval

---

## Context7 cross-check (2026-09-11)

Every library claim above was re-queried against context7 MCP documentation, treated as authoritative and current. Domain/academic claims (arXiv judge papers, Hamel Husain, Deepgram discussion #1168, LiveKit, Coval/Hamming/Cekura pricing) are outside context7's library corpus and are **NOT COVERED** — they are untouched.

### Libraries resolved

| Library | Context7 ID | Version info |
|---|---|---|
| Pipecat (docs) | `/pipecat-ai/docs` | unversioned (live docs), 6869 snippets |
| Pipecat (source) | `/pipecat-ai/pipecat` | unversioned (main), 3072 snippets |
| Pipecat API reference | `/websites/reference-server_pipecat_ai_en` | unversioned, 2654 snippets |
| OpenAI API | `/websites/developers_openai_api` | unversioned (live docs), 7786 snippets |
| OpenAI Python SDK | `/openai/openai-python` | versions offered: v1.68.0, v1_105_0, v2.8.1, v2.11.0 |
| pytest | `/pytest-dev/pytest` | 9.0.0 |
| pytest-asyncio | `/pytest-dev/pytest-asyncio` | unversioned (main) |
| Pydantic | `/pydantic/pydantic` | unversioned (main, v2 docs) |
| DeepEval | `/confident-ai/deepeval` | unversioned |
| promptfoo | `/promptfoo/promptfoo` | unversioned |
| Braintrust | `/websites/braintrust_dev` | unversioned |

### Claims table

| # | Claim (§) | Verdict | Evidence |
|---|---|---|---|
| 1 | OpenAI Evals read-only 31 Oct 2026, shutdown 30 Nov 2026 (§ Decision summary, §7) | **VERIFIED** | "switching to read-only mode on October 31, 2026, before the dashboard and API shut down completely on November 30, 2026" — developers.openai.com/api/docs/deprecations |
| 2 | `seed` is "best effort" (§3) | **VERIFIED** (+ new fact) | "**seed** (Optional[int]) - Optional (Deprecated, Beta) - If specified, a best effort is made to sample deterministically." Report did not know it is now marked Deprecated/Beta — noted inline. |
| 3 | `system_fingerprint` tracks backend changes affecting determinism (§3) | **VERIFIED** | "monitored in conjunction with the seed request parameter to detect when backend infrastructure updates might influence output determinism" |
| 4 | Reasoning effort `none…max` (§3) | **VERIFIED** | "Supported values are `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`… support for these values varies by model" — enumeration added inline |
| 5 | `temperature` only accepted at `reasoning_effort: none`; GPT-5 family returns 400 (§ Decision summary, §3) | **NOT COVERED** | No temperature restriction statement surfaced in context7's OpenAI corpus. Report already labels this community-reported and not in official docs; that labelling is correct and stands. |
| 6 | Eval transport is added as `"eval": lambda: EvalTransportParams(...)` (§1b) | **CONTRADICTED** | Quickstart: `from pipecat.transports.websocket.server import WebsocketServerParams` … `"eval": lambda: WebsocketServerParams(audio_in_enabled=True, audio_out_enabled=True)`. Corrected inline. |
| 7 | `pipecat eval run scenario.yaml` over `ws://localhost:7860`; `uv run bot.py -t eval` (§1b, §4) | **VERIFIED** | CLI reference: "Runs one or more scenarios against an already-running agent (started with -t eval)"; `--bot-url` "Default: ws://localhost:7860" |
| 8 | Text mode skips STT and TTS (§1b) | **VERIFIED** | "`user: modality: text` … utterances are sent as text to the agent, bypassing its STT"; "`judge: modality: text` … the agent's TTS is skipped"; "By default, scenarios run in text mode, which skips TTS to save costs" |
| 9 | Scripted turns support `event: function_call` with `calls:` subset-arg match and `eval:` judge (§1b) | **VERIFIED** | lifecycle.mdx appointment_booking example shows `event: function_call` / `calls: - name: book_appointment / args:` and `event: response / eval:` |
| 10 | `text_contains` and `within_ms` expectation keys (§1b) | **NOT COVERED** | Not surfaced in context7's scenario docs. Left as written; treat as unconfirmed. |
| 11 | `.eval.log` per scenario, `results.jsonl` for suites, exit 0/1 (§1b, §7) | **PARTIALLY VERIFIED** | CLI reference documents `--logs-dir` "Directory for each scenario's logs" and `--debug` → `<scenario>.debug.log`; suites doc confirms per-suite aggregation. Exact filenames/`results.jsonl` not surfaced. |
| 12 | `pipecat eval suite` spawns agents, runs scenarios, aggregates, concurrent, CI-suited (§4, §7) | **VERIFIED** | "spawns each agent with its eval transport, runs its scenarios, tears down the agent, and aggregates the results, processing multiple runs concurrently… ideal for… CI" |
| 13 | Simulated scenarios "cannot inject hidden facts or mid-conversation corrections" (§ Decision summary, §1b, §7) | **NOT COVERED** | context7 surfaces the simulated-scenario feature but no statement of this limitation. The report cites the docs page directly; body left unchanged. **Disagreement noted: this is the load-bearing reason for bypassing Pipecat — re-read docs.pipecat.ai/pipecat/evals/simulated-scenarios before defending it live.** |
| 14 | Default Pipecat Evals judge is local Ollama `gemma4:12b` (§7) | **NOT COVERED** | Judge model default not surfaced. Left as written. |
| 15 | `pipecat.tests.utils.run_test(...)` full signature and assertion semantics (§2) | **NOT COVERED** | context7 surfaces only the concept: "utilities in the test directory to send frames through a pipeline and assert expected outputs" (AGENTS.md). The report verified this against source (`src/pipecat/tests/utils.py`) — **source verification is more specific than context7 here; body left unchanged.** |
| 16 | `SleepFrame` is consumed by `run_test` to separate frames (§2) | **VERIFIED** (concept) | "Developers can use SleepFrame to simulate delays between frames during these tests" — pipecat AGENTS.md |
| 17 | Pipecat Evals is usable from pytest (§1b integration layer) | **VERIFIED** (+ better pattern) | library.mdx shows `@pytest.mark.asyncio async def test_…: result = await EvalSession.from_scenario(scenario, "ws://localhost:7860").run(); assert result.passed` — a cleaner integration hook than shelling out to the CLI |
| 18 | pytest `parametrize` over fixtures for async tests (§1a, layout) | **VERIFIED** | pytest-asyncio how-to: `@pytest.mark.asyncio` + `@pytest.mark.parametrize("value", [1,2,3])`; `asyncio_mode = "auto"` in `[tool.pytest.ini_options]` auto-marks all async tests — recommended for this repo |
| 19 | DeepEval = `ConversationSimulator`/`ConversationalTestCase`, pytest-native (§7) | **VERIFIED** (identity) | "open-source LLM evaluation framework for testing and evaluating large-language model systems… integrations for RAG pipelines, chatbots, and AI agents" |
| 20 | promptfoo = simulated user, multi-turn (§7) | **VERIFIED** (identity) | "developer-friendly local tool for testing LLM applications, enabling automated evaluations, red teaming, and side-by-side model comparisons" |
| 21 | Braintrust = dataset/dashboard product for teams (§7) | **VERIFIED** (identity) | "end-to-end platform for building AI applications… through experimentation, performance insights, monitoring, and data management" |

Counts: 11 VERIFIED, 1 PARTIALLY VERIFIED, 1 CONTRADICTED, 5 NOT COVERED (library), plus 3 identity confirmations.

### Corrections applied

1. **§1b** — eval transport params: `EvalTransportParams(...)` → `WebsocketServerParams(audio_in_enabled=True, audio_out_enabled=True)` from `pipecat.transports.websocket.server`, marked *(corrected via context7)*.
2. **§3** — `seed` annotated as `Deprecated, Beta` in the current Chat Completions reference, marked *(corrected via context7)*.
3. **§3** — reasoning-effort enumeration spelled out (`none, minimal, low, medium, high, xhigh, max`), marked *(corrected via context7)*.

Left deliberately unchanged: the temperature restriction (correctly flagged as unofficial), the `run_test` signature (source-verified, more specific than context7), and the simulated-scenario limitation (not in context7's corpus; flagged above as the one claim to re-confirm).

### Note for §1b/§4

context7's `library.mdx` shows Pipecat Evals scenarios can be driven from Python (`EvalScenario.load` + `EvalSession.from_scenario(...).run()`) inside a normal `@pytest.mark.asyncio` test, and built programmatically from dataclasses. That is a better fit for `make eval-pipecat` than backgrounding the bot and shelling out to the CLI. Also: in code-constructed scenarios use the `llm_response` event for text mode; `response` is "used only when audio judging is also configured" (YAML examples still use `response`).
