# Prior art: generative UI, agent-driven cards, and cash-flow dashboards

Researched 2026-09-12 for Ledgerline. Companion to `03a-tool-results-carrying-ui.md` (MCP-UI / MCP Apps,
OpenAI Apps SDK, Adaptive Cards — not repeated here, folded into the Summary and the protocol table) and
`01-pipecat-daily-voice-agents.md` (RTVI, Pipecat voice-ui-kit).

## Summary — ranked, most liftable first

1. **Full snapshot + replace is the industry consensus wherever the channel is unreliable.** AG-UI tells
   frontends to *replace*, never merge, on `StateSnapshot`; Adaptive Cards replaces the whole card; the Apps SDK
   re-pushes `toolOutput` wholesale (03a). Deltas appear only where ordered delivery is a transport contract.
   Daily guarantees neither order nor delivery — our snapshot + monotonic `v` is right. (§1, table)
2. **Row-level diff highlight is free given full snapshots, and it is the whole demo.** Keep the previous
   snapshot, flash only the rows whose text changed, and a correction visibly ripples income → summary → dip day
   → action instead of blinking one card. Highest value-per-line item in this document. (§9.2, adopt #1)
3. **Terraform's plan vocabulary fixes the "proposed, not done" finding**: future-tense count line
   ("3 changes proposed · 1 bill left unpaid"), a per-row action verb, an explicit "nothing here has happened
   yet", and the consequence annotated on the row that causes it. (§5, adopt #2)
4. **Proposed-vs-unpaid must be structural, not sniffed from prose.** `PlanPanel` currently detects "unpaid" by
   substring on the `when` column; emit the distinction from `cards.py`. (§5, adopt #3)
5. **AG-UI's resync leg is our one missing protocol piece**: snapshots on init, *on resynchronisation*, and
   periodically. A late-joining or desynced browser has no way to ask for the current state. (§1, adopt #5)
6. **A2UI makes `live` a per-component attribute.** Put `aria-live="polite"` on the focused card only — a live
   region over the whole stack announces nine cards on every snapshot. (§2, adopt #4)
7. **A2UI's "UI as data, not code" + a client-owned component catalog** is exactly our nine fixed card ids;
   never let the model name a card type or emit markup. It also splits structure (`updateComponents`) from data
   (`updateDataModel`) so a value change can never create or destroy a component. (§2)
8. **Four tool states, not two** (Vercel: `input-streaming` / `input-available` / `output-available` /
   `output-error`). Split "being written right now" (focus ring) from "not yet confirmed" (`?` + badge), and add
   a per-card error state so a failed tool marks *its* card. (§3, adopt #6, #7)
9. **Provisional means rendered and marked, never hidden** — Apps SDK's `"..."` + fade; Adaptive Cards'
   "screen readers skip `isVisible:false` entirely". And no count-up on money: it shows false amounts. (03a, §9.2/9.3)
10. **Nobody in this set ships a card surface for voice, a motion policy, or a mock-feed browser test.** The
    voice starters stop at transcript + visualiser; `?mock=1` plus one Playwright spec and a
    `prefers-reduced-motion` rule are cheap and are where Ledgerline is ahead. (§8, §9.2, §9.5, adopt #8, #10)


## 1. AG-UI protocol (CopilotKit) — the closest protocol relative

- Spec: https://docs.ag-ui.com/concepts/events · repo https://github.com/ag-ui-protocol/ag-ui · CopilotKit https://github.com/CopilotKit/CopilotKit
- What it is: a transport-agnostic event protocol between an agent backend and a frontend. Sixteen-plus
  event types in eight categories: lifecycle (`RunStarted`/`RunFinished`/`RunError`/`StepStarted`/`StepFinished`),
  text message (`TextMessageStart`/`Content`/`End`/`Chunk`), tool call (`ToolCallStart`/`Args`/`End`/`Result`/`Chunk`),
  **state (`StateSnapshot`, `StateDelta`, `MessagesSnapshot`)**, activity (`ActivitySnapshot`/`ActivityDelta`),
  reasoning, subagent, and `Raw`/`Custom`.

Learnings, highest value first:

1. **Snapshot + delta, not one or the other.** `StateSnapshot` carries field `snapshot` = the full state, and the
   spec tells frontends to *"replace their existing state model with the contents of this snapshot"* rather than
   merge. `StateDelta` carries field `delta` = an array of **JSON Patch (RFC 6902)** operations, applied
   sequentially. Documented usage: snapshots on **initial transfer, resynchronisation after inconsistency, and
   occasional full refresh points**; deltas for ongoing change. Ledgerline is pure-snapshot, which is correct at
   our size, but the *resync* leg is the missing piece: we have no way for a late-joining or desynced browser to
   ask for a fresh snapshot.
2. **All-or-nothing replacement semantics are stated explicitly.** For `MessagesSnapshot`, entries present replace
   existing copies and entries **omitted are removed**. Ledgerline's card reconcile must state the same rule: a
   card id absent from the snapshot is deleted, not retained. (Our reducer replaces `state.cards` wholesale, so
   this holds by construction — worth a comment so nobody "optimises" it into a merge.)
3. **`Custom` and `Raw` escape hatches** exist so app-specific payloads do not force protocol version bumps.
   Ledgerline's `{type:"cards"}` riding alongside `label:"rtvi-ai"` traffic is the same idea.
4. **Tool calls stream in three parts** (`Start` → `Args` chunks → `End` → `Result`). That is the wire-level
   source of the "provisional value" state: between `ToolCallStart` and `ToolCallResult` the UI knows a field is
   *being written* but not yet committed. Ledgerline's `?` + confirm badge is the same idea derived from domain
   state instead of wire state — cheaper and more honest, because ours survives the turn.

CopilotKit's React layer on top (https://docs.copilotkit.ai/agent-spec/shared-state):
`useCoAgentStateRender({ name: "basic_agent", render: ({ state }) => <WeatherDisplay {...state.final_response} /> })`
— an agent-state-driven component that re-renders on every state update, distinct from `useCopilotAction`'s
tool-result rendering. The framing worth stealing: **shared state is a synchronised layer both sides read and
write**, so the UI is a projection of agent state rather than a log of tool results. That is exactly Ledgerline's
"one state object → derived cards" model, and it is the reason our corrections ripple: a projection re-derives,
a log appends.

## 2. Google A2UI — "UI as data", and the structure/data split

- Spec: https://a2ui.org/specification/v1.0-a2ui/ (v1.0, status Candidate, created 2025-11-20, updated 2026-06-08)
- Announcement: https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/
- Transport binding: AG-UI (§1). A2UI is *what* to render; AG-UI is *how it gets there*.

Four agent→renderer message types: `createSurface`, `updateComponents`, `updateDataModel`, `deleteSurface`.

Learnings:

1. **Security posture is the headline and it validates Ledgerline's design.** "UI as data, not code": the agent may
   only reference a **client-controlled component catalog**, never emit markup or script. Ledgerline's card schema
   (`id`, `title`, `status`, `rows`, `kv`, `note`) is exactly a tiny fixed catalog, and `cards.py` is the only
   thing allowed to name a card id. Keep it that way — never let the model emit a card type or free HTML. Our
   existing escaping rule in `07-frontend.md` is the second half of the same argument.
2. **Split structure from data.** `updateComponents` changes the tree; `updateDataModel` changes values at a
   **JSON Pointer (RFC 6901)** path. This is why A2UI can stream: structure and content move independently.
   Ledgerline's analogue already exists implicitly — the nine card ids are the fixed structure, the rows are the
   data. Worth making explicit: the client should *never* create or destroy a card component on a value change;
   only `status`/`rows`/`kv` change, which is what makes a flash-highlight cheap and a layout jump impossible.
3. **Adjacency-list streaming with graceful placeholders.** Components stream as a flat list, the renderer rebuilds
   the tree from id references, rendering can begin as soon as `"id": "root"` arrives, and **missing references
   render as placeholders rather than blocking**. That is the right model for a card whose rows have not arrived:
   render the card frame with a placeholder, never withhold the card.
4. **Idempotency rule, verbatim-useful:** "Component IDs are immutable once defined; redefining a component
   replaces it entirely." Same rule Ledgerline needs for card ids. Plus: "Messages must arrive in order (transport
   contract enforced)" — Daily app-messages give us **no such contract**, which is precisely why our monotonic
   `v` + full snapshot is the correct deviation from A2UI, not a shortcut.
5. **Convergence handshake:** with `"sendDataModel": true`, the renderer appends its **full data model** to every
   outbound message so the agent can detect divergence. A cheap Ledgerline version: when the browser sends
   anything back (or on reconnect), include `lastV`; the bot replies with a fresh snapshot if it does not match.
6. **Accessibility is mandated at the catalog level**, not left to the app: every catalog must map
   `AccessibilityAttributes` (`label`, `description`, **`live`**, `hidden`) onto framework-native APIs, and SDKs
   must verify interactive components declare accessible labels. `live` being a first-class per-component
   attribute is the model to copy: put `aria-live` on the **focused** card only, not the whole card stack.
7. Versioning: every message carries `"version": "v1.0"`, catalogs declare `"protocolVersion"`. Ledgerline's `v`
   is a *sequence* number, not a schema version — the two are different and both are useful. Adding a one-byte
   schema tag now is free insurance.

## 3. Vercel AI SDK — tool-part states as the provisional-value vocabulary

- Repo: https://github.com/vercel/ai — 26,695 stars, last push 2026-09-11
- Docs: https://ai-sdk.dev/docs/ai-sdk-ui/generative-user-interfaces

Message parts are typed `tool-${toolName}` and carry a `state` the UI switches on:

```tsx
if (part.type === 'tool-displayWeather') {
  switch (part.state) {
    case 'input-streaming':  return <Skeleton />          // args still arriving
    case 'input-available':  return <div>Loading weather…</div>
    case 'output-available': return <Weather {...part.output} />
    case 'output-error':     return <div>Error: {part.errorText}</div>
  }
}
```

Learnings:

1. **Four states, not two.** `input-streaming` → `input-available` → `output-available` → `output-error`. Most UIs
   collapse this to loading/loaded and lose the most interesting state: *we know what is being asked, we do not
   yet know the answer*. Ledgerline already has the domain equivalent — `provisional` vs `confirm` vs `ok` — but
   only `summary`/`actions` use `provisional`. The mapping worth adopting: a card the current tool call is
   *writing to* should read as "input-streaming" (focus ring + skeleton row), distinct from a card holding a
   value the user has not yet confirmed (`?` + confirm badge). Today `focus` and `status` are doing both jobs.
2. **`output-error` is a first-class render branch.** Ledgerline has `ErrorBanner` at the session level but no
   per-card failure state. A tool that throws (bad date, unparseable amount) should leave a visible mark on
   *that* card, not only a banner — otherwise the user hears a correction and sees nothing change.
3. `useObject` / `streamObject` render **partial objects** as they arrive (deep-partial types, every field
   optional). Relevant as a warning more than a pattern: streaming partial money values into a card shows the
   user a wrong number for 200 ms. Ledgerline derives cards *after* the tool mutation commits, which is strictly
   better for numbers. Do not adopt partial-value streaming for amounts; the Apps SDK `"..."` placeholder (03a)
   is the honest version.

## 4. CopilotKit — human-in-the-loop as the "proposed, not done" primitive

- Repo: https://github.com/CopilotKit/CopilotKit — 37,306 stars, last push 2026-09-11
- Docs: https://docs.copilotkit.ai/agent-spec/human-in-the-loop, https://docs.copilotkit.ai/agent-spec/shared-state

Two distinct hooks, and the distinction is the lesson:

| Hook | Renders | Lifetime |
|---|---|---|
| `useCopilotAction({ handler })` | a tool the frontend executes | one call |
| `useCoAgentStateRender({ name, render: ({state}) => … })` | **agent state**, re-rendered on every state update | the whole run |
| `useCopilotAction({ renderAndWaitForResponse })` | a **proposal** the user approves or rejects | blocks the agent |

`renderAndWaitForResponse` gives the component `(args, status, respond)`. It renders the proposed action, and the
agent **stays paused** until `respond({approved: true|false, metadata})` is called. HITL definition from their
docs: "lets an agent pause mid-run to collect input, confirmation, or a choice from the user, then resume with
that answer folded back into its reasoning."

Learnings for the plan panel:

1. **A proposal has three visual states, and most UIs only build one.** `status` is part of the render signature
   for a reason: `executing` (awaiting the human), `complete` (decided), and the decision itself (approved vs
   rejected). Ledgerline's plan actions currently have one state — they are listed. They need at minimum
   *proposed* vs *accepted* vs *rejected/changed*, driven by the confirm phase, so that after the user says yes
   the panel visibly changes rather than just ending.
2. **The proposal component is the same component before and after the decision**, changing only its badge and
   affordance. That is why re-rendering a decided proposal still reads correctly in scrollback. Applies to
   `PlanPanel`: do not swap components on confirm, swap the badge and the verb.
3. Shared state (`useCoAgentStateRender`) vs tool-result rendering (`useCopilotAction`) is the same split as
   Ledgerline's cards (state projection) vs a hypothetical "tool call log" (event list). We chose the projection.
   Keep resisting requests to add a tool-call feed; it is the thing that makes corrections invisible.

## 5. Terraform `plan` — the canonical "proposed, not applied" vocabulary

- Docs: https://developer.hashicorp.com/terraform/cli/commands/plan,
  https://developer.hashicorp.com/terraform/tutorials/cli/plan

Not a UI library, but the best-known interface whose entire job is "here is what *would* happen". Worth copying
because millions of engineers already read it correctly on first sight.

1. **Per-item action symbols, one glyph each:** `+` create, `~` update in place, `-` destroy, `-/+` replace. Every
   line in the list is tagged with what *kind* of change it is, not merely that it is a change.
2. **A count summary in the future tense**, always present, always above or below the list:
   `Plan: 2 to add, 0 to change, 0 to destroy`. Note "to add", not "added".
3. **An explicit disclaimer that nothing has happened yet**, printed on every plan, plus a separate `apply` step
   that must be taken. The plan is never confusable with the result.
4. **Reasons are annotated inline** (`# forces replacement` on the attribute that caused a `-/+`), rather than
   hidden in prose elsewhere.

Direct map to Ledgerline's plan panel, which is where the reviewer finding lands. The panel should read:

- a future-tense count line — "3 changes proposed · 1 bill left unpaid" — not "Covered";
- per-row action verb glyph/word: `defer`, `part-pay`, `cut`, `skip`, mirroring `_action_rows`;
- an explicit "nothing here has happened yet" line before the confirm question;
- the consequence annotated on the row that causes it (already the case for `unpaid` rows via `u.consequence`).

**Status in the repo (checked 2026-09-12):** `frontend/src/components/PlanPanel.tsx` has *already been fixed* —
the header comment records that the `actions` card is deliberately not read because rendering both duplicated
every deferral, and the two groups are now "Proposed changes" and "Left unpaid this month". The remaining gap is
the future-tense count line, the per-row verb, and the "nothing has happened yet" disclaimer. `cards.py:333`
still builds `plan.rows = action_rows + unpaid`, so the client is splitting on a string sniff
(`isUnpaid` matches `"unpaid"` in the `when` column) — brittle. Move the distinction into the payload as a
fourth row element or a separate `kv` key.

## 6. OpenAI realtime-agents demo — a voice UI with a tool/event pane

- Repo: https://github.com/openai/openai-realtime-agents — 6,976 stars, last push 2026-01-07 (dormant)
- Layout: transcript pane left (messages **plus tool calls, tool results and agent handoffs**, non-message
  elements collapsed and click-to-expand), event log pane right (client and server events, click for full
  payload), bottom control bar (VAD vs push-to-talk, audio playback toggle, log visibility, connection status).
  Key files: `src/app/App.tsx`, `src/app/agentConfigs/`.

Learnings:

1. **Collapsed-by-default tool breadcrumbs inside the transcript.** Mechanism is visible but never competes with
   the conversation. Ledgerline's collapsed card stack is the same instinct applied to state rather than events.
2. **A separate debug pane, toggleable.** Cheap and high value for a demo: a hidden pane that dumps the raw
   snapshot JSON and the `v` sequence. Ledgerline can add this in ~30 lines behind a query param and it doubles
   as the manual test surface.
3. **Anti-pattern:** two dense scrolling panes side by side is a desktop layout. It does not survive phone width,
   and neither pane is ever the thing you are looking at while speaking. Ledgerline's "one focus card, everything
   else collapsed" is the right inversion; do not add a second scroller.

## 7. Actual Budget — the 30-day balance line and the dip day

- Repo: https://github.com/actualbudget/actual — 28,697 stars, last push 2026-09-11 (very active)
- Docs: https://actualbudget.org/docs/experimental/balance-forecast-report/
- Also seen: https://github.com/firefly-iii/firefly-iii (24,582 stars, active),
  https://github.com/maybe-finance/maybe (54,286 stars, **archived, last push 2025-07-24** — do not cite as live).

Actual's Balance Forecast Report is the closest open-source analogue to Ledgerline's timeline:

1. **Forecast = starting balance from posted transactions, then simulated occurrences.** "For each forecast day,
   Actual updates the running balance with posted transactions on that day plus simulated scheduled transactions
   on that day." Ledgerline's `_timeline` does the same thing; the useful confirmation is that the *day* is the
   unit and the balance is *after* that day's events — which is what our `TimelinePoint.b` comment already says.
2. **Forecast source is user-selectable** (scheduled transactions vs budget) and **granularity toggles daily
   vs monthly**. Ledgerline is fixed at 30 daily points; the transferable idea is that the chart must declare
   what it is forecasting *from*, in words, near the line.
3. **Gap worth exploiting:** the docs do **not** describe visually separating forecast from posted data, and do
   **not** describe marking the lowest or negative point. Actual's own issue tracker shows the running-balance
   feature is still limited to the accounts view and that ordering of future transactions causes confusing
   negative balances (https://github.com/actualbudget/actual/issues/4244, /issues/1675). So Ledgerline's marked
   dip day is a genuine differentiator, not a re-implementation — and the known failure mode to avoid is
   **ordering ambiguity within a day** (an income and an outflow on the same date producing a phantom dip).
   `_timeline` must apply same-day income before same-day outflows, or state the convention on the card.
4. Design rules that follow: label the dip day with both date and amount as text (never colour alone), keep the
   line's zero axis visible so "below the line" is literal, and state the shortfall in words in `summary.kv`
   (`"lowest": "-1,800 on 5 Oct"` already does this — keep it, it is the accessible version of the chart).

## 8. Briefly checked, lower value

- **assistant-ui** (https://github.com/assistant-ui/assistant-ui, 12,113 stars, last push 2026-09-11): a
  Radix-style primitives library for chat threads. Relevant only for its composition approach (unstyled
  primitives + your own shell); nothing to lift for a non-chat card surface.
- **LangGraph / langgraphjs** (https://github.com/langchain-ai/langgraphjs, 3,274 stars): generative UI is
  delivered through the AG-UI / CopilotKit layer covered in §1 and §4, so it adds no distinct protocol lesson.
- **LiveKit agent-starter-react** (https://github.com/livekit-examples/agent-starter-react, 938 stars, last push
  2026-09-09): chat transcript (`components/app/chat-transcript.tsx`), tile layout for application states
  (`components/app/tile-layout.tsx`), session view with control bar, five audio visualiser styles, theme
  switching. No custom data-channel card UI, no documented agent-state pill, no tests. Confirms that the voice
  starters in the ecosystem stop at transcript + visualiser — the card surface is the part nobody ships, which
  is where Ledgerline's differentiation sits (same conclusion as `01-…`'s voice-ui-kit section).
- **Thesys C1 / crayon** and **Hume EVI React examples**: no public repo resolved under those names via the
  GitHub API on 2026-09-12 (crayon and A2UI both returned no repository). Treated as unavailable rather than
  guessed at; C1 is a commercial hosted product (https://thesys.dev) and its generative-UI model is the same
  "server returns a spec, client renders from a catalog" shape already captured by A2UI in §2.

## 9. Cross-cutting themes

### 9.1 Keeping the screen consistent with what is being said

Nobody in this set solves it well, which makes it the cheapest place to look good.

- Apps SDK (03a) marks the streaming card by **styling only** (`phase === "streaming"` swaps text colour) and
  states the phase **in words** in a banner.
- A2UI gives every component an `AccessibilityAttributes.live` flag, so "the thing being updated" is a
  first-class, per-component property rather than a page-level guess.
- AG-UI's `StepStarted`/`StepFinished` bracket a unit of work, which is what a *turn* is.

Ledgerline already carries `focus` = the card the last tool call touched. The prior art says to do three things
with it and no more: (a) visually raise exactly that card, (b) put `aria-live="polite"` on **only** that card, and
(c) say the phase in words somewhere (`PhaseStrip` already does). Do not animate the other eight; A2UI's
"redefining a component replaces it entirely" plus reconcile-by-id means the rest should update silently in place.

### 9.2 Animating a correction so it ripples

- `07-frontend.md`'s existing recipe (`el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash')`)
  is the standard reflow-restart trick and survives into the React version as a keyed `key`/`data-v` change.
- The useful refinement from the snapshot protocols: because every message is a full snapshot, the client can
  **diff the previous snapshot against the new one** and flash only the rows whose text changed — not the whole
  card. That is what makes a correction *ripple* instead of *blink*: rent changes, and the rent row, the summary
  row, the dip day and the action row each flash, showing causality. This is the single highest-value visual idea
  in this document and it is free given full snapshots (patch protocols get it too, but ours is already there).
- **Nobody in this set documents a motion policy** (noted in 03a too). `prefers-reduced-motion` must be our own
  rule: reduced motion replaces the flash with a persistent "changed" dot that decays on the next snapshot.
- Count-up on numbers: attractive, and **wrong here**. A count-up shows a sequence of false amounts, which in a
  money app is exactly the thing the `?` badge exists to prevent. Flash the row, swap the number instantly.

### 9.3 Provisional, missing, and unconfirmed

- Apps SDK: render `"..."` and fade; never omit (03a).
- Adaptive Cards: **"Avoid `isVisible: false`: screen readers skip hidden elements entirely"** (03a) — so a
  missing field must be rendered present-but-empty, which `MissingChips` does.
- Vercel AI SDK: four states, including `output-error`, each with its own branch (§3).
- Terraform: annotate the *reason* on the row that caused it (§5).

### 9.4 Payload cap

Only Adaptive Cards and the Apps SDK document numeric caps (Teams host limits; widgetState "should not exceed
4k tokens"), and both handle overflow by **refusing detail, not by truncating silently**. Ledgerline's
`cards.py::_fit` degrades in a stated order — timeline points (keeping first / lowest / last), then row labels to
14 chars and notes to 60, then rows capped with a `"+N more"` sentinel, then a truncation note appended to the
summary. That is better than anything found here and should be kept; the one addition suggested by the prior art
is to **also degrade in the model-visible channel** (03a takeaway 2): when the card is truncated the spoken text
must still be complete, because the conversation has to remain useful if the UI cannot show everything.

### 9.5 Testing

- Adaptive Cards' process rule (03a): **one checked-in JSON fixture per feature**, edited side by side with the
  template in a designer. Ledgerline has `frontend/src/protocol/sample.json` generated from the Python side and a
  `?mock=1` scripted feed (`frontend/src/mock/script.ts`, `frontend/src/mock/install.ts`) that replays raw
  `app-message` payloads through the real parser, reducer and hook. That is the strongest testing asset in this
  comparison — none of the surveyed voice starters ship one.
- Gap: the frontend runs **Vitest only** (`frontend/package.json`); there is no Playwright/browser pass. The mock
  feed makes a browser test nearly free: launch with `?mock=1`, assert the phase strip advances, assert the
  focused card is the one with `aria-live`, assert a corrected value both changes and flashes, screenshot at
  390 px. Add one Playwright spec, not a suite.
- A2UI's rule that "SDKs must verify interactive components declare accessible labels" is a lint, not a test:
  a contract test asserting every rendered card has an accessible name is ~10 lines and already has a home in
  `frontend/src/components/contract.test.tsx`.

## Protocol comparison

| Protocol | Shape | Versioning / ordering | Size handling | Ordering with audio / speech |
|---|---|---|---|---|
| **Ledgerline cards** | Full snapshot every change, 9 fixed card ids + timeline | Monotonic `v`; client drops `v <= current`; no resync path | Hard 4 KB Daily cap; `_fit` degrades timeline → labels → rows → `"+N more"` + truncation note | `OutputTransportMessageUrgentFrame` (SystemFrame) jumps the audio queue, so cards land *before* speech finishes |
| **AG-UI** (§1) | `StateSnapshot` (replace, do not merge) **+** `StateDelta` (JSON Patch RFC 6902) + `MessagesSnapshot` (omitted = deleted) | Snapshot on init / resync / periodic refresh; deltas applied sequentially, so ordering is required | Deltas exist specifically for bandwidth; no numeric cap | None — transport-agnostic, no audio concept |
| **A2UI** (§2) | `createSurface` / `updateComponents` (structure) / `updateDataModel` (JSON Pointer value) / `deleteSurface` | `"version":"v1.0"` per message; **ordered delivery is a transport contract**; ids immutable, redefinition replaces | Flat adjacency list streams progressively; missing refs render as placeholders | None; bound to AG-UI for transport |
| **Vercel AI SDK** (§3) | Streamed message parts; `tool-*` parts carry `state`: `input-streaming` → `input-available` → `output-available` \| `output-error` | Stream order is the protocol; no version counter | Streaming, unbounded | None |
| **MCP-UI / MCP Apps** (03a) | Whole `UIResource` re-sent; typed host→guest notifications (`ui/notifications/tool-input`, `…-partial`, `tool-result`, `host-context-changed`) | `messageId` request/ack/response envelope, not a counter | `text` vs base64 `blob`; continuous `ResizeObserver` size messages | None |
| **OpenAI Apps SDK** (03a) | Host pushes globals wholesale (`toolInput`/`toolOutput`/`widgetState`) via `openai:set_globals` | `useSyncExternalStore` + cached globals + `Object.is` dedupe + 250 ms resync poll, max 40 tries | widgetState ≲ 4k tokens; invoking/invoked strings ≤ 64 chars | `ontoolinputpartial` / `ontoolinput` / `ontoolresult` phase the UI against the model's progress |
| **Adaptive Cards** (03a) | Whole replacement card; `Action.Execute` + `refresh` with `value.trigger: automatic\|manual` | `version` = required schema version, `fallbackText` + per-element `fallback`/`requires`; `refresh.expires` staleness | Host limits (Teams): ≤10 sections, ≤5 images/actions per section, no horizontal scroll, ≤3 columns | None |

Reading of the table: **every protocol that has to survive an unreliable or unordered channel converges on full
snapshot + replace.** Deltas appear only where ordered delivery is guaranteed (A2UI states it as a transport
contract; AG-UI applies patches sequentially). Daily app-messages guarantee neither delivery nor order, so
Ledgerline's snapshot choice is the correct one and the only missing leg is AG-UI's **resync**.

## Ideas to adopt in Ledgerline

| # | Idea | Effort | Files |
|---|---|---|---|
| 1 | **Row-level diff highlight.** Keep the previous snapshot in the reducer; flash only the rows whose text changed, so a correction visibly ripples across income → summary → timeline → actions. | M | `frontend/src/state/sessionReducer.ts` (keep `prev`), `frontend/src/components/CardRows.tsx`, `CardKv.tsx`, `styles/app.css` |
| 2 | **Plan panel: future tense + per-row verb + "nothing has happened yet".** Terraform's summary line (`3 changes proposed · 1 bill left unpaid`), an action verb per row, and an explicit disclaimer above the confirm question. | S | `frontend/src/components/PlanPanel.tsx` |
| 3 | **Move proposed-vs-unpaid into the payload.** `isUnpaid` currently sniffs the string `"unpaid"` in the `when` column. Emit the distinction structurally (a 4th row element, or two `kv` keys) so the client never parses prose. | S | `ledgerline/domain/cards.py` (`_action_rows`, `build_cards`), `frontend/src/protocol/types.ts`, `PlanPanel.tsx`, `protocol/sample.json` |
| 4 | **`aria-live` on the focused card only**, per A2UI's per-component `live` attribute — not on the whole stack (which announces nine cards on every snapshot). | S | `frontend/src/components/FocusCard.tsx`, `CardStack.tsx` |
| 5 | **Resync path.** Client sends `{type:"hello", lastV}` on join/reconnect; bot replies with a fresh snapshot. Covers the late-joining browser and any dropped app-message. AG-UI's snapshot-for-resynchronisation leg. | M | `frontend/src/call/useDailyCall.ts`, bot side (`on_app_message` handler, per `07-frontend.md` gotcha), `cards.py` |
| 6 | **Per-card error status.** Add `output-error`'s equivalent: a tool that fails marks its card, not just `ErrorBanner`, so the user sees where the failure landed. | S | `ledgerline/domain/cards.py` (`CardStatus` already has `blocked`), `frontend/src/components/StatusBadge.tsx` |
| 7 | **Separate "being written now" from "not yet confirmed".** `focus` = the Vercel `input-streaming` state (ring + skeleton); `status:"confirm"` + `?` = unconfirmed value. Today `focus` is carrying both. | S | `FocusCard.tsx`, `StatusBadge.tsx`, `styles/app.css` |
| 8 | **`prefers-reduced-motion` policy**, since no surveyed project has one: replace the flash with a persistent "changed" dot that clears on the next snapshot. | S | `frontend/src/styles/app.css`, `CardRows.tsx` |
| 9 | **Same-day ordering convention on the timeline.** Actual's known bug is phantom dips from intra-day ordering; apply income before outflows on a date and state it in the card note. | S | `ledgerline/domain/cards.py` (`_timeline`), `frontend/src/components/Timeline.tsx` |
| 10 | **One Playwright spec over `?mock=1`.** Assert phase advance, focused card has the live region, corrected value changes *and* flashes, 390 px screenshot. The mock feed already exists; this is the last mile. | M | new `frontend/e2e/journey.spec.ts`, `frontend/package.json`, `frontend/vite.config.ts` |
| 11 | **Schema tag alongside `v`.** `v` is a sequence number; add a one-byte schema version so an old client can degrade rather than mis-render (Adaptive Cards' `version` + `fallbackText`). | S | `ledgerline/domain/cards.py`, `frontend/src/protocol/types.ts`, `parse.ts` |
| 12 | **Debug pane behind a query param** dumping the raw snapshot and `v`, per the realtime-agents event pane. Doubles as the manual test surface. | S | `frontend/src/App.tsx` |
| 13 | **Accessible-name contract test** for every rendered card (A2UI's "SDKs must verify interactive components declare accessible labels"). | S | `frontend/src/components/contract.test.tsx` |

### Anti-patterns to keep avoiding

- **A tool-call feed / event log as the main surface.** The realtime-agents two-pane layout and the Apps SDK's
  "if you attach a widget template to every tool call, ChatGPT can re-render your iframe too often" (03a) are the
  same warning: a log makes corrections invisible because it appends instead of re-deriving. Cards are a
  projection of state; keep it that way.
- **Count-up / number-rolling animation on money.** Shows false amounts (§9.2).
- **Streaming partial values into amount fields** (Vercel `useObject`) — derive cards after the mutation commits.
- **Hiding missing or unknown fields** (`isVisible:false` is an accessibility trap, 03a).
- **Trusting client-computed totals** (Apps SDK, 03a) — `cards.py` must own every number.
- **Merging instead of replacing a snapshot.** AG-UI says replace; a merge silently resurrects deleted cards.
- **Two dense scrollers on a phone** (§6).
- **Naming the archived repo as prior art**: `maybe-finance/maybe` has not been pushed since 2025-07-24.

## Sources

- AG-UI events: https://docs.ag-ui.com/concepts/events · https://github.com/ag-ui-protocol/ag-ui
- CopilotKit: https://github.com/CopilotKit/CopilotKit · https://docs.copilotkit.ai/agent-spec/shared-state · https://docs.copilotkit.ai/agent-spec/human-in-the-loop
- A2UI: https://a2ui.org/specification/v1.0-a2ui/ · https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/ · https://www.copilotkit.ai/blog/build-with-googles-new-a2ui-spec-agent-user-interfaces-with-a2ui-ag-ui
- Vercel AI SDK: https://github.com/vercel/ai · https://ai-sdk.dev/docs/ai-sdk-ui/generative-user-interfaces
- Terraform: https://developer.hashicorp.com/terraform/cli/commands/plan · https://developer.hashicorp.com/terraform/tutorials/cli/plan
- OpenAI realtime-agents: https://github.com/openai/openai-realtime-agents
- Actual Budget: https://github.com/actualbudget/actual · https://actualbudget.org/docs/experimental/balance-forecast-report/ · https://github.com/actualbudget/actual/issues/4244 · https://github.com/actualbudget/actual/issues/1675
- Firefly III: https://github.com/firefly-iii/firefly-iii · Maybe (archived): https://github.com/maybe-finance/maybe
- assistant-ui: https://github.com/assistant-ui/assistant-ui · LangGraph JS: https://github.com/langchain-ai/langgraphjs
- LiveKit: https://github.com/livekit/agents · https://github.com/livekit-examples/agent-starter-react
- Thesys: https://thesys.dev
- Star counts and last-push dates via the GitHub API on 2026-09-12.
