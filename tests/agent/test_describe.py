"""`describe`: the result string the model reads.

Facts, one a line, every number from the domain. These tests are about the exact strings,
because the strings are the layer's output: the model speaks them, and a wording change here is
a behaviour change on a live call.
"""

from __future__ import annotations

import datetime as dt
import re

from factories import make_plan, make_summary, money

from ledgerline.agent.tools import describe, phrases
from ledgerline.domain.models import (
    Action,
    ActionType,
    ItemKind,
    OutcomeStatus,
    Phase,
    PlanStatus,
    Readiness,
    UnknownReason,
    Unpaid,
)
from ledgerline.domain.state import Outcome

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def created(**over) -> Outcome:
    base = dict(
        status=OutcomeStatus.CREATED,
        kind=ItemKind.ESSENTIAL,
        name="rent",
        field="essential:rent.amount",
        changes={"essential:rent.amount": ("", "11,000")},
    )
    base.update(over)
    return Outcome(**base)


def updated(changes: dict, **over) -> Outcome:
    base = dict(
        status=OutcomeStatus.UPDATED,
        kind=ItemKind.ESSENTIAL,
        name="rent",
        field="essential:rent.amount",
        changes=changes,
    )
    base.update(over)
    return Outcome(**base)


def parked(field: str = "essential:electricity.amount", **over) -> Outcome:
    base = dict(status=OutcomeStatus.CREATED, field=field)
    base.update(over)
    return Outcome(**base)


def ready(**over) -> Readiness:
    base = dict(phase="gathering", blockers=[], missing_fields=[])
    base.update(over)
    return Readiness(**base)


def lines(result: str) -> list[str]:
    return result.splitlines()


# ------------------------------------------------------------------ what the call just did


def test_a_create_names_the_item_and_every_value_stored_with_it():
    outcome = created(
        changes={
            "essential:rent.amount": ("", "12,000"),
            "essential:rent.due_date": ("", "5 Oct"),
        }
    )
    assert lines(describe(outcome, make_plan()))[0] == (
        "recorded rent 12,000 due 5 Oct; say this back, then ask"
    )


def test_a_card_result_already_reads_both_figures_back():
    """Pinned, not changed. A card has two confusable figures, and in 4 of 13 post-cut runs the
    model sent the full balance as `min_due` — which makes paying the minimum save nothing and
    quietly removes the one cheap action the engine can offer on a card. The result already
    names both, so the swap was visible in the string and the model made it anyway: this is the
    case where the result-carried lever does NOT apply, and the fix belongs in the field
    description instead. This test exists so nobody removes the second figure believing it
    unused."""
    outcome = created(
        kind=ItemKind.DEBT,
        name="hdfc card",
        field="debt:hdfc card.amount_due",
        changes={
            "debt:hdfc card.amount_due": ("", "3,000"),
            "debt:hdfc card.min_due": ("", "1,200"),
        },
    )
    first = lines(describe(outcome, make_plan()))[0]
    assert first == "recorded hdfc card amount due 3,000 minimum due 1,200; say this back, then ask"


def test_a_balance_result_asks_for_the_other_half_before_the_read_back():
    """The defect every other check passed. "20,000 in cash and 20,000 in bank balance" arrives
    as three fragments; in fifteen consecutive runs the model made ONE balance call, recorded
    20,000 and planned the person's month on half their money. `ToolContext.balance_total` was
    ready to add the parts and was never given a second one.

    One procedure, not two questions: record the rest, then read the total back. The parts have
    to be recorded before the reply or the total the model reads back is wrong."""
    outcome = created(
        kind=ItemKind.BALANCE,
        name="",
        field="opening_balance",
        changes={"opening_balance": ("", "20,000")},
    )
    first = lines(describe(outcome, make_plan()))[0]
    assert first == (
        "recorded opening balance 20,000; record any other amount they named before replying, "
        "then say the total back and ask"
    )


