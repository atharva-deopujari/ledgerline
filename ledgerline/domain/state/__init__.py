"""State operations: upsert, remove, unknowns, readiness.

Pure functions over FinancialState. They mutate the passed state in place and return an Outcome
describing what happened so tools.py can describe it to the model.

Code owns what must be correct: money, dates, what is missing, what blocks the plan. Judgement
about language -- correction or contradiction, plausible or mis-heard, what to ask next and how to
word it -- belongs to the model, so none of it lives here.
"""

from ledgerline.domain.state.items import Outcome, remove, upsert
from ledgerline.domain.state.names import (
    NO_INCOME,
    field_of,
    group_inr,
    label_for,
    normalise_name,
    possessive_of,
    quantise,
    resolve_day,
    spoken,
)
from ledgerline.domain.state.readiness import (
    StateSnapshot,
    blockers,
    readiness,
    snapshot,
)
from ledgerline.domain.state.unknowns import (
    answered,
    income_is_answered,
    mark_unknown,
    missing_fields,
)

__all__ = [
    "NO_INCOME",
    "Outcome",
    "StateSnapshot",
    "answered",
    "blockers",
    "field_of",
    "group_inr",
    "income_is_answered",
    "label_for",
    "mark_unknown",
    "missing_fields",
    "normalise_name",
    "possessive_of",
    "quantise",
    "readiness",
    "remove",
    "resolve_day",
    "snapshot",
    "spoken",
    "upsert",
]
