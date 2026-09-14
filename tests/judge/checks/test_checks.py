"""Rule checks over a transcript. No network, no LLM."""

from __future__ import annotations

import pytest

from ledgerline.agent.tools import phrases
from ledgerline.judge.checks import checks


def transcript(*turns, **over) -> dict:
    base = {"scenario": "t", "prompt_version": "v1", "turns": list(turns)}
    base.update(over)
    return base


def user(text: str) -> dict:
    return {"role": "user", "text": text}


def bot(text: str, calls: list[dict] | None = None) -> dict:
    return {"role": "assistant", "text": text, "tool_calls": calls or []}


def call(name: str = "upsert_item", args: dict | None = None, result: str = "") -> dict:
    return {"name": name, "args": args or {}, "result": result}


def recorded_result(line: str, read_back: bool = True) -> str:
    """What `describe._created_line` emits after the cut, via `_asked_back`."""
    return f"recorded {line}; say this back, then ask" if read_back else f"recorded {line}"


def change_result(label: str, old: str, new: str) -> str:
    """What `describe._change_lines` emits after the cut: both figures on one line with the
    instruction riding the fact. The fixtures here used to carry pre-cut strings ("updated rent.
    in 45,000, out 12,000.") that name only the winning figure, so they never exercised
    retirement against a result that re-states the losing one -- which is how the retirement half
    of `numbers_traceable` stayed inert through three matrix passes.
    """
    return f"{label}: {old} -> {new}; confirm which is right before moving on"


def rules(violations) -> set[str]:
    """The rule names the tests name: the sub-rule where a folded check records one, otherwise
    the check itself. The fold labels every violation `"<sub-rule>: <detail>"`, so this reads
    back what each assertion was written about."""
    found = set()
    for violation in violations:
        head = str(violation.detail).partition(": ")[0]
        found.add(head if head in SUB_RULES else violation.rule)
    return found


SUB_RULES = {name for group in checks.FOLDED.values() for name in group}


def both(transcript: dict) -> list:
    """Every check. The name is from when there were gates and advisory rules; most fixtures here
    predate both, and what they assert is unchanged by which check now carries the rule."""
    return checks.run_checks(transcript)


# ------------------------------------------------------------------ numbers_traceable


def test_number_from_a_tool_result_is_allowed():
    t = transcript(
        user("my salary is 45000"),
        bot(
            "So 45,000 rupees a month. What is your rent?",
            [call(result="created salary. in 45,000, out 0.")],
        ),
    )
    assert rules(both(t)) == set()


def test_number_from_the_user_turn_is_allowed():
    t = transcript(user("my rent is 11000"), bot("Rent of 11,000. Anything else?"))
    assert rules(both(t)) == set()


def test_invented_number_is_caught():
    t = transcript(
        user("my salary is 45000"),
        bot(
            "That leaves you 12,300 rupees spare. Sound right?",
            [call(result="created salary. in 45,000, out 0.")],
        ),
    )
    assert "numbers_traceable" in rules(both(t))