def test_a_balance_that_grew_by_a_part_is_read_back_not_disputed():
    """Measured, not guessed. With the parts persisting, the second fragment made the domain
    report "opening balance: 20,000 -> 40,000" and `describe` attached "confirm which is right" —
    so the result asked the person to choose between the half and the whole of their own money.
    `changed_value_acknowledged` went to 0% in five runs of five, and rightly: the model refused
    to ask a nonsense question.

    The tool owns this arithmetic. A balance total is never contested, because no two figures are
    competing — one is the sum of the parts and code computed it. It is read back instead."""
    outcome = updated({"opening_balance": ("20,000", "40,000")}, kind=ItemKind.BALANCE, name="")
    first = lines(describe(outcome, make_plan()))[0]
    assert first == "opening balance: 20,000 -> 40,000; say the total back and ask"
    assert phrases.CONFIRM_CHANGE not in first


def test_a_changed_amount_that_is_not_a_balance_still_asks_which_is_right():
    result = describe(updated({"essential:rent.amount": ("11,000", "12,000")}), make_plan())
    assert phrases.CONFIRM_CHANGE in result


def test_an_implausible_amount_is_flagged_instead_of_read_back():
    """The 0% case. STT drops the thousand, the person says "My rent is 12", and the result came
    back "recorded rent 12; say this back, then ask" — the string told the model to say twelve
    rupees back as a fact, which is exactly what it did in five runs out of five. The read-back
    instruction is replaced, not joined: a turn holds one question."""
    result = describe(created(changes={"essential:rent.amount": ("", "12")}), make_plan())
    first = lines(result)[0]
    assert first == "recorded rent 12; rent looks small, confirm it before moving on"
    assert phrases.READ_BACK not in result


def test_an_implausible_income_is_flagged_too():
    outcome = created(
        kind=ItemKind.INCOME,
        name="salary",
        field="income:salary.amount",
        changes={"income:salary.amount": ("", "45")},
    )
    assert lines(describe(outcome, make_plan()))[0] == (
        "recorded salary 45; salary looks small, confirm it before moving on"
    )


def test_a_small_optional_is_left_alone():
    """A 40 rupee subscription is a real thing a person pays for, and so is a 40 rupee balance.
    Flagging either would have the bot call a true answer a mishearing."""
    outcome = created(
        kind=ItemKind.OPTIONAL,
        name="streaming",
        field="optional:streaming.amount",
        changes={"optional:streaming.amount": ("", "40")},
    )
    assert phrases.CONFIRM_AMOUNT not in describe(outcome, make_plan())


def test_a_plausible_amount_is_read_back_as_before():
    result = describe(created(changes={"essential:rent.amount": ("", "11,000")}), make_plan())
    assert lines(result)[0] == "recorded rent 11,000; say this back, then ask"


def test_an_implausible_amount_that_changes_one_still_asks_which_is_right():
    """A changed value already carries an instruction. It does not get a second one."""
    result = describe(updated({"essential:rent.amount": ("11,000", "12")}), make_plan())
    assert lines(result)[0] == f"rent: 11,000 -> 12; {phrases.CONFIRM_CHANGE}"


def test_a_change_shows_both_figures():
    """The whole point of the cut. The domain cannot tell a correction from a contradiction, so
    it hands the model both figures and lets it decide whether to confirm or to ask."""
    result = describe(updated({"essential:rent.amount": ("11,000", "12,000")}), make_plan())
    assert lines(result)[0].startswith("rent: 11,000 -> 12,000")


def test_a_value_added_where_there_was_none_is_a_recording_not_a_change():
    """A due date filled in on an item that never had one is new information, not a disagreement.
    Writing it as " -> 5 Oct" would ask the model to reconcile a figure nobody ever gave."""
    result = describe(updated({"essential:rent.due_date": ("", "5 Oct")}), make_plan())
    assert lines(result)[0].startswith("recorded rent due date 5 Oct")
    assert phrases.CONFIRM_CHANGE not in result


def test_two_fields_that_moved_get_a_line_each():
    result = describe(
        updated(
            {
                "essential:rent.amount": ("11,000", "12,000"),
                "essential:rent.due_date": ("5 Oct", "7 Oct"),
            }
        ),
        make_plan(),
    )
    assert lines(result)[0].startswith("rent: 11,000 -> 12,000")
    assert lines(result)[1] == "rent due date: 5 Oct -> 7 Oct"


