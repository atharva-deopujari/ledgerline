"""Postgres persistence: who called, when, and what they told us last time.

Imports psycopg and the domain models, nothing else in the app. Every operation is bounded or
fire-and-forget: a database that is down degrades the product to what it was before it existed.
"""

from ledgerline.store.db import NullStore, open_store
from ledgerline.store.models import NewNote, ProfileFact, ProfileNote, SessionRow

__all__ = [
    "NewNote",
    "NullStore",
    "ProfileFact",
    "ProfileNote",
    "SessionRow",
    "open_store",
]
