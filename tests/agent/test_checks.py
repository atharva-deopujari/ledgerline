"""Rule checks over a transcript. No network, no LLM."""

from __future__ import annotations

import pytest

from evals import checks
from ledgerline.agent.tools import phrases


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
    return {v.rule for v in violations}


# ------------------------------------------------------------------ numbers_traceable


def test_number_from_a_tool_result_is_allowed():
    t = transcript(
        user("my salary is 45000"),
        bot(
            "So 45,000 rupees a month. What is your rent?",
            [call(result="created salary. in 45,000, out 0.")],
        ),
    )
    assert rules(checks.run_checks(t)) == set()


def test_number_from_the_user_turn_is_allowed():
    t = transcript(user("my rent is 11000"), bot("Rent of 11,000 noted. Anything else?"))
    assert rules(checks.run_checks(t)) == set()


def test_invented_number_is_caught():
    t = transcript(
        user("my salary is 45000"),
        bot(
            "That leaves you 12,300 rupees spare. Sound right?",
            [call(result="created salary. in 45,000, out 0.")],
        ),
    )
    assert "numbers_traceable" in rules(checks.run_checks(t))


def test_spoken_number_words_are_traced_too():
    t = transcript(
        user("my salary is 45000"),
        bot(
            "Forty-five thousand rupees. And your rent?",
            [call(result="created salary. in 45,000, out 0.")],
        ),
    )
    assert "numbers_traceable" not in rules(checks.run_checks(t))


def test_invented_number_words_are_caught():
    t = transcript(user("my salary is 45000"), bot("You have twelve thousand three hundred spare."))
    assert "numbers_traceable" in rules(checks.run_checks(t))


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


def test_two_questions_in_one_turn_is_caught():
    t = transcript(user("hi"), bot("What is your rent? And do you have loans?"))
    assert "one_question_per_turn" in rules(checks.run_checks(t))


def test_one_question_is_fine():
    t = transcript(user("hi"), bot("What is your rent?"))
    assert "one_question_per_turn" not in rules(checks.run_checks(t))


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
    assert "banned_phrases" in rules(checks.run_checks(transcript(user("hi"), bot(text))))


def test_clean_text_has_no_banned_phrase():
    t = transcript(user("hi"), bot("Your card minimum is due on the twelfth."))
    assert "banned_phrases" not in rules(checks.run_checks(t))


# ------------------------------------------------------------------ no_markdown


@pytest.mark.parametrize("text", ["**rent**", "# Plan", "- rent\n- food", "use `this`", "a | b"])
def test_markdown_is_caught(text):
    assert "no_markdown" in rules(checks.run_checks(transcript(user("hi"), bot(text))))


def test_plain_prose_passes_the_markdown_check():
    t = transcript(user("hi"), bot("Rent is due on the fifth, and the card on the twelfth."))
    assert "no_markdown" not in rules(checks.run_checks(t))


# ------------------------------------------------------------------ amounts_repeated


def test_recorded_amount_must_be_repeated_back():
    t = transcript(
        user("my rent is 11000"),
        bot(
            "Noted. What else?",
            [call(args={"name": "rent", "amount": 11000}, result=recorded_result("rent 11,000"))],
        ),
        user("that is all"),
        bot("Right. Anything about loans?"),
    )
    assert "amounts_repeated" in rules(checks.run_checks(t))


def test_amount_repeated_in_the_same_turn_passes():
    t = transcript(
        user("my rent is 11000"),
        bot(
            "Rent of 11,000. What else?",
            [call(args={"name": "rent", "amount": 11000}, result=recorded_result("rent 11,000"))],
        ),
    )
    assert "amounts_repeated" not in rules(checks.run_checks(t))


def test_amount_repeated_two_turns_later_passes():
    t = transcript(
        user("my rent is 11000"),
        bot(
            "Got it.",
            [call(args={"name": "rent", "amount": 11000}, result=recorded_result("rent 11,000"))],
        ),
        user("and groceries 6000"),
        bot(
            "Eleven thousand for rent, and groceries six thousand.",
            [
                call(
                    args={"name": "groceries", "amount": 6000},
                    result=recorded_result("groceries 6,000", read_back=False),
                )
            ],
        ),
    )
    assert "amounts_repeated" not in rules(checks.run_checks(t))


