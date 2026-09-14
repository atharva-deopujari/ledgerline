# Brief: from a plan to coaching

Decided by the owner on 14 Sep evening after the console landed: the plan reads as basic. On a healthy
month the engine has nothing to propose, `show_month` says "nothing to do: every payment is covered", and
prompt v2 gives the coach one sentence about advising ("explain it plainly, then agree what to do"). The
owner's line, which this brief holds to: do not make the engine clever; use the model's intelligence.

## The split, restated for this change

The model's intelligence is *what to ask the month*. The engine answers. The instrument for asking already
exists: `what_if` reruns the engine over a copy for any plain edit ("salary five days late", "rent on the
10th", "skip the gym", "pay the card in full") and returns the same picture plus the deltas. A coach with
a spreadsheet does not need the spreadsheet to guess which stress matters; they type it in. So:

- **Engine**: unchanged. (If, and only if, the measurement below shows the coach reaching for a figure it
  cannot get, one derivative may be added: cushion at the low point in days of everyday spending. Not
  before.)
- **Facts**: unchanged, except that `what_if`'s result must make comparison easy: the delta lines name what
  moved and by how much, and the low point and closing before and after sit side by side.
- **Prompt v2**: a coaching frame, written as what to do, under the 400 ceiling:
  - Before advising, test the month the way a coach would: `what_if` the salary landing late or short,
    the biggest bill moved, the discretionary items dropped, the card paid in full — whichever fit this
    person. Two or three, not all.
  - Then explain the shape in one breath (fine / tight before payday / more out than in), name the one
    risk that matters with its figure, propose two moves with what each does to the low point and the
    closing balance, and one habit for next month.
  - On a comfortable month say so and say what the cushion could do, rather than "nothing to do".
  - Check they understood by asking them to say back what they will do, not "does that make sense".
  - Figures still only from results; the derivation still read out when asked why.

## Measurement

Before/after, five runs each, on `owner_call_1` (a challenge and a correction) and `comfortable_surplus`
(the month with nothing to fix). Gates must not move: `money_traceable`, `state_matches_call`,
`speakable` at 100. What is expected to move: judge criteria `led_like_a_coach` and `low_point_explained`,
the count of `what_if` calls per run (0 today), and the length and content of the closing turns read by
the owner from the transcripts. Cap $0.30. Report section 10.17; provenance rows for every new prompt
line naming the failing case (the owner's own call: a comfortable month answered with a closing balance
and nothing else).

## Owner

Fresh session B. A, C, D stay frozen. The owner records the demo on the after build.
