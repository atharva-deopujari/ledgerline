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

import datetime as dt
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from ledgerline.agent.tools import facts, phrases
from ledgerline.agent.tools.coercion import (
    WINDOW_DAYS,
    Invalid,
    _amount,
    _debt_kind_for,
    _kind_of,
    _refused,
    _when,
)
from ledgerline.agent.tools.context import ToolContext
from ledgerline.agent.tools.phrases import spoken_day
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
    "nothing was tried; one change per entry, in these words: 'skip <item>', 'pay <card> in "
    "full', 'move <item> to the 10th', '<item> is 4,000', '<item> 7 days late', '<item> 5,000 "
    "short'. forget is not a trial: it drops an item for real."
)
COULD_NOT_READ = "could not read {change!r}; "
NOT_TRIED = " Nothing was tried; forget is not a trial, it drops an item for real."
SHIFT_PAST_WINDOW = (
    "{item} {days} days {direction} lands on {when}, after the window ends {end}; nothing was "
    "tried. Try '{item} is 0' to see the month without it."
)
SHIFT_BEFORE_TODAY = (
    "{item} {days} days {direction} lands on {when}, before today; nothing was tried."
)
NO_DATE_TO_MOVE = (
    "{item} has no one date to move, it is spread through the month; nothing was tried."
)
BELOW_ZERO = "{item} {amount} short takes it below zero; nothing was tried."

# What `what_if` understands. Free text in, a state edit out, and every edit is echoed back in
# the result so the model can read the hypothesis to the person and be corrected. The shapes are
# the ones the coach actually writes: the first after cell of the coaching frame sent 34 changes
# and 28 were refused, "salary arrives 7 days late" and "salary is 10,000 short" most of all --
# the very stresses the prompt names (REPORT 10.17). A shift is code's arithmetic on the copy.
SKIP = re.compile(r"^(?:skip|cut|drop|cancel|stop)\s+(?P<item>.+?)$", re.IGNORECASE)
IN_FULL = re.compile(r"^pay\s+(?P<item>.+?)\s+in full$", re.IGNORECASE)
# How a coach says a hypothesis -- "skip streaming this month", "drop the gym for now" -- and not
# part of any item's name. Two saved runs had the item read as "streaming this month", the tool
# refuse, and the coach reach for `forget` instead and lose the item for real.
TRAILING = re.compile(
    r"\s+(?:(?:for\s+)?(?:this month|this time|now)|instead of\s.+)$", re.IGNORECASE
)
# "the 1,800-rupee electricity bill": the amount is not part of the name.
RUPEE_TAG = re.compile(r"\b[\d,]+[-\s]rupee\s+", re.IGNORECASE)
# "reduce groceries by 2,000", "raise rent by 500": the amount moved, said as a verb.
BY = re.compile(
    r"^(?P<verb>reduce|cut|lower|raise|increase)\s+(?P<item>.+?)\s+by\s+(?P<amount>[\d,]+)"
    r"(?:\s+rupees)?$",
    re.IGNORECASE,
)
# "rent stays 13,000": a change that changes nothing, said as part of a hypothesis.
STAYS = re.compile(r"^(?P<item>.+?)\s+stays?\b", re.IGNORECASE)
# "salary arrives late, after 10 October": past the window, which only "is 0" can show.
LATE_AFTER = re.compile(
    r"^(?P<item>.+?)\s+(?:arrives?\s+|comes?\s+)?late,?\s+after\b", re.IGNORECASE
)
LATE_AFTER_WINDOW = (
    "{item} after the window ends {end} is a month without it; nothing was tried. Try "
    "'{item} is 0' to see it."
)
# "pay only the credit card minimum of 600 on 20 September": the opposite of paying in full, and
# the demo script's central what_if -- refused three times of three before this shape existed.
MINIMUM = re.compile(
    r"^pay\s+(?:only\s+)?(?:the\s+)?(?P<item>.+?)(?:'s)?\s+minimum(?:\s+due)?"
    r"(?:\s+of\s+[\d,]+)?(?:\s+on\s+.+)?$",
    re.IGNORECASE,
)
NO_MINIMUM = "no minimum on the books for {item}; nothing was tried."
# "gym membership of 1,500 from 18 September to 30 September": the amount and the old date are
# not part of the move.
OF_AMOUNT = re.compile(r"\s+of\s+[\d,]+(?:\s+rupees)?(?=\s|$)", re.IGNORECASE)
FROM_TO = re.compile(r"\s+from\s+.+?\s+(?=(?:to|on)\s)", re.IGNORECASE)
# "pay rent on 5 October", "keep groceries at 9,000": the verb is not the item.
LEAD = re.compile(r"^(?:pay|put|keep|make|move|shift|push)\s+", re.IGNORECASE)
_VERB = (
    r"(?:\s+(?:arrives?|arriving|comes?|coming|lands?|is paid|paid|is due|due|moves?|moved|"
    r"shifts?|shifted|goes|is|are)(?:\s+(?:\d+|an?|one|two|three|four|five|six|seven|ten)"
    r"\s+(?:days?|weeks?))?(?:\s+late|\s+early)?,?)?"
)
_N = r"(?P<n>\d+|an?|one|two|three|four|five|six|seven|ten)"
_UNIT = r"(?P<unit>days?|weeks?)"
_DIRECTION = r"(?P<direction>late|later|early|earlier)"
SHIFT = re.compile(rf"^(?P<item>.+?){_VERB}\s+{_N}\s+{_UNIT}\s+{_DIRECTION}$", re.IGNORECASE)
SHIFT_BY = re.compile(
    rf"^(?P<item>.+?){_VERB}\s+{_DIRECTION}\s+by\s+{_N}\s+{_UNIT}$", re.IGNORECASE
)
DELTA = re.compile(
    rf"^(?P<item>.+?){_VERB}\s+(?P<amount>[\d,]+)(?:\s+rupees)?"
    r"\s+(?P<direction>short|less|lower|more|higher|extra)$",
    re.IGNORECASE,
)
MOVE = re.compile(rf"^(?P<item>.+?){_VERB}\s+(?:to|on)\s+(?P<when>.+?)$", re.IGNORECASE)
SET = re.compile(
    r"^(?P<item>.+?)\s+(?:(?:is|are|to be|at)\s+)?(?P<amount>[\d,]+)(?:\s+rupees)?"
    r"(?:\s+on\s+(?P<when>.+?))?$",
    re.IGNORECASE,
)
# A date followed by more sentence -- ", while paying the card minimum and skipping the gym" --
# is two or three changes in one entry. `_when` reads the first day it finds and would apply
# half of it; a demo rehearsal had the coach explain the tool's own comparison was wrong.
CLAUSE = re.compile(r",|\b(?:while|and|but|then)\b", re.IGNORECASE)
NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "ten": 10,
}


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


