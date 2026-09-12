"""Simulated user: a persona that holds the hidden facts the agent has to extract.

It answers one thing at a time, never volunteers the whole list, and follows the scripted
behaviours in the scenario (a correction, a conflicting figure) on the turns they name.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

END = "[END]"

PERSONA = """You are role-playing a person on a phone call with a money coach. Stay in character.

Who you are: {description}

These are your real finances. They are private; reveal them only when asked, one at a time.
{facts}

How you talk:
- One or two short sentences. Answer only what was just asked.
- Never list several facts at once, even if the coach asks for several.
- Plain spoken English, the way someone says numbers out loud.
- Never mention that you are role-playing, and never invent a number that is not above.
- If asked about something not listed above, say you do not have that one.
{ending}
Once you have said goodbye and the coach has said goodbye back, reply with exactly {end} and
nothing else."""

ENDING = """
When the coach has finished explaining the plan and asks whether it makes sense, say plainly that
it does. When they say goodbye, say a short goodbye back."""


class SimUser:
    def __init__(self, scenario: dict, *, client, model: str) -> None:
        persona = scenario.get("persona", {})
        self.scripted = {
            int(b["turn"]): b["say"] for b in persona.get("scripted_behaviours", []) or []
        }
        self.client = client
        self.model = model
        self.instructions = PERSONA.format(
            description=persona.get("description", "a salaried person in India"),
            facts=_facts_block(persona.get("hidden_facts", {})),
            ending=ENDING,
            end=END,
        )
        self.items: list[dict[str, Any]] = []

    async def reply(
        self, agent_text: str, turn: int, *, plan_final: bool, usage: dict
    ) -> str | list[str] | None:
        """What the person says next, or None when the call is over.

        A list is one turn broken into the fragments voice would deliver separately.
        """
        self.items.append({"role": "user", "content": agent_text or "(silence)"})
        if turn in self.scripted:
            said = self.scripted[turn]
            spoken = " ".join(said) if isinstance(said, list) else said
            self.items.append({"role": "assistant", "content": spoken})
            return said

        nudge = "\n\nThe coach has now explained the plan." if plan_final else ""
        response = await asyncio.to_thread(
            lambda: self.client.responses.create(
                model=self.model,
                instructions=self.instructions + nudge,
                input=self.items,
                reasoning={"effort": "none"},
                store=False,
            )
        )
        if getattr(response, "usage", None):
            usage["input_tokens"] += response.usage.input_tokens or 0
            usage["output_tokens"] += response.usage.output_tokens or 0

        said = (response.output_text or "").strip()
        self.items.append({"role": "assistant", "content": said})
        return None if END in said else said


def _facts_block(facts: dict) -> str:
    """The hidden facts as flat, speakable lines the persona can read off."""
    lines = []
    if facts.get("opening_balance") is not None:
        lines.append(f"- In the account right now: {facts['opening_balance']} rupees.")
    for income in facts.get("incomes", []) or []:
        lines.append(
            f"- Income {income['name']}: {income['amount']} rupees, arrives on day "
            f"{income.get('day', 'unknown')} of the month."
        )
    for debt in facts.get("debts", []) or []:
        extra = f", minimum due {debt['min_due']}" if debt.get("min_due") else ""
        lines.append(
            f"- Debt {debt['name']} ({debt.get('debt_kind', 'unsecured_emi')}): "
            f"{debt['amount']} rupees due on day {debt.get('day', 'unknown')}{extra}."
        )
    for essential in facts.get("essentials", []) or []:
        when = f"due on day {essential['day']}" if essential.get("day") else "spread over the month"
        lines.append(f"- Must pay {essential['name']}: {essential['amount']} rupees, {when}.")
    for optional in facts.get("optionals", []) or []:
        lines.append(f"- Could skip {optional['name']}: {optional['amount']} rupees.")
    for note in facts.get("notes", []) or []:
        lines.append(f"- {note}")
    return "\n".join(lines) or json.dumps(facts)
