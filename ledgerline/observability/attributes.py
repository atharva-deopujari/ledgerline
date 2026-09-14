"""Every span attribute we set, and the conversation attributes for one call.

The names are Langfuse's OTel contract, read from `langfuse._client.attributes` in 4.15.2 rather
than from the docs: the two trace-identity ones are **not** `langfuse.`-prefixed
(`user.id`, `session.id`), and trace metadata is flattened as `langfuse.trace.metadata.<key>`.
Getting one of these wrong is silent — the span still exports, the field is just never populated.
"""

from __future__ import annotations

from enum import StrEnum

from ledgerline.config import Settings

TRACE_NAME = "coach-call"


class Attr(StrEnum):
    """Attribute names. `str`, so they can be used as dict keys for the OTel API directly."""

    # Trace identity, set once on the conversation span.
    TRACE_NAME = "langfuse.trace.name"
    USER_ID = "user.id"
    SESSION_ID = "session.id"
    ENVIRONMENT = "langfuse.environment"
    TAGS = "langfuse.trace.tags"
    METADATA_SESSION_ID = "langfuse.trace.metadata.session_id"
    # Written after the call, so they cannot be tags (which are immutable at creation).
    METADATA_ENDED_BY = "langfuse.trace.metadata.ended_by"
    METADATA_PLAN_FINAL = "langfuse.trace.metadata.plan_final"

    # Trace-level runtime values. Set on any span in the trace; the last write wins.
    TRACE_INPUT = "langfuse.trace.input"
    TRACE_OUTPUT = "langfuse.trace.output"

    # Per observation.
    OBSERVATION_TYPE = "langfuse.observation.type"
    OBSERVATION_INPUT = "langfuse.observation.input"
    OBSERVATION_OUTPUT = "langfuse.observation.output"


def conversation_attributes(
    settings: Settings, *, session_id: str, user_id: str | None = None
) -> dict[str, str | list[str]]:
    """The dimensions of one call that are known before it starts.

    `session_id` groups a person's calls in Langfuse's session view, so it is the phone number
    once we have one and the call id until then — never the call id when a phone is known, or
    each call would be its own session.
    """
    attrs: dict[str, str | list[str]] = {
        Attr.TRACE_NAME: TRACE_NAME,
        Attr.SESSION_ID: user_id or session_id,
        Attr.ENVIRONMENT: settings.langfuse_environment,
        Attr.METADATA_SESSION_ID: session_id,
        Attr.TAGS: [
            f"prompt:{settings.prompt_version}",
            f"tts:{settings.tts_provider}",
            f"llm_api:{settings.llm_api}",
            "source:voice",
        ],
    }
    if user_id:
        attrs[Attr.USER_ID] = user_id
    return attrs
