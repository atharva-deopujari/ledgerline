"""Which figures the assistant is allowed to say, and when one stops being allowed.

A number is sayable if it came back from a tool or from the person. The harder half is retirement:
once rent is overwritten from 11,000 to 12,000, the losing figure has to stop being sayable —
otherwise the spoken call can contradict the card beside it and still pass.
"""

from __future__ import annotations

from evals.spoken_numbers import numbers_in

# The one import of application code in the evals: item identity has to match the domain's, or a
# correction spelled "the rent" against an original "rent" looks like a different item and the
# stale amount is never retired. evals is outside the import-linter contracts, which cover the
# ledgerline package only.
from ledgerline.domain.state import normalise_name, possessive_of

RECORDING_TOOLS = frozenset({"upsert_item", "remove_item", "mark_unknown"})

RECENT_USER_TURNS = 2


def _recent_user_numbers(turns: list[dict], index: int) -> set[int]:
    """What the person said in the current or previous utterance, as at `index`."""
    said = [t for t in turns[: index + 1] if t["role"] == "user"][-RECENT_USER_TURNS:]
    return {n for turn in said for n in numbers_in(turn["text"])}


def _item_key(kind, name) -> str:
    """Item identity as the domain sees it, so "the rent" and "rent" are one item here too."""
    return f"{kind}:{normalise_name(str(name))}".lower()


def _same_item(key: str, stored: str) -> bool:
    """The domain's possessive rule, mirrored: "rent" and "my rent" are one item, "my loan" and
    "his loan" are two people's debts. Reimplemented on the exported `possessive_of` rather than
    imported, because `state.items._same_item` is private to Session A's layer.
    """
    owner, bare = possessive_of(key)
    stored_owner, stored_bare = possessive_of(stored)
    if bare != stored_bare:
        return False
    return not owner or not stored_owner or owner == stored_owner


def _stored_key(recorded: dict[str, int], key: str) -> str:
    """Which recorded item this call is about: the domain's `_find` order, exact match first and
    the possessive fallback only on a miss. A name that could be either of two recorded items
    matches neither -- the domain creates a third item rather than guessing, so nothing is
    retired here either.
    """
    if key in recorded:
        return key
    kind, _, name = key.partition(":")
    matches = [
        k for k in recorded if k.partition(":")[0] == kind and _same_item(name, k.partition(":")[2])
    ]
    return matches[0] if len(matches) == 1 else key


def _supersede(recorded: dict[str, int], args: dict) -> set[int]:
    """Note this call's amount for its item, and return the figure it replaces, if any.

    After the cut `upsert_item` always overwrites, so there is one live figure per item and no
    state to keep for a disputed pair: the turn that records the new value may still name both,
    and from the next turn only the new one is sayable.
    """
    name, amount = args.get("name"), args.get("amount")
    if not name or amount is None:
        return set()
    key = _stored_key(recorded, _item_key(args.get("kind"), name))
    previous = recorded.get(key)
    recorded[key] = int(amount)
    if previous is None or previous == int(amount):
        return set()
    return {previous}


def _sources_up_to(turns: list[dict], index: int) -> set[int]:
    """Numbers the assistant is allowed to speak at `index`.

    Tool *results* are trusted: the engine computed them, and nobody says a closing balance out
    loud. Tool *arguments* are not, for the three tools that record what the person said. An
    invented amount would otherwise launder itself in two steps — in as an `upsert_item`
    argument, back out inside the result string, and from there authorised. So for a recording
    tool, any argument number the person did not say in the current or previous utterance is
    struck from that call's result as well as from its arguments. Totals the engine worked out
    stay trusted; the echo of an invented figure does not.
    """
    allowed: set[int] = set()
    recorded: dict[str, int] = {}
    for i, turn in enumerate(turns[: index + 1]):
        if turn["role"] == "user":
            allowed |= numbers_in(turn["text"])
        for tool_call in turn.get("tool_calls", ()):
            is_recording = tool_call.get("name") in RECORDING_TOOLS
            args = tool_call.get("args", {})
            # A replaced figure stops being sayable, from the turn *after* the one that
            # replaced it. That turn may still name both — "not eleven thousand then, twelve
            # thousand" is how a person hears that a correction landed, and asking which of two
            # figures is right means saying both.
            superseded = _supersede(recorded, args) if is_recording else set()
            from_result = numbers_in(str(tool_call.get("result", "")))
            from_args = numbers_in(str(args))
            if is_recording:
                unsaid = from_args - _recent_user_numbers(turns, i)
                from_args -= unsaid
                from_result -= unsaid
            allowed |= from_result | from_args
            # Retire AFTER the union, not before it: the change result names both figures
            # ("rent: 11,000 -> 12,000"), so subtracting first only to re-add the loser from the
            # same result left the stale amount sayable for the rest of the call -- which is the
            # whole defect this module exists to catch. A later turn may re-authorise it: if the
            # person says 11,000 again, that utterance puts it back.
            if i != index:
                allowed -= superseded
    return allowed
