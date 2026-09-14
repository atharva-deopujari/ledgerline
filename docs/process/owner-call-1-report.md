# The owner's call, re-run on the redesigned agent

## 1. What was run

The owner's live call of 13 September (`voice-9869101897-20260913T194053Z`) was turned into a scripted
persona, `evals/scenarios/owner_call_1.yaml`, line for line from the recording: the hedging, the fragments
cut mid-sentence, the flat "I did not understand", and the challenge to the coach's own arithmetic. That
persona was run five times against the old build (before) and five times against the redesigned agent layer
(after: prompt v2, plain-word tools, results that state facts instead of issuing orders, the new turn
block). This report puts one after run and one before run side by side, gives the check table, and answers
the four questions the scenario carries. Two caveats belong up front. Five runs cannot separate 80 percent
from 100 percent, so the after column shows that nothing regressed on money or state, not that a rule now
holds always. And two of the five after runs never produced a plan at all: they spent the call establishing
loans and cards and ran out the scenario's 26-turn budget while still gathering.

## 2. The two calls, side by side

### AFTER, `evals/runs/owner_call_1-20260914-022330.json` (plan final, call ended, 48 turns)

- Coach: "What would you like help with today?"
- Person: "Hello. What's up?"
- Coach: "I'm well, thank you. I'm here to help you get through the next thirty days. What would you like to look at first?"
- Person: "That's too straightforward. By the way, I have around 60,000 right now."
- Coach: "Got it, I've noted around 60,000 rupees in your account today. What money do you expect to come in between 11 September and 10 October?" [note around 60,000 right now, balance, today]
- Person: "I think I'll get my salary credited, which is, like, around 30,000."
- Coach: "I've noted your salary as around 30,000 rupees, but you said you think it will arrive, so I'm treating it as uncertain for now. Which day of the month is it usually credited?" [note my salary 30,000, might not arrive]
- Person: "No. I'm sure it will arrive on" / "end of this September."
- Coach: "I've noted your salary as 30,000 rupees, arriving at the end of September. What bills or payments must go out before 10 October?" [note my salary 30,000 end of September, confirmed]
- Person: "I think at the starting week of October, I'll have to pay my rent, which is, like, around" / "13,000."
- Coach: "I've noted rent as around 13,000 rupees in the first week of October. Do you know which day it is due?" [note rent 13,000 first week of October, must pay]
- Person: "No. There will be other expenses. Nothing is" / "right now."
- Coach: "I've noted that there are no other bills right now, and I've checked the month. You have 60,000 rupees now. Your salary is 30,000 rupees on 30 September. Rent is 13,000 rupees in the first week of October. The month closes with 77,000 rupees, and every recorded payment is covered. I still need to ask about loans or cards, and your everyday spending. Do you have either?" [nothing_more of bills] [show_month final=false] **not a plan: the result line reads "not mentioned yet: loans or cards, everyday spending" and the coach says so out loud, which is where the live call declared a plan instead**
- Person: "Yeah. Sure."
- Coach: "Do you have any loan payments or credit-card dues between 11 September and 10 October?"
- Person: "I did not understand."
- Coach: "I mean, do you need to pay any EMIs or credit-card bills during this period?" **the live call answered this same line with silence**
- Person: "Like, there are many other things as well. Like, there can like," / "other expenses such as shopping or, you know," / "anything else. I cannot remember right now. Eating out, going out with friends and everything like that."
- Coach: "I've noted shopping, eating out, going out with friends, and other everyday spending, but there's no amount yet. About how much do you expect to spend on these during the month?" [note that spending, amount none, spread through the month]
- Person: "Oh, that you can do, like, let's say, 15000"
- Coach: "I've noted 15,000 rupees for shopping, eating out, going out with friends, and similar spending. With what we have recorded, the month closes with 62,000 rupees, and all recorded spending is covered. Are there any EMIs or credit-card bills in this period, or none?" [note that spending 15,000] [show_month final=false]
- Person: "No. Actually, it's 5,000." / "Not 15."
- Coach: "I've changed that spending to 5,000 rupees. With the recorded items, the month closes with 72,000 rupees, and everything is covered. Are there any EMIs or credit-card bills, or none?" [note that spending 5,000, result echoes "15,000 before, now 5,000"] [show_month final=false]
- Person: "Yeah. Sure."
- Coach: "Do you have any EMI payments or credit-card bills due between 11 September and 10 October?"
- Person: "Walk me through."
- Coach: "Sure. An EMI is a fixed loan payment. A credit-card bill is the amount due on your card. Do you have either one to pay during this period?" **the scripted "walk me through" lands on an open question and is read as "explain the term", not "explain the month"**
- Person: "Think the calculation is wrong."
- Coach: "Let me check it from the recorded figures. The account starts at 60,000 rupees. Salary adds 30,000 rupees. Rent is 13,000 rupees, and everyday spending is 5,000 rupees. The tool shows a closing balance of 72,000 rupees. Which part looks wrong to you?" [show_month final=false] **the challenge is taken to the tool, not to the coach's own head**
- Person: "If my salary is 30,000, rent is 13,000, shopping, eating out, and going out is 5,000," / "then that means"
- Coach: "The month's income minus those expenses is 12,000 rupees. The 72,000 rupees closing balance also includes the 60,000 rupees already in your account today. So 60,000 rupees plus 12,000 rupees leaves 72,000 rupees. Does that make sense?" [show_month final=false; the result carries "in 30,000, out 18,000, in minus out 12,000" and "opening 60,000, closing 72,000"] **every figure spoken here is a figure the result returned**
- Person: "30 minus" / "18 is not 57."
- Coach: "You're right. 30,000 rupees minus 18,000 rupees is 12,000 rupees, not 57,000 rupees. The 72,000 rupees includes the 60,000 rupees already in your account, plus that 12,000 rupees remaining from the month's income." [show_month final=false] **the challenge is answered, and answered from the result; no figure here was computed by the coach**
- Person: "Yeah, sure."
- Coach: "Do you have any EMI payments or credit-card bills during this period, or none?"
- Person: "None."
- Coach: "There are no EMIs or credit-card bills. The plan is: 60,000 rupees already in your account, 30,000 rupees salary on 30 September, 13,000 rupees rent, and 5,000 rupees for everyday spending. The month closes with 72,000 rupees. The lowest point is 48,619 rupees on 29 September, and everything is covered. Does this plan make sense to you?" [nothing_more of loans or cards] [show_month final=false] **the low point is stated, whole rupees, but not explained; the derivation was in the result and went unused**
- Person: "Yeah, it does."
- Coach: "Take care." [show_month final=true] [done understood=true]
- Person: "Bye."

