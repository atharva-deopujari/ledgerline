"""The plan engine. CONTRACT: one public function.

build_plan(state, policy) -> PlanResult

Pure. No I/O. Decimal only. See docs/architecture/02-hld.md section 5 and
docs/research/09-plan-engine.md for the algorithm and the ten reference scenarios.

Split by the step it belongs to: `events` turns the facts into dated money, `simulate` runs the
month, `settle` decides what cannot be funded, `actions` proposes the changes, `plan` is the order
they run in.
"""

from ledgerline.domain.engine.plan import build_plan

__all__ = ["build_plan"]
