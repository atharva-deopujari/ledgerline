# Design reference

`ledgerline-board-v2.dc.html` is the design canvas the frontend redesign was drawn from. It is a
reference, not runtime code: nothing in `frontend/` imports it, and it is never built or served.

It opens as a standalone page only alongside its generated runtime, which is deliberately not
parked here, so read it as a drawing of the board rather than something to run.

**Implemented from it:** the two-column board; the header wordmark, phase words and "still need"
line; the question headline; the card stack with `label / when / amount` columns, status word and
left status rule; the "Still need" chip row; the In / Out / Unpaid totals bar; the struck-through
figure a correction retires, beside the live one; the dark right column with its lowest-point
figure, thirty-day bar-and-line chart with hover readout and low-day marker, numbered plan list,
consequence line and confirm strip; the voice bar; the type pairing (Source Serif 4 for prose and
figures, Archivo for UI) and the colour palette.

**Treated as canvas fiction, not built:** the replay strip, play/pause and width toggle at the top
(`?mock=1` replays real generated snapshots instead); the six scripted states and their hard-coded
cards, totals and timelines; the count-up between old and new figures, which would put a number on
screen that no snapshot ever sent; the thirty-day series being invented from five points — the
chart plots the snapshot's own points, carried forward between them; and the note hidden behind a
hover or a pin, which is printed inline instead, because a note the board is keeping to itself is
a note nobody reading with their hands off the mouse will ever see.
