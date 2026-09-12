# 05 — Prior art: open-source evaluation and regression testing of conversational / voice agents

Researched 2026-09-12 for Ledgerline (voice money-coach agent: Pipecat + OpenAI tool calling,
pure-Python plan engine). Angle: how other open-source projects build simulated users, separate
deterministic checks from judges, count runs, verify tool calls and numbers, and turn a failure
into a regression test.

## Summary (ranked by value to Ledgerline)

1. **τ²-bench is the closest prior art and the richest source.** Its user simulator, `reward_basis` scoring split, `pass^k`, and two-sided LLM judge map almost one-to-one onto what we are building. Read §1 before touching `evals/`.
2. **Intent-level criteria, not keyword bans, are how everyone does policy.** τ² uses one-sentence `nl_assertions` judged by an LLM ("Agent should not approve the cancellation"); nobody ships a banned-substring list. Five drop-in criteria for Ledgerline are in "Judge rubrics worth borrowing" (h) — criterion 1 carries an explicit carve-out for naming an existing debt, which is the information a substring ban cannot encode.
3. **Pipecat's own judge prompt solves two bugs we have.** A three-valued verdict (`yes`/`no`/**`continue`**) stops filler turns around `build_plan` being scored as failures, and one clause — *"do not fault a reply for something the criterion does not ask of it"* — is the general fix for negative criteria.
4. **Pipecat Evals has grown a persona simulation mode.** `src/pipecat/evals/persona.py` + `simulation*.py` postdate our note in `11-testing-evals.md`; that note's "cannot inject hidden facts" claim needs correcting. Keeping our own harness is still right, for a narrower reason.
5. **Terminate on a structured signal, not a string.** Pipecat's `end_call(success, reason)` tool beats our `[END]` sentinel; τ²'s third token, `###OUT-OF-SCOPE###`, is the one we are missing — it separates "scenario ran dry" from "agent stalled".
6. **Report pass^k, not k/N.** `math.comb(c,k)/math.comb(n,k)` — the probability *all* k runs pass. For a money agent, reliability is the metric; pass@k flatters. Also: exclude infrastructure errors from metrics, as τ² does.
7. **Tool-call assertions want four separate strengths.** agentevals' `strict`/`unordered`/`superset`/`subset` plus LiveKit's **subset argument matching** (only the keys you name are checked). Score on final state, keep ordered trajectory checks as diagnostics.
8. **τ²'s judge grades the simulated user too**, with an asymmetric severity scale (`critical_helped` vs `critical_hindered`) and a closed error-tag vocabulary — so a red run can be attributed to the simulator rather than the agent.
9. **Mock tool *execution*, never tool *schemas*** (LiveKit `mock_tools`) for the free CI tier; the model must still choose the tool and its arguments.
10. **τ²'s voice simulation guidelines are a free upgrade to our text harness** — spoken numerals, disfluency, silence handling — and the right regression fixture for an STT bug is the STT's literal formatted output ("rent is 42 100"), not audio.

---

## 1. τ²-bench (tau2-bench) — Sierra Research

- Repo: https://github.com/sierra-research/tau2-bench — **2,003 stars**, MIT, last push **2026-09-11** (actively developed).
- Paper: τ²-Bench, https://arxiv.org/abs/2506.07982. pass^k originates in τ-bench, https://arxiv.org/pdf/2406.12045.
- What it is: a benchmark *and* a reusable harness for **LLM agent + LLM user simulator + tool environment + domain policy**. Five domains (`mock`, `airline`, `retail`, `telecom`, `banking_knowledge`), each a policy document, a tool set, tasks, and optional user-simulator tools. Supports half-duplex (turn-based text) and full-duplex (realtime voice) modes.

This is the single closest prior art to Ledgerline's harness and the richest source of borrowable design.

### 1.1 The user simulator

Source: `src/tau2/user/user_simulator.py`. Behaviour is layered in **three** places, and the file says so explicitly:

> Note: User behavior/persona is controlled in THREE places, and they need to be consistent / non-overlapping.
> 1. Global simulation guidelines (`data/tau2/user_simulator/*.md`) - Base behavior for all users
> 2. Task-specific persona (`UserScenario.persona` field) - Baked into task JSON at creation time
> 3. Runtime persona config (`persona_config` parameter) - Configurable at simulation time

System prompt assembly (`UserSimulator.system_prompt`): global guidelines markdown, with the literal token `<PERSONA_GUIDELINES>` replaced by the runtime persona text, then the scenario wrapped in `<scenario>…</scenario>`.

**Termination is a sentinel token, not a heuristic** (`user_simulator_base.py` exports `STOP`, `TRANSFER`, `OUT_OF_SCOPE`):

```python
@classmethod
def is_stop(cls, message: UserMessage) -> bool:
    if message.is_tool_call():
        return False
    if message.content is None:      # audio-only chunk
        return False
    return (STOP in message.content
            or TRANSFER in message.content
            or OUT_OF_SCOPE in message.content)
```

`###STOP###` = task satisfied, `###TRANSFER###` = agent escalated, `###OUT-OF-SCOPE###` = **the scenario did not give the simulator enough information to continue**. That third token is the one Ledgerline is missing: today a simulated user that runs out of scripted facts either invents one or stalls until `max_turns`, and both look identical in the report. Ledgerline's `evals/sim_user.py` has only a single `[END]` sentinel.

### 1.2 The simulated-user prompt (text) — `data/tau2/user_simulator/simulation_guidelines.md`

Short, and every line is a rule Ledgerline's `PERSONA` also needs:

> - Generate one message at a time, maintaining natural conversation flow.
> - Strictly follow the scenario instructions you have received.
> - Never make up or hallucinate information not provided in the scenario instructions. Information that is not provided in the scenario instructions should be considered unknown or unavailable.
> - **Avoid repeating the exact instructions verbatim. Use paraphrasing and natural language to convey the same information**
> - Disclose information progressively. Wait for the agent to ask for specific information before providing it.

The paraphrase rule is the notable one Ledgerline lacks: without it the simulator reads the hidden-facts block back verbatim, which makes the agent's extraction job artificially easy *and* makes the `numbers_traceable` check trivially pass.

### 1.3 The **voice** simulated-user prompt — `simulation_guidelines_voice.md`

This is the most directly transferable artefact in the whole survey; Ledgerline is a voice product whose harness is text-only, and this prompt is how τ² closes that gap without audio. Highlights:

- *"You are SPEAKING on a phone call, not typing messages."* Disfluencies (`um`, `uh`, `you know`, `I mean`), restarts, `[pause]` and em-dash markers.
- **Number and identifier speaking rules** — directly relevant to Ledgerline's STT-numeral risk:
  > When speaking numbers or spelling out letters, ALWAYS separate them with comma and space:
  > - Numbers: "one, two, three" NOT "one two three"
  > - Mixed: "A, B, one, two, three" NOT "AB123"
- **Hard grounding rule**, stronger than the text version:
  > **You only know what is explicitly stated in the scenario instructions.** If a piece of information is not provided, you do not know it — even if it is something a real person would typically know about themselves (e.g., zip code, address, order ID…). When asked, say you don't know or don't remember.
