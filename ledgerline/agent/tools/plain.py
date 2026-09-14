"""The plain-word tool set: what a person says, in the words they say it.

Six verbs instead of seven, and no schema for the model to reproduce. `note` takes an item, an
amount and when — "rent", 13000, "the 7th" — and code works out that rent is a bill, that the
seventh is a day of the month, and that a card is a credit card. Where a wrong translation would
move money the tool refuses with the question to ask instead, because the person can answer it
and the tool cannot.

Nothing here imports pipecat: each handler is a direct function whose docstring becomes the
schema, and the signature is the tool's public contract.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ledgerline.agent.tools import facts, phrases
from ledgerline.agent.tools.coercion import (
    Invalid,
    _amount,
    _debt_kind_for,
    _kind_of,
    _refused,
    _when,
)
from ledgerline.agent.tools.context import ToolContext
from ledgerline.domain import engine as engine_ops
from ledgerline.domain import state as state_ops
from ledgerline.domain.cards import CardId
from ledgerline.domain.models import Certainty, ItemKind, PlanStatus, UnknownReason
from ledgerline.domain.state.items import _find

TOOL_NAMES = ("note", "forget", "nothing_more", "show_month", "what_if", "done")

FOCUS_BY_KIND: dict[ItemKind, CardId] = {
    ItemKind.INCOME: CardId.INCOME,
    ItemKind.DEBT: CardId.DEBTS,
    ItemKind.ESSENTIAL: CardId.ESSENTIALS,
    ItemKind.OPTIONAL: CardId.OPTIONALS,
    ItemKind.BALANCE: CardId.SUMMARY,
}

# The categories `nothing_more(of=...)` can answer, in the words a person uses. "changes" is the
# returning caller's "it is all the same as last time".
OF_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("changes", ("change", "last call", "last time", "same as")),
    (ItemKind.INCOME.value, ("income", "coming in", "salary", "earn")),
    (ItemKind.ESSENTIAL.value, ("bill", "essential", "rent", "household")),
    (ItemKind.DEBT.value, ("loan", "card", "debt", "emi", "owe")),
    (ItemKind.OPTIONAL.value, ("spending", "optional", "extras", "day to day")),
    ("opening_balance", ("balance", "account", "cash", "savings")),
)

ASK_WHAT_OF = (
    "Say what there is no more of: money coming in, bills, loans and cards, everyday spending, "
    "or changes since the last call. For one missing detail use `about` instead."
)
BALANCE_IS_NEVER_NONE = (
    "A balance is never none — everybody has some number, even zero. Note it as zero if that is "
    "what they have."
)
NO_SUCH_ITEM = "Nothing called {item!r} is on the books. On the books: {names}."
NOTHING_ON_THE_BOOKS = "Nothing is on the books yet."
WHICH_DETAIL = (
    "Say which detail of which item, like 'the electricity amount' or 'the rent due date'. "
    "On the books: {names}."
)
WHAT_IF_SHAPES = (
    "I can try: 'skip <item>', 'pay <card> in full', 'move <item> to the 10th', "
    "'<item> is 4,000'. Send each change in those words."
)

# What `what_if` understands. Free text in, a state edit out, and every edit is echoed back in
# the result so the model can read the hypothesis to the person and be corrected.
SKIP = re.compile(r"^(?:skip|cut|drop|cancel|stop)\s+(?P<item>.+?)$", re.IGNORECASE)
IN_FULL = re.compile(r"^pay\s+(?P<item>.+?)\s+in full$", re.IGNORECASE)
MOVE = re.compile(r"^(?:move\s+)?(?P<item>.+?)\s+(?:to|on)\s+(?P<when>.+?)$", re.IGNORECASE)
SET = re.compile(
    r"^(?:make\s+)?(?P<item>.+?)\s+(?:is|to be|at)\s+(?P<amount>[\d,]+)$", re.IGNORECASE
)


def _all_items(state) -> list[tuple[ItemKind, Any]]:
    return [
        (kind, item)
        for kind, attribute in (
            (ItemKind.INCOME, "incomes"),
            (ItemKind.DEBT, "debts"),
            (ItemKind.ESSENTIAL, "essentials"),
            (ItemKind.OPTIONAL, "optionals"),
        )
        for item in getattr(state, attribute)
    ]


def _on_the_books(state) -> str:
    names = [item.name for _, item in _all_items(state)]
    return ", ".join(names) if names else ""


def _find_kind(state, item: str) -> ItemKind | None:
    """Which category an item the person named is filed under, or None when nothing matches.

    Matching is the domain's: `remove` and `upsert` both resolve a name through `_find`, which
    knows that "the rent" and "my rent" are the rent. Rather than reimplement that rule here --
    it has drifted twice between this layer and the domain -- the name is normalised the same way
    and compared against what is stored.
    """
    key = state_ops.normalise_name(item)
    _, bare = state_ops.possessive_of(key)
    for kind, stored in _all_items(state):
        name = state_ops.normalise_name(stored.name)
        if name == key or state_ops.possessive_of(name)[1] == bare:
            return kind
    return None


def _detail_field(state, about: str) -> str:
    """ "the electricity amount" -> "essential:electricity.amount".

    The item is whatever on the books the phrase names; the attribute is the word for it. Both
    have to land, because a field id that names nothing parks a gap the person can never place.
    """
    text = state_ops.normalise_name(about)
    matches = [
        (kind, item)
        for kind, item in _all_items(state)
        if state_ops.normalise_name(item.name) in text
    ]
    if not matches:
        raise Invalid(WHICH_DETAIL.format(names=_on_the_books(state) or "nothing yet"))
    kind, item = max(matches, key=lambda pair: len(pair[1].name))
    if "minimum" in text or "min due" in text:
        attribute = "min_due"
    elif any(word in text for word in ("date", "day", "when", "due")):
        attribute = "date" if kind in (ItemKind.INCOME, ItemKind.OPTIONAL) else "due_date"
    else:
        attribute = "amount"
    return state_ops.field_of(kind, item.name, attribute)


def build_tools(ctx: ToolContext) -> list[Callable[..., Any]]:
    """The six plain tools bound to ctx, in TOOL_NAMES order, for LLMContext(tools=[...])."""

    async def replayed(params: Any, name: str, args: dict) -> bool:
        previous = ctx.replay(name, args)
        if previous is None:
            return False
        await params.result_callback(previous)
        return True

    async def reply(params: Any, name: str, args: dict, result: str) -> None:
        ctx.remember(name, args, result)
        await params.result_callback(result)

    async def note(
        params: Any,
        item: str,
        amount: float | None = None,
        when: str = "",
        kind: str | None = None,
        might_not_arrive: bool | None = None,
        minimum_due: float | None = None,
        must_pay: bool | None = None,
    ) -> None:
        """Write down something about their money, in their words. Call it the moment they say
        anything about a figure, a date or a bill, even if you only have part of it, and before
        you tell them you have noted anything.

        Args:
            item: What they call it — "rent", "my salary", "the HDFC card", "cash in hand".
                Money in the account said in parts is one call per part: "20,000 in cash and
                20,000 in the bank" is a call for the cash and a call for the bank, and the tool
                adds them. Never add two amounts yourself.
            amount: Rupees, as a number. The whole amount for the month: the monthly cost, the
                EMI, or a card's full balance.
            when: When it arrives or is due, in their words — "the 7th", "end of the month",
                "spread through the month".
            kind: Only when the item alone does not say it: "money coming in", "bill", "loan or
                card", "everyday spending", or "balance" for what is in the account today.
            might_not_arrive: True when income is not certain — piece work, a bonus, a client who
                may not pay. It is then left out of the figures until it lands.
            minimum_due: A credit card's minimum for this month, when they give one.
            must_pay: True when this is food, power, medicine or anything they cannot go without,
                or when they insist a discretionary expense stays. Leave it out otherwise.
        """
        args = dict(
            item=item,
            amount=amount,
            when=when,
            kind=kind,
            might_not_arrive=might_not_arrive,
            minimum_due=minimum_due,
            must_pay=must_pay,
        )
        if await replayed(params, "note", args):
            return
        # An argument that only exists for one kind says which kind it is: nothing but income
        # might not arrive, and nothing but a card has a minimum due.
        if not kind and might_not_arrive is not None:
            kind = "income"
        elif not kind and minimum_due is not None:
            kind = "card"
        vague_date = ""
        try:
            item_kind = _kind_of(item, kind)
            fields: dict[str, Any] = {}
            if item_kind is not ItemKind.BALANCE:
                try:
                    fields.update(_when(when, ctx.state.today))
                except Invalid as unusable:
                    # The figure lands anyway. Refusing the whole call over a date cost the
                    # first v2 run its rent: the person said "around 13,000, first week of
                    # October", the tool refused the lot, and nothing was on the books ten turns
                    # later. A date nobody can pin down is a fact to report, not a reason to
                    # lose an amount.
                    vague_date = str(unusable)
            fields["amount"] = _amount(amount)
            if minimum_due is not None:
                fields["min_due"] = _amount(minimum_due, "minimum_due")
            if might_not_arrive is not None and item_kind is ItemKind.INCOME:
                fields["certainty"] = (
                    Certainty.UNCERTAIN if might_not_arrive else Certainty.CONFIRMED
                )
            if must_pay is not None:
                if item_kind is ItemKind.ESSENTIAL:
                    fields["survival"] = must_pay
                elif item_kind is ItemKind.OPTIONAL:
                    fields["flexible"] = not must_pay
            part = fields.get("amount")
            if item_kind is ItemKind.BALANCE and part is not None:
                # Cash and bank said in one breath are two calls and one balance. The domain
                # keeps a single opening balance, so the second call would replace the first and
                # plan the month on half the money; the tool adds them and the total comes back
                # in the result for the model to read out.
                fields["amount"] = ctx.balance_total(item, part)
        except Invalid as bad:
            await params.result_callback(str(bad))
            return
        try:
            outcome = state_ops.upsert(ctx.state, item_kind, item, **fields)
        except ValueError as refusal:
            if "debt_kind" not in str(refusal):
                await params.result_callback(_refused(refusal))
                return
            # A new debt has to be some kind of debt, and the person never says the word. What
            # they call it says it: a card is a card, a car loan is secured. Asking the domain
            # first rather than sending a kind every time keeps an existing card from being
            # refiled as a loan when they mention it again.
            outcome = state_ops.upsert(
                ctx.state, item_kind, item, debt_kind=_debt_kind_for(item), **fields
            )
        await ctx.recompute_and_push(FOCUS_BY_KIND[item_kind])
        said = facts.recorded(outcome, ctx.state)
        await reply(params, "note", args, f"{said}\n{vague_date}" if vague_date else said)

    async def forget(params: Any, item: str) -> None:
        """Drop something that no longer applies — a loan they have finished paying, a bill they
        have cancelled.

        Args:
            item: What they call it. It is dropped from wherever it is on the books.
        """
        args = dict(item=item)
        if await replayed(params, "forget", args):
            return
        kind = _find_kind(ctx.state, item)
        if kind is None:
            names = _on_the_books(ctx.state)
            await params.result_callback(
                NO_SUCH_ITEM.format(item=item, names=names) if names else NOTHING_ON_THE_BOOKS
            )
            return
        outcome = state_ops.remove(ctx.state, kind, item)
        await ctx.recompute_and_push(FOCUS_BY_KIND[kind])
        await reply(params, "forget", args, facts.recorded(outcome, ctx.state))

    async def nothing_more(params: Any, of: str = "", about: str = "") -> None:
        """Record that there is no more of something, or that one detail will not be answered.
        Either way it stops being a gap and you never ask again.

        Args:
            of: A whole category they have finished with or have none of — "money coming in",
                "bills", "loans and cards", "everyday spending" — or "changes" when a returning
                caller says everything is the same as last time.
            about: One detail nobody can give, in their words: "the electricity amount", "the
                rent due date".
        """
        args = dict(of=of, about=about)
        if await replayed(params, "nothing_more", args):
            return
        answer = next(
            (value for value, words in OF_WORDS if any(w in of.lower() for w in words)), None
        )
        # A category answered outright wins over a detail: the first v2 run sent both at once --
        # of="bills", about="other expenses right now" -- and the detail, which named nothing on
        # the books, swallowed the answer that did.
        if about and answer is None:
            try:
                field = _detail_field(ctx.state, about)
            except Invalid as bad:
                await params.result_callback(str(bad))
                return
            outcome = state_ops.mark_unknown(ctx.state, field, UnknownReason.UNKNOWN)
            await ctx.recompute_and_push(CardId.MISSING)
            await reply(
                params,
                "nothing_more",
                args,
                facts.recorded(outcome, ctx.state, reason=UnknownReason.UNKNOWN),
            )
            return
        if answer is None:
            await params.result_callback(
                ASK_WHAT_OF
                if not about
                else WHICH_DETAIL.format(names=_on_the_books(ctx.state) or "nothing yet")
            )
            return
        if answer == "opening_balance":
            await params.result_callback(BALANCE_IS_NEVER_NONE)
            return
        if answer == "changes":
            try:
                outcome = state_ops.confirm_carried(ctx.state, None)
            except ValueError as refusal:
                await params.result_callback(_refused(refusal))
                return
        else:
            outcome = state_ops.none_of(ctx.state, ItemKind(answer))
        await ctx.recompute_and_push(CardId.SUMMARY)
        await reply(
            params,
            "nothing_more",
            args,
            facts.recorded(outcome, ctx.state, reason=UnknownReason.NOT_APPLICABLE),
        )

    async def show_month(params: Any, final: bool = False) -> None:
        """Look at their whole month. Call it whenever you want the figures — to explain where
        they stand, to answer a question about a number, or when you have heard enough to plan.

        It returns what has been recorded and what has not come up, every item, what comes in
        and goes out, the lowest point with the arithmetic behind it, everything they could do
        and what each costs, and anything left out of the figures.

        When they ask why a figure is what it is, or say it looks wrong, the lines under "why the
        lowest point is" are the answer: read them out. They are the whole calculation, in order,
        and reading them is how you answer without working anything out yourself.

        Args:
            final: True only once you have talked it through and they have agreed this is the
                plan. It marks the plan final on their screen.
        """
        args = dict(final=final)
        if await replayed(params, "show_month", args):
            return
        plan = engine_ops.build_plan(ctx.state)
        settled = final and plan.status is not PlanStatus.BLOCKED
        ctx.state.plan_final = ctx.state.plan_final or settled
        plan = await ctx.recompute_and_push(CardId.PLAN if final else None)
        await reply(
            params, "show_month", args, facts.month(ctx.state, plan, final=ctx.state.plan_final)
        )

    async def what_if(params: Any, changes: list[str]) -> None:
        """Try a change without making it. Runs their month again with the change in place and
        tells you what moves.

        Args:
            changes: One or more in plain words: "skip gym", "pay the HDFC card in full",
                "move rent to the 10th", "groceries is 4000".
        """
        args = dict(changes=list(changes))
        if await replayed(params, "what_if", args):
            return
        trial = ctx.state.model_copy(deep=True)
        applied = []
        for change in changes:
            try:
                applied.append(_apply(trial, change))
            except Invalid as bad:
                await params.result_callback(str(bad))
                return
        now = engine_ops.build_plan(trial)
        against = ctx.last_plan or engine_ops.build_plan(ctx.state)
        await reply(
            params,
            "what_if",
            args,
            facts.month(trial, now, applied=applied, against=against),
        )

    async def done(params: Any, understood: bool, reason: str = "") -> None:
        """End the call. Use it when they are happy with the plan, or any time they say they are
        finished.

        Args:
            understood: True when they have said the plan makes sense to them, false when the
                call is ending without that.
            reason: Why it is ending, in a few words.
        """
        args = dict(understood=understood, reason=reason)
        if await replayed(params, "done", args):
            return
        ctx.state.understood = understood
        ctx.state.call_ended = True
        # Pushed before the transport goes away: this is the snapshot that stops the screen
        # asking a question the call has moved past.
        await ctx.recompute_and_push(CardId.PLAN)
        if ctx.request_end is not None:
            await ctx.request_end()
        await reply(params, "done", args, phrases.GOODBYE)

    return [note, forget, nothing_more, show_month, what_if, done]


def _apply(trial, change: str) -> str:
    """One plain edit against a copy of the month. Returns what was applied, for the result.

    Nothing is guessed: an edit it cannot read is refused with the shapes it can, because a
    hypothesis the person did not ask for is worse than a question.
    """
    text = change.strip()
    kind = None
    skip = SKIP.match(text)
    if skip:
        kind = _find_kind(trial, skip.group("item"))
        if kind is None:
            raise Invalid(NO_SUCH_ITEM.format(item=skip.group("item"), names=_on_the_books(trial)))
        state_ops.remove(trial, kind, skip.group("item"))
        return f"skip {skip.group('item')}"
    full = IN_FULL.match(text)
    if full:
        # The same identity the domain uses, not a second one: `_find` knows "my hdfc card" is the
        # hdfc card, and comparing normalised names here instead meant an alias matched no debt,
        # nothing changed on the copy, and the result still announced the change (KIRO-011).
        debt = _find(trial, ItemKind.DEBT, full.group("item"))
        if debt is None:
            raise Invalid(NO_SUCH_ITEM.format(item=full.group("item"), names=_on_the_books(trial)))
        # Paying in full is the absence of the minimum: with no minimum on the card the engine has
        # no smaller sum to propose, so the whole balance is what the month plans for. Set on the
        # item rather than through `upsert`, where None means "leave it alone".
        debt.min_due = None
        return f"pay {full.group('item')} in full"
    amount = SET.match(text)
    if amount:
        kind = _find_kind(trial, amount.group("item"))
        if kind is None:
            raise Invalid(
                NO_SUCH_ITEM.format(item=amount.group("item"), names=_on_the_books(trial))
            )
        state_ops.upsert(
            trial,
            kind,
            amount.group("item"),
            amount=_amount(float(amount.group("amount").replace(",", ""))),
        )
        return f"{amount.group('item')} {amount.group('amount')}"
    moved = MOVE.match(text)
    if moved:
        kind = _find_kind(trial, moved.group("item"))
        if kind is None:
            raise Invalid(NO_SUCH_ITEM.format(item=moved.group("item"), names=_on_the_books(trial)))
        state_ops.upsert(
            trial, kind, moved.group("item"), **_when(moved.group("when"), trial.today)
        )
        return f"{moved.group('item')} {moved.group('when')}"
    raise Invalid(WHAT_IF_SHAPES)