def _resolve(state, item: str) -> tuple[ItemKind, str] | None:
    """Which item the person named -- its category and the name on the books -- or None.

    Matching is the domain's first: `remove` and `upsert` both resolve a name through `_find`,
    which knows that "the rent" and "my rent" are the rent. Then the person's word for a longer
    name: "gym" for "gym membership", "card" for "credit card", when exactly one item fits. The
    stored name is what comes back, so the edit lands and the echo says what the books say. Two
    fits is a question, not a guess.
    """
    key = state_ops.normalise_name(item)
    _, bare = state_ops.possessive_of(key)
    for kind, stored in _all_items(state):
        name = state_ops.normalise_name(stored.name)
        if name == key or state_ops.possessive_of(name)[1] == bare:
            return kind, stored.name
    fits = [
        (kind, stored.name)
        for kind, stored in _all_items(state)
        if bare and bare in state_ops.normalise_name(stored.name).split()
    ]
    return fits[0] if len(fits) == 1 else None


def _find_kind(state, item: str) -> ItemKind | None:
    found = _resolve(state, item)
    return found[0] if found else None


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
        have cancelled. Not for something they could skip or cut this month: that is what_if,
        which leaves the books alone.

        Args:
            item: What they call it. It is dropped from wherever it is on the books.
        """
        args = dict(item=item)
        if await replayed(params, "forget", args):
            return
        found = _resolve(ctx.state, item)
        if found is None:
            names = _on_the_books(ctx.state)
            await params.result_callback(
                NO_SUCH_ITEM.format(item=item, names=names) if names else NOTHING_ON_THE_BOOKS
            )
            return
        kind, item = found
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
        # "They said the plan makes sense" is what final means. Six of seven coaching-frame runs
        # ended here after a say-back and never called `show_month(final=True)`, so the screen
        # kept the plan as a draft. Settled only where a plan exists and nothing blocks it.
        if understood and engine_ops.build_plan(ctx.state).status is not PlanStatus.BLOCKED:
            ctx.state.plan_final = True
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
    hypothesis the person did not ask for is worse than a question. The refusal says nothing was
    tried and that `forget` is not a trial, because three saved runs answered a refusal here with
    `forget` and dropped the item from the real month.
    """
    text = RUPEE_TAG.sub("", TRAILING.sub("", change.strip().replace("-", " ")))
    text = FROM_TO.sub(" ", OF_AMOUNT.sub("", text))
    minimum = MINIMUM.match(text)
    if minimum:
        kind, item = _kind_or_refuse(trial, minimum.group("item"))
        debt = _find(trial, ItemKind.DEBT, item) if kind is ItemKind.DEBT else None
        if debt is None or debt.min_due is None:
            raise Invalid(NO_MINIMUM.format(item=item))
        # Paying the minimum is the card owing its minimum this month, on the copy: the smaller
        # sum lands on the due date and the rest is not this month's business.
        debt.amount_due, debt.min_due = debt.min_due, None
        return f"pay {item} minimum"
    after = LATE_AFTER.match(text)
    if after:
        item = after.group("item")
        _kind_or_refuse(trial, item)
        end = spoken_day(trial.today + dt.timedelta(days=WINDOW_DAYS - 1))
        raise Invalid(LATE_AFTER_WINDOW.format(item=item, end=end))
    stays = STAYS.match(text)
    if stays:
        _, item = _kind_or_refuse(trial, stays.group("item"))
        return f"{item} stays"
    by = BY.match(text)
    if by:
        return _delta(trial, by)
    skip = SKIP.match(text)
    if skip:
        kind, item = _kind_or_refuse(trial, skip.group("item"))
        state_ops.remove(trial, kind, item)
        return f"skip {item}"
    full = IN_FULL.match(text)
    if full:
        # The same identity the domain uses, not a second one: `_find` knows "my hdfc card" is the
        # hdfc card, and comparing normalised names here instead meant an alias matched no debt,
        # nothing changed on the copy, and the result still announced the change (KIRO-011).
        debt = _find(trial, ItemKind.DEBT, full.group("item"))
        if debt is None:
            raise Invalid(_no_such(trial, full.group("item")))
        # Paying in full is the absence of the minimum: with no minimum on the card the engine has
        # no smaller sum to propose, so the whole balance is what the month plans for. Set on the
        # item rather than through `upsert`, where None means "leave it alone".
        debt.min_due = None
        return f"pay {full.group('item')} in full"
    shift = SHIFT.match(text) or SHIFT_BY.match(text)
    if shift:
        return _shift(trial, shift)
    text = LEAD.sub("", text)
    delta = DELTA.match(text)
    if delta:
        return _delta(trial, delta)
    amount = SET.match(text)
    if amount:
        kind, item = _kind_or_refuse(trial, amount.group("item"))
        when = amount.group("when") or ""
        if CLAUSE.search(when):
            raise Invalid(COULD_NOT_READ.format(change=text) + WHAT_IF_SHAPES)
        fields = _when(when, trial.today) if when else {}
        state_ops.upsert(
            trial, kind, item, amount=_amount(_number(amount.group("amount"))), **fields
        )
        return f"{item} {amount.group('amount')}" + (f" on {when}" if when else "")
    moved = MOVE.match(text)
    if moved:
        if CLAUSE.search(moved.group("when")):
            raise Invalid(COULD_NOT_READ.format(change=text) + WHAT_IF_SHAPES)
        kind, item = _kind_or_refuse(trial, moved.group("item"))
        state_ops.upsert(trial, kind, item, **_when(moved.group("when"), trial.today))
        return f"{item} {moved.group('when')}"
    raise Invalid(COULD_NOT_READ.format(change=text) + WHAT_IF_SHAPES)