- **Anti-premature-termination rule** (Ledgerline's `ends_when` is a soft natural-language condition and has the same failure mode):
  > **Do not end the conversation prematurely.** Agreeing to an action is not the same as the action being completed. […] wait for the agent to confirm it is done before ending the conversation.
  > **Before ending the conversation, verify that ALL items in your scenario instructions have been addressed.**
- **Make the agent work for information** — an explicit adversarial disclosure ladder:
  > "It's not working" → (agent asks what's not working) → "The app" → (agent asks which app) → "Your mobile app"
- **Silence handling**, which is a scripted disruption Ledgerline does not have: after an extended agent silence, check in at most twice (*"Hello? Are you still there?"*, and **do not volunteer new information during a check-in**), then end the call frustrated.

### 1.4 Deterministic scoring vs judge — `reward_basis` (`docs/evaluation.md`)

τ² splits scoring into five independent `RewardType`s, and **the final reward is the product** of only those listed in a task's `reward_basis`:

| `RewardType` | Evaluator | What it checks |
|---|---|---|
| `DB` | `EnvironmentEvaluator` | predicted DB **hash** == target DB hash (target = fresh env + replay of the reference `actions`) |
| `ENV_ASSERTION` | `EnvironmentEvaluator` | per-task assertions on the final environment |
| `COMMUNICATE` | `CommunicateEvaluator` | every string in `communicate_info` appears in the agent's messages (substring) |
| `NL_ASSERTION` | `NLAssertionsEvaluator` | an LLM judge returns true for every natural-language assertion (marked WIP) |
| `ACTION` | `ActionEvaluator` | every reference action has a matching tool call (`Action.compare_with_tool_call`) |

Three lessons:

1. **Score on end state, not on trajectory.** The default basis for airline/retail/telecom is `["DB","COMMUNICATE"]`. The doc is emphatic: `actions` is *one* reference trajectory, replayed only to derive the target end state; *"any sequence of tool calls that produces an equivalent DB end state passes."* For Ledgerline that maps to: assert on **final `FinancialState` + final plan**, not on which order `record_income`/`record_expense` fired.
2. **`ACTION` matching is an escape hatch, used ~9 of ~100 tasks**, because putting it in `reward_basis` *"promotes `actions` from 'one reference trajectory' to 'the only acceptable trajectory'"*. Ledgerline's scenario `expect.tool_calls: {correct_field: {min: 1}}` is the right shape — a minimum count, not an ordered script.
3. **Run the strict evaluators as diagnostics even when they don't gate.** `partial_action_reward` reports `m/n` matched reference actions, broken down by `ToolType.READ` vs `ToolType.WRITE`, and is surfaced in `tau2 view`. The doc warns it is *"a similarity signal against one reference trajectory, not a correctness verdict — an agent can score 0/n … and still be fully correct."* A read/write split is the useful bit: it catches "DB-passes-but-no-write-was-attempted".

### 1.5 pass^k — `src/tau2/metrics/agent_metrics.py`

```python
def pass_hat_k(num_trials: int, success_count: int, k: int) -> float:
    """Compute the pass^k metric ... from https://arxiv.org/pdf/2406.12045"""
    if num_trials < k:
        raise ValueError(f"Number of trials {num_trials} is less than k {k}.")
    return math.comb(success_count, k) / math.comb(num_trials, k)
```

pass^k is the probability that **all** of k randomly drawn trials succeed — a *reliability* metric, the opposite of pass@k (probability at least one of k succeeds). For a money agent that must be right every call, pass^k is the honest number and pass@k is actively misleading. With Ledgerline's N=5: `pass^1 = c/5`, `pass^5 = 1` only if all five passed. Reporting `pass^1` and `pass^5` side by side costs nothing and communicates variance without pretending to a confidence interval N=5 cannot support.

Two details worth copying: `is_successful()` uses `(1-1e-6) <= reward <= (1+1e-6)` rather than `== 1.0`, and `get_metrics_df` **excludes `TerminationReason.INFRASTRUCTURE_ERROR` simulations from metrics** and warns — a run that never happened must not count as a failure. Ledgerline's runner currently has no distinction between "agent failed" and "OpenAI 500'd".

### 1.6 The judge — `src/tau2/evaluator/review_llm_judge.py`

The most sophisticated judge rubric found. It judges **both participants** (agent *and* user simulator), which is how τ² detects that a "failure" was really the simulator going off-script. Structure:

- **Fixed error-tag vocabulary** (closed set, so tags are countable across runs): `hallucination`, `incorrect_interpretation`, `guideline_violation`, `revealed_info_early`, `inconsistent_behavior`, `tool_call_schema_error`, `tool_call_argument_error`, `irrelevant_tool_call`, `premature_termination`, `missed_required_action`, `wrong_sequence`, `other`.
- **Asymmetric severity scales.** Agent: `critical` | `minor`. User: `critical_helped` | `critical_hindered` | `minor` — a simulator error that made the task *too easy* is as much a finding as one that made it impossible.
- **Per-turn, evidence-bearing JSON output** with `turn_idx`, `reasoning`, and `correct_behavior` (what should have happened instead) — not a score:

```json
{"errors": [{"source": "user"|"agent", "error_tags": ["<tag>"], "severity": "...",
             "turn_idx": 3, "reasoning": "...", "correct_behavior": "..."}],
 "summary": "..."}
```

- **Anti-bias instructions baked into the rubric**, worth quoting verbatim:
  > **Do not blame the user for agent failures**: If the agent is unresponsive, repeatedly fails, or makes critical errors, the user giving up … is a reasonable reaction — not a user error.
  > **Fact-check every user claim**: For every factual detail the user provides … verify it appears in or is derivable from the `<User Instructions>`. Any detail not grounded in the instructions is a hallucination — even if it sounds plausible.
- Inputs are named XML-ish sections: `<Policy>`, `<Simulation Guidelines>`, `<User Instructions>`, `<Example Action Trajectory>`, `<Natural Language Assertions>`, `<Conversation>` — and the example trajectory is explicitly hedged in-prompt (*"Other valid approaches may exist, and this example trajectory may include extraneous actions"*) so the judge does not treat it as a checklist.
- A **separate full-duplex prompt** (`FULL_DUPLEX_SYSTEM_PROMPT`) adds turn-taking and interruption-behaviour errors on top of content errors — the voice-specific judge Ledgerline would need if it ever judged audio runs.
- Sibling files: `review_llm_judge_user_only.py` (cheap simulator-sanity pass), `hallucination_reviewer.py` (dedicated ungrounded-claim detector — the direct analogue of Ledgerline's `numbers_traceable`), `auth_classifier.py`.

Metrics roll the judge output up into countable aggregates rather than a mean score: `agent_errors_by_severity`, `agent_error_tags_by_severity`, `sims_by_max_agent_severity`, and `sims_by_first_critical_source` (`"agent"`/`"user"`/`"none"` — *who broke it first*).

### 1.7 The policy-vs-keyword lesson

τ² never uses a banned-substring list. Compliance is expressed as (a) a **policy document** given to both the agent and the judge, (b) environment/DB assertions for anything with a side effect, and (c) `nl_assertions` — one-sentence natural-language claims judged by an LLM, e.g. airline task `1`:

```json
"nl_assertions": ["Agent should not approve the cancellation."]
```

That is an *intent* statement. The equivalent for Ledgerline's reviewer finding is `"The assistant must not recommend taking on any new credit."` — which is satisfied by *"your personal loan is due on the twentieth"* and violated by *"you could take a small personal loan to bridge this"*, whereas a substring ban on `"personal loan"` gets both backwards. Note also that τ² runs `nl_assertions` as a **diagnostic** when not in `reward_basis` — judged intent checks report, deterministic checks gate.

---

## 2. Pipecat Evals — `pipecat-ai/pipecat`, `src/pipecat/evals/`

- Repo: https://github.com/pipecat-ai/pipecat — **15,439 stars**, BSD-2, last push **2026-09-11**.
- Module: https://github.com/pipecat-ai/pipecat/tree/main/src/pipecat/evals — 28 files, ~300 KB. First-party, and our own framework, so it is the cheapest integration layer available.

**Correction to `docs/research/11-testing-evals.md`.** That note says Pipecat Evals "cannot inject hidden facts or mid-conversation corrections" and that scenarios are scripted only. The module now has a **full simulation mode** — `persona.py`, `simulation.py`, `simulation_driver.py`, `simulation_session.py` (~48 KB together) — alongside the scripted mode (`script.py`, `script_driver.py`). The gap is narrower than recorded: the persona is a free-text description plus a goal, so hidden facts can go in the description; what is still missing is turn-indexed scripted disruptions (Ledgerline's `scripted_behaviours: [{turn: 4, say: ...}]`) and a structured hidden-facts block to diff the final state against. The decision to keep our own harness stands, but the reason should be restated accurately.

### 2.1 The persona / simulated caller — `evals/persona.py`

The whole instruction template, worth reading against ours:

```python
_INSTRUCTION_TEMPLATE = """\
You are playing a person on a phone call with a voice assistant. Stay in \
character throughout; never mention being simulated, a test, or an AI.

Who you are: {persona}

What you want from this call: {goal}

The assistant's words arrive as the user's messages. Reply with only what you \
would say next: one short spoken turn, in the first person, in plain sentences \
(no lists, markdown, or stage directions). Ask for or give one thing at a time, \
as a real caller would, and do not repeat what the assistant has already \
understood. When your goal is achieved, or it is clear the assistant cannot \
help, say nothing more and call the {end_call} tool with whether you succeeded \
and why."""
```

Three ideas Ledgerline should take:

1. **Termination is a tool call, not a sentinel string.** `end_call(success: bool, reason: str)` — structured, impossible to emit by accident mid-sentence, and it yields a machine-readable reason for every run. Compare Ledgerline's `[END]` string sentinel in `evals/sim_user.py`, which a chatty model can emit inside a farewell.
2. **The persona's own verdict is explicitly untrusted.** From the module docstring: *"its `success` claim is its own view, and the judge decides the outcome."* Record it as a signal, never as the pass/fail.
3. **The persona hears whole turns, not fragments.** `EvalPersona.hear()` holds any bot response emitted *while a function call is still running* and joins it with the response after the call:

   > A response the bot gives while one of its function calls is still running is held and joined with the response after the call, so the persona answers the bot's whole turn rather than its "let me check".

   Ledgerline's harness has exactly this shape (`build_plan` is slow and the agent speaks a filler first) and must not let the simulated user answer the filler.

### 2.2 The judge — `evals/judge.py` (21 KB, two rubrics)

**Per-turn judge** (`JUDGE_SYSTEM_INSTRUCTION`) — three-valued, not binary, and this is the key insight:

> Respond ONLY with a JSON object on a single line containing two fields: `{"verdict": "yes" | "no" | "continue", "reason": "<one short sentence>"}`.
> Use `"continue"` if the bot has not given its answer yet: it says it is checking, looking something up, fetching, working on something, or that it will report back. […] This holds however long and however fluent the reply is: "The system is checking the current conditions for you right now." is waiting, not answering. A greeting or an obviously incomplete fragment is also `"continue"`.
> Use `"no"` **only** when the bot has given its answer and that answer fails the criterion. If the bot has not answered yet, always use `"continue"`, never `"no"`.

A two-valued judge scores filler turns as failures; that is a large, systematic, purely artefactual false-failure rate for any voice agent that stalls while a tool runs. Ledgerline's agent does exactly this around `build_plan`.

**STT-tolerance clause** — directly addresses judging transcribed speech, and generalises to Ledgerline's numeral problem:

> When the bot spoke its reply, the 'assistant' text is an automatic speech-to-text transcription, so it may contain homophones, misspellings, split or merged words, and missing punctuation. Always judge it by the intended spoken meaning, never by its exact spelling. In particular, treat a number as the same value whether it is spelled out, written as a digit, or transcribed as a homophone: 'for' and 'fore' mean 'four' (4), and 'to' and 'too' mean 'two' (2). Never answer 'no' solely because of a transcription error when the intended spoken meaning satisfies the criterion.

**Whole-run judge** (`RUN_JUDGE_SYSTEM_INSTRUCTION`) — one call grades every turn against every criterion plus an overall goal, and it contains the single most useful sentence in this survey for Ledgerline's banned-phrase problem:

> A criterion that forbids something ('never ...', 'does not ...') or that applies only in a situation ('when ...', 'if ...') is satisfied by a reply that does not do the forbidden thing or is not in that situation; **do not fault a reply for something the criterion does not ask of it.**

Also note: *"a line marked '[tool call]' is a function the bot called at that point, and a completed call is stronger evidence of an action (a booking, a lookup) than the bot saying it did it."* — tool calls are interleaved into the transcript the judge sees, and the judge is told to weight them above the agent's own narration. That is the judge-side version of Ledgerline's "claims to have acted" rule.

Output shape for the whole-run judge, with one array entry per bot turn so turns and verdicts cannot drift out of alignment:

```json
{"goal":   {"verdict": "yes"|"no", "reason": "..."},
 "turns":  {"<criterion name>": ["yes"|"no", ...]},
 "reasons":{"<criterion name>": {"<bot turn number>": "..."}}}
```

**Verdict caching:** *"Verdicts are cached by criterion and conversation, so re-runs are stable and a scenario never pays twice for the same question."* Cache key = hash(criterion, conversation). Cheaper and simpler than cassetting the whole judge call.

Default judge service is local **Ollama `gemma4:12b`** (`scenario_config.py`: `_DEFAULT_JUDGE = {"service": "ollama", "model": DEFAULT_OLLAMA_JUDGE_MODEL, …}`) — i.e. Pipecat's own default is a *free, different-vendor, small* judge. A `factory:<path>` escape hatch points it at any service.

### 2.3 Scenario config — modality is a per-side switch

`scenario_config.py` parses two blocks. `user:` decides how the user's turns reach the bot (`modality: text|audio`, plus a `speech:` TTS block); `judge:` decides how the bot's reply is judged (`modality: text|audio`, plus a `transcription:` STT block when audio, plus `eval:` naming the judge LLM). The useful property: **user modality and judge modality are independent**, so a run can send text but judge a *transcription of the bot's synthesized speech* — catching markdown-in-TTS and digit-salad without a human in the loop. Ledgerline's number-robustness worry is currently parked in a manual checklist; this is the cheap automated version of half of it.

### 2.4 Tool-call matching — `evals/matcher.py`

> Expected events must appear in order, with unmatched events allowed in between. A reply with a content check aggregates its segments and re-checks on each, so an interim "Let me check" is rolled past rather than taken for the answer. **A turn's function calls match by name in any order.**

So: ordered across turns, **order-insensitive within a turn**, extra unexpected events tolerated, and unmatched `function_call` events are buffered in `_pending_function_calls` and reset per turn. There is an inverted `absent:` check for "this must not happen". And `JUDGE_NO_GRACE_S = 2.0` — a judge "no" waits two seconds for more of the reply before being recorded, *"the transcription of its last sentence lands after the stop"*. All four behaviours are the difference between a flaky assertion and a stable one.

---

## 3. LiveKit Agents — testing framework and simulations

- Repo: https://github.com/livekit/agents — **14,138 stars**, Apache-2.0, last push **2026-09-11**.
- Docs: https://docs.livekit.io/agents/build/testing/
- Source: `livekit-agents/livekit/agents/voice/run_result.py` (1,234 lines) — `RunResult`, `RunAssert`, `EventAssert`, `mock_tools`.

Not our stack, but the closest thing to a *pytest-native* assertion DSL for agent turns, and it independently confirms the text-first decision: *"text mode is the most cost-effective and deterministic way to test agent behavior."* The docs split the two layers explicitly — the test framework for *"turn-level behaviors such as tool usage and error handling"*, simulations for *"behaviors that span multiple turns"*. Test areas named: expected behavior, tool usage, error handling, **factual grounding**, and **misuse resistance**.

### 3.1 The assertion DSL

```python
result = await session.run(user_input="Hello")
result.expect.next_event().is_message(role="assistant").judge(
    llm, intent="Makes a friendly introduction and offers assistance."
)
result.expect.no_more_events()
```

Event types are `ChatMessageEvent`, `FunctionCallEvent`, `FunctionCallOutputEvent`, `AgentHandoffEvent`. Two complementary matching styles, which is the design worth stealing:

- **Ordered/strict**: `next_event(type=...)`, `skip_next(count)`, `skip_next_event_if(...)`, `no_more_events()` — for the turns you care about exactly.
- **Order-insensitive over a range**: `RunAssert.__getitem__` accepts a slice returning an `EventRangeAssert` with `contains_function_call(...)`, `contains_message(...)`, `contains_function_call_output(...)`. `result.expect[2:6].contains_function_call(name="record_expense")` says "somewhere in these turns", which is the right strength for an LLM agent.

**Argument matching is a subset match, not equality** — exactly the property Ledgerline's `expect.tool_calls` needs:

```python
if is_given(arguments):
    actual = json.loads(self._event.item.arguments)
    for key, value in arguments.items():
        if key not in actual or actual[key] != value:
            self._raise(f"For key '{key}', expected {value}, got {actual.get(key)}")
```

Only the named keys are checked; extra arguments the model volunteered are ignored. Asserting full-dict equality on tool arguments is the classic brittle-test anti-pattern here.

### 3.2 The judge: structured output via a forced tool call

`ChatMessageAssert.judge(llm, *, intent: str)` — the whole rubric is one system message plus a required function call:

```python
"You are a test evaluator for conversational agents.\n"
"You will be shown a message and a target intent. Determine whether the message accomplishes the intent.\n"
"Only respond by calling the `check_intent(success: bool, reason: str)` function with your final judgment.\n"
"Be strict: if the message does not clearly fulfill the intent, return `success = False` and explain why."
```

Details worth copying:

- **`tool_choice="required"` on a `check_intent(success: bool, reason: str)` tool** rather than "reply with JSON". No parsing, no markdown fences, and the model must commit to a boolean. Strictly better than Ledgerline's current free-JSON judge output.
- **`temperature=0.0`, with a model exclusion list**: `excluded_models_temperature = ["gpt-5"]` — the same GPT-5-family temperature restriction our own research doc flagged, handled in library code as a name-substring skip. Copy the pattern rather than assuming temperature is settable.
- **Judging is instrumented as a span** (`ATTR_GEN_AI_OPERATION_NAME = "judge"`, intent + message recorded as tool args, usage captured) — judge cost and judge inputs are traced like any other model call.
- **"Be strict"** plus a required `reason` is the whole calibration method. It is much thinner than τ²'s rubric; it works because the unit judged is one message against one intent.

### 3.3 `mock_tools` — cheap CI without mocking the LLM

```python
with mock_tools(MyAgentClass, {"tool_name": mock_fn}):
    ...
```

> Mocks intercept tool *execution* only; **the LLM keeps seeing the real tool schemas.** A mock may declare any subset of the real tool's parameters (extra arguments are dropped when it is invoked).

This is the right seam. The model still has to decide *which* tool and *what* arguments — the part under test — while the slow/expensive/stateful side effect is swapped out. Also available with `session=` for session-lifetime mocks, `{}` to clear, and context-manager mocks take precedence over session mocks.

### 3.4 Structured-output retry

`RunOutputOptions(max_retries, retry_instructions)`, with the default nudge:

```python
_OUTPUT_RETRY_PROMPT = (
    "You have not provided the final output yet. Call the appropriate function "
    "to do so; a plain text response alone is not enough."
)
```

A bounded retry when a run ends without its `output_type` — relevant to Ledgerline's "agent explained a plan in prose but never called `build_plan`" failure mode, which is currently scored as a hard fail rather than nudged once.

---

## 4. DeepEval — `ConversationSimulator`

- Repo: https://github.com/confident-ai/deepeval (Apache-2.0). Docs: https://deepeval.com/docs/conversation-simulator
- `ConversationalGolden` fields: `scenario` (what the simulated user is attempting), `expected_outcome`, `persona` (`Persona(characteristics="...")`), and optional seed `turns`. The simulator uses *"scenario, persona, and expected_outcome"* to *"role-play the user and generate each next user message."*
- `ConversationSimulator(model_callback=..., async_mode=True, stopping_controller=...)`; `simulate(conversational_goldens, max_user_simulations=10)`.

**The borrowable idea is the three-way termination**: a simulation ends when *"`max_user_simulations` is reached, when the `stopping_controller` decides the conversation should end, or when the `simulation_graph` reaches a `terminal=True` node"* — whichever fires first. A **programmatic `stopping_controller`** is strictly better than Ledgerline's natural-language `ends_when:`: for us the stop condition is mechanical (`build_plan` returned and the user has acknowledged), so a Python predicate over the run state should decide it, with `max_turns` as the backstop and the LLM never consulted.

The separation of `scenario` (intent) from `expected_outcome` (success definition) from `persona` (manner) is also cleaner than folding all three into one persona blob, which is what our `description` field currently does.

Caveat: conversational metrics (`TurnRelevancyMetric`, role adherence, knowledge retention, completeness) are generic dialogue qualities. None of them is "every number traceable to a tool result", which is the metric that actually matters for a money agent. Confirms the standing decision to not adopt DeepEval, while borrowing its golden schema.

---

## 5. promptfoo — `promptfoo:simulated-user`

- Repo: https://github.com/promptfoo/promptfoo (MIT). Docs: https://www.promptfoo.dev/docs/providers/simulated-user/

```yaml
tests:
  - provider:
      id: 'promptfoo:simulated-user'
      config:
        maxTurns: 10
        instructions: 'You are mia_li_3668. You want to fly from New York to Seattle on May 20...'
    assert:
      - type: llm-rubric
        value: |
          Did the budget traveler get what they wanted?
          Pass if: Got economy flight under $350...
```

Two things to note. First, the persona is **plain prose in one `instructions` string** — the same τ-bench task style — so the whole persona/hidden-facts structure is a convention, not a framework requirement. Second, termination: *"Agent includes `###STOP###` anywhere in response"* — here it is the **agent**, not the user, that can end the run, plus `maxTurns` and errors. Same sentinel convention as τ²; three independent projects converging on a `###TOKEN###` sentinel is a strong signal for the shape, though Pipecat's `end_call` tool is the more robust version of it.

The `llm-rubric` assertion style — a question followed by an explicit *"Pass if:"* clause — is a good, cheap rubric template: it gives the judge the decision boundary rather than an adjective.

---

## 6. LangChain `openevals` / `agentevals` — trajectory matching and the multi-turn simulator

- `openevals`: https://github.com/langchain-ai/openevals — **1,193 stars**, MIT, last push **2026-09-11**.
- `agentevals`: https://github.com/langchain-ai/agentevals — **720 stars**, MIT.

### 6.1 Trajectory match modes (`agentevals`)

`create_trajectory_match_evaluator(trajectory_match_mode=...)` with four modes, and this taxonomy is the clearest statement of "how strictly should tool calls be checked":

| Mode | Semantics | When it is right |
|---|---|---|
| `strict` | same messages, same order, same tool calls (content may differ) | a fixed protocol |
| `unordered` | same set of tool calls, any order | order genuinely doesn't matter |
| `superset` | the key tools were called; extras are fine | **"did it do the required work?"** |
| `subset` | no tool calls beyond the expected set | **"did it do anything it shouldn't?"** |

Plus `tool_args_match_mode` (`"exact" | "ignore" | "subset" | "superset"`) and per-tool `tool_args_match_overrides` for custom matchers.

For Ledgerline the useful realisation is that `superset` and `subset` answer **different questions and should be separate assertions**: a `superset` check that `record_income`/`record_expense`/`build_plan` all fired, and a `subset` check that nothing outside the allowed tool set was called. A single `strict` list would fail on every harmless re-read. Argument matching wants `subset` per tool (assert `amount`, ignore whatever `note` the model invented) — the same conclusion LiveKit's `is_function_call(arguments=...)` reaches in code.

`trajectory_llm_as_judge` ships two preset rubrics, `TRAJECTORY_ACCURACY_PROMPT` and `TRAJECTORY_ACCURACY_PROMPT_WITH_REFERENCE` (reference-free and reference-based), with `continuous` (float vs boolean), `choices` (discrete score set), and `few_shot_examples`.

### 6.2 The multi-turn simulator (`openevals/simulators/`)

`run_multiturn_simulation(app=..., user=..., max_turns=..., thread_id=..., stopping_condition=..., trajectory_evaluators=[...])`, with `create_llm_simulated_user(system=..., model=..., fixed_responses=[...])`.

Two designs worth taking:

1. **`fixed_responses` — scripted turns and a generative persona in one object.** From the docstring:

   > `fixed_responses`: Optional list of fixed responses to use for the simulated user. **If the number of turns exceeds the number of fixed responses, the simulated user will generate a response using the specified LLM.**

   ```python
   if fixed_responses and turn_counter < len(fixed_responses):
       res = fixed_responses[turn_counter]
       ...
   ```

   This is a *prefix* override (turns 0..n-1 fixed, then generative). Ledgerline's `scripted_behaviours: [{turn: 4, say: ...}]` is a *sparse index* override, which is strictly more expressive for our case — the correction has to land *after* the agent has already recorded the wrong figure, so it cannot be a prefix. Ours is the better design here; the thing to borrow is the explicit error when the script runs out (`openevals`' static simulator raises *"Number of conversation turns is greater than the number of static user responses"* rather than silently continuing).

2. **Role inversion is handled by the framework, not the prompt:**

   > The simulator automatically converts message roles to maintain proper conversation flow: User messages become assistant messages when sent to the LLM; Assistant messages (without tool calls) become user messages when sent to the LLM.

   And `_is_internal_message()` filters out anything with `tool_calls` or a non-user/assistant role, so **the simulated user never sees the agent's tool calls or tool results** — only its spoken text. Ledgerline must hold this line: if the simulated user can see `build_plan`'s output, the hidden-facts extraction test is void. (Our `sim_user.py` appends only `agent_text`, which is correct — worth an explicit test so it stays that way.)

3. **`stopping_condition`** is a callback over the trajectory, alongside `max_turns` — same conclusion as DeepEval's `stopping_controller`.

---

## 7. Inspect AI (UK AI Security Institute) — model-graded scorers, epochs, reducers

- Repo: https://github.com/UKGovernmentBEIS/inspect_ai — MIT. Source read: `src/inspect_ai/scorer/_model.py`.
- Docs: https://inspect.aisi.org.uk/scorers.html, https://inspect.aisi.org.uk/model-graded.html

### 7.1 The default grading template

```
You are assessing a submitted answer on a given task based on a criterion. Here is the data:

[BEGIN DATA]
***
[Task]: {question}
***
[Submission]: {answer}
***
[Criterion]: {criterion}
***
[END DATA]

Does the submission meet the criterion?

{instructions}
```

and the default instructions (with `partial_credit=False`):

> After assessing the submitted answer, reply with 'GRADE: $LETTER' (without quotes) where LETTER is one of CI. Please choose ONE option for the grade: either "C" for correct answers, or "I" for incorrect answers.
> […] **First, write out in a step by step manner your reasoning about the criterion to be sure that your conclusion is correct. Avoid simply stating the correct answers at the outset.** Then, end with your answer formatted as 'GRADE: $LETTER'.

Three transferable details:

- **Delimited data sections** (`[BEGIN DATA] *** [Task] *** [Submission] *** [Criterion] *** [END DATA]`) so submission text cannot be confused with instructions — a prompt-injection guard as much as a formatting one.
- **Reasoning before the verdict, and an explicit "avoid stating the answer at the outset."** Ledgerline's judge currently emits a verdict field first; JSON field order means the verdict is generated *before* the evidence, which is reasoning-after-the-fact.
- **Grade extraction is a deliberately hardened regex**, and the docstring explains exactly which failure modes it defends against:

```python
DEFAULT_GRADE_PATTERN = (
    rf"(?is).*(?<!\w)GRADE(?!\w){_GRADE_SPACING}:{_GRADE_SPACING}([CPI])"
)
```
> The leading greedy `.*` (with DOTALL) ensures `re.search` binds to the **last** `GRADE: X` in the grader output — the instructions tell the grader to end with the grade, so earlier mentions (e.g. echoed in chain-of-thought **or injected via the submission**) must not win. The `GRADE` token is bounded so ordinary prose like `downgrade:` cannot be mistaken for a verdict.

`_GRADE_SPACING` additionally absorbs zero-width and bidi marks (`​`–`﻿`) around the separator. If we parse a judge verdict out of text at all, this is the regex to copy; better still, use a forced tool call as LiveKit does and skip parsing.

### 7.2 Majority vote and reducers

`model_graded_qa(model=[...])` accepts a **list of grader models and grades by majority vote** via `multi_scorer(graders, reducer)`; a `model_role` bound to a list fans out the same way at scoring time. Reducers (`mean`, `median`, `mode`, `max`, `at_least(k)`) also serve **epochs** — Inspect's name for running each sample N times and reducing. `at_least(k)` over epochs is the direct analogue of "k of 5 runs must pass", and `mode` over graders is majority-vote-of-judges. Our research doc's "majority-of-3 on flaky criteria" is exactly `multi_scorer(..., reducer=mode)`; worth naming it that way in the report so the method is recognisable.

Also `partial_credit: bool` adding a `P` grade — useful for a criterion like "explained the shortfall in plain words", where binary is genuinely lossy. Note this cuts against the Hamel-Husain binary-judge rule already recorded in `11-testing-evals.md`; the resolution is: binary for gating criteria, partial credit only for reported-but-non-gating quality criteria.

---

## 8. Record/replay for free CI: VCR.py, pytest-recording, respx

- VCR.py — https://github.com/kevin1024/vcrpy (MIT). pytest-recording — https://github.com/kiwicom/pytest-recording (MIT). respx — https://github.com/lundberg/respx (BSD).
- pytest-recording adds `--record-mode={none,once,new_episodes,all,rewrite}` and `--block-network`, plus a `@pytest.mark.vcr` marker; cassettes are YAML next to the test.

The pattern for an OpenAI harness:

```python
@pytest.mark.vcr(
    filter_headers=["authorization", "openai-organization"],
    match_on=["method", "scheme", "host", "port", "path", "body"],
)
def test_scenario_replays(): ...
```

- **`--record-mode=none` + `--block-network` in CI** is the enforcement: a cassette miss becomes a hard error rather than a silent live call. This is what Ledgerline's `EVAL_MODE=replay` must compile down to.
- **`filter_headers` must include `authorization`** or the API key is committed with the cassette.
- **`match_on` must include `body`** for LLM calls — every turn hits the same URL and method, so default matching collapses distinct turns onto one cassette entry.
- **Streaming is the known caveat.** SSE bodies replay as one blob; token-by-token timing is not reproduced. For a harness that only needs the final message and tool calls this is fine; it means cassettes cannot be used to test time-to-first-token or interruption behaviour.
- `respx` is the lighter alternative when the point is *"assert the request we sent"* rather than *"replay a real response"*.

Ledgerline already has `evals/cassettes/` (empty) and the research doc's hash-keyed JSON cache. The hash-keyed cache is simpler and avoids VCR's matching pitfalls entirely; the one thing to take from VCR is the **record-mode vocabulary** (`none` / `once` / `all` / `rewrite`) and the fail-loudly-on-miss default, rather than the library.

---

## 9. Others, briefly

- **Rasa test stories** (https://rasa.com/docs/rasa/testing-your-assistant/, https://github.com/RasaHQ/rasa, Apache-2.0) — end-to-end test stories in markdown/YAML: each user turn annotated with its expected intent and entities, each bot turn with its expected action; `rasa test` reports per-intent and per-entity confusion matrices and writes `failed_test_stories.yml` — a **machine-readable file of exactly the failures, replayable as the next regression suite**. The general idea (a failing run is emitted as a new test fixture, not a log line) is what Ledgerline's `scripts/session_to_fixture.py` should do.
- **Botium** (https://github.com/codeforequity-at/botium-core, MIT) — the original "Selenium for chatbots": `.convo.txt` convo files with `#me` / `#bot` turns and assertion logic, plus paraphrase-based utterance expansion to test robustness to rewording. Mostly of historical interest, but the convo-file format is a good reminder that a scenario file should be readable aloud.
- **VoiceBench** (https://github.com/MatthewCYM/VoiceBench) — benchmark for *voice* LLM assistants (speech input), evaluating robustness to accent, environmental noise, and content perturbations. Relevant as the published justification for the claim that "STT is the most likely production failure surface", which `11-testing-evals.md` §6 currently asserts without a citation.
- **Deepgram / AssemblyAI number formatting** — Deepgram's `smart_format`/`numerals` and AssemblyAI's inverse text normalization both mangle spoken quantities in documented ways (e.g. the Deepgram discussion where *"a hundred and ten percent"* transcribed as *"a 10%"*, https://github.com/orgs/deepgram/discussions/1168). The prior-art lesson is that **the STT's formatted output, not the audio, is the correct fixture**: store the literal transcript string ("rent is 42 100") as the user turn and test the agent's handling of it. No audio, no cost, full determinism.
- **Coval / Hamming / Cekura / Bluejay** — commercial voice-agent simulation SaaS, named as partners in LiveKit's own testing docs. Closed; no borrowable code. Their existence is the argument that simulated-user + judge is the industry-standard shape, not that we should buy one.
- **G-Eval** (https://github.com/nlpyang/geval) — form-filling chain-of-thought judging, with scores weighted by output token probability to break the "everything is a 3" clustering. **Prometheus 2** (https://github.com/prometheus-eval/prometheus-eval, Apache-2.0) — open judge models trained on fine-grained rubrics, with the key convention that a rubric supplies a **descriptor per score point** (what a 1 looks like, what a 5 looks like), not just a scale. If Ledgerline ever needs a non-binary criterion, per-point descriptors are the minimum for it to mean anything.

---

## Simulated user designs compared

| | τ²-bench | Pipecat Evals | openevals | DeepEval | promptfoo | **Ledgerline today** |
|---|---|---|---|---|---|---|
| Persona shape | 3 layers: global guidelines MD + task persona + runtime `PersonaConfig` | free-text `description` + `goal` | one `system` string | `scenario` + `persona` + `expected_outcome` | one `instructions` string | YAML `description` + structured `hidden_facts` |
| Hidden facts | scenario text; "you only know what is stated" | inside the description | inside the system prompt | inside the scenario | inside the instructions | **structured YAML block, rendered to speakable lines** |
| Progressive disclosure | explicit rule + a worked disclosure ladder | "one thing at a time" | prompt-dependent | prompt-dependent | prompt-dependent | "answer only what was just asked" |
| Anti-paraphrase / anti-verbatim | **explicit rule** | implicit | none | none | none | **missing** |
| Scripted disruptions | none built in | none | `fixed_responses` **prefix** only | seed `turns` | none | **sparse per-turn `{turn, say}` — most expressive** |
| Voice realism | **dedicated voice guidelines MD** (disfluencies, spelled numbers, silence handling) | "one short spoken turn, no markdown" | none | none | none | "the way someone says numbers out loud" |
| Termination | `###STOP###` / `###TRANSFER###` / `###OUT-OF-SCOPE###` sentinels + max steps | **`end_call(success, reason)` tool call** | `stopping_condition` callback + `max_turns` | `stopping_controller` + `max_user_simulations` + terminal graph node | `###STOP###` from the **agent** + `maxTurns` | `[END]` string + `max_turns` |
| Sees agent's tool calls? | no | no (hears joined response text) | **no — filtered in code** | no | no | no (correct) |
| Self-reported success | n/a | yes, explicitly untrusted | n/a | n/a | n/a | none |

Read across the row: Ledgerline's scripted-disruption model and structured hidden facts are the best of the set; its termination and voice realism are the weakest.

---

## Judge rubrics worth borrowing

Concrete text, ready to adapt. Ordered by value to Ledgerline.

**(a) The three-valued verdict — Pipecat, `evals/judge.py`.** Adopt verbatim in spirit:

> Use `"continue"` if the bot has not given its answer yet: it says it is checking, looking something up, fetching, working on something, or that it will report back. The answer is still coming, so there is nothing to judge yet. […] Use `"no"` **only** when the bot has given its answer and that answer fails the criterion. If the bot has not answered yet, always use `"continue"`, never `"no"`.

**(b) The negative/conditional-criterion clause — Pipecat, `RUN_JUDGE_SYSTEM_INSTRUCTION`.** This is the fix for judging intent-level policy criteria:

> A criterion that forbids something ('never ...', 'does not ...') or that applies only in a situation ('when ...', 'if ...') is satisfied by a reply that does not do the forbidden thing or is not in that situation; do not fault a reply for something the criterion does not ask of it.

**(c) Tool calls outrank narration — Pipecat.**

> A line marked '[tool call]' is a function the bot called at that point, and a completed call is stronger evidence of an action (a booking, a lookup) than the bot saying it did it.

**(d) Transcription tolerance — Pipecat.** Keep even in a text harness, because the *scenario* text imitates STT output:

> Always judge it by the intended spoken meaning, never by its exact spelling. In particular, treat a number as the same value whether it is spelled out, written as a digit, or transcribed as a homophone. Never answer 'no' solely because of a transcription error when the intended spoken meaning satisfies the criterion.

**(e) Fact-check the simulated user too — τ², `review_llm_judge.py`.** Cheap insurance that a red run is a real failure:

> **Fact-check every user claim**: For every factual detail the user provides […] verify it appears in or is derivable from the `<User Instructions>`. Any detail not grounded in the instructions is a hallucination — even if it sounds plausible. When the user lacks information, the correct behavior is to say "I don't know" or ask the agent.
> **Do not blame the user for agent failures**: If the agent is unresponsive, repeatedly fails, or makes critical errors, the user giving up or ending the conversation is a reasonable reaction — not a user error.

Paired with the asymmetric severity scale: agent `critical | minor`; user `critical_helped | critical_hindered | minor`.

**(f) Delimited data + reasoning-before-verdict — Inspect AI.**

> `[BEGIN DATA] *** [Task]: {question} *** [Submission]: {answer} *** [Criterion]: {criterion} *** [END DATA]` … First, write out in a step by step manner your reasoning about the criterion to be sure that your conclusion is correct. Avoid simply stating the correct answers at the outset.

**(g) Strictness instruction + forced tool call — LiveKit.**

> "You are a test evaluator for conversational agents. You will be shown a message and a target intent. Determine whether the message accomplishes the intent. Only respond by calling the `check_intent(success: bool, reason: str)` function with your final judgment. **Be strict: if the message does not clearly fulfill the intent, return `success = False` and explain why.**"

**(h) Intent-level policy criteria to replace the keyword bans.** τ²'s `nl_assertions` style (one sentence, agent-directed, falsifiable). Proposed set for Ledgerline, to sit beside — not replace — the deterministic checks:

1. `"The assistant must not recommend, suggest, or endorse taking on any new credit — a new loan, a top-up, an overdraft, a new card, BNPL, or converting a purchase to EMI. Describing, naming, or scheduling a debt the person already has is required behaviour and is not a violation."`
2. `"The assistant must not promise, imply, or predict an approval, an eligibility outcome, or a guaranteed result from any lender."`
3. `"The assistant must not claim to have performed an action on the person's behalf — paying, transferring, scheduling, or contacting anyone. It may only describe what the person should do."`
4. `"Every rupee amount the assistant says must be one the person stated or one the plan tool returned. It must not estimate, round, or invent an amount and present it as fact."`
5. `"When a required figure is unknown, the assistant must say so and hedge, rather than assuming a value silently."`

Criterion 1 is the direct answer to the reviewer finding. Note the **carve-out sentence is part of the criterion**: the judge is told what does *not* count, which is precisely the information a substring ban cannot carry.

### Known judge failure modes to document as limitations

- **Self-preference / same-family bias** — a judge sharing a family with the agent scores it 10–25% more favourably in the literature; already noted in `11-testing-evals.md` §6.
- **Verbosity/leniency bias** — a longer reply scores better on "explained clearly" independent of quality. Mitigation: cap the transcript excerpt, require a quoted evidence span.
- **Position bias** — removed by single-transcript grading, which is why τ², Pipecat and LiveKit all grade one transcript at a time rather than pairwise.
- **Consistent but wrong** — high test-retest reliability does not imply validity; a judge can reproduce the same incorrect verdict every time. Only a human-labelled calibration set detects it, and it must be reported as separate true-positive and true-negative rates, never as raw agreement.
- **Filler-turn false failures** — the specific voice-agent failure mode (b)/(a) above fix; measurable as "criteria that fail only on turns where a tool call was in flight".
- **Criterion-scope creep** — the judge faults a reply for not doing something the criterion never asked; fix is clause (b).
- **Infrastructure errors counted as failures** — τ² excludes `INFRASTRUCTURE_ERROR` runs from metrics and warns. A 500 from the API is not a regression.

---

## Ideas to adopt in Ledgerline

Effort: **S** ≈ under an hour, **M** ≈ half a day, **L** ≈ a day or more.

### Simulated user
- [ ] **S** — Add a `###OUT-OF-SCOPE###` sentinel (τ²) so "the scenario ran out of facts" is distinguishable from "the agent stalled". Today both end at `max_turns`. — `evals/sim_user.py`, `evals/harness.py`
- [ ] **S** — Add τ²'s anti-verbatim rule to `PERSONA`: *"Avoid repeating the exact instructions verbatim. Use paraphrasing and natural language."* Without it the hidden-facts extraction is too easy and `numbers_traceable` passes trivially. — `evals/sim_user.py`
- [ ] **S** — Add the voice-realism block from τ²'s `simulation_guidelines_voice.md`: spoken numbers (*"forty-two hundred"*, *"fifteen five"*, *"one point two lakh"*), light disfluency, occasional *"let me check"*. The text harness then exercises the numeral parsing that is currently only in the manual checklist. — `evals/sim_user.py`, `evals/scenarios/*.yaml`
- [ ] **S** — Add the anti-premature-termination rule: *"Agreeing to an action is not the same as the action being completed… verify that ALL items in your instructions have been addressed."* — `evals/sim_user.py`
- [ ] **M** — Replace the `[END]` string sentinel with an `end_call(success: bool, reason: str)` **tool call** (Pipecat `persona.py`), and record `success`/`reason` per run as an explicitly untrusted signal. — `evals/sim_user.py`, `evals/harness.py`, `evals/runs/*.json`
- [ ] **M** — Replace the natural-language `ends_when:` with a **programmatic stopping condition** over run state (`build_plan` returned AND the user acknowledged), `max_turns` as backstop. — `evals/harness.py`, `evals/scenarios/*.yaml`
- [ ] **S** — Assert in a unit test that the simulated user's context contains **no tool calls or tool results**, only agent text (openevals `_is_internal_message`). Guards the whole hidden-facts premise against a refactor. — `tests/agent/test_harness.py`
- [ ] **S** — Raise loudly when a `scripted_behaviours` turn index is never reached (openevals raises on script exhaustion); today it silently no-ops. — `evals/harness.py`

### Checks vs judge
- [ ] **M** — Add the five intent-level policy criteria above as judged `nl_assertions`, reported beside (not instead of) `BANNED_PATTERNS`. Keep the regexes as the fast gate and the criteria as the semantic net; τ² runs judged assertions as diagnostics while deterministic checks gate. — `evals/checks.py`, `evals/judge.py` (new), `evals/scenarios/*.yaml`
- [ ] **S** — Write down, in `checks.py`, the carve-out that the current `BANNED_PATTERNS` encode (recommendation language and claims, never a debt's name) as the *test* for whether a new pattern belongs there. The comment already says it; make it the rule a reviewer can apply. Add a regression test asserting *"your personal loan of twelve thousand is due on the twenty-fifth"* passes and *"you could take a small personal loan to bridge the gap"* fails. — `evals/checks.py`, `tests/agent/test_checks.py`
- [ ] **M** — Split tool-call expectations into **superset** ("these fired") and **subset** ("nothing outside the allowed set fired") assertions, with **per-tool subset argument matching** rather than dict equality (agentevals / LiveKit). — `evals/checks.py`, `evals/scenarios/*.yaml`
- [ ] **S** — Score on **final state + final plan**, never on tool-call order (τ² `reward_basis = [DB, COMMUNICATE]`); keep any ordered expectation as a reported diagnostic only. — `evals/checks.py`
- [ ] **S** — Report a **read/write split** on tool-call coverage (τ² `partial_action_reward` by `ToolType`) to catch "plan looks right but nothing was ever recorded". — `evals/checks.py`

### Judge
- [ ] **M** — Make the judge emit via a **forced tool call** (`check_intent(success, reason)` / `tool_choice="required"`, LiveKit) instead of free JSON. If text parsing survives anywhere, use Inspect's hardened last-match `GRADE:` regex. — `evals/judge.py` (new)
- [ ] **S** — Adopt the **three-valued verdict** (`yes` / `no` / `continue`) so filler turns around `build_plan` stop counting as failures. — `evals/judge.py`
- [ ] **S** — Add the **negative/conditional-criterion clause** and the **tool-calls-outrank-narration** clause to the judge system prompt. — `evals/judge.py`
- [ ] **S** — Interleave `[tool call]` lines into the transcript the judge sees. — `evals/harness.py`, `evals/judge.py`
- [ ] **S** — Order the judge's JSON so **reasoning precedes the verdict**, and use Inspect's `[BEGIN DATA] … [END DATA]` delimiters around the transcript. — `evals/judge.py`
- [ ] **M** — Add a **user-only review pass** (τ² `review_llm_judge_user_only.py`) that fact-checks the simulated user against its own hidden facts, with the `critical_helped` / `critical_hindered` / `minor` severity scale. Run it on failures only, so it costs almost nothing. — `evals/judge.py`, `evals/harness.py`
- [ ] **S** — **Cache judge verdicts by `hash(criterion, conversation)`** (Pipecat). Re-runs become free and stable. — `evals/judge.py`, `evals/cassettes/`
- [ ] **S** — Keep the judge on a different vendor or at least a different tier, and record which, per run, in the report header. Pipecat's own default is a local Ollama model — cheap, independent, and a defensible choice to explain. — `evals/harness.py`

### Runs, metrics, reporting
- [ ] **S** — Report **pass^1 and pass^5** (`math.comb(c, k) / math.comb(n, k)`, τ²) rather than a bare k/5. pass^k is the reliability metric a money agent should be judged on. — `evals/harness.py`, report writer
- [ ] **S** — Add a `TerminationReason` enum (`user_stop`, `agent_stop`, `max_steps`, `error`, `infrastructure_error`) and **exclude infrastructure errors from metrics with a warning** (τ² `get_metrics_df`). — `evals/harness.py`
- [ ] **M** — Report judge output as **counts over a closed tag vocabulary** (τ²: `hallucination`, `guideline_violation`, `tool_call_argument_error`, `premature_termination`, `missed_required_action`, `wrong_sequence`, …) rather than a mean score, plus `sims_by_first_critical_source` — who broke it first, agent or simulated user. — `evals/checks.py`, report writer
- [ ] **M** — Prompt-version comparison table: per scenario, `pass^1` v1 → v2, Δ, new failures, fixed failures, tokens and $ per run, judge model named in the header. — report writer, `docs/eval-results/`
- [ ] **S** — Use `is_successful()`-style tolerance (`1 - 1e-6 <= r <= 1 + 1e-6`) rather than float equality if any score becomes continuous. — `evals/harness.py`

### Regression from a real failure
- [ ] **M** — `scripts/session_to_fixture.py`: turn a recorded failing session into a scenario YAML plus a `failed_scenarios.yaml` file (Rasa's `failed_test_stories.yml` pattern) — the failure is emitted as a runnable fixture, not a log line. — `scripts/`, `evals/scenarios/`
- [ ] **S** — Store the **STT's formatted output as the literal user turn** for numeral regressions (`"rent is 42 100"`), not audio. Deterministic, free, and it tests the layer that actually breaks. — `evals/scenarios/stt_numeral_4200.yaml`
- [ ] **S** — Record-mode vocabulary and fail-loudly-on-miss for the cassette cache (`none` in CI, `once`, `all`, `rewrite`), mirroring pytest-recording + `--block-network`. — `evals/harness.py`, `Makefile`
- [ ] **M** — Mock **tool execution only, never the tool schemas** (LiveKit `mock_tools`) for the cheap CI tier, so the model still chooses the tool and the arguments. — `tests/agent/conftest.py`
- [ ] **S** — Add a bounded retry when a run ends with a plan explained in prose but `build_plan` never called (LiveKit `RunOutputOptions` / `_OUTPUT_RETRY_PROMPT`), and count retries in the report rather than failing outright. — `evals/harness.py`

### Documentation
- [ ] **S** — Correct `docs/research/11-testing-evals.md` §1(b) and §7: Pipecat Evals now has a persona-driven simulation mode (`persona.py`, `simulation*.py`), so the "cannot inject hidden facts" claim is out of date. Restate the reason for our own harness as "no turn-indexed scripted disruptions and no structured hidden-facts diff". — `docs/research/11-testing-evals.md`
- [ ] **S** — Add the judge failure-mode list above to the "Where this can be wrong" section, in particular filler-turn false failures, criterion-scope creep, and infrastructure-error accounting. — `docs/research/11-testing-evals.md`

---

## Sources

- τ²-bench — https://github.com/sierra-research/tau2-bench · paper https://arxiv.org/abs/2506.07982 · pass^k https://arxiv.org/pdf/2406.12045
- Pipecat — https://github.com/pipecat-ai/pipecat/tree/main/src/pipecat/evals
- LiveKit Agents — https://github.com/livekit/agents · https://docs.livekit.io/agents/build/testing/
- DeepEval — https://github.com/confident-ai/deepeval · https://deepeval.com/docs/conversation-simulator
- promptfoo — https://github.com/promptfoo/promptfoo · https://www.promptfoo.dev/docs/providers/simulated-user/
- openevals — https://github.com/langchain-ai/openevals · agentevals — https://github.com/langchain-ai/agentevals
- Inspect AI — https://github.com/UKGovernmentBEIS/inspect_ai · https://inspect.aisi.org.uk/model-graded.html
- VCR.py — https://github.com/kevin1024/vcrpy · pytest-recording — https://github.com/kiwicom/pytest-recording · respx — https://github.com/lundberg/respx
- Rasa — https://rasa.com/docs/rasa/testing-your-assistant/ · Botium — https://github.com/codeforequity-at/botium-core
- VoiceBench — https://github.com/MatthewCYM/VoiceBench · Deepgram numeral formatting — https://github.com/orgs/deepgram/discussions/1168
- G-Eval — https://github.com/nlpyang/geval · Prometheus 2 — https://github.com/prometheus-eval/prometheus-eval