def test_a_debt_kind_is_not_a_value_anyone_reads_back():
    outcome = created(
        kind=ItemKind.DEBT,
        name="hdfc card",
        changes={
            "debt:hdfc card.amount": ("", "8,000"),
            "debt:hdfc card.kind": ("", "credit_card"),
        },
    )
    assert lines(describe(outcome, make_plan()))[0].startswith("recorded hdfc card 8,000")


def test_an_unchanged_call_says_so():
    outcome = Outcome(status=OutcomeStatus.UNCHANGED, kind=ItemKind.ESSENTIAL, name="rent")
    assert lines(describe(outcome, make_plan()))[0] == "unchanged rent"


def test_a_removal_names_what_went():
    outcome = Outcome(status=OutcomeStatus.REMOVED, kind=ItemKind.DEBT, name="bike loan")
    assert lines(describe(outcome, make_plan()))[0] == "removed bike loan"


def test_removing_something_that_was_never_there_says_that():
    outcome = Outcome(status=OutcomeStatus.NOOP, kind=ItemKind.DEBT, name="bike loan")
    assert lines(describe(outcome, make_plan()))[0] == "nothing recorded for bike loan"


def test_the_balance_is_named_even_though_it_has_no_item_name():
    outcome = Outcome(
        status=OutcomeStatus.CREATED,
        kind=ItemKind.BALANCE,
        name="opening balance",
        field="opening_balance",
        changes={"opening_balance": ("", "18,000")},
    )
    assert lines(describe(outcome, make_plan()))[0].startswith("recorded opening balance 18,000")


# ------------------------------------------------------------------ parking a field


def test_a_field_the_person_does_not_know():
    result = describe(parked(), make_plan(), reason=UnknownReason.UNKNOWN)
    assert lines(result)[0] == "not known: electricity amount"


def test_a_field_there_is_none_of():
    result = describe(parked(field="income"), make_plan(), reason=UnknownReason.NOT_APPLICABLE)
    assert lines(result)[0] == "none: income"


def test_parking_the_same_field_twice_says_it_was_already_parked():
    outcome = parked(status=OutcomeStatus.UNCHANGED)
    result = describe(outcome, make_plan(), reason=UnknownReason.UNKNOWN)
    assert lines(result)[0] == "already not known: electricity amount"


# ------------------------------------------------------------------ where the month stands


def test_the_summary_carries_every_figure_the_model_might_be_asked_for():
    """The prompt forbids saying a figure that is not in a result, so anything missing here is a
    number the bot cannot say — including the one it is most likely to be asked for, how much is
    left over."""
    result = describe(created(), make_plan())
    assert "in 45,000, out 38,000, lowest 1,200 on 28 September" in result
    assert "surplus 0, shortfall 0" in result


def test_a_shortfall_is_named_as_one():
    plan = make_plan(summary=make_summary(shortfall_after_actions=money(-2300)))
    assert "surplus 0, shortfall 2,300" in describe(created(), plan)


def test_a_plan_with_money_left_over_still_states_the_shortfall_as_zero():
    """The whole point. `correction_and_conflict` turn 20: the result said "surplus 1,000" and
    nothing about a shortfall, the model was asked what happens if the uncertain income never
    arrives, and it derived out 14,000 minus lowest 1,000 and told a person with money left over
    that they were thirteen thousand rupees short. There is nothing to derive when the figure is
    already there."""
    plan = make_plan(summary=make_summary(shortfall_after_actions=money(1000)))
    assert "surplus 1,000, shortfall 0" in describe(created(), plan)


def test_unpaid_money_is_never_folded_into_the_outflow():
    """`total_out_planned` is money that actually moves. Adding what the plan cannot fund into it
    is how a summary comes to disagree with its own timeline."""
    plan = make_plan(
        status=PlanStatus.UNSOLVABLE,
        summary=make_summary(total_out_planned=money(38000), unpaid_total=money(5000)),
    )
    result = describe(created(), plan)
    assert "out 38,000" in result
    assert "unpaid total 5,000" in result