def _no_such(trial, item: str) -> str:
    return NO_SUCH_ITEM.format(item=item, names=_on_the_books(trial)) + NOT_TRIED


def _kind_or_refuse(trial, item: str) -> tuple[ItemKind, str]:
    """The category and the name on the books for the person's word, or the refusal."""
    found = _resolve(trial, item)
    if found is None:
        raise Invalid(_no_such(trial, item))
    return found


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _shift(trial, match: re.Match) -> str:
    """ "salary 7 days late": the item's own date moved by that many days, on the copy.

    `resolve_day` maps a day of month to its next occurrence, so a shift past the window would
    wrap to a date before today and plan the salary in the past; that is refused with where the
    shift lands and how to ask for the month without the item instead.
    """
    item = match.group("item")
    kind, item = _kind_or_refuse(trial, item)
    stored = _find(trial, kind, item)
    date = getattr(stored, "date", None) or getattr(stored, "due_date", None)
    if date is None:
        raise Invalid(NO_DATE_TO_MOVE.format(item=item))
    n = match.group("n").lower()
    days = NUMBER_WORDS.get(n) or int(n)
    if match.group("unit").lower().startswith("week"):
        days *= 7
    direction = "late" if match.group("direction").lower().startswith("late") else "early"
    landing = date + dt.timedelta(days=days if direction == "late" else -days)
    said = dict(item=item, days=days, direction=direction, when=spoken_day(landing))
    if landing > trial.today + dt.timedelta(days=WINDOW_DAYS - 1):
        end = spoken_day(trial.today + dt.timedelta(days=WINDOW_DAYS - 1))
        raise Invalid(SHIFT_PAST_WINDOW.format(end=end, **said))
    if landing < trial.today:
        raise Invalid(SHIFT_BEFORE_TODAY.format(**said))
    state_ops.upsert(trial, kind, item, day_of_month=landing.day)
    return f"{item} {days} days {direction}"


def _delta(trial, match: re.Match) -> str:
    """ "salary 10,000 short", "groceries 2,000 more": the amount moved by that much, on the
    copy."""
    kind, item = _kind_or_refuse(trial, match.group("item"))
    stored = _find(trial, kind, item)
    current = getattr(stored, "amount", None) if hasattr(stored, "amount") else stored.amount_due
    step = _amount(_number(match.group("amount")))
    word = (match.groupdict().get("direction") or match.group("verb")).lower()
    direction = "more" if word in ("more", "higher", "extra", "raise", "increase") else "short"
    new = (current or Decimal(0)) + (step if direction == "more" else -step)
    if new < 0:
        raise Invalid(BELOW_ZERO.format(item=item, amount=match.group("amount")))
    state_ops.upsert(trial, kind, item, amount=new)
    return f"{item} {match.group('amount')} {direction}"
