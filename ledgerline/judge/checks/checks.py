"""Deterministic transcript checks: the rules that gate a run.

Number reading lives in `checks.spoken_numbers`, and the question of which figures are still
sayable in `checks.provenance`. Both are re-exported here, because a transcript check is the only
reason either exists and the tests reach for them by this name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ledgerline.agent.tools import phrases
from ledgerline.domain.models import Coverage, FinancialState, ItemKind
from ledgerline.domain.state import coverage, normalise_name
from ledgerline.judge.checks.provenance import (
    _same_item,
    _sources_up_to,
    carried_numbers,
)
from ledgerline.judge.checks.spoken_numbers import ISO_DATE, TRACE_FLOOR, numbers_in

# The one import of application code in this file: item identity has to match the domain's, or a
# correction spelled "the rent" against an original "rent" looks like a different item and the
# stale amount is never retired. evals is outside the import-linter contracts, which cover the
# ledgerline package only.

# The planner never proposes getting new money: no loan, no BNPL, no shopkeeper's tab, nothing
# from family. Two halves to that.
#
# First, phrases that propose money in any context. These come from Session A's predicate in
# tests/domain/conftest.py, kept in the same shape so the engine's own text and the spoken
# transcript are judged by one rule — with two deliberate omissions. A bans the bare words "loan"
# and "borrow", which is right for engine-authored text but wrong here: a transcript has to be
# able to say "your personal loan is due on the twentieth" and "you borrowed that from your
# brother". Those two are covered by the proposal patterns below instead.
PROPOSES_MONEY = (
    "bnpl",
    "overdraft",
    "buy now",
    "pay later",
    "advance from",
    "lend you",
    "lend me",
    "a tab",
    "on tab",
    "instalment plan",
    "installment plan",
)

# The only honest uses of the word "credit": a record the person already has. Anything else is an
# offer — "a few days' credit" is new money. Session A's rule, verbatim.
# "record", "history" and "file" were added after five runs paraphrased the engine's own
# "nothing reaches your credit report" as "affect your credit record": the same record the person
# already has, and naming what a missed payment does to it is the job.
# "Credited" is not credit: in Indian English a salary is credited to an account, and that is
# the most ordinary sentence in this product -- "when do you expect it to be credited?" failed
# this gate on the first v2 run. The verb describes money arriving, which is the opposite of an
# offer.
CREDIT_IS_ABOUT = (
    "credited",
    "crediting",
    "credits to",
    "credit bureau",
    "credit report",
    "credit card",
    "credit score",
    "credit record",
    "credit history",
    "credit file",
)

# Second, language that proposes or promises without naming one of those phrases, and claims to
# have acted. Naming a debt the person already has is not only allowed, it is the job.
BANNED_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "recommends new borrowing",
        r"\b(take|taking|get|getting|apply for|applying for|consider|considering|opt for|go for)"
        r"\b[^.?!]{0,25}\b(a|an|another)\s+(new\s+|small\s+|personal\s+|top[-\s]?up\s+)*"
        r"(loan|overdraft|advance|credit card|credit line)\b",
    ),
    ("suggests borrowing", r"\b(you (could|should|can|might)|why not)\b[^.?!]{0,30}\bborrow\b"),
    ("suggests borrowing", r"\bborrow (more|money|from|against)\b"),
    ("suggests a top-up loan", r"\btop[-\s]?up (loan|on your loan)\b"),
    ("suggests buy now pay later", r"\b(bnpl|buy now,? pay later)\b"),
    ("suggests converting to EMI", r"\bemi conversion\b|\bconvert[^.?!]{0,20}\bto emi\b"),
    ("suggests a settlement", r"\bsettlement offer\b|\bsettle (your|the) (card|loan|debt)\b"),
    (
        "promises an outcome",
        r"\b(pre[-\s]?approved|approved|guaranteed|you are eligible|eligible)\b",
    ),
    ("claims to have acted", r"\bi('ve| have) (paid|transferred|made the payment|arranged)\b"),
)

MARKDOWN = re.compile(r"[*#`|_]|^\s*[-+]\s", re.MULTILINE)


@dataclass(frozen=True)
class Violation:
    rule: str
    turn: int
    detail: str


def _offered_readings(turn: dict) -> set[int]:
    """Figures the model may put up for the person to accept or reject, in a turn it was told to
    settle an implausible amount.

    `phrases.CONFIRM_AMOUNT` asks it to check a figure that is too small to be real, and the only
    useful way to ask is to name the reading the person probably meant: "twelve rupees, or did
    you mean twelve thousand?". That twelve thousand is in no result and no user turn, so the
    two rules were failing each other -- three runs in five, on the first live matrix after the
    instruction landed.

    Narrow on purpose. The licence exists only in a turn whose own result asked for it, and only
    inside a question: offering a reading is a question, and telling somebody what they pay is a
    claim. The constant is imported rather than copied, unlike the implausibility floors, because
    this rule is ABOUT the product's instruction and should follow it if the wording changes.
    """
    results = " ".join(str(c.get("result", "")) for c in turn.get("tool_calls", ()))
    if phrases.CONFIRM_AMOUNT not in results:
        return set()
    return {n for question in _questions(turn["text"].lower()) for n in numbers_in(question)}


def _numbers_traceable(transcript: dict) -> list[Violation]:
    """Every figure the assistant says came back in a tool result or from the person."""
    out = []
    turns = transcript["turns"]
    carried = carried_numbers(transcript)
    for i, turn in enumerate(turns):
        if turn["role"] != "assistant":
            continue
        allowed = _sources_up_to(turns, i) | _offered_readings(turn) | carried
        invented = {n for n in numbers_in(turn["text"]) if n >= TRACE_FLOOR} - allowed
        if invented:
            out.append(
                Violation("numbers_traceable", i, f"not in any tool result: {sorted(invented)}")
            )
    return out


def _loose_credit(text: str) -> bool:
    """ "credit" not followed by bureau, report, card or score. Session A's predicate.

    Hyphens are spelling, not meaning: "the credit-card minimum" is the card the person already
    has, and a live run failed this gate for saying so. They are flattened to spaces first.
    """
    text = text.replace("-", " ").replace("\u2011", " ")
    at = 0
    while (found := text.find("credit", at)) != -1:
        if not any(text.startswith(ok, found) for ok in CREDIT_IS_ABOUT):
            return True
        at = found + len("credit")
    return False


def _banned_phrases(transcript: dict) -> list[Violation]:
    """Proposing new money, promising an outcome, or claiming to have acted."""
    out = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] != "assistant":
            continue
        text = turn["text"].lower()
        hits = {label for label, pattern in BANNED_PATTERNS if re.search(pattern, text)}
        hits |= {"proposes new money" for phrase in PROPOSES_MONEY if phrase in text}
        if _loose_credit(text):
            hits.add("offers credit")
        if hits:
            out.append(Violation("banned_phrases", i, ", ".join(sorted(hits))))
    return out


def _no_markdown(transcript: dict) -> list[Violation]:
    out = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] == "assistant" and MARKDOWN.search(turn["text"]):
            out.append(Violation("no_markdown", i, turn["text"]))
    return out


def _no_iso_dates(transcript: dict) -> list[Violation]:
    """A date read as digits. Text to speech says "2026-10-10" one digit at a time, and the
    per-turn prompt block is where the model picks the habit up."""
    out = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] != "assistant":
            continue
        found = ISO_DATE.findall(turn["text"])
        if found:
            out.append(Violation("no_iso_dates", i, ", ".join(found)))
    return out


# Tools that record something the person just said, and so have an acknowledgement to speak
# first. finalize_plan and end_call answer a request instead: there is nothing to echo, and the
# model rightly calls them before it speaks.


QUESTION = re.compile(r"[^.?!]*\?")


def _questions(text: str) -> list[str]:
    """The question clauses in a turn, and only those.

    A semicolon is not a full stop, so "the electricity amount is parked as not known; when is
    your rent due?" arrived as one question sentence carrying the word "amount" — and the rule
    read the report half as the asking half. Only the clause the question mark belongs to counts.
    """
    return [q.rpartition(";")[2].strip() for q in QUESTION.findall(text)]


# Where each kind of hidden fact is stored, and under which field the domain keeps its figure.
# Debts are the odd one: the money is `amount_due`, because a debt also has a `min_due`.
_FACT_GROUPS = (
    ("incomes", "income", "amount"),
    ("essentials", "essential", "amount"),
    ("debts", "debt", "amount_due"),
    ("optionals", "optional", "amount"),
)


def _money(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (ArithmeticError, TypeError):
        return None


def _parked(state: dict, name: str) -> bool:
    """Whether the person declined this field. "I don't know" is an answer, and a coach that
    parked it did what it was told; the gap is the person's, not the bot's."""
    key = normalise_name(name)
    for unknown in state.get("unknowns", ()):
        field = str(unknown.get("field", ""))
        head = field.partition(".")[0].partition(":")[2] or field
        if head == key or _same_item(key, head):
            return True
    return False


def _state_matches_facts(transcript: dict) -> list[Violation]:
    """The recorded state says what the person actually said.

    Every other rule in this file reads what the bot SAID. This one reads what it WROTE DOWN,
    which is what the plan is built from, and it exists because of a defect all eleven of the
    others passed: `fragmented_balance` says "20,000 in cash and 20,000 in bank balance" in three
    fragments, and in fifteen consecutive runs the model recorded one balance of 20,000 and
    planned the person's month on half their money. Nothing was invented, the read-back matched
    the result, and no value changed, so there was nothing for the other rules to see.

    A fact the person declined is excused. An item the bot named differently is matched the way
    the domain matches it, so a correctly recorded fact under a possessive is not reported lost.
    A transcript with no persona behind it -- a real call -- is not judged at all.
    """
    hidden, state = transcript.get("hidden_facts"), transcript.get("state")
    if not hidden or not state:
        return []
    turns = transcript.get("turns", ())
    turn = max(len(turns) - 1, 0)
    said = {n for t in turns if t.get("role") == "user" for n in numbers_in(t.get("text", ""))}
    out = []

    expected = _money(hidden.get("opening_balance"))
    if expected is not None:
        stored = _money(state.get("opening_balance"))
        if stored is None:
            if not _parked(state, "opening_balance"):
                out.append(Violation("state_matches_facts", turn, "opening_balance never recorded"))
        elif stored != expected:
            out.append(
                Violation(
                    "state_matches_facts",
                    turn,
                    f"opening_balance is {stored:g}, the person has {expected:g}",
                )
            )

    for group, kind, money_field in _FACT_GROUPS:
        for fact in hidden.get(group, ()) or ():
            want = _money(fact.get("amount"))
            name = str(fact.get("name", ""))
            if want is None or not name:
                continue
            key = normalise_name(name)
            items = state.get(group, ()) or []
            match = next(
                (
                    item
                    for item in items
                    if _same_item(key, normalise_name(str(item.get("name", ""))))
                ),
                None,
            )
            if match is None:
                # The figure under another noun is the same fact. What the person calls their
                # money is language and the cut gave language to the model: a persona's "client
                # payments" recorded as "freelance income" is the coach paraphrasing, not losing
                # it, and reporting that as a lost fact failed all 51 runs of one scenario.
                match = next((i for i in items if _money(i.get(money_field)) == want), None)
            if match is None:
                # Only a fact the person actually stated is owed. `hidden_facts` is the persona's
                # whole truth, and the scripted turns deliberately keep some of it back -- the
                # "Nothing." in `one_word_answers` is the person declining to mention the phone
                # EMI, not the bot losing it. Judging the notes instead of the conversation
                # failed 84% of all saved runs and would have been noise, not a net.
                if want in said and not _parked(state, name):
                    out.append(
                        Violation("state_matches_facts", turn, f"{kind} {name} never recorded")
                    )
                continue
            got = _money(match.get(money_field))
            if got is None and _parked(state, name):
                continue  # the item is on the books, the figure is one they could not give
            if got is None or got != want:
                out.append(
                    Violation(
                        "state_matches_facts",
                        turn,
                        f"{kind} {name} is {got if got is not None else 'unset'}, "
                        f"the person said {want:g}",
                    )
                )
            # A card's minimum is a second figure and a second way to be wrong. Recording the
            # full balance as the minimum means paying the minimum saves nothing, so the one
            # cheap action the engine can offer on a card quietly stops existing: the person is
            # planned as owing 3,000 this month when they could have paid 1,200. `amount_due` is
            # right in every one of those runs, so nothing else here could see it.
            minimum = _money(fact.get("min_due"))
            if minimum is not None:
                stored_min = _money(match.get("min_due"))
                if stored_min is None or stored_min != minimum:
                    out.append(
                        Violation(
                            "state_matches_facts",
                            turn,
                            f"{kind} {name} minimum is "
                            f"{stored_min if stored_min is not None else 'unset'}, "
                            f"the person said {minimum:g}",
                        )
                    )
    return out


# Verbs that propose a CHANGE to what happens, one family per `ActionType`. Deliberately not
# "keep", "set aside" or a bare "pay": telling somebody to have the rent ready on the eighteenth
# describes the plan's own timeline and proposes nothing, and a first cut that counted those
# failed 41% of post-cut runs on sentences that were doing the job correctly. What is left are
# the verbs that alter the month -- defer it, cut it, pay only part of it, ask the lender -- and
# those are exactly what the engine claims the right to decide. "at least" had to narrow to
# "pay at least" for the same reason: "keep at least 11,000 available for rent" is a due date
# being explained, not a part payment being proposed.
PROPOSAL_VERBS = (
    # DEFER_OPTIONAL
    "defer",
    "put off",
    "move it",
    "move the",
    "push it",
    "push the",
    "delay",
    "next month instead",
    # CUT_OPTIONAL
    "cut ",
    "drop ",
    "cancel",
    "stop paying",
    "skip ",
    # PAY_MIN_DUE
    "only the minimum",
    "pay at least",
    "minimum due",
    "minimum payment",
    # ASK_LENDER
    "ask the lender",
    "ask your lender",
    "ask them to move",
)

PLAN_FINAL_MARKER = "plan final"

# Tool names under both sets. v1 has seven verbs, the redesign has six plain ones, and a check
# that matched only the old names would silently stop measuring the moment v2 ran -- which is
# how a harness comes to report 100% on a call it never looked at.
PLANNING_TOOLS = frozenset({"finalize_plan", "show_month"})
RECORDING_A_FACT = frozenset({"upsert_item", "note"})
PARKING_TOOLS = frozenset({"mark_unknown", "nothing_more"})
ENDING_TOOLS = frozenset({"end_call", "done"})


def _plans(tool_call: dict) -> bool:
    """A call that settled the plan. `show_month` is also the read-only look at the month, so
    the result has to say the plan is final; `finalize_plan` only ever did the one thing."""
    return tool_call.get("name") in PLANNING_TOOLS and PLAN_FINAL_MARKER in str(
        tool_call.get("result", "")
    )


def _final_plan_result(turns: list[dict]) -> str | None:
    """The text of the last result that settled the plan, or None if the run never planned."""
    found = None
    for turn in turns:
        for tool_call in turn.get("tool_calls", ()):
            if _plans(tool_call):
                found = str(tool_call.get("result", ""))
    return found


def _item_names(state: dict) -> list[str]:
    return [
        normalise_name(str(item.get("name", "")))
        for group, _, _ in _FACT_GROUPS
        for item in state.get(group, ()) or []
        if item.get("name")
    ]


def _actions_match_plan(transcript: dict) -> list[Violation]:
    """Every action the assistant proposes was proposed by the engine.

    The gap this was written for: a run whose plan came back with a surplus and NO actions, where
    the bot went on to propose keeping money aside for rent and paying a card minimum. Both
    figures were traceable, because both had been recorded earlier in the call, so a run invented
    an entire course of action and passed every other rule. `numbers_traceable` guards the
    numbers and nothing guarded the advice.

    Deliberately coarse. It reads only the turns that explain a final plan, only sentences
    carrying a proposal verb, and asks whether the item named in one appears anywhere in the
    `finalize_plan` result. Paraphrase is fine and expected -- the model words the action, code
    never does -- so nothing here matches on a sentence. What it cannot do is judge a proposal
    that names no item at all; that is the honest limit and it is the reason this is a rule about
    items rather than about advice.
    """
    turns = transcript.get("turns", ())
    plan = _final_plan_result(list(turns))
    state = transcript.get("state")
    if plan is None or not state:
        return []
    planned = plan.lower()
    names = [n for n in _item_names(state) if n]
    out = []
    started = False
    for i, turn in enumerate(turns):
        if any(_plans(c) for c in turn.get("tool_calls", ())):
            started = True
        if not started or turn["role"] != "assistant":
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", turn["text"].lower()):
            if not any(verb in sentence for verb in PROPOSAL_VERBS):
                continue
            named = [n for n in names if n in sentence]
            # One item in the sentence being in the plan authorises the sentence. "If you don't
            # move it, the streaming payment may be taken before your salary arrives" proposes
            # the move the plan actually contains, and flagging it for mentioning the salary in
            # passing punishes a correct explanation for naming a second thing.
            if not named or any(n in planned for n in named):
                continue
            out.append(
                Violation(
                    "actions_match_plan",
                    i,
                    f"{', '.join(named)}: {sentence.strip()[:80]}",
                )
            )
    return out


# Words the coach uses to tell somebody a figure is now on the books. Taken from the saved runs
# rather than imagined: "is recorded", "I've recorded", "noted", "updated". A sentence with one of
# these and a figure is a receipt the person will act on.
CLAIM_VERBS = (
    "recorded",
    "noted",
    "updated",
    "changed to",
    "got it as",
    "logged",
    "saved",
    "set to",
)


def _claimed_values_recorded(transcript: dict) -> list[Violation]:
    """A figure the coach says it has written down was actually written down.

    From the third live call. Speech to text heard "my red went up to" with the amount in the
    next fragment; the bot replied "I've noted rent as 13,000 rupees" and called no tool. The
    state kept 11,000, the stored profile kept 11,000, and the person rang off believing their
    correction had landed. Every rule passed: `numbers_traceable` because the person really did
    say 13,000, `state_matches_facts` because the scenario had no hidden fact for the change.

    A claim is a receipt. The person hears "noted" and stops repeating themselves, so a claim
    with nothing behind it is worse than silence -- silence at least leaves them trying. The
    figure must appear in a tool call's arguments or its result, in the claiming turn or the one
    before it, because the coach is told to speak once after the result and the harness records
    the call on the turn that made it.
    """
    turns = list(transcript.get("turns", ()))
    out = []
    for i, turn in enumerate(turns):
        if turn.get("role") != "assistant":
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", turn.get("text", "")):
            said = sentence.lower()
            if not any(verb in said for verb in CLAIM_VERBS):
                continue
            claimed = {n for n in numbers_in(said) if n >= TRACE_FLOOR}
            if not claimed:
                continue
            # Everything recorded so far in the call, not a window of a turn or two. "I've
            # already recorded rent of eleven thousand" refers to a call made ten turns back and
            # is a true statement; a narrow window flagged six of those across the saved runs and
            # would have been noise. What the rule is for is a figure recorded NOWHERE.
            recorded: set[int] = set()
            for t in turns[: i + 1]:
                for tool_call in t.get("tool_calls", ()) or ():
                    recorded |= numbers_in(str(tool_call.get("args", {})))
                    recorded |= numbers_in(str(tool_call.get("result", "")))
            unbacked = claimed - recorded
            if unbacked:
                out.append(
                    Violation(
                        "claimed_values_recorded",
                        i,
                        f"claimed but not recorded: {sorted(unbacked)}",
                    )
                )
    return out


def _no_silent_turn(transcript: dict) -> list[Violation]:
    """The coach acted and said nothing, with the person waiting for an answer.

    From the owner's live call, three times: "I did not understand" -> `record_understanding`
    and not one word spoken; "yeah, sure" -> `finalize_plan` and silence; a correction ->
    `upsert_item` and silence. On a phone line that is dead air, and the person starts over.
    Sixteen rules passed that call.

    The pairing is what makes it a defect: a tool call with no speech, in a turn that answers
    the person. Two assistant turns in a row are one reply -- the first records, the second
    speaks -- so only a turn that follows a user utterance is judged. Across the 381 saved runs
    that rule flags 69 turns and not one of them is followed by the coach speaking, so the
    narrower shape is the whole shape.

    `end_call` is not exempt, unlike in `silent_before_acting`: there the goodbye is allowed to
    go before the tool, here a hang-up with no goodbye at all is exactly the defect.
    """
    turns = list(transcript.get("turns", ()))
    out = []
    for i, turn in enumerate(turns):
        if turn.get("role") != "assistant" or not turn.get("tool_calls"):
            continue
        if (turn.get("text") or "").strip():
            continue
        if i == 0 or turns[i - 1].get("role") != "user":
            continue
        called = ", ".join(str(c.get("name")) for c in turn["tool_calls"])
        out.append(Violation("no_silent_turn", i, f"called {called}, said nothing"))
    return out


# A figure with paise in it. The engine works in Decimal and quantises to 0.01; text to speech
# reads "57166.61" out as "fifty-seven thousand one hundred sixty-six point six one", which is
# not a thing anybody says about their own money. Both spellings, because the model writes the
# digits and the words depending on the sentence.
PAISE_DIGITS = re.compile(r"\d\.\d")
PAISE_WORDS = re.compile(
    r"\bpoint\s+(zero|oh|nought|one|two|three|four|five|six|seven|eight|nine)\b", re.IGNORECASE
)
# ponytail: "1.5 lakh" and "one point five lakh" are a round figure, not paise. A scale word
# after the fraction is the only exception seen in the corpus; widen it if a second turns up.
SCALE_AFTER = re.compile(r"^\W*(k|lakhs?|crores?|cr|million)\b", re.IGNORECASE)


def _no_spoken_decimals(transcript: dict) -> list[Violation]:
    """No figure said out loud carries paise.

    The live call spoke "fifty-seven thousand one hundred sixty-six point six one rupees" twice,
    and the owner's verdict on that call was "a bot". Replayed over the saved runs the rule flags
    22 figures in 15 runs, every one of them an engine Decimal read aloud; whole rupees in the
    results is Session A's half of the same fix, and this is the rule that says so.

    The coach's words only: a tool result may carry the Decimal, and the person may say whatever
    they like.
    """
    out = []
    for i, turn in enumerate(transcript.get("turns", ())):
        if turn.get("role") != "assistant":
            continue
        text = turn.get("text") or ""
        for match in list(PAISE_DIGITS.finditer(text)) + list(PAISE_WORDS.finditer(text)):
            if SCALE_AFTER.match(text[match.end() :]):
                continue
            out.append(
                Violation(
                    "no_spoken_decimals", i, text[max(0, match.start() - 30) : match.end() + 10]
                )
            )
    return out


def _no_premature_plan(transcript: dict) -> list[Violation]:
    """A plan was reached with a whole category never mentioned and never ruled out.

    The owner's complaint about the live call, in one rule: it planned on a balance, a salary and
    a rent, said the month was covered in full, and had never asked about a card, a loan or what
    the person spends in a week. The arithmetic was right and the picture was half a picture.

    `state.coverage` is the domain's own three-valued answer per category -- something recorded,
    the person said there is none, or nothing usable has been said -- so this reads what the call
    established rather than reading the words for intent. The end-of-call state is what is judged:
    a category still UNASKED when the line dropped was never covered, whenever the plan landed.

    A state the domain cannot validate (pre-cut runs, a different shape) reports nothing. A rule
    that cannot read its evidence must not invent a verdict in either direction.
    """
    if not transcript.get("plan_final") or not transcript.get("state"):
        return []
    try:
        state = FinancialState.model_validate(transcript["state"])
    except Exception:  # noqa: BLE001 - an unreadable state is not a defect in the call
        return []
    covered = coverage(state)
    unasked = [kind.value for kind in ItemKind if covered.get(kind.value) is Coverage.UNASKED]
    if not unasked:
        return []
    turn = max(len(transcript.get("turns", ())) - 1, 0)
    return [
        Violation("no_premature_plan", turn, f"planned with never discussed: {', '.join(unasked)}")
    ]


# Three checks, since 14 September. Twenty rules had become twenty ways to rot quietly: each one
# read the result strings or the transcript through its own pattern, and when the redesign changed
# a line the rule that no longer matched went on reporting 100% on runs it was not looking at.
# `changed_value_acknowledged` did exactly that -- it parsed v1's "rent: 11,000 -> 12,000" and v2
# writes "rent 11,000 before, now 12,000" -- and it is one of the nine deleted here.
#
# Nothing about what is detected changed in the fold: every rule below is the same function under
# a private name, and every violation still names the sub-rule that raised it, in the detail. What
# changed is the score: three numbers per call instead of twenty, so a trace is readable and a
# drop points somewhere.


def _fold(name: str, transcript: dict, rules: tuple) -> list[Violation]:
    """Run the sub-rules and label what they find with the public check that carries them.

    The sub-rule's name leads the detail, so granularity lives in the violation rather than in
    the count: "spoken decimal 56,833.27" is still findable in a trace, and still attributable.
    """
    return [
        Violation(name, v.turn, f"{v.rule}: {v.detail}") for rule in rules for v in rule(transcript)
    ]


def money_traceable(transcript: dict) -> list[Violation]:
    """Every figure spoken came from a tool result, in whole rupees, and every claim to have
    written one down has a tool call behind it.

    The oldest rule in the product and the one the owner's own call broke: challenged on its
    arithmetic, the bot did the subtraction rather than reading a figure back.
    """
    return _fold(
        "money_traceable",
        transcript,
        (_numbers_traceable, _claimed_values_recorded, _no_spoken_decimals),
    )


def state_matches_call(transcript: dict) -> list[Violation]:
    """What was written down and planned matches what the person said and what the call covered.

    The half of the product code owns. `_state_matches_facts` reads the recorded state rather
    than the words, which is how it found a defect eleven transcript rules had passed.
    """
    return _fold(
        "state_matches_call",
        transcript,
        (_state_matches_facts, _actions_match_plan, _no_premature_plan),
    )


def speakable(transcript: dict) -> list[Violation]:
    """Voice-safe output: nothing offered that is new borrowing, no ISO dates, no markdown, and
    never an action with no words on a turn the person is waiting through."""
    return _fold(
        "speakable",
        transcript,
        (_banned_phrases, _no_iso_dates, _no_markdown, _no_silent_turn),
    )


# What each public check is made of, for the replay test and for anyone reading a detail string.
FOLDED: dict[str, tuple[str, ...]] = {
    "money_traceable": ("numbers_traceable", "claimed_values_recorded", "no_spoken_decimals"),
    "state_matches_call": ("state_matches_facts", "actions_match_plan", "no_premature_plan"),
    "speakable": ("banned_phrases", "no_iso_dates", "no_markdown", "no_silent_turn"),
}

CHECKS = (money_traceable, state_matches_call, speakable)


def run_checks(transcript: dict) -> list[Violation]:
    return [v for check in CHECKS for v in check(transcript)]


def passed(transcript: dict) -> bool:
    return not run_checks(transcript)
