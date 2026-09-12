"""Deterministic transcript checks: the rules that gate a run.

Number reading lives in `evals.spoken_numbers`, and the question of which figures are still
sayable in `evals.provenance`. Both are re-exported here, because a transcript check is the only
reason either exists and the tests reach for them by this name.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from evals.provenance import RECORDING_TOOLS, _same_item, _sources_up_to
from evals.spoken_numbers import ISO_DATE, TRACE_FLOOR, numbers_in
from ledgerline.agent.tools import phrases
from ledgerline.domain.state import normalise_name

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
CREDIT_IS_ABOUT = (
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


def numbers_traceable(transcript: dict) -> list[Violation]:
    """Every figure the assistant says came back in a tool result or from the person."""
    out = []
    turns = transcript["turns"]
    for i, turn in enumerate(turns):
        if turn["role"] != "assistant":
            continue
        allowed = _sources_up_to(turns, i) | _offered_readings(turn)
        invented = {n for n in numbers_in(turn["text"]) if n >= TRACE_FLOOR} - allowed
        if invented:
            out.append(
                Violation("numbers_traceable", i, f"not in any tool result: {sorted(invented)}")
            )
    return out


def one_question_per_turn(transcript: dict) -> list[Violation]:
    out = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] == "assistant" and turn["text"].count("?") > 1:
            out.append(Violation("one_question_per_turn", i, turn["text"]))
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


def banned_phrases(transcript: dict) -> list[Violation]:
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


def no_markdown(transcript: dict) -> list[Violation]:
    out = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] == "assistant" and MARKDOWN.search(turn["text"]):
            out.append(Violation("no_markdown", i, turn["text"]))
    return out


# What the domain says when a call changed nothing — the same amount sent again while fixing a
# due date, say. Nothing was recorded, so no read-back is owed for it.
UNCHANGED = "unchanged"


def _recorded_figures(tool_call: dict, turn: dict) -> set[int]:
    """What the person may hear back: the amount asked for, or the one actually recorded.

    They are the same except where the handler changes the figure. Two balance parts said in one
    breath — "20,000 in cash and" / "20,000 in bank balance." — are added by the tool, so the
    second call's argument is 20,000 and the opening balance is 40,000; reading back 40,000 is
    the honest confirmation and reading back 20,000 would be wrong. Only the result's first
    line counts: the totals under it are the shape of the month, not a read-back.
    """
    amount = tool_call.get("args", {}).get("amount")
    figures = {int(amount)} if amount is not None else set()
    kin = [tool_call]
    if tool_call.get("args", {}).get("kind") == "balance":
        # Every part of the balance said this turn: the model speaks the total once, after the
        # last of them, and that one sentence is the read-back for all of them.
        kin = [
            c
            for c in turn.get("tool_calls", ())
            if c.get("name") == "upsert_item" and c.get("args", {}).get("kind") == "balance"
        ]
    for call in kin:
        headline, _, _ = str(call.get("result", "")).partition("\n")
        figures |= {n for n in numbers_in(headline) if n >= TRACE_FLOOR}
    return figures


def amounts_repeated(transcript: dict) -> list[Violation]:
    """Every amount an upsert records is said out loud near the call that records it.

    Near, not after: the prompt asks the model to echo the figure first and call the tool second,
    so the read-back is often in the same turn's text or the turn before the call lands. The
    window is the previous assistant turn through the next two.
    """
    out = []
    turns = transcript["turns"]
    for i, turn in enumerate(turns):
        for tool_call in turn.get("tool_calls", ()):
            if tool_call.get("name") != "upsert_item":
                continue
            amount = tool_call.get("args", {}).get("amount")
            if amount is None or amount < TRACE_FLOOR:
                continue
            if str(tool_call.get("result", "")).startswith(UNCHANGED):
                continue  # the domain stored nothing, so there is nothing to hear back
            expected = _recorded_figures(tool_call, turn)
            headline = str(tool_call.get("result", "")).split("\n", 1)[0]
            if not expected & numbers_in(headline):
                # The result does not report this amount, so there is nothing to read back. A
                # call that carries the amount again while recording a DATE reports only the
                # date — "recorded salary date 1 Oct" — and demanding the figure anyway asks
                # the model to speak something no result offered, which the prompt forbids.
                continue
            before = [t for t in turns[:i] if t["role"] == "assistant"][-1:]
            after = [t for t in turns[i : i + 4] if t["role"] == "assistant"][:2]
            window = before + after
            if not any(expected & numbers_in(t["text"]) for t in window):
                out.append(
                    Violation("amounts_repeated", i, f"{tool_call['args'].get('name')} {amount:g}")
                )
    return out


def no_iso_dates(transcript: dict) -> list[Violation]:
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


def silent_before_acting(transcript: dict) -> list[Violation]:
    """Nothing spoken before a tool call, except the goodbye.

    Reversed after the owner's third live call. Speaking first and again after the result gave
    every tool turn two spoken segments, each with its own question — "What else would you like
    to tell me?What's your next income or expense?" — and the person heard the bot repeat itself
    all the way to "Goodbye.Goodbye." The pipeline speaks the filler now; the model speaks once,
    after the result.

    `end_call` alone is exempt, and has to be: its result is "call ended, say nothing more", so a
    model that never speaks before a tool can never say goodbye in the turn that ends the call.
    The first suite run showed exactly that — four runs in five ended on a silent `end_call` or a
    goodbye one turn early. The farewell goes before the line drops. A turn that *also* records
    something is a normal tool turn and is judged normally.
    """
    out = []
    for i, turn in enumerate(transcript["turns"]):
        order = turn.get("event_order")
        if turn["role"] != "assistant" or not order or "function_call" not in order:
            continue
        if {c.get("name") for c in turn.get("tool_calls", ())} == {"end_call"}:
            continue
        first_call = order.index("function_call")
        if "message" in order[:first_call]:
            out.append(Violation("silent_before_acting", i, " then ".join(order)))
    return out


SENTENCE = re.compile(r"[^.?!]+[.?!]")


def no_repeated_sentence(transcript: dict) -> list[Violation]:
    """The same sentence twice in one turn. What doubled speech sounds like from the other end."""
    out = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] != "assistant":
            continue
        said = [s.strip().lower() for s in SENTENCE.findall(turn["text"])]
        repeats = {s for s in said if len(s) > 3 and said.count(s) > 1}
        if repeats:
            out.append(Violation("no_repeated_sentence", i, "; ".join(sorted(repeats))))
    return out


QUESTION = re.compile(r"[^.?!]*\?")


def _questions(text: str) -> list[str]:
    """The question clauses in a turn, and only those.

    A semicolon is not a full stop, so "the electricity amount is parked as not known; when is
    your rent due?" arrived as one question sentence carrying the word "amount" — and the rule
    read the report half as the asking half. Only the clause the question mark belongs to counts.
    """
    return [q.rpartition(";")[2].strip() for q in QUESTION.findall(text)]


# Words that make a question one about an amount, or about a date. A field is asked again only
# when the question is about the same attribute: parking the rent amount does not park the rent,
# and "when is it due?" after "I don't know what it is" is one conversation, not a repeat.
ASKS_AMOUNT = ("how much", "how many", "amount", "cost", "costs", "rupees", "what do you pay")
ASKS_DATE = ("when", "what day", "which day", "date", "due on")
DATE_ATTRIBUTES = ("due_date", "date", "day", "day_of_month")


# How a tool result says it did nothing. A refused call parks nothing, so the next question
# about that field is a first asking, not a repeat.
REFUSED = "call the tool again"


def _refused(tool_call: dict) -> bool:
    return REFUSED in str(tool_call.get("result", ""))


def _parked_subject(field: str) -> tuple[str, str]:
    """ "essential:rent.amount" -> ("rent", "amount"); "monthly_income" -> ("monthly income", "").

    The second shape is the one the live defect used, and the old rule dropped it: it read the
    item name out of everything before the dot, which for a bare field is empty, so the turn that
    parked "monthly_income" and asked "What's your monthly income?" passed.
    """
    head, dot, attribute = field.rpartition(".")
    if not dot:
        return field.replace("_", " ").strip().lower(), ""
    kind, _, name = head.partition(":")
    return (name or kind).replace("_", " ").strip().lower(), attribute.strip().lower()


def _asks_about(question: str, attribute: str) -> bool:
    """Whether a question that names the parked item is asking for the parked attribute."""
    if not attribute:
        return True  # the whole field was parked, so any question about it is a repeat
    if attribute == "amount":
        return any(word in question for word in ASKS_AMOUNT)
    if attribute in DATE_ATTRIBUTES:
        return any(word in question for word in ASKS_DATE)
    return attribute.replace("_", " ") in question


def no_question_after_unknown(transcript: dict) -> list[Violation]:
    """Never ask again about a field just parked. The bot recorded "nothing else to add" and in
    the same breath asked "What's your monthly income?" twice.

    Only the question sentences count. Naming the item in the sentence that parks it — "I've
    noted the credit card is outside this window. Anything else?" — is reporting, not asking, and
    reading the whole turn made that a failure in a live run.
    """
    out = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] != "assistant":
            continue
        parked = [
            c.get("args", {}).get("field", "")
            for c in turn.get("tool_calls", ())
            if c.get("name") == "mark_unknown" and not _refused(c)
        ]
        questions = _questions(turn["text"].lower())
        if not parked or not questions:
            continue
        for field in parked:
            subject, attribute = _parked_subject(field)
            if not subject:
                continue
            if any(subject in q and _asks_about(q, attribute) for q in questions):
                out.append(Violation("no_question_after_unknown", i, f"{field}: {subject}"))
    return out


FAREWELLS = ("goodbye", "take care", "bye for now")


def _farewell_sentences(text: str) -> int:
    """How many separate farewells were spoken.

    Sentences, not words: "Goodbye, and take care." is one goodbye, and counting the words made
    it two and failed a run whose ending was exactly right. "Goodbye.Goodbye." is two, which is
    the defect — the tool result spoken after the model had already said its farewell.
    """
    said = SENTENCE.findall(text.lower())
    rest = SENTENCE.sub("", text.lower()).strip()
    if rest:
        said.append(rest)
    return sum(any(word in sentence for word in FAREWELLS) for sentence in said)


def one_goodbye_with_the_end_call(transcript: dict) -> list[Violation]:
    """Said once, in the same turn that ends the call."""
    out = []
    farewells = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] != "assistant":
            continue
        ends = any(c.get("name") == "end_call" for c in turn.get("tool_calls", ()))
        count = _farewell_sentences(turn["text"])
        if count:
            farewells.append(i)
        if count > 1:
            out.append(Violation("one_goodbye_with_the_end_call", i, f"{count} farewells"))
        if ends and not count:
            out.append(Violation("one_goodbye_with_the_end_call", i, "end_call with no goodbye"))
        if count and not ends:
            out.append(Violation("one_goodbye_with_the_end_call", i, "goodbye without end_call"))
    if len(farewells) > 1:
        detail = f"farewells on turns {farewells}"
        out.append(Violation("one_goodbye_with_the_end_call", farewells[-1], detail))
    return out


# How a result reports that a value the person had already given has moved: "rent: 11,000 ->
# 12,000". A create has no left-hand figure and writes "recorded rent 12,000" instead, so this
# pattern is exactly the set of changes that owe the person an explanation.
CHANGE = re.compile(r"^(?P<label>[^:\n]+): (?P<old>[^\n>;]+) -> (?P<new>[^\n;]+)", re.MULTILINE)

# Words that make a question an attempt to settle which of two figures is right.
WHICH_IS_RIGHT = ("which", "right", "correct", "sure", "or is it", "did you mean")

# A date the result spelled "7 Sep" is spoken "the seventh of September", so a day is named by
# its digit or by its ordinal word, and a month by either spelling.
ORDINALS = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
    11: "eleventh",
    12: "twelfth",
    13: "thirteenth",
    14: "fourteenth",
    15: "fifteenth",
    16: "sixteenth",
    17: "seventeenth",
    18: "eighteenth",
    19: "nineteenth",
    20: "twentieth",
    21: "twenty-first",
    22: "twenty-second",
    23: "twenty-third",
    24: "twenty-fourth",
    25: "twenty-fifth",
    26: "twenty-sixth",
    27: "twenty-seventh",
    28: "twenty-eighth",
    29: "twenty-ninth",
    30: "thirtieth",
    31: "thirty-first",
}
MONTHS = {
    abbr.lower(): full.lower()
    for abbr, full in zip(calendar.month_abbr, calendar.month_name, strict=True)
    if abbr
}


def _names_value(said: str, new: str) -> bool:
    """Whether the reply names the value the result just recorded, however it says it aloud."""
    figures = {n for n in numbers_in(new) if n >= TRACE_FLOOR}
    if figures:
        return bool(figures & numbers_in(said))
    tokens = re.findall(r"[a-z0-9]+", new.lower())
    for token in tokens:
        if token.isdigit() and int(token) in ORDINALS:
            day = int(token)
            if re.search(rf"\b{day}\b", said) or ORDINALS[day] in said:
                return True
        for spelling in {token, MONTHS.get(token, token)}:
            if len(spelling) > 3 and re.search(rf"\b{re.escape(spelling)}", said):
                return True
    return False


def _acknowledges(text: str, label: str, new: str) -> bool:
    """Whether this reply either names the new value or asks the person which figure is right.

    Naming it is the normal case: the value changed and the person hears the one that stuck.
    The other is the case the cut created — the model reads both figures, cannot tell a
    correction from a contradiction, and asks. Any question will not do: the reply has to name
    the item that moved and the question has to be about settling it, or every turn ending in a
    question passes for free.
    """
    said = text.lower()
    if _names_value(said, new):
        return True
    subject = label.split()[0].lower() if label.split() else ""
    if not subject or subject not in said:
        return False
    return any(any(word in question for word in WHICH_IS_RIGHT) for question in _questions(said))


def changed_value_acknowledged(transcript: dict) -> list[Violation]:
    """A figure that moved is either read back or queried, in the turn that moved it.

    The cut took the conflict machinery out of the domain: `upsert_item` overwrites and reports
    "rent: 11,000 -> 12,000", and deciding whether that was a correction or a contradiction is
    now the model's job. This is the rule that says it has to do that job out loud. Silence here
    is the failure the machinery used to prevent — the card says 12,000, the person believes
    they still pay 11,000, and nobody said anything.
    """
    out = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] != "assistant":
            continue
        for tool_call in turn.get("tool_calls", ()):
            if tool_call.get("name") not in RECORDING_TOOLS:
                continue
            for change in CHANGE.finditer(str(tool_call.get("result", ""))):
                label, new = change.group("label"), change.group("new")
                if not _acknowledges(turn["text"], label, new):
                    out.append(Violation("changed_value_acknowledged", i, change.group(0)))
    return out


# A monthly figure this small for one of these kinds is almost always the thousand that speech
# to text dropped: "my rent is twelve thousand" arriving as "rent is 12". Deliberately not the
# 100 of TRACE_FLOOR, which answers a different question (is this money or a day of the month),
# and deliberately only these three kinds. A 40 rupee optional is a real subscription, and a 40
# rupee opening balance is a real person -- exactly the person this call is for -- so flooring
# either would call their situation a mishearing.
IMPLAUSIBLE_BELOW = {"income": 500, "essential": 200, "debt": 200}


def _confirms_figure(text: str, name: str) -> bool:
    """Whether the reply asks about this item's figure, rather than merely ending in a question.

    Unlike `_acknowledges`, naming the value is not enough and cannot be: saying "twelve rupees
    for rent" out loud IS the failure here. Only a question that names the item and asks whether
    the figure is right counts.
    """
    said = text.lower()
    subject = name.split()[0].lower() if name.split() else ""
    if not subject or subject not in said:
        return False
    return any(any(word in question for word in WHICH_IS_RIGHT) for question in _questions(said))


def implausible_amount_confirmed(transcript: dict) -> list[Violation]:
    """An amount too small to be real for its kind is queried in the turn that records it.

    The cut handed implausibility to the model: no outlier list, no blocking state, just a
    coach who is expected to notice that nobody pays twelve rupees in rent. This is the rule
    that measures whether it does. A turn that asks INSTEAD of recording raises nothing at all,
    because there is no figure in the state to be wrong about.
    """
    out = []
    for i, turn in enumerate(transcript["turns"]):
        if turn["role"] != "assistant":
            continue
        for tool_call in turn.get("tool_calls", ()):
            if tool_call.get("name") != "upsert_item":
                continue
            args = tool_call.get("args", {})
            amount, name = args.get("amount"), str(args.get("name", ""))
            floor = IMPLAUSIBLE_BELOW.get(str(args.get("kind", "")))
            if amount is None or floor is None or amount >= floor:
                continue
            if not _confirms_figure(turn["text"], name):
                out.append(Violation("implausible_amount_confirmed", i, f"{name} {amount:g}"))
    return out


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


def state_matches_facts(transcript: dict) -> list[Violation]:
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


CHECKS = (
    numbers_traceable,
    state_matches_facts,
    changed_value_acknowledged,
    implausible_amount_confirmed,
    one_question_per_turn,
    banned_phrases,
    no_markdown,
    amounts_repeated,
    no_iso_dates,
    silent_before_acting,
    no_repeated_sentence,
    no_question_after_unknown,
    one_goodbye_with_the_end_call,
)


# Rules that describe the model's behaviour rather than the product's promises. They are
# reported, never used to fail a run.
ADVISORY: tuple = ()


def run_checks(transcript: dict) -> list[Violation]:
    return [v for check in CHECKS for v in check(transcript)]


def run_advisory(transcript: dict) -> list[Violation]:
    return [v for check in ADVISORY for v in check(transcript)]


def passed(transcript: dict) -> bool:
    return not run_checks(transcript)