# ------------------------------------------------------------------ reporting


def test_violation_carries_the_turn_and_a_detail():
    t = transcript(user("hi"), bot("You are approved."))
    v = checks.run_checks(t)[0]
    assert v.turn == 1 and v.rule == "banned_phrases"
    assert v.detail == "promises an outcome"


def test_passed_is_true_only_with_no_violations():
    assert checks.passed(transcript(user("hi"), bot("What is your rent?")))
    assert not checks.passed(transcript(user("hi"), bot("You are approved.")))


def test_an_iso_date_is_not_three_invented_numbers():
    t = transcript(user("hi"), bot("Your window ends 2026-10-10. Is that clear?"))
    assert "numbers_traceable" not in rules(checks.run_checks(t))
    assert checks.numbers_in("2026-10-10") == set()


def test_an_iso_date_spoken_aloud_is_flagged():
    t = transcript(user("hi"), bot("Your window ends 2026-10-10."))
    assert "no_iso_dates" in rules(checks.run_checks(t))


def test_a_spoken_date_is_not_flagged():
    t = transcript(user("hi"), bot("Your window ends on the tenth of October."))
    assert "no_iso_dates" not in rules(checks.run_checks(t))


def turn_with_order(order, calls=None):
    return {
        "role": "assistant",
        "text": "Okay, forty-two thousand.",
        "tool_calls": calls or [],
        "event_order": order,
    }


def test_calling_the_tool_before_speaking_passes():
    t = transcript(user("I earn 42000"), turn_with_order(["function_call", "message"], [call()]))
    assert "silent_before_acting" not in rules(checks.run_checks(t))


def test_speaking_before_the_tool_call_is_now_a_failure():
    """Reversed after the owner's third live call: speaking first and again after the result is
    what gave every tool turn two segments and two questions."""
    t = transcript(user("I earn 42000"), turn_with_order(["message", "function_call"], [call()]))
    violations = [v for v in checks.run_checks(t) if v.rule == "silent_before_acting"]
    assert violations and "message then function_call" in violations[0].detail


def test_a_turn_with_no_tool_call_is_free_to_speak():
    assert "silent_before_acting" not in rules(
        checks.run_checks(transcript(user("hi"), turn_with_order(["message"])))
    )


def test_every_tool_is_called_before_the_model_speaks():
    for name in ("finalize_plan", "upsert_item"):
        t = transcript(
            user("yes please"),
            turn_with_order(["function_call", "message"], [call(name=name)]),
        )
        assert "silent_before_acting" not in rules(checks.run_checks(t)), name


def test_the_goodbye_may_be_spoken_before_end_call():
    """The one exception, and the two rules were mutually unsatisfiable without it: `end_call`
    returns "call ended, say nothing more", so a model that stays silent until the result can
    never say goodbye in the turn that ends the call. Spoken first, then the line drops."""
    t = transcript(
        user("thank you"),
        turn_with_order(["message", "function_call"], [call(name="end_call")]),
    )
    assert "silent_before_acting" not in rules(checks.run_checks(t))


def test_a_recording_call_in_the_same_turn_as_end_call_is_still_not_licensed_to_speak():
    """Only a lone end_call is exempt. A turn that also records something is a normal tool turn
    and the ordering rule still applies to it."""
    t = transcript(
        user("thank you"),
        turn_with_order(
            ["message", "function_call", "function_call"],
            [call(name="upsert_item"), call(name="end_call")],
        ),
    )
    assert "silent_before_acting" in rules(checks.run_checks(t))


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
    assert rules(checks.run_checks(t)) == set()


def test_recommending_borrowing_fails():
    t = transcript(
        user("what do I do about the gap"),
        bot("You could borrow from a friend to cover the gap."),
    )
    violation = next(v for v in checks.run_checks(t) if v.rule == "banned_phrases")
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
    assert "banned_phrases" in rules(checks.run_checks(transcript(user("hi"), bot(text))))


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
    assert "banned_phrases" not in rules(checks.run_checks(transcript(user("hi"), bot(text))))


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
    assert "numbers_traceable" in rules(checks.run_checks(t))


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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


