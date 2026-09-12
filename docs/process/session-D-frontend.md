# Session D · frontend (React + Vite + TypeScript)

Read `docs/process/00-orchestration.md` first. You own everything under `frontend/` except
`frontend/src/protocol/types.ts` and `frontend/src/protocol/sample.json` (contracts, read only), plus
`tests/e2e/**`. You never touch Python.

Research to read: `docs/research/07-frontend.md` (daily-js specifics: `window.Daily`, `createCallObject`,
`track-started`, `app-message`), `docs/research/02-daily-transport.md` section 4, `docs/architecture/02-hld.md`
sections 6 and 6b, `docs/architecture/03-folder-structure.md` frontend section.

The backend (Session C) is being built in parallel. Develop against `sample.json` and a mock: a dev-only
`?mock=1` query flag that replays `sample.json` and a few variants on a timer instead of joining Daily. The
Vite dev server proxies `/api` to `http://localhost:7860`.

## 1. Scaffold
`npm create vite@latest . -- --template react-ts` inside `frontend/` (keep the existing `src/protocol/`).
Add `@daily-co/daily-js` (pin the version research 07 verified, 0.92.x), `vitest`, `@testing-library/react`,
`@testing-library/jest-dom`, `jsdom`, `eslint` with the React and TypeScript presets, `prettier`. No UI kit, no
CSS framework, no state manager, no router. `vite.config.ts`: `server.proxy['/api'] = 'http://localhost:7860'`,
`build.outDir = 'dist'`. `npm run build` must produce `frontend/dist/index.html`. Scripts: `dev`, `build`,
`test`, `lint`, `typecheck`.

## 2. Protocol (`src/protocol/parse.ts`)
`parseIncoming(raw: unknown): Incoming | null`. Accepts a `CardsMessage` when `type === "cards"` and the shape
validates (hand-written guards, no zod; keep it small). Accepts the four RTVI messages by `label === "rtvi-ai"`
and `type`. Returns null for everything else. Vitest: `sample.json` parses; each RTVI shape parses; an RTVI
message of another type returns null; a cards message with a missing field returns null.

## 3. State (`src/state/sessionReducer.ts`)
`useReducer` over `{ call: "idle"|"connecting"|"live"|"ended"|"error", speak: SpeakState, cards: CardsMessage |
null, question: string, lastQuestion: string, error: string | null }`. Actions: `connect`, `joined`, `left`,
`error`, `cards` (ignore if `v <= current.v`), `botText` (append to current question until
`bot-stopped-speaking`, then it becomes the settled question), `botSpeaking`, `botStopped`, `userSpeaking`.
Vitest: stale `v` ignored; question assembles across chunks; speak state transitions.

## 4. Call hook (`src/call/useDailyCall.ts`)
Wraps daily-js call-object mode. `start()`: `POST /api/sessions`, `Daily.createCallObject({ videoSource: false })`,
`join({ url, token })`; on `track-started` with `type === "audio"` and `!participant.local`, set an `<audio>`
element's `srcObject` and `play()`; on `app-message` dispatch `parseIncoming(ev.data)`; on `participant-left`
for the bot or `left-meeting` dispatch `left`; `stop()`: `leave()` then `destroy()`. `toggleMic()` via
`setLocalAudio`. Everything triggered from the Start click so autoplay is satisfied. Errors surface as
`error` with a human sentence: mic permission denied, could not reach server, room join failed.
Test with a fake `Daily` global.

## 5. Components (`src/components/`)
Per HLD 6b: `PhaseStrip` (four segments filled to `phase`), `QuestionHeadline` (settled question large, current
bot text streaming below it while speaking), `FocusCard` (the card whose id equals `focus`; title, status badge,
rows; values ending in " ?" render with a muted question mark), `CardStack` (all other cards collapsed to title
plus one-line summary, click to focus locally), `MissingChips` (rows of the `missing` card), `Timeline` (inline
SVG polyline over `timeline`, lowest point marked, first and last date labels; no chart library), `PlanPanel`
(shown when a `plan` card exists: summary kv, actions rows, unpaid rows, "say the changes back" prompt),
`VoiceBar` (mic toggle, state pill idle/listening/speaking/thinking, End), `ErrorBanner`.

`App.tsx` layout: phone-first single column, max-width 480px centred; at >= 960px the stack becomes a
two-column board to the right of the focus card. Start screen before `live`: one Start button and one sentence.

Styles: `src/styles/tokens.css` (colour, spacing, type scale, light and dark via `prefers-color-scheme`) and
`app.css`. No framework. Status badge colours are semantic (ok, confirm, warn, provisional, final, blocked) and
separate from the accent. Respect `prefers-reduced-motion`. Every interactive element keyboard reachable with
a visible focus ring. Card updates animate in place (a brief highlight on the changed row), nothing else moves.

Vitest with Testing Library: `FocusCard` renders rows and badge; `CardStack` excludes the focused card;
`Timeline` marks the lowest point; `PlanPanel` appears only with a plan card; `VoiceBar` pill text follows state.

## 6. Mock mode
`?mock=1`: skip Daily, play a scripted sequence from `src/mock/script.ts`: gathering snapshot, a correction that
changes salary and summary, a conflict badge, plan phase with timeline and actions, final plan. Also emits fake
RTVI text so the headline animates. This is how the owner reviews the UI without spending voice minutes.

## 7. E2E (`tests/e2e/test_journey.py`, marker `e2e`)
Python Playwright (the `webapp-testing` skill in `.claude/skills/` has a server-lifecycle helper). Serve
`frontend/dist` with any static server or the FastAPI app if available, open `/?mock=1`, click Start, assert
the focus card shows, the summary changes after the scripted correction, and the plan panel appears. Not run by
default.

## Done when
`npm run typecheck`, `npm run lint`, `npm run test`, `npm run build` all pass; `?mock=1` walks the full journey
in the browser; `frontend/dist/` exists. Write `docs/process/status-D.md` with a screenshot path or two saved under
`docs/process/screens/`.
