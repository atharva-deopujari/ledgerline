"""LLM tools. CONTRACT: build_tools() signature and the six tool names are fixed.

Session B implements. Session C consumes via build_tools(). Nothing here imports pipecat: the
handlers are direct functions, so Pipecat derives each schema from the signature and the
Google-style docstring, and only requires the first parameter to be named `params` (it is
pipecat's FunctionCallParams at runtime, annotated Any so `get_type_hints` can resolve the
signature without pipecat in scope). See the import-linter contract: agent must not import
pipecat at module level.

Split across modules, but one import surface: everything that was importable from
`ledgerline.agent.tools` before still is.
"""

from __future__ import annotations

from ledgerline.agent.tools.coercion import DEBT_KINDS, Invalid, _refused
from ledgerline.agent.tools.context import PushCards, RequestEnd, ToolContext
from ledgerline.agent.tools.describe import _parked_fields, describe
from ledgerline.agent.tools.handlers import FOCUS_BY_KIND, TOOL_NAMES, build_tools
from ledgerline.agent.tools.phrases import GOODBYE, MAX_UNPAID_SPOKEN

# The private helpers are re-exported deliberately: the tests reach for them by name, and this
# package's own tests are part of its contract.
__all__ = [
    "DEBT_KINDS",
    "FOCUS_BY_KIND",
    "GOODBYE",
    "MAX_UNPAID_SPOKEN",
    "Invalid",
    "PushCards",
    "RequestEnd",
    "TOOL_NAMES",
    "ToolContext",
    "_parked_fields",
    "_refused",
    "build_tools",
    "describe",
]