def test_spoken_number_words_are_traced_too():
    t = transcript(
        user("my salary is 45000"),
        bot(
            "Forty-five thousand rupees. And your rent?",
            [call(result="created salary. in 45,000, out 0.")],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_invented_number_words_are_caught():
    t = transcript(user("my salary is 45000"), bot("You have twelve thousand three hundred spare."))
    assert "numbers_traceable" in rules(both(t))


@pytest.mark.parametrize(
    ("phrase", "value"),
    [
        ("forty five thousand", 45000),
        ("twelve thousand three hundred", 12300),
        ("one lakh twenty thousand", 120000),
        ("three thousand two hundred", 3200),
        ("eleven", 11),
        ("fifteen hundred", 1500),
    ],
)
def test_words_to_numbers(phrase, value):
    assert value in checks.numbers_in(phrase)


# ------------------------------------------------------------------ one_question_per_turn


# ------------------------------------------------------------------ banned_phrases


@pytest.mark.parametrize(
    "text",
    [
        "You are approved for this.",
        "That is guaranteed to work.",
        "You could take a loan to cover it.",
        "I can get you a settlement offer.",
        "I have transferred the money.",
        "I have paid the card for you.",
    ],
)
def test_banned_phrases_are_caught(text):
    assert "banned_phrases" in rules(both(transcript(user("hi"), bot(text))))


def test_clean_text_has_no_banned_phrase():
    t = transcript(user("hi"), bot("Your card minimum is due on the twelfth."))
    assert "banned_phrases" not in rules(both(t))


# ------------------------------------------------------------------ no_markdown


@pytest.mark.parametrize("text", ["**rent**", "# Plan", "- rent\n- food", "use `this`", "a | b"])
def test_markdown_is_caught(text):
    assert "no_markdown" in rules(both(transcript(user("hi"), bot(text))))


def test_plain_prose_passes_the_markdown_check():
    t = transcript(user("hi"), bot("Rent is due on the fifth, and the card on the twelfth."))
    assert "no_markdown" not in rules(both(t))


# ------------------------------------------------------------------ amounts_repeated


# ------------------------------------------------------------------ reporting


def test_violation_carries_the_turn_the_check_and_the_rule_that_raised_it():
    t = transcript(user("hi"), bot("You are approved."))
    v = both(t)[0]
    assert v.turn == 1 and v.rule == "speakable"
    assert v.detail == "banned_phrases: promises an outcome"


def test_passed_is_true_only_with_no_violations():
    assert checks.passed(transcript(user("hi"), bot("What is your rent?")))
    assert not checks.passed(transcript(user("hi"), bot("You are approved.")))


def test_an_iso_date_is_not_three_invented_numbers():
    t = transcript(user("hi"), bot("Your window ends 2026-10-10. Is that clear?"))
    assert "numbers_traceable" not in rules(both(t))
    assert checks.numbers_in("2026-10-10") == set()


def test_an_iso_date_spoken_aloud_is_flagged():
    t = transcript(user("hi"), bot("Your window ends 2026-10-10."))
    assert "no_iso_dates" in rules(both(t))


def test_a_spoken_date_is_not_flagged():
    t = transcript(user("hi"), bot("Your window ends on the tenth of October."))
    assert "no_iso_dates" not in rules(both(t))


# ------------------------------------------------------------------ banned phrases, revisited


def test_naming_an_existing_personal_loan_passes():
    """Repeating a debt the person already has is the job, not a violation. The old check
    banned the words "personal loan" outright and failed correct sentences."""
    t = transcript(
        user("my personal loan emi is 12000 on the twentieth"),
        bot(
            "Your personal loan is due on the twentieth, twelve thousand rupees. "
            "Shall we look at the card next?",
            [call(result="created personal loan. in 45,000, out 12,000.")],
        ),
    )
    assert rules(both(t)) == set()


def test_recommending_borrowing_fails():
    t = transcript(
        user("what do I do about the gap"),
        bot("You could borrow from a friend to cover the gap."),
    )
    violation = next(v for v in both(t) if v.detail.startswith("banned_phrases: "))
    assert "borrow" in violation.detail


@pytest.mark.parametrize(
    "text",
    [
        "You could take a loan to cover it.",
        "Consider applying for a personal loan.",
        "I can get you a small loan.",
        "You might want a top-up loan on that.",
        "Buy now pay later would bridge it.",
        "Ask them about EMI conversion on the card.",
        "I can get you a settlement offer.",
        "You are pre-approved for this.",
        "I have arranged the payment.",
    ],
)
def test_recommendation_and_claim_language_is_caught(text):
    assert "banned_phrases" in rules(both(transcript(user("hi"), bot(text))))


@pytest.mark.parametrize(
    "text",
    [
        "Your personal loan is due on the twentieth.",
        "The bike loan takes four thousand five hundred rupees on the twentieth.",
        "Let me get your credit card minimum next.",
        "You borrowed that from your brother, so it sits below the card.",
        "That leaves the loan and the card to cover.",
    ],
)
def test_talking_about_existing_debt_is_not_caught(text):
    assert "banned_phrases" not in rules(both(transcript(user("hi"), bot(text))))


# ------------------------------------------------------------------ invented tool arguments


def test_an_invented_upsert_amount_cannot_authorise_itself():
    """The model puts 12,300 into an upsert argument the person never said, then speaks it. The
    tool result echoes it too, so without this rule the number launders itself clean."""
    t = transcript(
        user("my rent is eleven thousand"),
        bot(
            "Okay, twelve thousand three hundred for rent. What is next?",
            [
                call(
                    name="upsert_item",
                    args={"kind": "essential", "name": "rent", "amount": 12300},
                    result="created rent. in 45,000, out 12,300.",
                )
            ],
        ),
    )
    assert "numbers_traceable" in rules(both(t))


def test_an_upsert_amount_the_person_said_in_words_is_fine():
    t = transcript(
        user("my rent is forty-two hundred"),
        bot(
            "Okay, four thousand two hundred for rent. What is next?",
            [
                call(
                    name="upsert_item",
                    args={"kind": "essential", "name": "rent", "amount": 4200},
                    result="created rent. in 45,000, out 4,200.",
                )
            ],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_an_upsert_amount_from_the_turn_before_last_is_still_fine():
    """The model often records a fact one turn after hearing it."""
    t = transcript(
        user("rent is 11000"),
        bot("Okay, eleven thousand. Is it due on a set day?"),
        user("the fifth"),
        bot(
            "Eleven thousand on the fifth, noted.",
            [
                call(
                    name="upsert_item",
                    args={"kind": "essential", "name": "rent", "amount": 11000, "day": 5},
                    result="created rent. in 45,000, out 11,000.",
                )
            ],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_a_figure_the_engine_computed_is_still_trusted():
    """finalize_plan returns numbers nobody said out loud; those are the engine's, not invented."""
    t = transcript(
        user("yes please"),
        bot(
            "You end the month with forty-six thousand rupees. Does that work?",
            [call(name="finalize_plan", args={}, result="plan final. surplus 46,000.")],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


@pytest.mark.parametrize(
    ("phrase", "value"),
    [("12k", 12000), ("1.5 lakh", 150000), ("2 lakhs", 200000), ("45K", 45000)],
)
def test_shorthand_amounts_are_read_as_numbers(phrase, value):
    assert value in checks.numbers_in(phrase)


# ------------------------------------------------------------------ borrowing, A's shape


@pytest.mark.parametrize(
    "text",
    [
        "You could ask family or a local shop for a few days' credit.",
        "See if the shopkeeper will put it on tab.",
        "Ask your employer for an advance from next month's pay.",
        "Could a friend lend you the difference?",
        "They offer an instalment plan on that.",
        "An overdraft would cover the gap.",
        "Buy now, pay later would bridge it.",
    ],
)
def test_every_way_of_proposing_new_money_is_caught(text):
    assert "banned_phrases" in rules(both(transcript(user("hi"), bot(text))))


@pytest.mark.parametrize(
    "text",
    [
        "You could ask the lender whether the date can move.",
        "Missing it gets reported to the credit bureaus.",
        "That shows on your credit report for years.",
        "Your credit card minimum is due on the twelfth.",
        "It would dent your credit score.",
        "Your personal loan is due on the twentieth.",
        "You borrowed that from your brother, so it sits below the card.",
    ],
)
def test_talking_about_credit_you_already_have_is_not_caught(text):
    assert "banned_phrases" not in rules(both(transcript(user("hi"), bot(text))))


def test_the_credit_record_a_missed_payment_shows_on_is_not_an_offer():
    """The engine's own warning is "nothing reaches your credit report"; over five runs the model
    paraphrased it as "affect your credit record", which is the same record the person already
    has. Saying what a missed payment does to it is the job, not an offer of new money."""
    for said in ("It can affect your credit record.", "That stays on your credit history."):
        t = transcript(user("ok"), bot(said))
        assert "banned_phrases" not in rules(both(t)), said


def test_a_hyphenated_credit_card_is_the_same_card():
    """A live run failed the banned-phrase gate for "the credit-card minimum due on the
    twentieth". Spoken aloud that is the card the person already has; the hyphen is spelling."""
    t = transcript(user("ok"), bot("Keep 1,200 rupees for the credit-card minimum."))
    assert "banned_phrases" not in rules(both(t))


def test_the_word_credit_alone_is_treated_as_an_offer():
    """ "a few days' credit" is new money. "credit bureau", "credit card", "credit report" and
    "credit score" are the only honest uses: a record you already have."""
    t = transcript(user("hi"), bot("The shop might give you credit until payday."))
    assert "banned_phrases" in rules(both(t))


# ------------------------------------------------------------------ two amounts in one breath


def test_a_full_stop_ends_an_amount():
    """Live defect, one_word_answers: the person answered "Day thirty. Thirty-eight thousand
    rupees." and the parser ran straight through the full stop into 68,000. The 38,000 they
    actually said then counted as never said — and because a recording tool's arguments are
    struck from its result when the person did not say them, the figure vanished from the tool
    result too and the assistant was failed for speaking a number it had been handed."""
    found = checks.numbers_in("Day thirty. Thirty-eight thousand rupees.")
    assert 38000 in found
    assert 68000 not in found


def test_a_comma_ends_an_amount_too():
    """Same shape without the full stop: "Day thirty, thirty-eight thousand rupees"."""
    found = checks.numbers_in("Day thirty, thirty-eight thousand rupees")
    assert 38000 in found
    assert 68000 not in found


def test_a_scale_still_spans_the_words_inside_one_clause():
    """The boundary must not be so eager that it breaks a single spoken amount apart."""
    assert 45200 in checks.numbers_in("forty-five thousand two hundred")


def test_two_amounts_joined_by_and_are_not_added_together():
    """ "forty-five thousand and twelve thousand" is two figures. Folding them into 57,000 made
    that sum a user-sourced number, so the assistant could speak arithmetic nobody did."""
    found = checks.numbers_in("forty-five thousand and twelve thousand")
    assert 45000 in found and 12000 in found
    assert 57000 not in found


@pytest.mark.parametrize(
    ("phrase", "value"),
    [
        ("one thousand and two hundred", 1200),
        ("twelve thousand three hundred", 12300),
        ("one lakh twenty thousand", 120000),
        ("two hundred and fifty", 250),
        ("fifteen hundred", 1500),
    ],
)
def test_one_amount_spoken_across_several_words_still_parses(phrase, value):
    assert value in checks.numbers_in(phrase)


def test_a_sum_of_two_spoken_amounts_is_not_traceable():
    t = transcript(
        user("I earn forty-five thousand and my wife earns twelve thousand"),
        bot("So fifty-seven thousand between you. Is that right?"),
    )
    assert "numbers_traceable" in rules(both(t))


# ------------------------------------------------------------------ superseded figures


def test_a_corrected_amount_stops_being_a_valid_source():
    """Rent goes 11,000 -> 12,000. Saying 11,000 afterwards contradicts the cards and the plan,
    and the old figure was staying allowed forever."""
    t = transcript(
        user("rent is 11000"),
        bot(
            "Okay, eleven thousand for rent.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 11000},
                    result=recorded_result("rent 11,000"),
                )
            ],
        ),
        user("sorry, rent is 12000"),
        bot(
            "Twelve thousand for rent.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12000},
                    result=change_result("rent", "11,000", "12,000"),
                )
            ],
        ),
        user("that's all"),
        bot("Your rent of 11,000 is the biggest item."),
    )
    violations = [v for v in both(t) if v.detail.startswith("numbers_traceable: ")]
    assert violations and violations[0].turn == 5


def test_the_current_amount_is_still_fine_after_a_correction():
    t = transcript(
        user("rent is 11000"),
        bot(
            "Okay, eleven thousand for rent.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 11000},
                    result=recorded_result("rent 11,000"),
                )
            ],
        ),
        user("sorry, rent is 12000"),
        bot(
            "Twelve thousand for rent.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12000},
                    result=change_result("rent", "11,000", "12,000"),
                )
            ],
        ),
        user("that's all"),
        bot("Your rent of 12,000 is the biggest item."),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_a_conflict_question_may_name_both_figures():
    """The tool result asks which is right; the model has to be able to say both."""
    t = transcript(
        user("rent is 11000"),
        bot(
            "Okay, eleven thousand.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 11000},
                    result=recorded_result("rent 11,000"),
                )
            ],
        ),
        user("rent is 12000"),
        bot(
            "Earlier you said 11,000 for rent, now 12,000. Which is right?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12000},
                    result=change_result("rent", "11,000", "12,000"),
                )
            ],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_a_different_item_keeps_its_own_amount():
    t = transcript(
        user("rent is 11000 and food is 6000"),
        bot(
            "Rent eleven thousand, food six thousand.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 11000},
                    result=recorded_result("rent 11,000"),
                ),
                call(
                    args={"kind": "essential", "name": "food", "amount": 6000},
                    result=recorded_result("food 6,000", read_back=False),
                ),
            ],
        ),
        user("rent is 12000 now"),
        bot(
            "Twelve thousand for rent.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12000},
                    result=change_result("rent", "11,000", "12,000"),
                )
            ],
        ),
        user("ok"),
        bot("Food is 6,000 a month."),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_the_turn_that_speaks_the_correction_may_name_both_figures():
    """ "Not eleven thousand then, twelve thousand for rent" is the natural way to acknowledge a
    correction. The old figure is retired from the turn after, not from the turn that makes it."""
    t = transcript(
        user("rent is 11000"),
        bot(
            "Okay, eleven thousand.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 11000},
                    result=recorded_result("rent 11,000"),
                )
            ],
        ),
        user("no, make it 12000"),
        bot(
            "Not eleven thousand then, twelve thousand for rent.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12000},
                    result=change_result("rent", "11,000", "12,000"),
                )
            ],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("the rent", "rent"),
        ("rent", "The Rent"),
        ("rent.", "rent"),
        ("a  rent", "rent"),
    ],
    ids=["article", "case", "punctuation", "spacing"],
)
def test_an_item_named_differently_is_still_the_same_item(first, second):
    """The domain keys items through normalise_name, so "the rent" and "rent" are one row on the
    cards. The checker used the raw string, so a correction under a different spelling never
    retired the old amount."""
    t = transcript(
        user("rent is 11000"),
        bot(
            "Eleven thousand for rent.",
            [
                call(
                    args={"kind": "essential", "name": first, "amount": 11000},
                    result=recorded_result("rent 11,000"),
                )
            ],
        ),
        user("sorry, 12000"),
        bot(
            "Twelve thousand.",
            [
                call(
                    args={"kind": "essential", "name": second, "amount": 12000},
                    result=change_result("rent", "11,000", "12,000"),
                )
            ],
        ),
        user("ok"),
        bot("Your rent of 11,000 is the biggest item."),
    )
    assert "numbers_traceable" in rules(both(t))


