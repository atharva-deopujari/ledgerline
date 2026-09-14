"""The Langfuse client we use, and the twin that does nothing when there are no keys.

Two rules hold everywhere in this file. **Nothing raises**: every call here happens beside a
real call, and an observability outage must never become a product outage, so the real client
catches and logs. **Unconfigured is a real mode**, not an error path: `NullLangfuse` is what the
app gets without keys, and every test that does not care about tracing gets it too.
"""

from __future__ import annotations

from typing import Any, Protocol

from loguru import logger


class NoPrompt(LookupError):
    """No prompt could be fetched. The caller falls back to the file on disk."""


class LangfuseClient(Protocol):
    """What the rest of the app is allowed to ask of Langfuse."""

    def score(
        self,
        *,
        trace_id: str,
        name: str,
        value: float | str,
        data_type: str | None = None,
        comment: str | None = None,
    ) -> None:
        """Attach one score to a finished trace. Phase 5 calls this from `aftercall`."""

    def get_prompt(self, name: str, *, label: str = "production", fallback: str | None = None):
        """Fetch a managed prompt. **Raises** when it cannot; never answers with nothing.

        The caller's fallback is the prompt file in the repo, and it reaches it through the
        exception. A client that returned an empty string here would make that string the
        system instruction of a real call, silently.
        """

    def create_prompt(self, *, name: str, prompt: str, type: str = "text", labels=None) -> None:
        """Create or update the managed prompt at boot. Never raises."""

    def trace_url(self, trace_id: str) -> str | None:
        """A link a person can open, or None when the project id is not configured."""

    def shutdown(self) -> None:
        """Flush what is queued and stop the background threads."""


class NullLangfuse:
    """No keys, no Langfuse. Every method is a no-op and `trace_url` has nothing to link to."""

    def score(self, **kwargs: Any) -> None:
        pass

    def get_prompt(self, name: str, *, label: str = "production", fallback: str | None = None):
        raise NoPrompt(f"no Langfuse client: {name} must come from the file")

    def create_prompt(self, **kwargs: Any) -> None:
        pass

    def trace_url(self, trace_id: str) -> str | None:
        return None

    def shutdown(self) -> None:
        pass


class RealLangfuse:
    """The SDK, wrapped so its failures stay inside this class.

    The client is constructed by `tracing.setup`, which hands it our own `TracerProvider`; this
    class only ever uses it for scores, trace attributes and the lifecycle.
    """

    def __init__(self, client: Any, *, base_url: str, project_id: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._project_id = project_id

    def score(
        self,
        *,
        trace_id: str,
        name: str,
        value: float | str,
        data_type: str | None = None,
        comment: str | None = None,
    ) -> None:
        try:
            self._client.create_score(
                trace_id=trace_id,
                name=name,
                value=value,
                data_type=data_type,
                comment=comment,
            )
        except Exception as exc:
            logger.warning("langfuse score {} not recorded: {}", name, exc)

    def get_prompt(self, name: str, *, label: str = "production", fallback: str | None = None):
        """Deliberately not wrapped: the caller treats any exception as "use the file"."""
        return self._client.get_prompt(name, label=label, fallback=fallback)

    def create_prompt(
        self, *, name: str, prompt: str, type: str = "text", labels: list[str] | None = None
    ) -> None:
        try:
            self._client.create_prompt(
                name=name, prompt=prompt, type=type, labels=labels or ["production"]
            )
        except Exception as exc:
            logger.warning("langfuse prompt {} not created: {}", name, exc)

    def trace_url(self, trace_id: str) -> str | None:
        if not self._project_id:
            return None
        return f"{self._base_url}/project/{self._project_id}/traces/{trace_id}"

    def shutdown(self) -> None:
        try:
            self._client.shutdown()
        except Exception as exc:
            logger.warning("langfuse shutdown failed: {}", exc)