### BEFORE, `evals/runs/owner_call_1-20260914-013403.json` (plan final, call ended, 48 turns)

- Coach: "Hi, I'm Ledgerline. How much money is in your account today, in rupees?"
- Person: "Hello. What's up?"
- Coach: "I'm here to help plan your next thirty days; how much money is in your account today, in rupees?"
- Person: "That's too straightforward. By the way, I have around 60,000 right now."
- Coach: "You have around 60,000 rupees today. When will your next income arrive, and how much will it be?" [upsert_item balance 60,000; result ends "blocked: income"]
- Person: "I think I'll get my salary credited, which is, like, around 30,000."
- Coach: "Your estimated salary is 30,000 rupees. What day should it arrive?" [upsert_item income salary 30,000 estimated]
- Person: "No. I'm sure it will arrive on" / "end of this September."
- Coach: "Your confirmed salary of 30,000 rupees should arrive on the thirtieth of September. What else will go out during these thirty days?" [upsert_item salary day 30; result: "ready to plan; ask once, then finalize_plan"] **the premature-plan pressure, present from the third recorded figure onwards; in the live call this is the turn that produced a plan**
- Person: "I think at the starting week of October, I'll have to pay my rent, which is, like, around" / "13,000."
- Coach: "Your rent is around 13,000 rupees, due on the seventh of October. Is there anything else that will go out during these thirty days?" [upsert_item essential rent 13,000 day 7; result again "ready to plan"]
- Person: "No. There will be other expenses. Nothing is" / "right now."
- Coach: "What amount should I allow for those other expenses, in rupees?" [upsert_item essential other expenses, amount none]
- Person: "Yeah. Sure."
- Coach: "What amount should I allow for those other expenses, in rupees?" **the same sentence twice, no tool call, the form asking its field again**
- Person: "I did not understand."
- Coach: "Sorry, I mean the total you expect to spend on those other expenses. How many rupees will that be?" [record_understanding confirmed=false, refused: "There is no plan to restate yet. Call finalize_plan first."] **refused tool call**
- Person: "Like, there are many other things as well. Like, there can like," / "other expenses such as shopping or, you know," / "anything else. I cannot remember right now. Eating out, going out with friends and everything like that."
- Coach: "What total amount should I set aside for shopping and social spending, in rupees?" [upsert_item optional, amount none]
- Person: "Oh, that you can do, like, let's say, 15000"
- Coach: "I'll allow 15,000 rupees for shopping and social spending. What total amount should I set aside for the other expenses, in rupees?" [upsert_item 15,000]
- Person: "No. Actually, it's 5,000." / "Not 15."
- Coach: "Is 5,000 rupees the correct amount for shopping and social spending?" [upsert_item 5,000; result: "confirm which is right before moving on"; lowest 56,833.27]
- Person: "Yeah. Sure."
- Coach: "You confirmed 5,000 rupees for shopping and social spending. What amount should I set aside for the other expenses, in rupees?" [confirm_carried names="shopping and social spending", refused: "is not carried from the last call; carried: nothing. Fix that argument and call the tool again."] **second refused tool call**
- Person: "Walk me through."
- Coach: "I can walk you through it, but I still need the amount for other expenses. What rupee amount should I use?" **the request to explain is declined in favour of the empty field**
- Person: "Think the calculation is wrong."
- Coach: "Which figure seems wrong: the 60,000 rupees in your account, the 30,000 rupees salary, the 13,000 rupees rent, or the 5,000 rupees spending?"
- Person: "If my salary is 30,000, rent is 13,000, shopping, eating out, and going out is 5,000," / "then that means"
- Coach: "That leaves 12,000 rupees from the salary after rent and those expenses, before considering your current balance. What amount should I use for the other expenses?" [upsert_item unchanged; result carries "in 30,000, out 18,000" and no difference figure] **12,000 is the coach's own subtraction; no result on this call returned it**
- Person: "30 minus" / "18 is not 57."
- Coach: "You're right: 30,000 minus 18,000 is 12,000 rupees; the 56,833 rupees figure included your current balance and timing. What amount should I use for the other expenses?" [upsert_item unchanged] **arithmetic again, and the answer is a half-sentence with the form's question stapled to it**
- Person: "Yeah, sure, but the numbers still don't add up. 12,000 is what's left from the salary, not 56,833."
- Coach: "You're right: 12,000 rupees is what remains from the salary after those costs; 56,833 rupees was the projected account balance, not salary left over. What amount should I use for other expenses?" [upsert_item unchanged] **the person has to push twice, which is what the persona was written to do**
- Person: "I don't have any other amount."
- Coach: "Your plan covers the 13,000-rupee rent and 5,000 rupees for shopping and social spending, with no other amount set aside; your lowest projected balance is 56,833.27 rupees on the twenty-ninth of September. There are no actions needed, does that and what happens if you spend more than 5,000 rupees make sense?" [mark_unknown] [finalize_plan] **the spoken decimal, and a plan finalised with loans, cards, utilities, groceries and transport never raised**
- Person: "Yes, that makes sense."
- Coach: "Thanks for your time. Goodbye." [record_understanding] [end_call]
- Person: "Goodbye"