def test_a_correction_retires_the_old_amount_even_though_the_result_names_both():
    """The live defect: the change result prints "rent: 11,000 -> 12,000" so the losing figure is
    re-authorised by the same result that retired it, and the bot can go on saying 11,000."""
    t = transcript(
        user("my rent is eleven thousand"),
        bot(
            "Rent 11,000 rupees. When is it due?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 11000},
                    result="recorded rent 11,000; say this back, then ask",
                )
            ],
        ),
        user("actually the rent is twelve thousand"),
        bot(
            "Rent 12,000 rupees, not 11,000. Which is right?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12000},
                    result=change_result("rent", "11,000", "12,000"),
                )
            ],
        ),
        user("twelve thousand is right"),
        bot("So your rent of 11,000 rupees is the big one."),
    )
    assert "numbers_traceable" in rules(both(t))


def test_the_turn_that_makes_the_change_may_still_name_both_figures():
    """The other side of it: asking which of two figures is right means saying both, so the turn
    that records the change is allowed to."""
    t = transcript(
        user("my rent is eleven thousand"),
        bot(
            "Rent 11,000 rupees. When is it due?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 11000},
                    result="recorded rent 11,000; say this back, then ask",
                )
            ],
        ),
        user("actually the rent is twelve thousand"),
        bot(
            "I had 11,000 rupees and now 12,000 rupees. Which is right?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12000},
                    result=change_result("rent", "11,000", "12,000"),
                )
            ],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_a_possessive_names_the_same_item_the_domain_merged():
    """A-10b: the domain matches "rent" then "my rent" as one item, so the checker has to as well
    or the 11,000 it overwrote is never retired."""
    t = transcript(
        user("rent is eleven thousand"),
        bot(
            "Rent 11,000 rupees.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 11000},
                    result="recorded rent 11,000; say this back, then ask",
                )
            ],
        ),
        user("my rent is twelve thousand"),
        bot(
            "Twelve thousand rupees.",
            [
                call(
                    args={"kind": "essential", "name": "my rent", "amount": 12000},
                    result=change_result("rent", "11,000", "12,000"),
                )
            ],
        ),
        user("that is all"),
        bot("Your rent of 11,000 rupees is the biggest item."),
    )
    assert "numbers_traceable" in rules(both(t))