def test_nothing_is_said_about_unpaid_money_when_there_is_none():
    assert "unpaid" not in describe(created(), make_plan())


def test_a_blocked_plan_names_the_field_ids_as_labels():
    plan = make_plan(status=PlanStatus.BLOCKED, summary=None, blockers=["opening_balance"])
    assert "blocked: opening balance" in describe(created(), plan)


def test_a_blocker_the_person_already_declined_is_flagged_as_parked():
    """`build_plan` stays blocked on the opening balance for the rest of the call, so its blocker
    line repeats in every result. Without this the model cannot obey "ask what the result says"
    and "never ask again about something you marked unknown" at the same time."""
    plan = make_plan(status=PlanStatus.BLOCKED, summary=None, blockers=["opening_balance"])
    result = describe(created(), plan, parked=frozenset({"opening_balance"}))
    assert "parked, do not ask again: opening balance" in result


def test_a_blocker_nobody_declined_is_not_flagged():
    plan = make_plan(status=PlanStatus.BLOCKED, summary=None, blockers=["opening_balance"])
    assert "parked" not in describe(created(), plan)


def test_a_plan_without_a_summary_says_only_what_it_knows():
    plan = make_plan(status=PlanStatus.BLOCKED, summary=None, blockers=["opening_balance"])
    result = describe(created(), plan)
    assert "in " not in result
    assert "blocked: opening balance" in result


def test_a_provisional_plan_says_what_leaving_them_out_did_to_the_figures():
    """ "provisional: electricity" named a category and left the consequence to inference. The
    model inferred the opposite of the truth -- that the figures above counted the excluded
    income and a worse case sat underneath -- and invented that worse case. The line says what
    the exclusion DID to the numbers now."""
    plan = make_plan(provisional=True, excluded_items=["electricity"])
    assert "already left out of these figures: electricity" in describe(created(), plan)


def test_a_provisional_plan_with_nothing_named_still_says_the_totals_are_incomplete():
    result = describe(created(), make_plan(provisional=True))
    assert "these totals already leave out something not known yet" in result


def test_an_ok_plan_says_nothing_about_its_shape():
    """TIMING and STRUCTURAL need a frame; OK does not, and a line saying so is one more thing
    for the model to read aloud."""
    result = describe(created(), make_plan())
    for shape in phrases.PLAN_SHAPE.values():
        assert shape not in result


def test_a_timing_shortfall_is_named_next_to_the_surplus():
    """A closing surplus beside a list of deferrals reads as "you are fine". It is not: the money
    exists and the dates do not line up."""
    plan = make_plan(
        status=PlanStatus.TIMING, summary=make_summary(shortfall_after_actions=money(0))
    )
    result = describe(created(), plan)
    assert "timing shortfall" in result
    assert "surplus 0, shortfall 0" in result


def test_the_turn_nothing_blocks_any_more_asks_once_about_what_else_goes_out():
    """Review 13 F2. `blockers` is the opening balance and the income question and nothing else,
    so a call that has a balance, an income and one essential is READY — and
    `fragmented_balance-20260912-220810` finalised there, on cash, rent and salary alone,
    reporting a 54,000 surplus while the groceries, the card and the gym were never asked about.

    No code gate: the cut put discovery with the model on purpose, and a category checklist in
    code is a questionnaire wearing a different hat. What code does know, and the model does not,
    is the moment nothing is blocking any more. That is the one turn worth a nudge.
    """
    ready = Readiness(phase=Phase.READY, blockers=[], missing_fields=[])
    result = describe(created(), make_plan(), ready)
    assert phrases.READY_TO_PLAN in result


def test_the_nudge_is_not_repeated_once_the_plan_is_final():
    """PLAN and DONE are past it; a second nudge would be a rule fighting the ending."""
    for phase in (Phase.PLAN, Phase.DONE):
        done = Readiness(phase=phase, blockers=[], missing_fields=[])
        assert phrases.READY_TO_PLAN not in describe(created(), make_plan(), done)