The live recording carries the same defects harder: three turns where the coach said nothing at all
(after "I did not understand", after "Yeah. Sure.", and after "then that means"), two refused
`mark_unknown` calls in one turn, a plan declared with only balance, salary and rent on the books, and
the low point spoken as "fifty-seven thousand one hundred sixty-six point six one rupees".

## 3. The check table (evals/REPORT.md section 10.13)

Both columns are replayed under today's rules, so they are like-for-like. Five runs each.

| check | before | after |
|---|---|---|
| no_premature_plan | 0% | 100% |
| numbers_traceable | 60% | 100% |
| claimed_values_recorded | 80% | 100% |
| no_spoken_decimals | 80% | 100% |
| explains_on_request | 80% | 100% |
| state_matches_facts, actions_match_plan, banned_phrases, no_iso_dates, no_markdown, no_silent_turn | 100% | 100% |
| one_question_per_turn (advisory) | 100% | 80% |
| one_goodbye_with_the_end_call (advisory) | 100% | 80% |

The eleven gates are the ones registered in `ledgerline/judge/checks/checks.py`; the report's grouped row
reads "every other gate (7)" where the registry leaves six unnamed, and the six are listed above.

Two caveats the report records. `banned_phrases` was 80 percent before and is 100 percent in both columns
now because the rule changed: "credited" is an ordinary word for a salary and is no longer banned, while
offering credit still is. `numbers_traceable` was corrected so that a bare small number the person said, in
an utterance holding at least two of them, licenses its thousand-scaled form for the coach to say; replayed
over all 391 saved runs the licence changes exactly three, the three it was written for.

The abstention note on `no_premature_plan`: the check cannot fail a call that never planned. Three of the
five after runs planned and all three were covered; two never planned. So the 100 percent is three real
passes and two abstentions, against 0 of 5 before where every run planned on a month with a category
nobody had raised.

## 4. The four questions the scenario asks

