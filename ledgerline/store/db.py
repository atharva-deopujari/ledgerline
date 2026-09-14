"""The pool, the schema at boot, and the twin that does nothing.

Nothing here may raise into a call. A database that is down, slow or absent degrades to the
product as it was before any of this existed: the person gets a call with an empty state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from loguru import logger
from psycopg_pool import AsyncConnectionPool

from ledgerline.domain.models import FinancialState
from ledgerline.store import notes, profile, sessions
from ledgerline.store.models import (
    NewNote,
    ProfileFact,
    ProfileNote,
    SessionRow,
    UserSummary,
)
from ledgerline.store.profile import PROFILE_MAX_AGE_DAYS

SCHEMA = Path(__file__).with_name("schema.sql")

# The call path waits this long for a profile and no longer. A person hears a delay; they do not
# hear a missing memory, because the first tool result tells them what was carried.
PROFILE_TIMEOUT_SECS = 0.2

# The console is a page someone opened, not a person waiting mid-sentence, so it may take longer
# than the call path -- but it is still bounded: a database that cannot answer shows an empty
# console rather than holding the page open.
CONSOLE_TIMEOUT_SECS = 2.0


@runtime_checkable
class Store(Protocol):
    """What the rest of the app may ask of persistence. `NullStore` is the other implementation."""

    async def apply_schema(self) -> None: ...

    async def create_session(self, session_id: str, phone: str, *, prompt_version: str) -> None: ...

    async def end_session(
        self,
        session_id: str,
        *,
        ended_by: str,
        langfuse_trace_id: str | None = None,
        recording_path: str | None = None,
    ) -> None: ...

    async def load_active(
        self, phone: str, *, timeout: float = PROFILE_TIMEOUT_SECS
    ) -> list[ProfileFact] | None: ...

    async def load_notes(
        self, phone: str, *, timeout: float = PROFILE_TIMEOUT_SECS
    ) -> list[ProfileNote] | None: ...

    async def record_call(
        self,
        phone: str,
        session_id: str,
        state: FinancialState,
        *,
        loaded: list[ProfileFact] | None,
    ) -> None: ...

    async def history(
        self, phone: str, *, kind: str, name: str, field: str
    ) -> list[ProfileFact]: ...

    async def history_all(self, phone: str) -> list[ProfileFact]: ...

    async def calls_for(self, phone: str) -> list[SessionRow]: ...

    async def list_users(self, *, timeout: float = CONSOLE_TIMEOUT_SECS) -> list[UserSummary]: ...

    async def record_notes(
        self, phone: str, session_id: str, new: list[NewNote], *, active: list[ProfileNote]
    ) -> None: ...

    async def forget(self, phone: str) -> None: ...

    async def close(self) -> None: ...


class NullStore:
    """No database configured. Every write is dropped and every read is "nothing remembered".

    Distinct from a timeout: `load_active` returns `[]` here, never `None`. Nothing is remembered
    because nothing was ever stored, which is a first-time caller, not a failure.
    """

    async def apply_schema(self) -> None:
        return None

    async def create_session(self, session_id: str, phone: str, *, prompt_version: str) -> None:
        return None

    async def end_session(
        self,
        session_id: str,
        *,
        ended_by: str,
        langfuse_trace_id: str | None = None,
        recording_path: str | None = None,
    ) -> None:
        return None

    async def load_active(
        self, phone: str, *, timeout: float = PROFILE_TIMEOUT_SECS
    ) -> list[ProfileFact] | None:
        return []

    async def load_notes(
        self, phone: str, *, timeout: float = PROFILE_TIMEOUT_SECS
    ) -> list[ProfileNote] | None:
        return []

    async def record_call(
        self,
        phone: str,
        session_id: str,
        state: FinancialState,
        *,
        loaded: list[ProfileFact] | None,
    ) -> None:
        return None

    async def history(self, phone: str, *, kind: str, name: str, field: str) -> list[ProfileFact]:
        return []

    async def history_all(self, phone: str) -> list[ProfileFact]:
        return []

    async def calls_for(self, phone: str) -> list[SessionRow]:
        return []

    async def list_users(self, *, timeout: float = CONSOLE_TIMEOUT_SECS) -> list[UserSummary]:
        return []

    async def record_notes(
        self, phone: str, session_id: str, new: list[NewNote], *, active: list[ProfileNote]
    ) -> None:
        return None

    async def forget(self, phone: str) -> None:
        return None

    async def close(self) -> None:
        return None


class PostgresStore:
    """The real one. Holds the pool; the SQL lives beside the thing it is about."""

    def __init__(
        self, pool: AsyncConnectionPool, *, profile_max_age_days: int = PROFILE_MAX_AGE_DAYS
    ) -> None:
        self.pool = pool
        self.profile_max_age_days = profile_max_age_days

    async def apply_schema(self) -> None:
        """Every boot, not only the first: CREATE TABLE IF NOT EXISTS makes it a no-op after."""
        async with self.pool.connection() as connection:
            await connection.execute(SCHEMA.read_text())

    async def create_session(self, session_id: str, phone: str, *, prompt_version: str) -> None:
        await sessions.create(self.pool, session_id, phone, prompt_version=prompt_version)

    async def end_session(
        self,
        session_id: str,
        *,
        ended_by: str,
        langfuse_trace_id: str | None = None,
        recording_path: str | None = None,
    ) -> None:
        await sessions.end(
            self.pool,
            session_id,
            ended_by=ended_by,
            langfuse_trace_id=langfuse_trace_id,
            recording_path=recording_path,
        )

    async def load_active(
        self, phone: str, *, timeout: float = PROFILE_TIMEOUT_SECS
    ) -> list[ProfileFact] | None:
        return await profile.load_active(
            self.pool, phone, timeout=timeout, max_age_days=self.profile_max_age_days
        )

    async def load_notes(
        self, phone: str, *, timeout: float = PROFILE_TIMEOUT_SECS
    ) -> list[ProfileNote] | None:
        return await notes.load_active(
            self.pool, phone, timeout=timeout, max_age_days=self.profile_max_age_days
        )

    async def record_call(
        self,
        phone: str,
        session_id: str,
        state: FinancialState,
        *,
        loaded: list[ProfileFact] | None,
    ) -> None:
        await profile.record_call(self.pool, phone, session_id, state, loaded=loaded)

    async def history(self, phone: str, *, kind: str, name: str, field: str) -> list[ProfileFact]:
        return await profile.history(self.pool, phone, kind=kind, name=name, field=field)

    async def history_all(self, phone: str) -> list[ProfileFact]:
        return await profile.history_all(self.pool, phone)

    async def calls_for(self, phone: str) -> list[SessionRow]:
        return await sessions.for_phone(self.pool, phone)

    async def list_users(self, *, timeout: float = CONSOLE_TIMEOUT_SECS) -> list[UserSummary]:
        return await profile.list_users(
            self.pool, timeout=timeout, max_age_days=self.profile_max_age_days
        )

    async def record_notes(
        self, phone: str, session_id: str, new: list[NewNote], *, active: list[ProfileNote]
    ) -> None:
        await notes.record(self.pool, phone, session_id, new, active=active)

    async def forget(self, phone: str) -> None:
        await profile.forget(self.pool, phone)

    async def close(self) -> None:
        await self.pool.close()


async def open_store(dsn: str, *, profile_max_age_days: int = PROFILE_MAX_AGE_DAYS) -> Store:
    """The one way to get a store. An empty DSN is not an error; it is the null twin."""
    if not dsn.strip():
        return NullStore()
    pool = AsyncConnectionPool(dsn, min_size=1, max_size=4, open=False)
    try:
        await pool.open(wait=True, timeout=5)
        store = PostgresStore(pool, profile_max_age_days=profile_max_age_days)
        await store.apply_schema()
    except Exception as failure:
        # Configured but unreachable. Raising here would take the whole product down with the
        # database; the promise is that an absent database leaves it as it was before any of this
        # existed -- calls still happen, nothing is remembered. Said once, at boot, not per call.
        logger.warning("no database this run, going on without memory: {}", failure)
        await pool.close()
        return NullStore()
    return store