def test_the_nudge_stays_quiet_while_anything_is_still_blocking():
    gathering = Readiness(phase=Phase.GATHERING, blockers=["income"], missing_fields=[])
    assert phrases.READY_TO_PLAN not in describe(created(), make_plan(), gathering)


def test_the_nudge_stays_quiet_while_the_plan_is_being_explained():
    """`actions=True` is the turn that walks through the plan. Pointing the model back at the
    gathering question there is the defect `missing:` suppression was written for."""
    ready = Readiness(phase=Phase.READY, blockers=[], missing_fields=[])
    assert phrases.READY_TO_PLAN not in describe(None, make_plan(), ready, actions=True)


# ------------------------------------------------------------------ the missing list


def test_the_missing_fields_come_back_as_labels():
    readiness = ready(missing_fields=["essential:electricity.amount", "income:salary.date"])
    result = describe(created(), make_plan(), readiness)
    assert lines(result)[-1] == "missing: electricity amount, salary date"


def test_only_the_first_five_missing_fields_are_named():
    readiness = ready(missing_fields=[f"essential:e{i}.amount" for i in range(9)])
    line = lines(describe(created(), make_plan(), readiness))[-1]
    assert line.count(",") == 4
    assert "e5" not in line


def test_nothing_missing_means_no_missing_line():
    assert "missing:" not in describe(created(), make_plan(), ready())


# ------------------------------------------------------------------ the finalised plan


def action(**over) -> Action:
    base = dict(
        type=ActionType.DEFER_OPTIONAL,
        target="netflix",
        amount=money(500),
        rationale="move netflix to after the salary lands",
    )
    base.update(over)
    return Action(**base)


def test_the_plan_headline_and_its_two_actions():
    plan = make_plan(
        status=PlanStatus.TIMING,
        actions=[
            action(),
            action(
                target="hdfc card",
                type=ActionType.PAY_MIN_DUE,
                rationale="pay the minimum on the hdfc card this month",
            ),
        ],
    )
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert lines(result)[0] == "plan final"
    assert "move netflix to after the salary lands" in result
    assert "pay the minimum on the hdfc card this month" in result


def test_the_same_action_is_never_narrated_twice():
    """The engine emits one action per prorated day of a spread item, so the raw head of the list
    can be the same thing three times over and the second real action never gets spoken."""
    plan = make_plan(
        actions=[action(), action(), action(target="groceries", rationale="trim the groceries")]
    )
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert result.count("move netflix to after the salary lands") == 1
    assert "trim the groceries" in result


def test_the_rationale_is_the_policy_text_word_for_word():
    """Policy wrote it, policy owns it: it is the domain's knowledge about what a deferral costs
    and what a minimum payment does not cover."""
    plan = make_plan(actions=[action(rationale="netflix can wait until the salary lands")])
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert "netflix can wait until the salary lands" in lines(result)


def test_the_target_is_prefixed_only_when_the_rationale_does_not_name_it():
    plan = make_plan(actions=[action(rationale="it can wait until the salary lands")])
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert "netflix: it can wait until the salary lands" in lines(result)


def test_an_action_warning_is_a_line_of_its_own():
    plan = make_plan(actions=[action(warning="interest accrues on the card balance")])
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert "interest accrues on the card balance" in lines(result)


def test_every_unpaid_row_carries_its_consequence():
    plan = make_plan(
        status=PlanStatus.UNSOLVABLE,
        unpaid=[
            Unpaid(
                name="hdfc card",
                amount=money(4000),
                due_date=dt.date(2026, 9, 20),
                tier=2,
                consequence="a late fee and interest on the whole balance",
                ask="you could ask for more time",
            ),
        ],
    )
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert (
        "unpaid hdfc card 4,000 due 20 September, a late fee and interest on the whole balance"
        in lines(result)
    )