Turn numbers are zero-based indices into the `turns` list of each recording.

**Did it ask about EMIs, cards, utilities, groceries and transport before planning?**
BEFORE: no. Loans, cards, utilities, groceries and transport are never raised in the whole call. The plan
is finalised at turn 44 on balance, salary, rent and one spending line.
AFTER: partly. Loans and cards are asked four times before the plan, at turns 17, 30, 32 and 42, answered
"None" at 43, and the plan follows at 44 and 46. Bills are asked as a category at turn 9 and everyday
spending at 15 and 23. Utilities, groceries and transport are never named individually; they are covered
only by the words "bills or payments" and "everyday spending". The coverage line the coach reads out at
turn 15 is why the plan waits.

**Did it explain why the low point is what it is, without arithmetic of its own?**
BEFORE: no. The low point is spoken once, at turn 44, as "56,833.27 rupees on the twenty-ninth of
September", with no reason attached. When the person disputes the figure at turns 39 and 41, the coach
answers with its own subtraction ("30,000 minus 18,000 is 12,000") and a vague "included your current
balance and timing".
AFTER: no, but for a smaller reason. The low point is spoken once, at turn 44, as "48,619 rupees on 29
September", in whole rupees and correct, but the derivation the result supplies ("opening 60,000, rent
-8,227 by 29 September, everyday spending -3,154 by 29 September = 48,619") is never spoken. What the
coach does explain, at turns 37 and 40, is the closing balance, and it explains it entirely from result
figures: in 30,000, out 18,000, in minus out 12,000, opening 60,000, closing 72,000.

**Did it ever go silent?**
BEFORE: no silent turn in this simulated run, though it repeats itself word for word at turn 17. The live
recording it reproduces did go silent three times, at turns 18, 29 and 36.
AFTER: no. Every one of the 24 coach turns has speech.

**Did it speak a decimal?**
BEFORE: yes, at turn 44, "56,833.27 rupees". The live recording spoke the same class of figure aloud as
"fifty-seven thousand one hundred sixty-six point six one rupees".
AFTER: no. Every figure in the call is whole rupees.

## 5. Reading

The after call leads where the before call interrogates: it names the window, asks what comes in, then what
must go out, and it says out loud what it has not asked about yet, which is what keeps it from planning at
turn 9 the way the old build did. The challenge is the clearest gain. Asked "30 minus 18 is not 57", the
after coach calls the month view, answers with the figures the result returned, and concedes the point
without inventing a number; the before coach does its own subtraction twice and still needs the person to
push a second time. Correction is handled in one turn rather than by asking "is 5,000 the correct amount",
and the two refused tool calls that made the before call visibly mechanical do not occur. Where it still
does not read like a coach: it states the low point and never explains it, although the derivation sat in
the result it had just read, so the single most coach-like sentence available was left on the table. It
asks about loans and cards four separate times across turns 17, 30, 32 and 42, twice after the person has
already moved on, which reads as persistence with a checklist rather than judgement about when enough is
enough. It never names utilities, groceries or transport, so the coverage it claims is category-level, not
a real sweep of a person's month. And when the person says "walk me through", it explains what an EMI is,
because it was mid-question, so the one explicit request to be walked through the month goes unanswered.
Does it feel like an expert rather than a form? Yes on the money turns and no on the closing turns: it
establishes the month, holds its numbers under pressure and never computes, but it still finishes by
reciting the plan rather than teaching it, and it does not know when to stop gathering. On the two runs
that never planned: the same instinct that stops premature planning has no brake on it, so a call can be
spent well and still end with nothing decided, which is a failure the person would feel even though no
gate catches it.

## 6. Open

- Two of five after runs (`-022308`, `-022310`) ended with `plan_final: false`. Both had every figure
  recorded correctly and both answered the arithmetic challenge; they simply ran out of turns while still
  asking about loans and cards. `owner_call_1` expects `plan_final: true`, so these are failures of the
  scenario expectation even though no gate fires.
- Three possible causes, named in REPORT 10.13 and not separated by five runs: the 26-turn budget is too
  short for a call that gathers properly; the scripted "walk me through" lands before the month is
  established and pulls the coach into explaining terms; or the coach does not know when enough is enough
  and needs something that says so.
- The advisory drops: one run asked two questions in a turn (`one_question_per_turn` 80 percent) and one
  ended without a goodbye in the same reply as `done` (`one_goodbye_with_the_end_call` 80 percent). Both
  are advisory by design and both are the shape the redesign expects to trade for a call that leads.
- The full matrix has not been re-run on v2. This is one scenario, the one the redesign was aimed at.
