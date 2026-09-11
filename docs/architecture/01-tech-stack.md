# Tech stack

Decided 2026-09-11. Full reasoning, alternatives rejected, and verified API details live in `docs/research/`
(start with `00-index.md`). This page is the one-line version.

| Part | Choice | Why |
|---|---|---|
| Voice framework | Pipecat 1.9 | Mandated. Streams STT to LLM to TTS with built-in interruption. |
| Transport | Daily | Mandated. WebRTC audio both ways plus app-message channel for cards. |
| STT | Deepgram Nova-3 | Fastest in Pipecat's benchmark, converts "forty-two hundred" to 4200, $200 free credit. |
| LLM | gpt-5.6-luna, reasoning off | Only key available. Cheapest, fastest OpenAI tier. Reasoning must be off or tools fail and first-token latency triples. |
| LLM service | Pipecat `OpenAIResponsesLLMService` | Auto-disables reasoning for gpt-5.x, strict tool schemas, sends only incremental context. `OpenAILLMService` kept as one-line fallback. |
| TTS | Cartesia Sonic 3.6 | Lowest latency, word timestamps so interrupted speech is recorded correctly in context. Free tier about 27 min/month. |
| TTS fallback | Deepgram Aura-2 | Same $200 credit, effectively unlimited for dev. Switched by env var. |
| VAD and turn end | Silero + Smart Turn v3 | Both bundled in the wheel, no download. Smart Turn keeps the turn open on "um" while the user recalls a number. |
| Agent logic | System prompt + tool handlers, no graph | One agent, one session, one state object. A graph would have one node. |
| Tools | Generic `upsert_item` keyed by (kind, name) | A correction hits the same record. Under ten tools, one habit for the model. |
| State | One Pydantic object, in memory, per call | Single source of truth for speech and cards. Dies with the call, correct for scope. |
| Plan engine | Pure Python, `Decimal`, day-by-day simulation | Testable without mocks. Catches salary-after-EMI timing gaps that monthly totals miss. |
| Cards | Daily app-message, versioned full snapshot | Channel already open, no extra port. 4 KB cap forces compact cards. |
| Frontend | React 19 + Vite + TypeScript in `frontend/`, built in a Node stage of the same Dockerfile, served by FastAPI | Cards are a component tree; TypeScript types mirror the Pydantic card models; still one image, one command. |
| Server | FastAPI in package `ledgerline/` split `domain` ← `agent` ← `voice` ← `api`, pipeline runs as an asyncio task in-process | One-way imports enforced with import-linter; Pipecat's current in-process pattern. See `03-folder-structure.md`. |
| Docker | python 3.11-slim, uv, one compose service, port 7860 | One command, one container, one process. |
| Tests | pytest + text-only conversation harness + LLM judge | Engine tests are pure. Harness reuses the real tool handlers without audio. No eval framework to defend. |

## Keys

| Var | Vendor | Card needed | Free tier |
|---|---|---|---|
| `OPENAI_API_KEY` | OpenAI | pay as you go | none, cost under $1 per eval pass |
| `DAILY_API_KEY` | Daily | yes, card on file | 10,000 min/month |
| `DEEPGRAM_API_KEY` | Deepgram | no | $200 credit, no expiry |
| `CARTESIA_API_KEY` | Cartesia | no | 20,000 credits/month |

## Rejected, in one line each

- LangGraph in the loop: `graph.invoke()` is a barrier, kills streaming and interruption; the graph would be one node.
- Pipecat Flows: fixed node graph, conflicts with "no fixed questionnaire".
- Speech-to-speech models (OpenAI Realtime, Gemini Live): weaker tool control, hides the STT boundary worth understanding.
- Vanilla-JS single file frontend: fewest parts, but does not scale past one page and reads as a prototype. Revised to React + Vite on 2026-09-11.
- Pipecat client SDK / RTVI on the client: rides the same 4 KB app-message channel, adds a protocol layer we do not need.
- Subprocess per call: removed from Pipecat's own examples in 1.x.
- Redis or SQLite for state: no cross-call requirement.
- DeepEval, promptfoo, Braintrust, OpenAI Evals: dashboards we do not need; OpenAI Evals shuts down Nov 2026.
