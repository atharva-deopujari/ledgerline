"""The facts a person stated, carried from one call to the next.

Read path first, because it is the one on the call path and the one with a deadline: a person
hears a delay, and they do not hear a memory that failed to load -- the first tool result tells
them what was carried, and an empty list is a first-time caller.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from decimal import Decimal

from loguru import logger
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ledgerline.domain.models import (
    Debt,
    DebtKind,
    EssentialExpense,
    FinancialState,
    Income,
    ItemKind,
    OptionalExpense,
    UnknownReason,
)
from ledgerline.domain.policy import carries
from ledgerline.domain.state import group_inr
from ledgerline.store.models import ProfileFact, UserSummary

# One billing cycle plus slack. Older facts stay as history and never reach a call: a rent from
# four months ago is not a fact about this month, and asking is cheaper than being wrong.
PROFILE_MAX_AGE_DAYS = 60

_ACTIVE = """
    SELECT * FROM profile_facts
    WHERE phone = %s
      AND superseded_by IS NULL
      -- A tombstone is the newest row for a field the person ended, and it is history rather
      -- than a fact: it exists so nothing carries, not so something does.
      AND value IS NOT NULL
      AND greatest(recorded_at, last_confirmed_at) > now() - make_interval(days => %s)
    ORDER BY kind, name, field
"""


async def read_within(
    pool: AsyncConnectionPool, sql: str, args: tuple, *, timeout: float, what: str
) -> list[dict] | None:
    """A read with a deadline, or None. The call path's only way into the database.

    None and [] are different answers and every caller must keep them apart: [] is a person with
    nothing remembered, None is a person whose memory we could not read this time.
    """
    try:
        async with asyncio.timeout(timeout):
            async with pool.connection() as connection:
                cursor = await connection.cursor(row_factory=dict_row).execute(sql, args)
                return await cursor.fetchall()
    except Exception as failure:  # a timeout, a dead database, a bad row: all the same answer
        logger.warning("{} could not be read for this call, going on without it: {}", what, failure)
        return None


async def load_active(
    pool: AsyncConnectionPool,
    phone: str,
    *,
    timeout: float,
    max_age_days: int = PROFILE_MAX_AGE_DAYS,
) -> list[ProfileFact] | None:
    rows = await read_within(pool, _ACTIVE, (phone, max_age_days), timeout=timeout, what="profile")
    return None if rows is None else [ProfileFact.model_validate(row) for row in rows]


async def forget(pool: AsyncConnectionPool, phone: str) -> None:
    """Everything the person said, gone. The sessions stay with the phone nulled, so the call is
    still countable while nothing about it points at them."""
    async with pool.connection() as connection:
        async with connection.transaction():
            await connection.execute("DELETE FROM profile_notes WHERE phone = %s", (phone,))
            await connection.execute(
                "UPDATE profile_facts SET superseded_by = NULL WHERE phone = %s", (phone,)
            )
            await connection.execute("DELETE FROM profile_facts WHERE phone = %s", (phone,))
            await connection.execute("UPDATE sessions SET phone = NULL WHERE phone = %s", (phone,))
            await connection.execute(
                "UPDATE users SET forgotten_at = now() WHERE phone = %s", (phone,)
            )


# Which state list and which model each kind lives in. The models do the parsing on the way back:
# a Decimal string, an ISO date and a flag all come out of the database as text, and pydantic
# already knows what each field is.
_KINDS: dict[ItemKind, tuple[str, type[Income | Debt | EssentialExpense | OptionalExpense]]] = {
    ItemKind.INCOME: ("incomes", Income),
    ItemKind.DEBT: ("debts", Debt),
    ItemKind.ESSENTIAL: ("essentials", EssentialExpense),
    ItemKind.OPTIONAL: ("optionals", OptionalExpense),
}


# Not facts about an item: its identity, its free text, and whether it came from a previous call.
_NOT_A_FACT = frozenset({"name", "notes", "carried", "certainty"})


# Field ids spell a debt's money field `amount`, the way the cards, the unknowns and the model all
# say it. Only a debt's pydantic attribute differs, and only for that one field.
def _field_name(attribute: str) -> str:
    return "amount" if attribute == "amount_due" else attribute


def _attribute_name(kind: ItemKind, field: str) -> str:
    return "amount_due" if kind is ItemKind.DEBT and field == "amount" else field


def _as_text(value: object) -> str | None:
    """One value as the database holds it. Money is the Decimal's own string: nothing here goes
    near a float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _stated(
    state: FinancialState, remembered: set[tuple[str, str, str]]
) -> dict[tuple[str, str, str], tuple[str | None, str | None]]:
    """Every field of every item the person spoke about this call, keyed (kind, name, field).

    Carried items are left out on purpose: a call that ended before they were confirmed refreshes
    nothing, so those facts keep their old timestamps and age out on their own.

    `remembered` is the keys the profile already holds a value for. A field sitting at its model
    default is normally not a fact -- "the rent is not spread" is not something anybody said -- but
    if the profile remembers a value for it, the default IS what the person said this time: they
    corrected it back. Dropping those silently undid the correction between calls.
    """
    out: dict[tuple[str, str, str], tuple[str | None, str | None]] = {}
    for kind, (attribute, _) in _KINDS.items():
        for item in getattr(state, attribute):
            if item.carried:
                continue
            certainty = _as_text(getattr(item, "certainty", None))
            for name, value in item.model_dump().items():
                if name in _NOT_A_FACT or value is None:
                    continue
                key = (kind.value, item.name, _field_name(name))
                if value == type(item).model_fields[name].default and key not in remembered:
                    # A flag nobody mentioned sits at its model default. "The rent is not spread"
                    # is not something the person said, and storing it would put a fact in their
                    # profile that no turn of the call supports.
                    continue
                out[key] = (_as_text(value), certainty)
    return out