def test_a_figure_the_engine_computed_is_still_trusted():
    """finalize_plan returns numbers nobody said out loud; those are the engine's, not invented."""
    t = transcript(
        user("yes please"),
        bot(
            "You end the month with forty-six thousand rupees. Does that work?",
            [call(name="finalize_plan", args={}, result="plan final. surplus 46,000.")],
        ),
    )
    assert "numbers_traceable" not in rules(checks.run_checks(t))


@pytest.mark.parametrize(
    ("phrase", "value"),
    [("12k", 12000), ("1.5 lakh", 150000), ("2 lakhs", 200000), ("45K", 45000)],
)
def test_shorthand_amounts_are_read_as_numbers(phrase, value):
    assert value in checks.numbers_in(phrase)


def test_an_amount_acknowledged_before_the_tool_call_counts_as_repeated():
    """The prompt now asks the model to echo the figure first and call the tool second, so the
    read-back can sit in the same turn's text or in the turn before the call lands."""
    t = transcript(
        user("utilities are five thousand"),
        bot("Okay, five thousand for utilities. Anything else?"),
        user("that's all"),
        bot(
            "Right.",
            [
                call(
                    name="upsert_item",
                    args={"kind": "essential", "name": "utilities", "amount": 5000},
                    result="created utilities. in 30,000, out 25,000.",
                )
            ],
        ),
    )
    assert "amounts_repeated" not in rules(checks.run_checks(t))


def test_an_amount_never_said_at_all_is_still_caught():
    t = transcript(
        user("utilities are five thousand"),
        bot("Noted."),
        user("that's all"),
        bot(
            "Right. Anything else?",
            [
                call(
                    name="upsert_item",
                    args={"kind": "essential", "name": "utilities", "amount": 5000},
                    result="created utilities. in 30,000, out 25,000.",
                )
            ],
        ),
    )
    assert "amounts_repeated" in rules(checks.run_checks(t))


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
    assert "banned_phrases" in rules(checks.run_checks(transcript(user("hi"), bot(text))))


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
    assert "banned_phrases" not in rules(checks.run_checks(transcript(user("hi"), bot(text))))


def test_the_credit_record_a_missed_payment_shows_on_is_not_an_offer():
    """The engine's own warning is "nothing reaches your credit report"; over five runs the model
    paraphrased it as "affect your credit record", which is the same record the person already
    has. Saying what a missed payment does to it is the job, not an offer of new money."""
    for said in ("It can affect your credit record.", "That stays on your credit history."):
        t = transcript(user("ok"), bot(said))
        assert "banned_phrases" not in rules(checks.run_checks(t)), said


def test_a_hyphenated_credit_card_is_the_same_card():
    """A live run failed the banned-phrase gate for "the credit-card minimum due on the
    twentieth". Spoken aloud that is the card the person already has; the hyphen is spelling."""
    t = transcript(user("ok"), bot("Keep 1,200 rupees for the credit-card minimum."))
    assert "banned_phrases" not in rules(checks.run_checks(t))


def test_the_word_credit_alone_is_treated_as_an_offer():
    """ "a few days' credit" is new money. "credit bureau", "credit card", "credit report" and
    "credit score" are the only honest uses: a record you already have."""
    t = transcript(user("hi"), bot("The shop might give you credit until payday."))
    assert "banned_phrases" in rules(checks.run_checks(t))


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
    assert "numbers_traceable" in rules(checks.run_checks(t))


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
    violations = [v for v in checks.run_checks(t) if v.rule == "numbers_traceable"]
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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


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
    assert "numbers_traceable" in rules(checks.run_checks(t))


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
    assert "numbers_traceable" in rules(checks.run_checks(t))


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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


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
    assert "numbers_traceable" in rules(checks.run_checks(t))


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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


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
    assert "numbers_traceable" not in rules(checks.run_checks(t))


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
    assert "numbers_traceable" in rules(checks.run_checks(t))


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
    assert "numbers_traceable" in rules(checks.run_checks(t))


# ------------------------------------------------------------------ implausible amounts


def implausible(kind: str, name: str, amount: int) -> dict:
    return call(
        args={"kind": kind, "name": name, "amount": amount},
        result=recorded_result(f"{name} {amount}"),
    )