def test_two_owners_are_two_debts_and_neither_retires_the_other():
    """The other half of A-10b, and the one that loses money if it goes wrong: "my loan" and "his
    loan" are two people's debts. Retiring one against the other would make a real figure
    unsayable and hide a debt that is still owed."""
    t = transcript(
        user("my loan is eleven thousand"),
        bot(
            "Eleven thousand rupees.",
            [
                call(
                    args={"kind": "debt", "name": "my loan", "amount": 11000},
                    result="recorded my loan 11,000; say this back, then ask",
                )
            ],
        ),
        user("his loan is twelve thousand"),
        bot(
            "Twelve thousand rupees.",
            [
                call(
                    args={"kind": "debt", "name": "his loan", "amount": 12000},
                    result="recorded his loan 12,000; say this back, then ask",
                )
            ],
        ),
        user("that is all"),
        bot("Your loan of 11,000 rupees is due first."),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_an_ambiguous_possessive_retires_nothing():
    """`_find` answers None when a bare name could be either of two stored items, so the domain
    creates a third rather than guessing. The checker must not retire a figure the domain kept."""
    t = transcript(
        user("my loan is eleven thousand and his loan is twelve thousand"),
        bot(
            "Eleven thousand rupees.",
            [
                call(
                    args={"kind": "debt", "name": "my loan", "amount": 11000},
                    result="recorded my loan 11,000; say this back, then ask",
                ),
                call(
                    args={"kind": "debt", "name": "his loan", "amount": 12000},
                    result="recorded his loan 12,000; say this back, then ask",
                ),
            ],
        ),
        user("the loan is thirteen thousand"),
        bot(
            "Thirteen thousand rupees.",
            [
                call(
                    args={"kind": "debt", "name": "loan", "amount": 13000},
                    result="recorded loan 13,000; say this back, then ask",
                )
            ],
        ),
        user("that is all"),
        bot("The 11,000 rupees one is due first."),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_the_figure_offered_when_querying_an_implausible_amount_is_sayable():
    """Two rules collided on the first live run of the new instruction. The result says "rent
    looks small, confirm it before moving on", and the only useful way to ask is to offer the
    reading the person probably meant: "is that twelve rupees, or did you mean twelve thousand?"
    That twelve thousand is in no result and no user turn, so `numbers_traceable` failed three
    runs in five for doing exactly what the other rule had just told it to do.

    A candidate offered inside a question is not a figure claimed as fact, so it is allowed --
    but only in a turn the result actually asked to have settled, and only inside the question.
    """
    t = transcript(
        user("My rent is 12."),
        bot(
            "You said rent is twelve rupees; is that correct, or did you mean twelve thousand?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12},
                    result=f"recorded rent 12; rent{phrases.CONFIRM_AMOUNT}",
                )
            ],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_the_exemption_does_not_cover_a_figure_stated_as_fact():
    """Same turn, same instruction, but the number is asserted outside the question. Offering a
    reading is a question; telling someone what they pay is a claim."""
    t = transcript(
        user("My rent is 12."),
        bot(
            "Your rent is twelve thousand rupees. Shall we go on?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12},
                    result=f"recorded rent 12; rent{phrases.CONFIRM_AMOUNT}",
                )
            ],
        ),
    )
    assert "numbers_traceable" in rules(both(t))


def test_the_exemption_does_not_leak_into_ordinary_turns():
    """A turn whose result carried no such instruction gets no licence to invent, however many
    question marks it contains."""
    t = transcript(
        user("My rent is 11000."),
        bot(
            "Rent eleven thousand. Is your salary forty-five thousand rupees?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 11000},
                    result=recorded_result("rent 11,000"),
                )
            ],
        ),
    )
    assert "numbers_traceable" in rules(both(t))


# ------------------------------------------------------------------ implausible amounts


def implausible(kind: str, name: str, amount: int) -> dict:
    return call(
        args={"kind": kind, "name": name, "amount": amount},
        result=recorded_result(f"{name} {amount}"),
    )


# ------------------------------------------------------------------ carried figures


CARRIED_RESULT = (
    "carried from last call: rent 12,000 on the 5th, salary 45,000 on the 1st; "
    "say each back, then ask whether all still hold, confirm or change each before the plan\n"
    "blocked: carried"
)


def returning(*turns) -> dict:
    return transcript(
        user("hello again"),
        bot(
            "Welcome back.",
            [call(name="upsert_item", args={"name": "rent"}, result=CARRIED_RESULT)],
        ),
        *turns,
        state=state(),
    )