def test_a_consequence_an_action_warning_already_carried_is_not_said_twice():
    consequence = "a late fee and interest on the whole balance"
    plan = make_plan(
        status=PlanStatus.UNSOLVABLE,
        actions=[action(warning=consequence)],
        unpaid=[
            Unpaid(
                name="hdfc card",
                amount=money(4000),
                due_date=dt.date(2026, 9, 20),
                tier=2,
                consequence=consequence,
                ask="you could ask for more time",
            ),
        ],
    )
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert result.count(consequence) == 1
    assert "unpaid hdfc card 4,000 due 20 September" in lines(result)


def test_more_than_three_unpaid_rows_are_summarised():
    unpaid = [
        Unpaid(
            name=f"debt {i}",
            amount=money(1000),
            due_date=dt.date(2026, 9, 20),
            tier=2,
            consequence="a late fee",
            ask="ask for more time",
        )
        for i in range(5)
    ]
    plan = make_plan(status=PlanStatus.UNSOLVABLE, unpaid=unpaid)
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert "and 2 more unpaid" in lines(result)


def test_a_plan_that_needs_nothing_says_so_in_words_the_model_can_use():
    """B-13. `fragmented_balance-20260913-003557`: the engine returned a surplus of 63,500 and no
    actions at all, and the model invented two actions and a remainder to go with them — "paying
    only the minimum leaves 1,800 rupees still due", which is 3,000 minus 1,200. Same shape as
    the 13,000: a result with nothing to explain is read as a gap, and the model fills it."""
    result = describe(None, make_plan(actions=[]), headline=phrases.PLAN_FINAL, actions=True)
    assert phrases.NO_ACTIONS in result


def test_the_no_actions_line_does_not_claim_cover_that_does_not_exist():
    """The boundary the balance regression taught: an instruction has to be true of the case it
    rides on. "Every payment is covered in full" beside a list of unpaid bills is the one lie
    that matters — it tells somebody who is short that they are fine."""
    plan = make_plan(
        status=PlanStatus.UNSOLVABLE,
        actions=[],
        unpaid=[
            Unpaid(
                name="credit card",
                amount=money(3000),
                due_date=dt.date(2026, 9, 20),
                tier=2,
                consequence="interest accrues",
                ask="ask the lender to move the date",
            )
        ],
    )
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert phrases.NO_ACTIONS not in result


def test_the_no_actions_line_stays_out_of_a_gathering_result():
    """Mid-gathering there are no actions yet because nothing has been planned, which is not the
    same fact at all."""
    assert phrases.NO_ACTIONS not in describe(created(), make_plan(actions=[]))


def test_a_plan_with_actions_says_nothing_about_having_none():
    plan = make_plan(
        actions=[
            Action(
                type=ActionType.DEFER_OPTIONAL,
                target="gym",
                amount=money(1500),
                rationale="move it to next month",
            )
        ]
    )
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert phrases.NO_ACTIONS not in result


def test_the_first_plan_warning_is_carried_as_a_note_not_as_a_sentence():
    """Engine warnings were passed through whole, and Session A's new one — "rent has no date;
    spread across the month." — is a finished sentence with a full stop on it. Every other line
    in a result is a compact fact behind a label, and the one time a bare label reached the model
    it was read out verbatim ("missing: electricity amount", F7). A sentence is likelier still.
    The carrier changes here rather than the engine string: `note:` marks it as something to
    paraphrase, and the trailing stop goes so it does not read as speech ready to say."""
    plan = make_plan(warnings=["two incomes fall outside the window"])
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert "note: two incomes fall outside the window" in lines(result)


def test_a_warning_that_ends_in_a_full_stop_loses_it():
    plan = make_plan(warnings=["rent has no date; spread across the month."])
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert "note: rent has no date; spread across the month" in lines(result)
    assert "spread across the month." not in result


def test_actions_stay_out_of_a_result_that_is_only_recording_a_fact():
    """Mid-gathering the engine already has actions to suggest. Putting them in every result
    pushes the model into explaining a plan the person has not asked to hear yet."""
    plan = make_plan(actions=[action()])
    assert "netflix" not in describe(created(), plan)


def test_the_explain_again_branch_gives_the_actions_back():
    plan = make_plan(actions=[action()])
    result = describe(None, plan, headline=phrases.EXPLAIN_AGAIN, actions=True)
    assert lines(result)[0] == phrases.EXPLAIN_AGAIN
    assert "move netflix to after the salary lands" in result