def _present_items(state: FinancialState) -> set[tuple[str, str]]:
    return {
        (kind.value, item.name)
        for kind, (attribute, _) in _KINDS.items()
        for item in getattr(state, attribute)
    }


def _not_applicable(state: FinancialState) -> set[tuple[str, str, str]]:
    """Fields the person said there are none of. A confirmed absence ends the fact."""
    ended: set[tuple[str, str, str]] = set()
    for unknown in state.unknowns:
        if unknown.reason is not UnknownReason.NOT_APPLICABLE:
            continue
        head, _, field = unknown.field.rpartition(".")
        kind, _, name = head.partition(":")
        if kind and name and field:
            ended.add((kind, name, field))
    return ended


async def record_call(
    pool: AsyncConnectionPool,
    phone: str,
    session_id: str,
    state: FinancialState,
    *,
    loaded: list[ProfileFact] | None,
) -> None:
    """Write what this call changed, in one transaction.

    Unchanged is no row: a restated figure is the same fact, and only its `last_confirmed_at`
    moves. Changed or new inserts a row and stamps the old one's `superseded_by`, so rent 11,000
    then 12,000 is two rows and the history reads. An item the person ended, or a field they said
    there is none of, gets a tombstone row with no value, so it never carries again.

    `loaded` is what `load_active` returned at the start of this call. **None means the memory was
    not read this call**, and then an item's absence from the state says nothing about whether the
    person still has it -- so nothing is tombstoned. Without that distinction, one slow database
    would quietly delete every fact the person did not happen to repeat.
    """
    remembered = {(f.kind, f.name, f.field) for f in loaded or ()}
    stated = _stated(state, remembered)
    present = _present_items(state)
    ended = _not_applicable(state)

    async with pool.connection() as connection:
        async with connection.transaction():
            cursor = connection.cursor(row_factory=dict_row)
            rows = await (
                await cursor.execute(
                    "SELECT * FROM profile_facts WHERE phone = %s AND superseded_by IS NULL",
                    (phone,),
                )
            ).fetchall()
            active = {
                (row["kind"], row["name"], row["field"]): ProfileFact.model_validate(row)
                for row in rows
            }

            for key, (value, certainty) in stated.items():
                current = active.get(key)
                if (
                    current is not None
                    and current.value == value
                    and current.certainty == certainty
                ):
                    await connection.execute(
                        "UPDATE profile_facts SET last_confirmed_at = now() WHERE id = %s",
                        (current.id,),
                    )
                    continue
                await _supersede(connection, current, key, value, certainty, phone, session_id)

            if loaded is None:
                return
            for key, current in active.items():
                kind, name, _ = key
                if (kind, name) not in present or key in ended:
                    if current.value is None:
                        continue  # already a tombstone
                    await _supersede(connection, current, key, None, None, phone, session_id)


async def _supersede(
    connection,
    current: ProfileFact | None,
    key: tuple[str, str, str],
    value: str | None,
    certainty: str | None,
    phone: str,
    session_id: str,
) -> None:
    """Insert the new row and point the old one at it. History is the product here, not a log."""
    kind, name, field = key
    inserted = await (
        await connection.execute(
            "INSERT INTO profile_facts (phone, kind, name, field, value, certainty, "
            "source_session_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (phone, kind, name, field, value, certainty, session_id),
        )
    ).fetchone()
    if current is not None:
        await connection.execute(
            "UPDATE profile_facts SET superseded_by = %s WHERE id = %s", (inserted[0], current.id)
        )


async def history(
    pool: AsyncConnectionPool, phone: str, *, kind: str, name: str, field: str
) -> list[ProfileFact]:
    """Every value this field has ever had, oldest first. The review screen reads this."""
    async with pool.connection() as connection:
        cursor = await connection.cursor(row_factory=dict_row).execute(
            "SELECT * FROM profile_facts WHERE phone = %s AND kind = %s AND name = %s "
            "AND field = %s ORDER BY id",
            (phone, kind, name, field),
        )
        rows = await cursor.fetchall()
    return [ProfileFact.model_validate(row) for row in rows]


