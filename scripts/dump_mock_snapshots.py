"""Write four real CardsMessage snapshots to frontend/src/mock/snapshots.json.

The reviewer-facing mock journey used hand-written cards, which drifted: a lowest balance its own
timeline contradicted, an unpaid row dated outside the window, an action verb the backend has no
enum for. These four come out of the real domain layer, so the mock cannot show anything the
engine could not produce.

    uv run python scripts/dump_mock_snapshots.py

Re-run it whenever the cards contract or the engine changes.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledgerline.domain.cards import CardsMessage, build_cards
from ledgerline.domain.engine import build_plan
from ledgerline.domain.models import DebtKind, FinancialState, ItemKind
from ledgerline.domain.state import upsert

TODAY = dt.date(2026, 9, 11)
OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "mock" / "snapshots.json"


def D(x: int | str) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


def gathering() -> FinancialState:
    """Mid-call: the salary was restated, which simply overwrites, and the electricity bill has
    not been given yet, so the "Still need" card is on screen."""
    state = FinancialState(today=TODAY)
    state.turn = 1
    upsert(state, ItemKind.BALANCE, "balance", amount=D(8000))
    upsert(state, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(state, ItemKind.ESSENTIAL, "groceries", amount=D(9000), spread=True, survival=True)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)
    upsert(state, ItemKind.ESSENTIAL, "electricity")
    state.turn = 3
    # 42,000 -> 45,000: the overwrite lands and the Outcome tells the model what moved.
    upsert(state, ItemKind.INCOME, "salary", amount=D(45000))
    return state


def ready() -> FinancialState:
    """Everything the plan needs, nothing left in doubt."""
    state = FinancialState(today=TODAY)
    state.turn = 1
    upsert(state, ItemKind.BALANCE, "balance", amount=D(8000))
    upsert(state, ItemKind.INCOME, "salary", amount=D(72000), day_of_month=1)
    upsert(state, ItemKind.ESSENTIAL, "groceries", amount=D(9000), spread=True, survival=True)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=D(18000), day_of_month=5)
    upsert(state, ItemKind.OPTIONAL, "streaming", amount=D(700), day_of_month=14)
    return state


def finalized() -> FinancialState:
    """A bike EMI that lands before the salary: one lender request, one uncovered obligation."""
    state = ready()
    upsert(
        state,
        ItemKind.DEBT,
        "bike emi",
        amount=D(4500),
        day_of_month=20,
        debt_kind=DebtKind.SECURED_EMI,
    )
    state.plan_final = True
    return state


def done() -> FinancialState:
    """Agreed AND over. The two are separate: `phase == "done"` comes from `understood`, `ended`
    from the call finishing, and a goodbye without agreement sets only the second."""
    state = finalized()
    state.understood = True
    state.call_ended = True
    return state


SNAPSHOTS = {
    "gathering": gathering,
    "ready": ready,
    "plan": finalized,
    "done": done,
}

FOCUS = {"gathering": "essentials", "ready": "summary", "plan": "plan", "done": "plan"}


def main() -> None:
    out: dict[str, object] = {}
    for version, (name, build) in enumerate(SNAPSHOTS.items(), start=1):
        state = build()
        message = build_cards(
            state,
            build_plan(state),
            version=version,
            focus=FOCUS[name],  # type: ignore[arg-type]
        )
        payload = message.model_dump_json()
        assert CardsMessage.model_validate_json(payload) == message
        assert len(payload.encode()) <= 4096, f"{name} is over the app-message limit"
        out[name] = json.loads(payload)
        print(
            f"{name:10} phase={message.phase:9} ended={str(message.ended):5} "
            f"cards={len(message.cards)} {len(payload)} bytes"
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
