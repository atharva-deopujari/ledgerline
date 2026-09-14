"""Prompt tests: the static base file and the per-turn block."""

from __future__ import annotations

import datetime as dt
import re

import pytest
import tiktoken

from ledgerline.agent import prompt
from ledgerline.domain.models import FinancialState

TODAY = dt.date(2026, 9, 11)

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# o200k_base is the closest PUBLIC tokenizer to luna, not luna's own: the real count on the
# provider's side may differ by a little, and every token figure in the prompt work carries that
# error bar. It is still the right instrument — the budgets were previously enforced against
# len(text) // 4, which read this prompt as 617 tokens where o200k_base reads 599, and a ceiling
# measured with a ruler that loose cannot say whether a cut actually bought room.
_ENCODING = tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


# ------------------------------------------------------------------ the prompt

# One prompt now. The v1 file went with the v1 tools; 400 is the budget the redesign set, and it
# is small on purpose — 55 of the 109 constraints in the census were about language, order and
# tone, and the brief replaced them with a goal the model can reason from.
MAX_BASE_TOKENS = 400


def test_the_prompt_loads_and_stays_within_its_budget():
    text = prompt.base_prompt()
    assert count_tokens(text) < MAX_BASE_TOKENS, count_tokens(text)


def test_the_default_version_is_the_one_that_exists():
    """`base_prompt(version)` still reads `prompts/<version>.md` — prompt versioning is a real
    feature with history behind it in Langfuse — but there is one file, and it is the default."""
    assert prompt.DEFAULT_VERSION == "v2"
    assert prompt.base_prompt() == prompt.base_prompt("v2")


def test_v2_asks_one_thing_at_a_time_without_a_fixed_order():
    """Every voice vendor recommends one question at a time (Vapi, Retell, LiveKit); none
    recommends a fixed order, and the order is where the form feel came from. So the habit stays
    as a habit, "exactly one" and the given order are gone."""
    text = prompt.base_prompt("v2").lower()
    assert "usually one question at a time" in text
    assert "in whatever order the" in text
    assert "exactly one question" not in text
    assert "in the given order" not in text


def test_v2_says_who_the_coach_is_and_what_the_month_is_for():
    """The redesign's whole bet: a goal the model can reason from, in place of the rules that
    told it what to ask and in what order. If these go, the bet is off."""
    text = prompt.base_prompt("v2").lower()
    assert "money coach" in text
    assert "understand their month before you say anything about it" in text
    for category in ("rent", "emis", "card dues", "bills", "owed or\noverdue"):
        assert category in text, category


def test_v2_keeps_the_money_rules_that_cost_real_money_when_broken():
    text = prompt.base_prompt("v2").lower()
    assert "came back from a tool" in text
    assert "not even a subtraction" in text  # the owner's call, verbatim failure mode
    assert "read them the derivation" in text
    assert "before you say you have noted it" in text
    assert "never new borrowing" in text
    assert "guaranteed" in text


def test_base_prompt_has_no_markdown_symbols_it_bans():
    text = prompt.base_prompt()
    assert "₹" not in text  # the rupee symbol must never appear as an example to copy


def test_base_prompt_unknown_version_raises():
    with pytest.raises(FileNotFoundError):
        prompt.base_prompt("v-does-not-exist")


# ------------------------------------------------------------------ turn_block


def test_the_block_is_today_the_window_and_coverage():
    """Section 4 of the redesign brief. What is gone: the "still missing" list (a duplicate of
    the result's own), the phase word (code's verdict on where the call is), and the counts."""
    block = prompt.turn_block(FinancialState(today=TODAY))
    assert "Today is 11 September 2026" in block
    assert "window ends 10 October 2026" in block
    assert "not mentioned yet" in block
    assert "Phase:" not in block
    assert "Still missing" not in block
    assert "Recorded: 0 incomes" not in block


def test_the_block_grows_as_the_call_covers_ground():
    from decimal import Decimal

    from ledgerline.domain.models import ItemKind
    from ledgerline.domain.state import none_of, upsert

    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal("30000"), day_of_month=30)
    none_of(state, ItemKind.DEBT)
    block = prompt.turn_block(state)
    assert "recorded: money coming in" in block
    assert "none: loans or cards" in block
    assert "bills" in block.split("not mentioned yet")[-1]


