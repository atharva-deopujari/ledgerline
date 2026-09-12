"""The six tools, as Pipecat direct functions.

They stay closures over the call's `ToolContext`: Pipecat derives each schema from a plain async
function whose first parameter is named `params`, and validates that shape when the pipeline is
built, so the function signature is the tool's public contract and cannot be reshaped freely.

Each handler: validate and coerce, call one domain function, push exactly one cards message, then
return one short result. Never await the network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ledgerline.agent.tools import phrases
from ledgerline.agent.tools.coercion import (
    Invalid,
    _amount,
    _day,
    _debt_kind,
    _field,
    _income_fields,
    _kind,
    _refused,
)
from ledgerline.agent.tools.context import ToolContext
from ledgerline.agent.tools.describe import _parked_fields, describe
from ledgerline.domain import state as state_ops
from ledgerline.domain.cards import CardId
from ledgerline.domain.models import Certainty, ItemKind, UnknownReason

TOOL_NAMES = (
    "upsert_item",
    "remove_item",
    "mark_unknown",
    "finalize_plan",
    "record_understanding",
    "end_call",
)

FOCUS_BY_KIND: dict[ItemKind, CardId] = {
    ItemKind.INCOME: CardId.INCOME,
    ItemKind.DEBT: CardId.DEBTS,
    ItemKind.ESSENTIAL: CardId.ESSENTIALS,
    ItemKind.OPTIONAL: CardId.OPTIONALS,
    ItemKind.BALANCE: CardId.SUMMARY,
}


def build_tools(ctx: ToolContext) -> list[Callable[..., Any]]:
    """Return the six direct functions bound to ctx, in TOOL_NAMES order, ready for
    LLMContext(tools=[...]). Each has a Google-style docstring Pipecat turns into the schema."""

    async def replayed(params: Any, name: str, args: dict) -> bool:
        """True when this exact call already ran this turn; its result is sent again."""
        previous = ctx.replay(name, args)
        if previous is None:
            return False
        await params.result_callback(previous)
        return True

    async def reply(params: Any, name: str, args: dict, result: str) -> None:
        ctx.remember(name, args, result)
        await params.result_callback(result)

    def told(outcome: Any, plan: Any, **extra: Any) -> str:
        """describe(), with the readiness and the declined fields this call has to be read
        against."""
        return describe(
            outcome,
            plan,
            state_ops.readiness(ctx.state),
            _parked_fields(ctx.state),
            **extra,
        )

    async def upsert_item(
        params: Any,
        kind: str,
        name: str,
        amount: float | None = None,
        day_of_month: int | None = None,
        debt_kind: str | None = None,
        min_due: float | None = None,
        spread: bool | None = None,
        survival: bool | None = None,
        flexible: bool | None = None,
        certainty: str | None = None,
        latest_day_of_month: int | None = None,
    ) -> None:
        """Record or change one financial fact. Call this the moment the person states or
        changes anything about their money, even when you only have part of it. It overwrites
        what was there and tells you what moved.

        Args:
            kind: One of income, debt, essential, optional, balance. Use balance for money in
                the account today; its name is ignored.
            name: What the person calls it, such as salary, rent, car loan, netflix.
            amount: Rupees, as a number. The FULL amount for this cycle: the monthly cost, the
                EMI, or a card's whole balance due.
            day_of_month: Day it arrives or is due, 1 to 31.
            debt_kind: For debts only: secured_emi, unsecured_emi, credit_card or informal.
            min_due: Credit cards only, and only when the person gives it: the smaller sum the
                card will accept this month instead of the full amount. Never the same as
                amount -- a minimum equal to the whole balance is not a minimum. If they did
                not say one, leave it out.
            spread: True when an essential is spread across the month, like groceries.
            survival: True for food, utilities and medicine.
            flexible: False when the person insists an optional expense stays.
            certainty: Income only: confirmed, estimated, or uncertain when it may not arrive.
            latest_day_of_month: Income only: the last day it could arrive, when they give a
                range. Put the earliest day in day_of_month.
        """
        args = dict(
            kind=kind,
            name=name,
            amount=amount,
            day_of_month=day_of_month,
            debt_kind=debt_kind,
            min_due=min_due,
            spread=spread,
            survival=survival,
            flexible=flexible,
            certainty=certainty,
            latest_day_of_month=latest_day_of_month,
        )
        if await replayed(params, "upsert_item", args):
            return
        try:
            item_kind = _kind(kind)
            fields = dict(
                amount=_amount(amount),
                day_of_month=_day(day_of_month),
                debt_kind=_debt_kind(debt_kind),
                min_due=_amount(min_due, "min_due"),
                spread=spread,
                survival=survival,
                flexible=flexible,
            )
            fields.update(_income_fields(item_kind, certainty, latest_day_of_month))
            if item_kind is ItemKind.BALANCE and fields["amount"] is not None:
                # Cash and bank said in one breath are two calls and one balance; the tool adds
                # them, because the domain keeps a single opening balance and the second call
                # would otherwise replace the first.
                fields["amount"] = ctx.balance_total(name, fields["amount"])
        except Invalid as bad:
            await params.result_callback(str(bad))
            return
        try:
            outcome = state_ops.upsert(ctx.state, item_kind, name, **fields)
        except ValueError as refusal:
            await params.result_callback(_refused(refusal))
            return
        plan = await ctx.recompute_and_push(FOCUS_BY_KIND[item_kind])
        result = told(outcome, plan)
        if certainty == Certainty.UNCERTAIN:
            result += "\nnot counted as money until it arrives"
        await reply(params, "upsert_item", args, result)

    async def remove_item(params: Any, kind: str, name: str) -> None:
        """Drop a fact that no longer applies, such as a loan they have finished paying.

        Args:
            kind: One of income, debt, essential, optional, balance.
            name: What the person calls it.
        """
        args = dict(kind=kind, name=name)
        if await replayed(params, "remove_item", args):
            return
        try:
            item_kind = _kind(kind)
        except Invalid as bad:
            await params.result_callback(str(bad))
            return
        try:
            outcome = state_ops.remove(ctx.state, item_kind, name)
        except ValueError as refusal:
            await params.result_callback(_refused(refusal))
            return
        plan = await ctx.recompute_and_push(FOCUS_BY_KIND[item_kind])
        await reply(params, "remove_item", args, told(outcome, plan))

    async def mark_unknown(params: Any, field: str, not_applicable: bool = False) -> None:
        """Note that something will not be answered, so you never ask for it again.

        Args:
            field: What is missing, such as essential:electricity.amount or opening_balance.
            not_applicable: True when there is none of it at all — no income, no card. False
                when they simply do not know the figure.
        """
        args = dict(field=field, not_applicable=not_applicable)
        if await replayed(params, "mark_unknown", args):
            return
        why = UnknownReason.NOT_APPLICABLE if not_applicable else UnknownReason.UNKNOWN
        try:
            outcome = state_ops.mark_unknown(ctx.state, _field(field), reason=why)
        except Invalid as bad:
            await params.result_callback(phrases.REFUSAL_FIELD.format(message=bad))
            return
        except ValueError as refusal:
            # The model invents field names here more than anywhere else — "other spending
            # details", "rent.due_day" — and the domain's own message ("'' is not a valid
            # ItemKind") names a type it has never seen, so that one gets the shape spelled out.
            # Every other refusal already says what to do ("a balance cannot be not applicable;
            # record it as zero"), and telling the model to fix the field name on top of it
            # points it at the wrong argument.
            template = (
                phrases.REFUSAL_FIELD if "ItemKind" in str(refusal) else phrases.REFUSAL_AS_GIVEN
            )
            await params.result_callback(template.format(message=str(refusal).rstrip(".")))
            return
        plan = await ctx.recompute_and_push(CardId.MISSING)
        await reply(params, "mark_unknown", args, told(outcome, plan, reason=why))

    async def finalize_plan(params: Any) -> None:
        """Work out the final 30 day plan. Call this only once nothing is blocking it and the
        person has agreed to hear it. It refuses and tells you what is still missing."""
        if await replayed(params, "finalize_plan", {}):
            return
        readiness = state_ops.readiness(ctx.state)
        if readiness.blockers:
            await params.result_callback(
                phrases.BLOCKED
                + ", ".join(state_ops.label_for(field) for field in readiness.blockers)
            )
            return
        ctx.state.plan_final = True
        plan = await ctx.recompute_and_push(CardId.PLAN)
        await reply(
            params,
            "finalize_plan",
            {},
            told(None, plan, headline=phrases.PLAN_FINAL, actions=True),
        )

    async def record_understanding(params: Any, confirmed: bool) -> None:
        """Record whether the person has understood the plan's actions and consequences, after
        you have asked them once.

        Args:
            confirmed: True when they say it makes sense. False when they sound unsure or ask a
                question, which is your cue to go over that one thing once more.
        """
        args = dict(confirmed=confirmed)
        if await replayed(params, "record_understanding", args):
            return
        if not ctx.state.plan_final or ctx.last_plan is None:
            await params.result_callback(phrases.NO_PLAN_YET)
            return
        ctx.state.understood = confirmed
        plan = await ctx.recompute_and_push(CardId.PLAN)
        if confirmed:
            # Nothing else: the next thing to happen is a goodbye, and a result that also
            # carries the cashflow invites one more sentence about the month instead.
            await reply(params, "record_understanding", args, phrases.UNDERSTOOD)
            return
        await reply(
            params,
            "record_understanding",
            args,
            told(None, plan, headline=phrases.EXPLAIN_AGAIN, actions=True),
        )

    async def end_call(params: Any, reason: str) -> None:
        """Finish the call. Use it once the person is happy with the plan, or any time they say
        they are done or say goodbye.

        Args:
            reason: Why the call is ending, in a few words.
        """
        args = dict(reason=reason)
        if await replayed(params, "end_call", args):
            return
        ctx.state.call_ended = True
        # Push before the transport goes away: readiness reads call_ended as the done phase, and
        # this is the snapshot that stops the screen asking a question the call has moved past.
        await ctx.recompute_and_push(CardId.PLAN)
        if ctx.request_end is not None:
            await ctx.request_end()
        await reply(params, "end_call", args, phrases.GOODBYE)

    return [
        upsert_item,
        remove_item,
        mark_unknown,
        finalize_plan,
        record_understanding,
        end_call,
    ]