def finalised() -> dict:
    return {
        "role": "assistant",
        "text": "Here is the plan.",
        "tool_calls": [{"name": "finalize_plan", "args": {}, "result": "plan final\nsurplus 0"}],
    }


def test_a_carried_figure_is_sayable_before_any_tool_result_names_it():
    """Two rules pointing opposite ways, found on the first returning-caller cell. The greeting
    block tells the coach to read the carried figures back, and in the greeting there is no tool
    result yet — so `numbers_traceable` failed three runs in five for saying exactly what the
    other instruction had just asked for. The figures came from the store, which is a source, and
    the recording carries them so the check can see it."""
    t = transcript(
        bot("Welcome back. Last time you had rent of 12,000 and salary of 45,000. Still right?"),
        user("Yes."),
        state=state(),
        carried=[["rent", "12,000 on the 5th"], ["salary", "45,000 on the 1st"]],
    )
    assert "numbers_traceable" not in rules(both(t))


def test_a_figure_that_was_never_carried_is_still_not_sayable():
    t = transcript(
        bot("Welcome back. Last time your rent was 99,000, wasn't it?"),
        user("No."),
        state=state(),
        carried=[["rent", "12,000 on the 5th"]],
    )
    assert "numbers_traceable" in rules(both(t))


# ------------------------------------------------------------------ actions match the plan


def planned(result: str, *after) -> dict:
    """A run that finalised, plus the assistant turns that explained the plan."""
    return transcript(
        user("go on then"),
        bot("Here is the plan.", [call(name="finalize_plan", args={}, result=result)]),
        *after,
        state=state(
            essentials=[{"name": "rent", "amount": "11000.00"}],
            debts=[{"name": "credit card", "amount_due": "3000.00"}],
            optionals=[{"name": "gym", "amount": "1500.00"}],
        ),
    )


PLAN_WITH_AN_ACTION = (
    "plan final\n"
    "in 45,000, out 21,500, lowest 1,000 on 30 September\n"
    "surplus 0, shortfall 0\n"
    "gym: move it to next month, the money is needed for rent"
)

PLAN_WITH_NOTHING_TO_DO = (
    "plan final\n"
    "in 45,000, out 21,500, lowest 21,000 on 30 September\n"
    "surplus 63,500, shortfall 0\n"
    "no actions needed: every payment is covered in full; "
    "explain the lowest point and propose nothing"
)


def test_an_action_the_plan_proposed_is_fine():
    t = planned(PLAN_WITH_AN_ACTION, bot("Move the gym payment to next month. Does that work?"))
    assert "actions_match_plan" not in rules(both(t))


def test_an_action_the_plan_never_proposed_is_caught():
    """The live defect, `fragmented_balance-20260913-003557`: the engine returned a surplus and no
    actions, and the bot proposed keeping money back for rent and paying the card minimum. Both
    figures were traceable because both had been recorded earlier in the call, so every existing
    rule passed a run that invented an entire course of action."""
    t = planned(
        PLAN_WITH_NOTHING_TO_DO,
        bot("Pay at least 1,200 rupees toward the credit card by the twentieth. Make sense?"),
    )
    assert "actions_match_plan" in rules(both(t))


def test_naming_an_item_without_proposing_anything_is_not_an_action():
    """Walking through the month is the job. "Your rent is due on the eighteenth" proposes
    nothing, and a rule that reads it as a proposal would fail every explanation there is."""
    t = planned(
        PLAN_WITH_NOTHING_TO_DO,
        bot("Your rent of 11,000 rupees is due on the eighteenth. Does that match?"),
    )
    assert "actions_match_plan" not in rules(both(t))


def test_the_rule_says_nothing_about_turns_before_the_plan():
    """Mid-gathering the engine has actions it would suggest and the model is right to ignore
    them; this rule is only about the turns that explain a final plan."""
    t = transcript(
        user("my gym is 1500"),
        bot("Recorded. Shall we move the gym payment?", [call(args={"name": "gym"})]),
        state=state(optionals=[{"name": "gym", "amount": "1500.00"}]),
    )
    assert "actions_match_plan" not in rules(both(t))


def test_a_run_that_never_finalised_is_not_judged():
    t = transcript(user("hello"), bot("Hi."), state=state())
    assert "actions_match_plan" not in rules(both(t))


# ------------------------------------------------------------------ state matches the facts


def facts(**over) -> dict:
    base = {
        "opening_balance": "40000",
        "incomes": [{"name": "salary", "amount": "45000", "day": 1}],
        "essentials": [{"name": "rent", "amount": "11000", "day": 18}],
        "debts": [],
        "optionals": [],
    }
    base.update(over)
    return base


def state(**over) -> dict:
    base = {
        "opening_balance": "40000.00",
        "incomes": [{"name": "salary", "amount": "45000.00"}],
        "essentials": [{"name": "rent", "amount": "11000.00"}],
        "debts": [],
        "optionals": [],
        "unknowns": [],
    }
    base.update(over)
    return base


def run(hidden=None, recorded=None, *turns) -> dict:
    return transcript(*turns, hidden_facts=hidden or facts(), state=recorded or state())


def test_a_run_that_recorded_everything_the_person_said_is_clean():
    assert "state_matches_facts" not in rules(both(run()))


def test_half_the_balance_is_the_defect_every_other_check_passes():
    """`fragmented_balance`: 20,000 in cash AND 20,000 in the bank, said as three fragments. In
    all fifteen post-cut runs the model made ONE balance call and stored 20,000, so the plan was
    built on half the person's money. Nothing was invented, the read-back matched the result and
    no value changed, so every existing rule is clean on those runs. This is the check that was
    missing."""
    violations = both(run(recorded=state(opening_balance="20000.00")))
    assert "state_matches_facts" in rules(violations)
    assert any("opening_balance" in v.detail for v in violations)


def test_an_amount_recorded_wrongly_is_caught():
    wrong = state(essentials=[{"name": "rent", "amount": "1100.00"}])
    assert "state_matches_facts" in rules(both(run(recorded=wrong)))


def test_a_fact_the_person_stated_and_the_bot_never_recorded_is_caught():
    t = run(None, state(essentials=[]), user("my rent is eleven thousand"), bot("Noted."))
    assert "state_matches_facts" in rules(both(t))


