# Status — frontend redesign

Rebuilt `frontend/` to the board design. The wire contract, the parser, the call layer, the
reducer and the mock feed are untouched; everything below is view code, styles, tests and
screenshots.

## The design input, and where it lives

One design canvas, `Ledgerline Board v2.dc.html`, from the design project the owner
shared (project `793fb805-2968-4104-9b45-e20c5cc3bc69`). It is parked at
`docs/process/design/ledgerline-board-v2.dc.html` with a `README.md` saying what it is and
which parts were built. The file carries no attribution or watermark of any kind. Its
sibling `support.js` is the generated runtime that makes the canvas interactive and was not
parked; neither were the three older boards in the same project.

The canvas is a drawing of the call, driven by six hard-coded states. It is the design
reference and nothing more: the states, their cards, totals and timelines are all invented
for the drawing, and `?mock=1` — which replays real `build_cards` output — is still the only
demo path and the only path the browser tests drive.

## What is on the board

A ledger page on the left, a standing panel on the right, the call along the foot.

- **Masthead** — wordmark, the three phase words (`gathering / ready / plan`, all three
  ruled and none current at `done`), and an all-clear line when nothing is still needed.
- **Ledger** — the question set large in the serif; then every card the snapshot sends,
  open, in three columns (`label`, `when`, `amount`). Card titles and status come from the
  snapshot. The card the bot last touched is marked with a rule down its left edge. Below
  the cards: the "Still need" chips, ruled paper to the foot of the page, and the totals
  bar — In / Out / Unpaid if nothing changes — ruled off with a hard line.
- **Panel** — the lowest point set at 48px, the thirty-day chart, then the plan: numbered
  proposed changes, what is left unpaid, the consequence, and the confirm strip. Before a
  plan exists the strip carries the summary card's own note.
- **Voice bar** — a wave that keeps time with the speak state, the state written out beside
  it, Mute and End call.

## Decisions

- **Two type families, self-hosted.** Source Serif 4 for anything that is *said* on the call
  (question, card names, notes, the plan, the low point) and Archivo for anything that
  *labels* (column heads, keys, buttons). Both are OFL; the six woff2 files and both
  licences are in `frontend/public/fonts/`, loaded by `styles/fonts.css` with a real system
  fallback stack. No Google Fonts link at runtime, so the Docker demo works offline. They
  are the variable builds, so one file covers every weight and Source Serif 4's optical-size
  axis sets the 48px figure with a display cut and the 15px notes with a text cut.
- **One token set, read twice.** `styles/tokens.css` is the whole palette; `app.css` uses no
  literal colour. Light and dark are the same design: in dark the ledger comes down to meet
  the panel and the panel lifts a step, so the board still reads as two surfaces.
- **Nothing on the ledger is collapsed, behind a click, or behind a hover.** The old board
  had one focus card and a stack of one-line summaries. The board is read while the person
  is talking, usually without a hand on the mouse, so a figure they gave has to be on screen
  to be correctable. `focus` from the snapshot marks a card now; it no longer opens one.
  This retired `FocusCard`, `oneLineSummary` and the click-to-focus state in `App`.
- **The chart is honest about its scale.** Bars are anchored at zero, so a month with a
  salary spike genuinely shows three flat weeks — that is the month. To keep the low
  findable anyway, the day it falls on carries a full-height band, a red bar and a red axis
  mark. Balances between the points the backend sent are the last balance it sent, carried
  forward, which is what "balance after that day's events" means on a day with no events —
  nothing is interpolated and nothing is summed.
- **The low is printed once.** `summary.lowest` is the panel's big figure, so the chart's
  own label is suppressed while that exists and appears only when the summary carries no
  lowest. Two figures on one panel read as two findings.
- **Status words.** The five contract statuses are written out (`confirmed`, `needs
  attention`, `not confirmed`, `settled`, `blocked`) so colour is never the only signal. The
  words describe the enum and never the figures — `warn` says attention is needed, not why;
  the card's own note is where the backend explains itself.
- **Motion is short and switched off on request.** New cards, chips and plan lines rise in;
  a corrected row washes once with the accent; chart bars transition their height; the wave
  keeps time with the speak state. Everything collapses to 1ms under
  `prefers-reduced-motion`.
- **No new dependency, no chart library.** The chart is one inline SVG.

## A rule that changed

The old e2e journey asserted that after a correction the retired figure is **gone from the
page**: `expect(page.get_by_text("45,000")).to_have_count(0)`.

The design shows the correction happening — the figure that was replaced struck through
beside the live one — and the owner ruled that this is what the board should do, because the
moment a number moves while someone is talking is the moment they most need to see it move.
The assertion now guards the thing that actually matters, which is that a retired figure can
never be mistaken for the current one:

- it exists only inside a `data-retired` element and never as a live value
  (`.row__live` never carries it);
- that element is an `<s>`, `aria-hidden`, so assistive tech cannot read it as current;
- the row instead carries one visually-hidden sentence, so a screen reader hears
  "was 45,000, now 72,000" rather than two competing amounts.

Both figures are strings the backend sent; the retired one is the value from the previous
snapshot, not a step computed on the way to the new one. There is no count-up.

## Where "what changed" is computed

`components/useChangedRows.ts`. Snapshots are full replacements reconciled by card id, so
the difference between two of them is not in the message. It is kept beside the view rather
than in the reducer (`state/` is not mine to edit), using React's own
adjust-state-during-render pattern rather than a ref — the linter's `react-hooks/refs` rule
forbids reading a ref during render, and it is right to.

## Assumptions

- The design has no dark variant, no error state and no disabled state. Dark is derived from
  the token set; error, connecting, disabled and ended-early carry the previous behaviour
  forward in the new visual language.
- `summary.kv` keys are labelled where known (`in`, `out`, `unpaid`) and printed under their
  own de-underscored name otherwise, so a field the engine starts sending appears on the
  board rather than disappearing from it. `lowest` is routed to the panel.
- The masthead says "nothing still needed" when the missing card is empty, and says nothing
  when it is not — the chips below already name what is missing, and a count of them would
  be a number the client worked out for itself.
- `capture_screens.py` was writing to `docs/plans/screens`, which does not exist; it now
  writes to `docs/process/screens`, where the ten screenshots actually live.

## Gates

All run from a clean tree, in this order:

| gate | result |
|---|---|
| `npm run lint` | clean |
| `npm run format:check` | clean |
| `npm run typecheck` | clean |
| `npm run test -- --run` | 265 passed, 25 files |
| `npm run build` | built (the >500 kB chunk warning is daily-js, and predates this work) |
| `uv run pytest -m e2e tests/e2e` | 7 passed, no page errors |

The ten screenshots under `docs/process/screens/` were regenerated from the fresh build.

## Left

- Nothing outstanding in my files, and nothing written to `requests.md`: no change was
  needed in `protocol/`, `call/`, `state/`, `mock/` or the domain.
- The panel has a tall empty run between the chart and the note in the `gathering` desktop
  state, where the plan will later sit. It reads as room rather than as a gap, but it is the
  one place the desktop board is looser than the design.
