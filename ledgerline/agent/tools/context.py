"""The per-call context every handler shares."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal

from ledgerline.domain import cards as cards_ops
from ledgerline.domain import engine as engine_ops
from ledgerline.domain.cards import CardId, CardsMessage
from ledgerline.domain.models import FinancialState, PlanResult
from ledgerline.domain.state import normalise_name

PushCards = Callable[[CardsMessage], Awaitable[None]]
RequestEnd = Callable[[], Awaitable[None]]


class ToolContext:
    """Everything a handler needs. One per call. Owned by the voice session."""

    def __init__(
        self,
        state: FinancialState,
        push_cards: PushCards,
        request_end: RequestEnd | None = None,
    ) -> None:
        self.state = state
        self.push_cards = push_cards
        # The voice session's hang-up. None in the text harness, which has no transport.
        self.request_end = request_end
        self.cards_version = 0
        self.last_plan: PlanResult | None = None
        self.last_focus: CardId | None = None
        self._handled: dict[tuple[int, str, str], str] = {}
        self._balance_parts: dict[str, Decimal] = {}

    def balance_total(self, name: str, amount: Decimal) -> Decimal:
        """The opening balance after this part is added in.

        "I have" / "20,000 in cash and" / "20,000 in bank balance." is one utterance and two
        `note` calls. The domain keeps a single opening balance and ignores its name, so
        the second call replaced the first and a person with 40,000 was planned for as if they
        had 20,000. The model must not add the two itself — it must not add anything — so the
        tool does it, and the total comes back in the result where the model may read it.

        The parts live for the whole call, not for one turn. Review 13 found the turn-scoped
        version losing money in the commonest case there is: VAD cuts the utterance, the model
        answers the cash before the bank fragment lands, and the bank arrives in the next turn
        — where the parts had just been thrown away, so it replaced the cash instead of adding
        to it. A name already seen is that part again, however late: "the cash is actually
        twenty-five" corrects the cash and does not open a second pile of money.

        There is deliberately no heuristic for a name that sounds like a total. If somebody
        restates the whole balance under a new word the sum is spoken back to them and they can
        correct it, which is a better failure than silently planning on half. Restating a part by
        the name they gave it corrects that part, which is why there is no way to forget a
        balance: "actually the cash is five thousand" is a `note`, not a deletion.
        """
        self._balance_parts[normalise_name(name)] = amount
        return sum(self._balance_parts.values(), Decimal(0))

    def take_carried(self) -> list[tuple[str, str]]:
        """The carried figures, once. Empty for a first-time caller, and empty ever after."""
        carried, self._carried = self._carried, []
        return carried

    def _key(self, name: str, args: dict) -> tuple[int, str, str]:
        return (self.state.turn, name, json.dumps(args, sort_keys=True, default=str))

    def replay(self, name: str, args: dict) -> str | None:
        """The result of an identical call already handled this turn, if there was one.

        The model sometimes emits the same call two or four times for one utterance. Re-running
        is not harmless: each run pushes another cards message and bumps the version, so the
        screen redraws for nothing.
        """
        return self._handled.get(self._key(name, args))

    def remember(self, name: str, args: dict, result: str) -> None:
        self._handled[self._key(name, args)] = result

    async def recompute_and_push(self, focus: CardId | None) -> PlanResult:
        """Run build_plan, bump version, build cards, push. Returns the plan."""
        plan = engine_ops.build_plan(self.state)
        self.cards_version += 1
        message = cards_ops.build_cards(self.state, plan, version=self.cards_version, focus=focus)
        await self.push_cards(message)
        self.last_plan = plan
        self.last_focus = focus
        return plan