def test_recording_a_rent_of_twelve_rupees_without_asking_is_the_defect():
    """STT drops the thousand and "my rent is twelve thousand" arrives as "rent is 12". Recording
    it silently plans the person's month around a rent of twelve rupees."""
    t = transcript(
        user("my rent is 12"),
        bot("Twelve rupees for rent. What comes next?", [implausible("essential", "rent", 12)]),
    )
    assert "implausible_amount_confirmed" in rules(checks.run_checks(t))


def test_recording_it_and_asking_in_the_same_reply_passes():
    t = transcript(
        user("my rent is 12"),
        bot(
            "Twelve rupees for rent — did you mean twelve thousand?",
            [implausible("essential", "rent", 12)],
        ),
    )
    assert "implausible_amount_confirmed" not in rules(checks.run_checks(t))


def test_asking_instead_of_recording_passes():
    """Nothing was recorded, so there is nothing to confirm and no violation to raise."""
    t = transcript(
        user("my rent is 12"),
        bot("Twelve rupees sounds low for rent. Is that right?"),
    )
    assert "implausible_amount_confirmed" not in rules(checks.run_checks(t))


def test_a_question_that_does_not_settle_the_figure_is_not_a_confirmation():
    """A turn that merely ends in a question passes nothing: the question has to be about the
    figure, or every reply confirms by accident."""
    t = transcript(
        user("my rent is 12"),
        bot("Twelve rupees for rent. What is your salary?", [implausible("essential", "rent", 12)]),
    )
    assert "implausible_amount_confirmed" in rules(checks.run_checks(t))


def test_a_plausible_amount_needs_no_confirmation():
    t = transcript(
        user("my rent is 12000"),
        bot(
            "Twelve thousand rupees for rent. What comes next?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 12000},
                    result=recorded_result("rent 12,000"),
                )
            ],
        ),
    )
    assert "implausible_amount_confirmed" not in rules(checks.run_checks(t))


def test_a_small_optional_is_not_implausible():
    """A 400 rupee cable subscription is a real thing a person says. Only the kinds where a
    two-figure monthly amount is almost certainly a dropped thousand are floored."""
    t = transcript(
        user("cable tv is 40"),
        bot(
            "Forty rupees for cable. What comes next?",
            [
                call(
                    args={"kind": "optional", "name": "cable tv", "amount": 40},
                    result=recorded_result("cable tv 40"),
                )
            ],
        ),
    )
    assert "implausible_amount_confirmed" not in rules(checks.run_checks(t))


def test_a_small_balance_is_not_implausible():
    """Someone really can have 40 rupees in the account, and that is exactly the person this
    call is for. Flooring the balance would call their real situation a mishearing."""
    t = transcript(
        user("I have 40 rupees"),
        bot(
            "Forty rupees. What income do you expect?",
            [
                call(
                    args={"kind": "balance", "name": "balance", "amount": 40},
                    result=recorded_result("opening balance 40"),
                )
            ],
        ),
    )
    assert "implausible_amount_confirmed" not in rules(checks.run_checks(t))


def test_an_implausible_salary_is_caught_too():
    t = transcript(
        user("salary forty-five"),
        bot("Forty-five rupees. What is your rent?", [implausible("income", "salary", 45)]),
    )
    assert "implausible_amount_confirmed" in rules(checks.run_checks(t))


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
    assert "actions_match_plan" not in rules(checks.run_checks(t))


def test_an_action_the_plan_never_proposed_is_caught():
    """The live defect, `fragmented_balance-20260913-003557`: the engine returned a surplus and no
    actions, and the bot proposed keeping money back for rent and paying the card minimum. Both
    figures were traceable because both had been recorded earlier in the call, so every existing
    rule passed a run that invented an entire course of action."""
    t = planned(
        PLAN_WITH_NOTHING_TO_DO,
        bot("Pay at least 1,200 rupees toward the credit card by the twentieth. Make sense?"),
    )
    assert "actions_match_plan" in rules(checks.run_checks(t))