def test_a_fact_the_person_never_mentioned_is_not_the_bot_s_fault():
    """`hidden_facts` is the persona's whole truth and the scripted turns hold some of it back --
    "Nothing." in `one_word_answers` is the person declining to mention the phone EMI. Judging
    the notes rather than the conversation failed 84% of every saved run."""
    t = run(None, state(essentials=[]), user("that is all"), bot("Right."))
    assert "state_matches_facts" not in rules(both(t))


def test_a_fact_the_person_declined_to_give_is_not_a_mismatch():
    """ "I don't know" is an answer. The coach parked it and moved on, which is what it was told
    to do, so the gap is the person's and not the bot's."""
    parked = state(
        essentials=[], unknowns=[{"field": "essential:rent.amount", "reason": "unknown"}]
    )
    assert "state_matches_facts" not in rules(both(run(recorded=parked)))


def test_an_item_stored_under_a_possessive_is_the_same_item():
    """The domain merges "rent" and "my rent"; so must this, or a coach that recorded the fact
    correctly is reported as having lost it."""
    renamed = state(essentials=[{"name": "my rent", "amount": "11000.00"}])
    assert "state_matches_facts" not in rules(both(renamed and run(recorded=renamed)))


def test_a_debt_is_read_from_its_own_field():
    """Debts store the figure as `amount_due`, not `amount`. Reading the wrong field would report
    every correctly recorded debt as missing."""
    hidden = facts(debts=[{"name": "credit card", "amount": "3000", "debt_kind": "credit_card"}])
    recorded = state(debts=[{"name": "credit card", "amount_due": "3000.00"}])
    assert "state_matches_facts" not in rules(both(run(hidden, recorded)))


def test_a_card_minimum_recorded_as_the_full_balance_is_caught():
    """Live in 4 of 13 post-cut runs: `amount` is right and `min_due` is the TOTAL. A minimum
    equal to the balance means paying the minimum saves nothing, so the engine's one cheap action
    on a card quietly stops existing and a person who could have paid 1,200 this month is planned
    as owing 3,000. `amount_due` alone was right, so the check could not see it."""
    hidden = facts(
        debts=[
            {"name": "credit card", "amount": "3000", "debt_kind": "credit_card", "min_due": "1200"}
        ]
    )
    recorded = state(debts=[{"name": "credit card", "amount_due": "3000.00", "min_due": "3000.00"}])
    violations = both(run(hidden, recorded))
    assert "state_matches_facts" in rules(violations)
    assert any("minimum" in v.detail for v in violations)


def test_a_card_minimum_recorded_correctly_is_clean():
    hidden = facts(
        debts=[
            {"name": "credit card", "amount": "3000", "debt_kind": "credit_card", "min_due": "1200"}
        ]
    )
    recorded = state(debts=[{"name": "credit card", "amount_due": "3000.00", "min_due": "1200.00"}])
    assert "state_matches_facts" not in rules(both(run(hidden, recorded)))


def test_a_minimum_the_person_never_gave_is_not_demanded():
    hidden = facts(debts=[{"name": "credit card", "amount": "3000", "debt_kind": "credit_card"}])
    recorded = state(debts=[{"name": "credit card", "amount_due": "3000.00"}])
    assert "state_matches_facts" not in rules(both(run(hidden, recorded)))


def test_a_transcript_with_no_hidden_facts_is_not_judged():
    """Checks run over live recordings too, and a real call has no persona to compare against."""
    t = transcript(user("hello"), bot("Hi."))
    assert "state_matches_facts" not in rules(both(t))


# ------------------------------------------------------------------ parking and farewells


def unknown_turn(field: str, text: str) -> dict:
    return {
        "role": "assistant",
        "text": text,
        "tool_calls": [call(name="mark_unknown", args={"field": field, "not_applicable": False})],
    }


def ending(text: str) -> dict:
    return {"role": "assistant", "text": text, "tool_calls": [call(name="end_call")]}


# ------------------------------------------------------------------ changed_value_acknowledged


def changed(field: str = "essential:rent.amount", line: str = "rent: 11,000 -> 12,000") -> dict:
    """An upsert whose result reports that a value the person had already given has moved."""
    return call(
        "upsert_item",
        {"kind": "essential", "name": "rent", "amount": 12000},
        f"{line}\nin 45,000, out 27,700",
    )


# ------------------------------------------------------------------ claims have receipts


def test_claiming_to_have_noted_a_figure_that_was_never_recorded_is_the_defect():
    """The third live call. STT heard "my red went up to" with the amount in the next fragment;
    the bot said "I've noted rent as 13,000 rupees" and called no tool. The state kept 11,000,
    the stored profile kept 11,000, and the person rang off believing the correction had landed.
    Every other rule passed — numbers_traceable because they really did say 13,000."""
    t = transcript(
        user("my red went up to"),
        user("thirteen thousand"),
        bot("I've noted rent as 13,000 rupees. What else has changed?"),
        state=state(),
    )
    assert "claimed_values_recorded" in rules(both(t))


def test_a_claim_backed_by_a_call_in_the_same_turn_passes():
    t = transcript(
        user("rent is thirteen thousand now"),
        bot(
            "I've noted rent as 13,000 rupees. What else?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 13000},
                    result=change_result("rent", "11,000", "13,000"),
                )
            ],
        ),
        state=state(),
    )
    assert "claimed_values_recorded" not in rules(both(t))


def test_a_claim_backed_by_the_previous_assistant_turn_passes():
    """The coach is told to speak once after the result, so the words can land a turn later."""
    t = transcript(
        user("rent is thirteen thousand now"),
        bot(
            "Let me update that.",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 13000},
                    result=change_result("rent", "11,000", "13,000"),
                )
            ],
        ),
        user("thanks"),
        bot("Rent is recorded as 13,000 rupees. Anything else?"),
        state=state(),
    )
    assert "claimed_values_recorded" not in rules(both(t))


def test_a_sentence_with_a_claim_verb_and_no_figure_is_not_judged():
    """ "Your groceries are recorded across the month" claims nothing a person could be wrong
    about; the rule is about figures, not about the word."""
    t = transcript(
        user("groceries about six thousand"),
        bot("Groceries are recorded across the month. What else?"),
        state=state(),
    )
    assert "claimed_values_recorded" not in rules(both(t))


def test_speaking_a_figure_without_claiming_to_have_stored_it_is_not_judged():
    """Reading a figure back is the job and has its own rules. This one only fires on a receipt."""
    t = transcript(
        user("rent is thirteen thousand"),
        bot("Thirteen thousand rupees for rent. When is it due?"),
        state=state(),
    )
    assert "claimed_values_recorded" not in rules(both(t))


