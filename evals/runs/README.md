# Saved transcripts

Gitignored working evidence, not a fixture set. Every run of `evals/harness.py` and
`evals/run_suite.py` lands here as `<scenario>-<YYYYMMDD-HHMMSS>[-n].json`. The `-n` suffix
exists because five copies of a scenario run concurrently and two can finish inside one second;
before it was added, the second silently overwrote the first and the evidence for one failing
run was lost.

## Superseded recordings

Replaying today's checks over an old transcript judges it by rules that did not exist when it was
recorded, and against scenario files that have since changed. Three cases to know about:

- **`comfortable_surplus-20260911-2143*.json`, `-2145*`, `-2147*` (3 runs).** Recorded while the
  name `comfortable_surplus` held an opening balance of **8,000**; that scenario is now
  `timing_emi_before_salary`, and `comfortable_surplus` is the 20,000 version. The files were
  left byte-identical rather than relabelled, on purpose. `state_matches_facts` therefore reports
  `opening_balance is 8000.00, the person has 20000` on all three, and **the check is right while
  the pairing is stale** — it is comparing a run of one scenario against another scenario's facts.
  Superseded by the post-cut `timing_emi_before_salary` runs.

- **Anything before `20260912-2135`** is pre-cut: `upsert_item` still took `is_correction`, and
  the result strings were prose sentences rather than compact facts. Two defects visible only in
  these — a card recorded as 1,200 against a stated 3,000, and a rent recorded as 0.00 against a
  stated 9,000 — do not occur in any post-cut run. Do not quote them as live behaviour.

- **`comfortable_surplus-20260911-214731.json`** predates the ISO-date fix, so replaying the
  checks over it reports `no_iso_dates` violations that the current code cannot produce.

When a replay number is quoted anywhere, say which era it covers. The honest split is
pre-cut (before `20260912-2135`) and post-cut.