def test_naming_an_item_without_proposing_anything_is_not_an_action():
    """Walking through the month is the job. "Your rent is due on the eighteenth" proposes
    nothing, and a rule that reads it as a proposal would fail every explanation there is."""
    t = planned(
        PLAN_WITH_NOTHING_TO_DO,
        bot("Your rent of 11,000 rupees is due on the eighteenth. Does that match?"),
    )
    assert "actions_match_plan" not in rules(checks.run_checks(t))


def test_the_rule_says_nothing_about_turns_before_the_plan():
    """Mid-gathering the engine has actions it would suggest and the model is right to ignore
    them; this rule is only about the turns that explain a final plan."""
    t = transcript(
        user("my gym is 1500"),
        bot("Recorded. Shall we move the gym payment?", [call(args={"name": "gym"})]),
        state=state(optionals=[{"name": "gym", "amount": "1500.00"}]),
    )
    assert "actions_match_plan" not in rules(checks.run_checks(t))


def test_a_run_that_never_finalised_is_not_judged():
    t = transcript(user("hello"), bot("Hi."), state=state())
    assert "actions_match_plan" not in rules(checks.run_checks(t))


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
    assert "state_matches_facts" not in rules(checks.run_checks(run()))


def test_half_the_balance_is_the_defect_every_other_check_passes():
    """`fragmented_balance`: 20,000 in cash AND 20,000 in the bank, said as three fragments. In
    all fifteen post-cut runs the model made ONE balance call and stored 20,000, so the plan was
    built on half the person's money. Nothing was invented, the read-back matched the result and
    no value changed, so every existing rule is clean on those runs. This is the check that was
    missing."""
    violations = checks.run_checks(run(recorded=state(opening_balance="20000.00")))
    assert "state_matches_facts" in rules(violations)
    assert any("opening_balance" in v.detail for v in violations)


def test_an_amount_recorded_wrongly_is_caught():
    wrong = state(essentials=[{"name": "rent", "amount": "1100.00"}])
    assert "state_matches_facts" in rules(checks.run_checks(run(recorded=wrong)))


def test_a_fact_the_person_stated_and_the_bot_never_recorded_is_caught():
    t = run(None, state(essentials=[]), user("my rent is eleven thousand"), bot("Noted."))
    assert "state_matches_facts" in rules(checks.run_checks(t))


def test_a_fact_the_person_never_mentioned_is_not_the_bot_s_fault():
    """`hidden_facts` is the persona's whole truth and the scripted turns hold some of it back --
    "Nothing." in `one_word_answers` is the person declining to mention the phone EMI. Judging
    the notes rather than the conversation failed 84% of every saved run."""
    t = run(None, state(essentials=[]), user("that is all"), bot("Right."))
    assert "state_matches_facts" not in rules(checks.run_checks(t))


def test_a_fact_the_person_declined_to_give_is_not_a_mismatch():
    """ "I don't know" is an answer. The coach parked it and moved on, which is what it was told
    to do, so the gap is the person's and not the bot's."""
    parked = state(
        essentials=[], unknowns=[{"field": "essential:rent.amount", "reason": "unknown"}]
    )
    assert "state_matches_facts" not in rules(checks.run_checks(run(recorded=parked)))


def test_an_item_stored_under_a_possessive_is_the_same_item():
    """The domain merges "rent" and "my rent"; so must this, or a coach that recorded the fact
    correctly is reported as having lost it."""
    renamed = state(essentials=[{"name": "my rent", "amount": "11000.00"}])
    assert "state_matches_facts" not in rules(checks.run_checks(renamed and run(recorded=renamed)))


def test_a_debt_is_read_from_its_own_field():
    """Debts store the figure as `amount_due`, not `amount`. Reading the wrong field would report
    every correctly recorded debt as missing."""
    hidden = facts(debts=[{"name": "credit card", "amount": "3000", "debt_kind": "credit_card"}])
    recorded = state(debts=[{"name": "credit card", "amount_due": "3000.00"}])
    assert "state_matches_facts" not in rules(checks.run_checks(run(hidden, recorded)))


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
    violations = checks.run_checks(run(hidden, recorded))
    assert "state_matches_facts" in rules(violations)
    assert any("minimum" in v.detail for v in violations)