# ------------------------------------------------------------------ no_silent_turn


def test_acting_and_saying_nothing_after_the_person_spoke_is_caught():
    """From the owner's live call: the person says "I did not understand", the bot calls
    `record_understanding` and speaks no word at all. The person hears silence and starts again.
    Three turns of that call are this shape, and no rule saw them."""
    t = transcript(
        user("I did not understand."),
        bot("", [call("record_understanding", {"confirmed": False}, "not agreed")]),
    )
    assert rules(checks._no_silent_turn(t)) == {"no_silent_turn"}


def test_a_tool_turn_that_speaks_is_fine():
    t = transcript(
        user("rent is thirteen thousand"),
        bot("Thirteen thousand rupees for rent. What else?", [call(result="recorded rent 13,000")]),
    )
    assert not checks._no_silent_turn(t)


def test_a_silent_hang_up_is_a_silent_turn():
    """A call that ends with no goodbye at all is the defect the old `silent_before_acting`
    exemption existed to prevent, and `done` is not exempt from this rule."""
    t = transcript(user("no, that's all"), bot("", [call("done", {}, "call ending")]))
    assert rules(checks._no_silent_turn(t)) == {"no_silent_turn"}


def test_a_turn_with_no_tool_call_and_no_words_is_not_this_rule():
    """An empty turn with nothing behind it is a transport failure, not a coach that acted and
    stayed quiet. This rule is about the pairing of an action with silence."""
    t = transcript(user("hello?"), bot(""))
    assert not checks._no_silent_turn(t)


def test_a_silent_turn_that_follows_the_bot_rather_than_the_person_is_not_judged():
    """Two assistant turns in a row are one reply to the pipeline: the first records, the second
    speaks. Nobody is left waiting, so there is no silence to hear."""
    t = transcript(
        user("rent is thirteen thousand"),
        bot("Let me put that down.", [call(result="recorded rent 13,000")]),
        bot("", [call(result="recorded rent 13,000")]),
    )
    assert not checks._no_silent_turn(t)


# ------------------------------------------------------------------ no_spoken_decimals


@pytest.mark.parametrize(
    "text",
    [
        "Your lowest balance is 1,466.57 rupees on the second of October.",
        "That leaves 4,433.37 rupees unpaid.",
        "You have a 1,166.75-rupee gap.",
    ],
)
def test_paise_spoken_as_digits_is_caught(text):
    assert rules(checks._no_spoken_decimals(transcript(bot(text)))) == {"no_spoken_decimals"}


def test_paise_spoken_in_words_is_caught():
    """The owner's live call, twice: "fifty-seven thousand one hundred sixty-six point six one
    rupees". Text to speech reads the engine's Decimal out loud and nobody says paise."""
    said = "Your lowest balance is fifty-seven thousand one hundred sixty-six point six one rupees."
    t = transcript(bot(said))
    assert rules(checks._no_spoken_decimals(t)) == {"no_spoken_decimals"}


def test_whole_rupees_pass():
    t = transcript(bot("Your lowest balance is 1,466 rupees on the second of October."))
    assert not checks._no_spoken_decimals(t)


def test_a_shorthand_amount_is_not_paise():
    """ "One point five lakh" and "1.5 lakh" are how people say a round figure, not paise."""
    t = transcript(bot("That is 1.5 lakh, or one point five lakh, a year."))
    assert not checks._no_spoken_decimals(t)


def test_only_what_the_coach_says_is_judged():
    """A tool result carries the engine's own Decimal and the person can say what they like; the
    rule is about what was spoken aloud."""
    t = transcript(
        user("it says 1,466.57"),
        bot("Fourteen hundred and sixty-six rupees. What else?", [call(result="lowest 1,466.57")]),
    )
    assert not checks._no_spoken_decimals(t)


# ------------------------------------------------------------------ gates and advisory


def test_no_rule_is_both_and_none_is_lost():
    assert [check.__name__ for check in checks.CHECKS] == list(checks.FOLDED)
    assert len(checks.CHECKS) == 3


# ------------------------------------------------------------------ no_premature_plan


def planning_state(**over) -> dict:
    base = {
        "today": "2026-09-11",
        "horizon_days": 30,
        "opening_balance": "60000.00",
        "incomes": [{"name": "salary", "amount": "30000.00", "date": "2026-09-30"}],
        "debts": [],
        "essentials": [{"name": "rent", "amount": "13000.00", "due_date": "2026-10-07"}],
        "optionals": [],
        "unknowns": [],
        "plan_final": True,
    }
    base.update(over)
    return base


def test_planning_with_a_kind_never_mentioned_is_caught():
    """The owner's call: it planned with no debt and no everyday spending ever discussed, and
    said the month was covered in full. Nothing was wrong with the arithmetic; the picture was
    half a picture. `coverage` is the domain's own three-valued answer, so this reads what the
    call established rather than guessing from the words."""
    t = transcript(bot("Here is the plan."), state=planning_state(), plan_final=True)
    violations = checks._no_premature_plan(t)
    assert rules(violations) == {"no_premature_plan"}
    assert "debt" in violations[0].detail and "optional" in violations[0].detail


def test_a_kind_the_person_said_they_have_none_of_is_covered():
    """ "No loans, no cards" is an answer. `nothing_more` records it and the domain reports NONE,
    which is coverage, not a gap."""
    t = transcript(
        bot("Here is the plan."),
        state=planning_state(
            unknowns=[
                {"field": "debt", "reason": "not_applicable"},
                {"field": "optional", "reason": "not_applicable"},
            ]
        ),
        plan_final=True,
    )
    assert not checks._no_premature_plan(t)


def test_a_kind_with_something_recorded_is_covered():
    t = transcript(
        bot("Here is the plan."),
        state=planning_state(
            debts=[{"name": "bike loan", "amount": "4000.00", "debt_kind": "loan"}],
            unknowns=[{"field": "optional", "reason": "not_applicable"}],
        ),
        plan_final=True,
    )
    assert not checks._no_premature_plan(t)


def test_a_call_that_never_planned_cannot_plan_prematurely():
    t = transcript(bot("What else goes out?"), state=planning_state(plan_final=False))
    assert not checks._no_premature_plan(t)