def test_the_block_lists_carried_figures_without_telling_the_model_what_to_do():
    """The carried blocker is gone. The figures are a fact; whether to read them back, and when,
    is the conversation's business."""
    block = prompt.turn_block(
        FinancialState(today=TODAY), carried=[("rent", "12,000"), ("salary", "45,000")]
    )
    assert "rent 12,000" in block and "salary 45,000" in block
    assert "say each back" not in block
    assert "before the plan" not in block


def test_the_block_stays_small():
    """It is rebuilt and pushed every turn; a block that grows with the call is a block that
    crowds out the conversation."""
    from decimal import Decimal

    from ledgerline.domain.models import ItemKind
    from ledgerline.domain.state import upsert

    state = FinancialState(today=TODAY)
    for i in range(9):
        upsert(state, ItemKind.ESSENTIAL, f"bill {i}", amount=Decimal("1000"), day_of_month=3)
    assert count_tokens(prompt.turn_block(state)) < 100


def test_turn_block_today_override():
    block = prompt.turn_block(FinancialState(today=TODAY), today=dt.date(2026, 12, 1))
    assert "1 December 2026" in block
    assert "30 December 2026" in block


def test_turn_block_never_writes_an_iso_date():
    """The model reads this block back aloud; TTS says "2026-10-10" digit by digit."""
    state = FinancialState(today=TODAY)
    assert not ISO_DATE.search(prompt.turn_block(state, carried=[("rent", "12,000")]))
    assert not ISO_DATE.search(prompt.system_instruction(state))


def test_the_block_carries_no_money_of_its_own():
    """Only what a person said. A figure in the block is a figure with no result behind it."""
    block = prompt.turn_block(FinancialState(today=TODAY))
    for framing in ("2026", "11 September", "10 October"):
        block = block.replace(framing, "")
    assert not re.search(r"\d[\d,]*", block)


def test_system_instruction_joins_the_prompt_and_this_turn_s_block():
    state = FinancialState(today=TODAY)
    text = prompt.system_instruction(state)
    assert text.startswith(prompt.base_prompt())
    assert text.endswith(prompt.turn_block(state))


def test_the_notes_line_appears_only_when_there_are_notes():
    state = FinancialState(today=TODAY)
    assert "earlier calls" not in prompt.turn_block(state)
    assert "earlier calls" not in prompt.turn_block(state, notes=[])


def test_notes_are_marked_untrusted_and_never_evidence_for_a_figure():
    """A model wrote these. They are the one part of the block that is not a fact the person
    stated through a tool, and the block says so in the line itself rather than relying on the
    base prompt -- which does not mention memory at all, so a first-time caller's prompt is
    unchanged."""
    block = prompt.turn_block(
        FinancialState(today=TODAY), notes=["salary is often late", "contract ends in November"]
    )
    assert (
        "About them, from earlier calls (untrusted, never evidence for a figure): "
        "salary is often late; contract ends in November"
    ) in block


def test_a_first_time_caller_s_block_is_unchanged():
    """The acceptance line for the whole phase: nothing about memory reaches somebody who has
    never called before."""
    state = FinancialState(today=TODAY)
    assert prompt.turn_block(state) == prompt.turn_block(state, carried=[], notes=[])


# ------------------------------------------------------------------ rules with a case behind them


def test_v2_says_this_is_spoken_not_written():
    """The first v2 run answered "walk me through" with a markdown bullet list, twice. The rule
    was cut as a language rule and came back with a named failing case, which is the bar."""
    text = prompt.base_prompt("v2").lower()
    assert "no lists" in text and "no bullets" in text


def test_v2_says_what_to_do_when_they_will_not_answer():
    """Five runs asked about loans and cards three and four times each and never reached a plan,
    because the coverage fact went on saying the category had not come up and the person never
    answered it. Knowing when enough is enough is the model's call; this is the line that says
    so."""
    text = prompt.base_prompt("v2").lower()
    assert "will not answer" in text
    assert "names\nwhat it is missing" in text