def hydrate(today: dt.date, facts: list[ProfileFact]) -> FinancialState:
    """The facts a person stated last time, as this call's starting state.

    Every item is `carried`: counted in the maths, provisional until the person speaks, and
    blocking `finalize_plan` meanwhile. What may carry at all is the policy table's decision --
    the opening balance and a card's statement balance are always asked fresh.
    """
    state = FinancialState(today=today)
    by_item: dict[tuple[str, str], dict[str, str]] = {}
    for fact in facts:
        if fact.value is None:  # a tombstone: the person ended this, so it never carries
            continue
        by_item.setdefault((fact.kind, fact.name), {})[fact.field] = fact.value
        if fact.certainty is not None:
            by_item[(fact.kind, fact.name)]["certainty"] = fact.certainty

    for (kind_value, name), fields in by_item.items():
        try:
            kind = ItemKind(kind_value)
        except ValueError:
            continue  # a kind this version does not know; history, not a fact for this call
        attribute, model = _KINDS[kind]
        debt_kind = DebtKind(fields["kind"]) if kind is ItemKind.DEBT and "kind" in fields else None
        payload = {
            _attribute_name(kind, field): value
            for field, value in fields.items()
            if field == "certainty" or carries(kind, field, debt_kind=debt_kind)
        }
        if not payload:
            continue
        getattr(state, attribute).append(
            model.model_validate({"name": name, "carried": True, **payload})
        )
    return state


async def history_all(pool: AsyncConnectionPool, phone: str) -> list[ProfileFact]:
    """Everything ever recorded for this person, oldest first, superseded rows and tombstones
    included.

    `history()` answers about one field somebody already knows to ask about, which means it can
    only be reached from a fact that is still active. An item the person has since ended is
    invisible that way, and that is exactly what someone opens the page to read.
    """
    async with pool.connection() as connection:
        cursor = await connection.cursor(row_factory=dict_row).execute(
            "SELECT * FROM profile_facts WHERE phone = %s ORDER BY recorded_at, id", (phone,)
        )
        rows = await cursor.fetchall()
    return [ProfileFact.model_validate(row) for row in rows]


# The two figures a person's month is recognised by, in the order a console should show them.
_HEADLINE_FIRST = ("rent", "salary")

_USERS = """
    SELECT phone, count(*) AS calls, max(started_at) AS last_call_at
    FROM sessions WHERE phone IS NOT NULL
    GROUP BY phone ORDER BY last_call_at DESC
"""

_ACTIVE_FOR = """
    SELECT phone, name, field, value, recorded_at FROM profile_facts
    WHERE phone = ANY(%s)
      AND superseded_by IS NULL
      AND value IS NOT NULL
      AND greatest(recorded_at, last_confirmed_at) > now() - make_interval(days => %s)
    ORDER BY recorded_at DESC, id DESC
"""


def _spoken_fact(field: str, value: str) -> str:
    """A stored fact as a person would read it: money grouped, a date as a day and month."""
    if field in {"amount", "min_due"}:
        try:
            return group_inr(Decimal(value))
        except (ArithmeticError, ValueError):
            return value
    if field.endswith("date"):
        try:
            return f"{dt.date.fromisoformat(value):%-d %b}"
        except ValueError:
            return value
    return value


def _headline(rows: list[dict]) -> list[tuple[str, str]]:
    """Two facts that say who this is: the rent and the salary when they are known, otherwise the
    two most recently recorded. One line per item, never two fields of the same one."""
    amounts = [row for row in rows if row["field"] == "amount"]
    named = {row["name"]: row for row in reversed(amounts)}  # newest wins on a repeated name
    chosen = [named.pop(name) for name in _HEADLINE_FIRST if name in named]
    chosen += [row for row in amounts if row["name"] in named][: 2 - len(chosen)]
    return [(row["name"], _spoken_fact(row["field"], row["value"])) for row in chosen[:2]]


async def list_users(
    pool: AsyncConnectionPool,
    *,
    timeout: float,
    max_age_days: int = PROFILE_MAX_AGE_DAYS,
) -> list[UserSummary]:
    """Everyone who has called, newest call first, with what the next call would carry.

    A forgotten person has no rows here: `forget` nulls the phone on their sessions, so the calls
    stay countable and nothing points at them. Bounded like every other read; a console that cannot
    answer shows nobody rather than holding the page open.
    """
    people = await read_within(pool, _USERS, (), timeout=timeout, what="the caller list")
    if not people:
        return []
    phones = [row["phone"] for row in people]
    facts = await read_within(
        pool, _ACTIVE_FOR, (phones, max_age_days), timeout=timeout, what="the callers' facts"
    )
    by_phone: dict[str, list[dict]] = {phone: [] for phone in phones}
    for row in facts or ():
        by_phone[row["phone"]].append(row)
    return [
        UserSummary(
            phone=row["phone"],
            calls=row["calls"],
            last_call_at=row["last_call_at"],
            facts=len(by_phone[row["phone"]]),
            headline=_headline(by_phone[row["phone"]]),
        )
        for row in people
    ]