def test_a_card_minimum_recorded_correctly_is_clean():
    hidden = facts(
        debts=[
            {"name": "credit card", "amount": "3000", "debt_kind": "credit_card", "min_due": "1200"}
        ]
    )
    recorded = state(debts=[{"name": "credit card", "amount_due": "3000.00", "min_due": "1200.00"}])
    assert "state_matches_facts" not in rules(checks.run_checks(run(hidden, recorded)))


def test_a_minimum_the_person_never_gave_is_not_demanded():
    hidden = facts(debts=[{"name": "credit card", "amount": "3000", "debt_kind": "credit_card"}])
    recorded = state(debts=[{"name": "credit card", "amount_due": "3000.00"}])
    assert "state_matches_facts" not in rules(checks.run_checks(run(hidden, recorded)))


def test_a_transcript_with_no_hidden_facts_is_not_judged():
    """Checks run over live recordings too, and a real call has no persona to compare against."""
    t = transcript(user("hello"), bot("Hi."))
    assert "state_matches_facts" not in rules(checks.run_checks(t))


# ------------------------------------------------------------------ parking and farewells


def unknown_turn(field: str, text: str) -> dict:
    return {
        "role": "assistant",
        "text": text,
        "tool_calls": [call(name="mark_unknown", args={"field": field, "not_applicable": False})],
    }


def test_asking_again_for_the_field_just_parked_is_the_live_defect():
    """Turn 16 of the owner's third call: "Nothing." was recorded as two unknowns and the same
    turn asked "What's your monthly income?". The field has no item prefix, which the rule used
    to drop on the floor — it derived an empty subject and passed the turn."""
    t = transcript(
        user("Nothing."),
        unknown_turn("monthly_income", "Okay, no income to record. What's your monthly income?"),
    )
    assert "no_question_after_unknown" in rules(checks.run_checks(t))


def test_asking_for_a_different_field_of_the_same_item_is_allowed():
    """Parking the rent amount does not park the rent. "I don't know what it is" followed by
    "when is it due?" is one conversation, and three live runs failed the gate for having it."""
    t = transcript(
        user("I do not know."),
        unknown_turn("essential:rent.amount", "When is your rent due?"),
    )
    assert "no_question_after_unknown" not in rules(checks.run_checks(t))


def test_asking_for_the_parked_amount_in_other_words_is_still_asking_again():
    t = transcript(
        user("I do not know."),
        unknown_turn("essential:rent.amount", "Roughly how much is the rent each month?"),
    )
    assert "no_question_after_unknown" in rules(checks.run_checks(t))


def test_naming_the_parked_item_outside_the_question_is_not_asking():
    """ "I've noted the credit card is outside the window. Is there anything else?" names the item
    in the sentence that parks it and asks about something else. The rule reads the question, not
    the whole turn."""
    t = transcript(
        user("It's due next month."),
        unknown_turn(
            "debt:credit card.amount",
            "I've noted the credit card is outside this window. Anything else to include?",
        ),
    )
    assert "no_question_after_unknown" not in rules(checks.run_checks(t))


def ending(text: str) -> dict:
    return {"role": "assistant", "text": text, "tool_calls": [call(name="end_call")]}


def test_one_farewell_sentence_may_hold_two_farewell_words():
    """ "Goodbye, and take care." is one goodbye. Counting the words made it two and failed a run
    whose ending was exactly right."""
    t = transcript(user("Goodbye."), ending("Goodbye, and take care."))
    assert "one_goodbye_with_the_end_call" not in rules(checks.run_checks(t))


def test_the_doubled_goodbye_is_still_caught():
    """ "You're welcome. Goodbye.Goodbye." — the live call, with the tool result spoken after the
    model had already said its farewell."""
    t = transcript(user("Thank you."), ending("You're welcome. Goodbye.Goodbye."))
    assert "one_goodbye_with_the_end_call" in rules(checks.run_checks(t))


def test_a_goodbye_without_the_hang_up_is_caught():
    t = transcript(user("That makes sense."), bot("Thanks for speaking with me. Goodbye."))
    assert "one_goodbye_with_the_end_call" in rules(checks.run_checks(t))