# ------------------------------------------------------------------ shape and hygiene


def test_describe_invents_no_numbers():
    """Every figure in a result came out of the domain. This is the guarantee the whole number
    traceability check rests on."""
    result = describe(created(), make_plan(), ready())
    from evals.spoken_numbers import numbers_in

    assert numbers_in(result) <= {11000, 45000, 38000, 1200, 28, 0}


def test_describe_never_writes_an_iso_date():
    plan = make_plan(summary=make_summary(lowest_balance_date=dt.date(2026, 10, 10)))
    assert not ISO_DATE.search(describe(created(), plan, ready()))


def test_every_line_is_a_fact_not_a_sentence():
    """No full stops, no joined-up prose: the model reads these as data, and a result that reads
    like speech is a result it reads out."""
    plan = make_plan(provisional=True, excluded_items=["electricity"])
    readiness = ready(missing_fields=["essential:electricity.amount"])
    for line in lines(describe(created(), plan, readiness)):
        assert not line.endswith(".")
        assert line == line.strip()


def test_a_finalised_plan_carrying_consequences_still_fits_in_ninety_words():
    plan = make_plan(
        status=PlanStatus.UNSOLVABLE,
        actions=[
            action(warning="interest accrues on the card balance"),
            action(target="groceries", rationale="trim the groceries", warning="short week"),
        ],
        unpaid=[
            Unpaid(
                name=f"debt {i}",
                amount=money(1000),
                due_date=dt.date(2026, 9, 20),
                tier=2,
                consequence="a late fee and interest on the whole balance",
                ask="you could ask for more time",
            )
            for i in range(3)
        ],
        warnings=["two incomes fall outside the window"],
    )
    result = describe(None, plan, ready(), headline=phrases.PLAN_FINAL, actions=True)
    assert len(result.split()) < 90, result


def test_a_clean_plan_stays_short():
    """35, raised from 25 when the no-actions line landed (B-13). The budget exists so a result
    does not turn into a speech the model reads out, and the fifteen words bought here are the
    ones that stop it inventing a speech of its own: a plan with nothing to do used to say
    nothing about having nothing to do."""
    result = describe(None, make_plan(), ready(), headline=phrases.PLAN_FINAL, actions=True)
    assert len(result.split()) < 35, result


def test_one_consequence_shared_by_three_unpaid_rows_is_said_once():
    """Policy gives every card the same sentence. Reading it out three times in a row is how a
    result stops being information and starts being noise."""
    consequence = "a late fee and interest on the whole balance"
    plan = make_plan(
        status=PlanStatus.UNSOLVABLE,
        unpaid=[
            Unpaid(
                name=f"debt {i}",
                amount=money(1000),
                due_date=dt.date(2026, 9, 20),
                tier=2,
                consequence=consequence,
                ask="you could ask for more time",
            )
            for i in range(3)
        ],
    )
    result = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert result.count(consequence) == 1
    assert result.count("unpaid debt") == 3


# ------------------------------------------------------------------ the instruction on a change


def test_a_changed_value_carries_the_instruction_to_settle_it():
    """The rule is in the prompt as well, and it has to be in both. Across the three pre-cut
    passes every rule a result string enforced held at 100% and every rule left to the model's
    reading of the prompt sat between 0% and 80%; the goodbye only stopped going missing when
    the instruction moved into the result the model reads at the moment it has to act."""
    result = describe(updated({"essential:rent.amount": ("11,000", "12,000")}), make_plan())
    assert lines(result)[0] == "rent: 11,000 -> 12,000; confirm which is right before moving on"


def test_the_instruction_is_asked_for_once_a_turn():
    """Two fields moving is still one thing to settle. Asking twice in one result is how a turn
    ends up with two questions in it."""
    result = describe(
        updated(
            {
                "essential:rent.amount": ("11,000", "12,000"),
                "essential:rent.due_date": ("5 Oct", "7 Oct"),
            }
        ),
        make_plan(),
    )
    assert result.count(phrases.CONFIRM_CHANGE) == 1
    assert lines(result)[1] == "rent due date: 5 Oct -> 7 Oct"