def test_a_recording_whose_state_cannot_be_read_is_not_judged():
    """Pre-cut runs carry a state shape the domain no longer validates. A rule that cannot read
    the evidence reports nothing rather than inventing a verdict either way."""
    t = transcript(bot("Here is the plan."), state={"nonsense": True}, plan_final=True)
    assert not checks._no_premature_plan(t)


# ------------------------------------------------------------------ explains_on_request


# ------------------------------------------------------------------ provenance, plain tools


def test_a_figure_from_a_plain_note_is_sayable():
    """The tool names changed with the redesign; provenance follows them or every v2 run fails
    `numbers_traceable` for saying what the person just said."""
    t = transcript(
        user("my rent is thirteen thousand"),
        bot(
            "Thirteen thousand for rent. What else goes out?",
            [call("note", {"item": "rent", "amount": 13000}, "noted rent 13,000")],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_an_invented_note_amount_cannot_authorise_itself():
    """The laundering path: an amount the person never said goes in as an argument, comes back
    inside the result, and from there reads as a figure a tool gave us."""
    t = transcript(
        user("rent, I think"),
        bot(
            "Thirteen thousand for rent, then.",
            [call("note", {"item": "rent", "amount": 13000}, "noted rent 13,000")],
        ),
    )
    assert "numbers_traceable" in rules(both(t))


def test_a_corrected_amount_stops_being_sayable_after_a_plain_note():
    t = transcript(
        user("rent is eleven thousand"),
        bot(
            "Eleven thousand.",
            [call("note", {"item": "rent", "amount": 11000}, "noted rent 11,000")],
        ),
        user("sorry, thirteen thousand"),
        bot(
            "Thirteen thousand, not eleven.",
            [call("note", {"item": "rent", "amount": 13000}, "rent 11,000 before, now 13,000")],
        ),
        user("right"),
        bot("Your rent of 11,000 rupees is what I have."),
    )
    assert "numbers_traceable" in rules(both(t))


def test_a_salary_being_credited_is_not_an_offer_of_credit():
    """Indian English: a salary is credited to an account. The first v2 run failed this gate for
    asking "when do you expect it to be credited?", which is the most ordinary sentence here."""
    t = transcript(bot("When do you expect your salary to be credited?"))
    assert not checks._banned_phrases(t)
    assert not checks._banned_phrases(transcript(bot("Your pay is crediting on the thirtieth.")))


def test_offering_credit_is_still_caught():
    t = transcript(bot("I can get you a few days of credit on that."))
    assert rules(checks._banned_phrases(t)) == {"banned_phrases"}


def test_the_persons_own_mental_arithmetic_may_be_quoted_back_to_reject_it():
    """Three v2 runs of `owner_call_1` failed for the right answer. The person says "thirty minus
    eighteen is not fifty-seven" — a whole sentence in thousands — and the coach replies that the
    57,000 figure is not the result. 57 is below the tracing floor, so the challenge was not a
    source for the figure it is about."""
    t = transcript(
        user("30 minus"),
        user("18 is not 57."),
        bot(
            "You're right to question it. The 57,000 figure is not the result.",
            [call("show_month", {}, "in 30,000, out 18,000, in minus out 12,000")],
        ),
    )
    assert "numbers_traceable" not in rules(both(t))


def test_a_figure_nobody_said_at_any_scale_is_still_caught():
    t = transcript(
        user("30 minus"),
        user("18 is not 57."),
        bot("Your closing balance is 84,000 rupees.", [call("show_month", {}, "closing 72,000")]),
    )
    assert "numbers_traceable" in rules(both(t))


def test_the_three_checks_are_money_state_and_speech():
    """The fold the owner asked for: one score for the figures, one for what was written down and
    planned, one for what a voice can say. Twenty scores per call was twenty ways to rot quietly
    and no way to read a trace."""
    assert checks.FOLDED == {
        "money_traceable": ("numbers_traceable", "claimed_values_recorded", "no_spoken_decimals"),
        "state_matches_call": ("state_matches_facts", "actions_match_plan", "no_premature_plan"),
        "speakable": ("banned_phrases", "no_iso_dates", "no_markdown", "no_silent_turn"),
    }
    for name, group in checks.FOLDED.items():
        for sub in group:
            assert callable(getattr(checks, f"_{sub}")), f"{name} names a rule that is gone"


def test_a_violation_still_names_the_rule_that_raised_it():
    """Granularity moved into the violation rather than out of the product: "spoken decimal" is
    still findable in a trace, and still attributable, with one score instead of three."""
    t = transcript(bot("Your lowest balance is 1,466.57 rupees."))
    violations = checks.money_traceable(t)
    assert {v.rule for v in violations} == {"money_traceable"}
    assert any(v.detail.startswith("no_spoken_decimals: ") for v in violations)


def test_the_fold_changes_nothing_it_detects():
    """The acceptance test for the fold, replayed over every saved run: the violations the three
    checks report are exactly the violations the sub-rules report, run for run, turn for turn.

    The recordings under `evals/runs` are committed for this reason -- they are the evidence
    behind `evals/REPORT.md`. Skipped rather than failed if they are ever not there, because an
    empty corpus proves nothing either way.
    """
    import json
    from pathlib import Path

    runs = sorted(Path("evals/runs").glob("*.json"))
    if not runs:
        pytest.skip("no saved runs to replay")
    subs = {name: getattr(checks, f"_{name}") for group in checks.FOLDED.values() for name in group}
    for path in runs:
        recording = json.loads(path.read_text())
        direct = sorted(
            (name, v.turn, v.detail) for name, rule in subs.items() for v in rule(recording)
        )
        folded = sorted(
            (v.detail.partition(": ")[0], v.turn, v.detail.partition(": ")[2])
            for check in checks.CHECKS
            for v in check(recording)
        )
        assert direct == folded, path.name


@pytest.mark.parametrize(
    "line",
    [
        "Confirm any charges or credit impact before you ask the lender.",
        "A missed secured instalment can bring penalties and credit consequences.",
        "Paying late can hurt your credit standing.",
    ],
)
def test_naming_what_a_missed_payment_does_to_their_credit_is_not_an_offer(line):
    """`comfortable_surplus-20260914-214555` and `-214624` failed `speakable` for warning that
    moving a secured EMI has credit consequences -- the job, not an offer. Same family as
    "credit record" and "credit history" above."""
    t = transcript(bot(line))
    assert not [v for v in checks.speakable(t) if "offers credit" in v.detail]