def test_the_read_back_may_be_the_total_the_tool_recorded():
    """Two balance parts in one turn are one recorded figure. The handler adds them, so the
    second call's argument is 20,000 and what was recorded — and what the person needs to hear
    back — is 40,000. The result's first sentence says which."""
    t = transcript(
        user("20,000 in cash and"),
        user("20,000 in bank balance."),
        bot(
            "40,000 rupees is recorded across cash and bank. What income do you expect?",
            [
                call(
                    args={"kind": "balance", "name": "cash", "amount": 20000},
                    result="created opening balance 20,000. in 0, out 0.",
                ),
                call(
                    args={"kind": "balance", "name": "bank", "amount": 20000},
                    result="updated opening balance 40,000. in 0, out 0.",
                ),
            ],
        ),
    )
    assert "amounts_repeated" not in rules(checks.run_checks(t))


def test_an_amount_neither_said_nor_recorded_is_still_caught():
    """The totals after the first sentence are not a read-back: "in 38,000, out 400" is the shape
    of the month, and a model that reads one of those instead of the figure it just recorded has
    told the person nothing about what it heard."""
    t = transcript(
        user("Four hundred rupees."),
        bot(
            "Thirty-eight thousand rupees is due on the thirtieth. Anything else?",
            [
                call(
                    args={"kind": "optional", "name": "optional expenses", "amount": 400},
                    result="optional expenses: 300 -> 400\nin 38,000, out 400",
                )
            ],
        ),
    )
    assert "amounts_repeated" in rules(checks.run_checks(t))


def test_a_refused_mark_unknown_parks_nothing():
    """The model invents field names — "other spending details" — and the domain refuses them.
    Nothing was parked, so the next question about it is not asking again."""
    turn = {
        "role": "assistant",
        "text": "What is the amount for any other spending details?",
        "tool_calls": [
            call(
                name="mark_unknown",
                args={"field": "other spending details", "not_applicable": False},
                result="'' is not a valid ItemKind. Fix that argument and call the tool again.",
            )
        ],
    }
    t = transcript(user("I don't have any other spending details."), turn)
    assert "no_question_after_unknown" not in rules(checks.run_checks(t))


def test_an_unchanged_item_owes_no_read_back():
    """ "unchanged rent 9,000" is the domain saying it stored nothing: the call carried the same
    amount again while fixing the due date. Reading the figure back a second time is not what
    the rule is for — it is for hearing what was just recorded."""
    t = transcript(
        user("September."),
        bot(
            "September noted for the rent, but I still don't have a day. What else?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 9000},
                    result="unchanged rent\nin 0, out 6,000",
                )
            ],
        ),
    )
    assert "amounts_repeated" not in rules(checks.run_checks(t))


def test_a_change_the_result_does_not_report_owes_no_read_back():
    """Live shape, stt_implausible_amount turn 14: the call carried the amount again while
    recording the salary DATE, and the domain reported only the date — "recorded salary date
    1 Oct". The rule demanded the amount back anyway and failed four runs in five for a
    read-back the result never offered and the prompt forbids inventing. The read-back is owed
    for what the result says was recorded, not for every argument the call happened to carry."""
    t = transcript(
        user("The first of the month."),
        bot(
            "Your salary arrives on the first of October. When is your rent due?",
            [
                call(
                    args={"kind": "income", "name": "salary", "amount": 45000, "day_of_month": 1},
                    result="recorded salary date 1 Oct; say this back, then ask\n"
                    "in 45,000, out 12,000, lowest 1,000 on 30 Sep",
                )
            ],
        ),
    )
    assert "amounts_repeated" not in rules(checks.run_checks(t))


def test_a_recorded_item_still_owes_one():
    t = transcript(
        user("Rent is nine thousand."),
        bot(
            "What else do you pay?",
            [
                call(
                    args={"kind": "essential", "name": "rent", "amount": 9000},
                    result="recorded rent 9,000\nin 0, out 9,000",
                )
            ],
        ),
    )
    assert "amounts_repeated" in rules(checks.run_checks(t))


# ------------------------------------------------------------------ changed_value_acknowledged