def test_a_first_value_carries_no_instruction():
    """Nothing was replaced, so there is nothing to settle and no question to ask."""
    result = describe(updated({"essential:rent.due_date": ("", "5 Oct")}), make_plan())
    assert phrases.CONFIRM_CHANGE not in result


def test_a_create_carries_no_confirmation_but_asks_for_the_read_back():
    """Nothing was replaced, so there is nothing to settle — but the person still has to hear the
    figure that was just recorded. Over the 25-run matrix the model recorded and went straight to
    its next question in a third of the calls, most reliably on the first fact of all, where the
    result is the recording line and a blocker line and the blocker reads as the instruction."""
    result = describe(created(), make_plan())
    assert phrases.CONFIRM_CHANGE not in result
    assert lines(result)[0] == "recorded rent 11,000; say this back, then ask"


def test_a_record_with_no_figure_in_it_asks_for_nothing():
    outcome = created(name="groceries", changes={})
    assert lines(describe(outcome, make_plan()))[0] == "recorded groceries"


def test_a_turn_carries_one_instruction_even_across_two_recordings():
    result = describe(
        updated(
            {
                "essential:rent.amount": ("", "12,000"),
                "essential:rent.due_date": ("", "5 Oct"),
            }
        ),
        make_plan(),
    )
    assert result.count(phrases.READ_BACK) == 1
    assert lines(result)[1] == "recorded rent due date 5 Oct"


# ------------------------------------------------------------------ how an item is filed


def test_a_flag_is_not_read_back_when_an_item_is_created():
    """The domain reports how it filed the item alongside what the person said. A live run read
    one out as "recorded rent 11,000 due 18 Sep spread dated survival survival"."""
    outcome = created(
        changes={
            "essential:rent.amount": ("", "11,000"),
            "essential:rent.due_date": ("", "18 Sep"),
            "essential:rent.spread": ("", "dated"),
            "essential:rent.survival": ("", "survival"),
        }
    )
    assert lines(describe(outcome, make_plan()))[0].startswith("recorded rent 11,000 due 18 Sep")


def test_a_flag_that_changes_is_reported_as_a_state_not_two_figures():
    """ "which is right, dated or spread?" is not a question anybody asked and not one the person
    could answer. The item is filed differently now; that is the whole fact."""
    result = describe(updated({"essential:rent.spread": ("dated", "spread")}), make_plan())
    assert lines(result)[0] == "rent spread: now spread"
    assert phrases.CONFIRM_CHANGE not in result


def test_income_turning_uncertain_is_reported_the_same_way():
    outcome = Outcome(
        status=OutcomeStatus.UPDATED,
        kind=ItemKind.INCOME,
        name="salary",
        changes={"income:salary.certainty": ("confirmed", "uncertain")},
    )
    assert lines(describe(outcome, make_plan()))[0] == "salary certainty: now uncertain"


def test_the_end_of_an_income_range_is_a_value_not_a_flag():
    outcome = created(
        kind=ItemKind.INCOME,
        name="salary",
        changes={
            "income:salary.amount": ("", "45,000"),
            "income:salary.date": ("", "1 Oct"),
            "income:salary.latest_date": ("", "5 Oct"),
        },
    )
    assert lines(describe(outcome, make_plan()))[0].startswith(
        "recorded salary 45,000 on 1 Oct or 5 Oct"
    )


def test_the_plan_being_explained_does_not_end_in_a_gathering_prompt():
    """ "missing:" is what to ask about next. Ending the finalised plan with one points the model
    back at a question when it should be walking through what to do."""
    readiness = ready(missing_fields=["essential:electricity.amount"])
    plan = make_plan(actions=[action()])
    assert "missing:" not in describe(
        None, plan, readiness, headline=phrases.PLAN_FINAL, actions=True
    )
    assert "missing:" not in describe(
        None, plan, readiness, headline=phrases.EXPLAIN_AGAIN, actions=True
    )
    assert "missing:" in describe(created(), plan, readiness)