def changed(field: str = "essential:rent.amount", line: str = "rent: 11,000 -> 12,000") -> dict:
    """An upsert whose result reports that a value the person had already given has moved."""
    return call(
        "upsert_item",
        {"kind": "essential", "name": "rent", "amount": 12000},
        f"{line}\nin 45,000, out 27,700",
    )


def test_naming_the_new_value_acknowledges_the_change():
    t = transcript(bot("Twelve thousand for rent, noted. When is it due?", [changed()]))
    assert not checks.changed_value_acknowledged(t)


def test_asking_which_figure_is_right_acknowledges_the_change():
    t = transcript(bot("You said rent was eleven thousand before. Which is right?", [changed()]))
    assert not checks.changed_value_acknowledged(t)


def test_saying_neither_is_the_failure():
    t = transcript(bot("Got it. What else comes out each month?", [changed()]))
    assert rules(checks.changed_value_acknowledged(t)) == {"changed_value_acknowledged"}


def test_a_question_about_something_else_does_not_acknowledge_a_change():
    """Every turn ends in a question, so "there was a question" cannot be the test. It has to be
    a question about the item whose figure moved."""
    t = transcript(bot("Noted. What day does your salary arrive?", [changed()]))
    assert rules(checks.changed_value_acknowledged(t)) == {"changed_value_acknowledged"}


def test_a_first_recording_owes_no_acknowledgement():
    """ "recorded rent 12,000" is a create: there is no old figure, so nothing to reconcile."""
    first = call(
        "upsert_item",
        {"kind": "essential", "name": "rent", "amount": 12000},
        "recorded rent 12,000\nin 45,000, out 27,700",
    )
    assert not checks.changed_value_acknowledged(transcript(bot("Right, what else?", [first])))


def test_a_date_change_is_acknowledged_by_naming_the_new_date():
    moved = call(
        "upsert_item",
        {"kind": "essential", "name": "rent", "day_of_month": 7},
        "rent due date: 5 Sep -> 7 Sep\nin 45,000, out 27,700",
    )
    t = transcript(bot("The seventh, then. Anything else due this month?", [moved]))
    assert not checks.changed_value_acknowledged(t)


def test_an_unacknowledged_date_change_is_caught():
    moved = call(
        "upsert_item",
        {"kind": "essential", "name": "rent", "day_of_month": 7},
        "rent due date: 5 Sep -> 7 Sep\nin 45,000, out 27,700",
    )
    t = transcript(bot("Fine. What about groceries?", [moved]))
    assert rules(checks.changed_value_acknowledged(t)) == {"changed_value_acknowledged"}


def test_the_check_is_one_of_the_gates():
    assert checks.changed_value_acknowledged in checks.CHECKS


def test_the_check_reads_the_line_the_tool_writes():
    """The check and the result string are one rule in two places. This is the real line
    `describe` produces for a changed amount, instruction and all."""
    from ledgerline.agent.tools.describe import _change_lines

    class Changed:
        changes = {"essential:rent.amount": ("11,000", "12,000")}

    line = _change_lines(Changed())[0]
    made = call(
        "upsert_item",
        {"kind": "essential", "name": "rent", "amount": 12000},
        f"{line}\nin 45,000, out 27,700",
    )
    assert rules(checks.changed_value_acknowledged(transcript(bot("Right, next?", [made])))) == {
        "changed_value_acknowledged"
    }
    assert not checks.changed_value_acknowledged(
        transcript(bot("Twelve thousand it is. What else?", [made]))
    )


def test_a_change_with_no_number_in_it_is_judged_on_the_words():
    """Not every value that moves is money. A lender name, a day, a word — the reply still has to
    name the new one, as the result spelled it, or ask which is right."""
    moved = call(
        "upsert_item",
        {"kind": "debt", "name": "bike loan", "lender": "canara"},
        "bike loan lender: hdfc -> canara\nin 45,000, out 27,700",
    )
    assert not checks.changed_value_acknowledged(
        transcript(bot("Canara, noted. When is it due?", [moved]))
    )
    assert not checks.changed_value_acknowledged(
        transcript(bot("You had hdfc on the bike loan before. Which is right?", [moved]))
    )
    assert rules(
        checks.changed_value_acknowledged(transcript(bot("Fine. What else?", [moved])))
    ) == {"changed_value_acknowledged"}
