"""One TracerProvider for the process, and the Langfuse client that exports it.

Spike S3 (docs/process/spike-findings.md, 13 Sep) settled the shape:

- We build the provider and register it. Pipecat's `setup_tracing()` would build one of its own
  and call `set_tracer_provider`, and OpenTelemetry drops a second registration with a warning
  rather than an error, so whichever ran first would win silently. Pipecat needs no setup call:
  its spans come from `trace.get_tracer(...)`, which resolves to whatever is registered, and the
  only flag in `pipecat.utils.tracing.setup` reports whether the OTel packages import, not
  whether anyone configured them.
- The SDK owns the exporter. `Langfuse(tracer_provider=...)` adds its span processor to our
  provider, so there is exactly one export path; adding an OTLP exporter of our own beside it
  would send every span twice.
- Tracing stays enabled on the client. `create_score` returns early when it is not, which would
  lose every judge score in phase 5 without a word in the log.
"""

from __future__ import annotations

from loguru import logger
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from ledgerline.config import Settings
from ledgerline.observability.langfuse import LangfuseClient, NullLangfuse, RealLangfuse

try:  # pragma: no cover - exercised by the live path, not by the suite
    from langfuse import Langfuse, is_default_export_span
except ImportError:  # pragma: no cover
    Langfuse = None  # type: ignore[assignment]

    def is_default_export_span(span) -> bool:  # type: ignore[misc]
        return False


# Scopes whose spans are ours: Pipecat's conversation, turn and service spans, and the tool and
# call spans this package creates.
OUR_SCOPES = ("pipecat", "ledgerline")

SERVICE_NAME = "ledgerline"


def should_export_span(span) -> bool:
    """Which spans reach Langfuse. The SDK's default silently drops most of ours.

    `is_default_export_span` in 4.15.2 keeps a span only if it came from the Langfuse SDK's own
    tracer, carries a `gen_ai.*` attribute, or comes from a scope on its list of known LLM
    instrumentors. Pipecat's `conversation` and `turn` spans and our `tool` spans have none of
    those, so the first live call arrived as 32 loose generations with no tree at all and
    nothing in any log to say why. Widening the filter to our own scopes is the SDK's
    documented extension point for exactly this.
    """
    scope = span.instrumentation_scope.name if span.instrumentation_scope else ""
    return is_default_export_span(span) or scope.startswith(OUR_SCOPES)


_client: LangfuseClient | None = None


def setup(settings: Settings) -> LangfuseClient:
    """Register the provider and build the client. Idempotent; safe without keys.

    Returns `NullLangfuse` when the keys are absent, which is what makes "unconfigured means
    off" a single branch in one place instead of a check at every call site.
    """
    global _client
    if _client is not None:
        return _client

    if not settings.tracing_configured or Langfuse is None:
        _client = NullLangfuse()
        return _client

    provider = _provider(settings)
    sdk = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        environment=settings.langfuse_environment,
        tracer_provider=provider,
        should_export_span=should_export_span,
    )
    _client = RealLangfuse(
        sdk,
        base_url=settings.langfuse_base_url,
        project_id=settings.langfuse_project_id,
    )
    return _client


def _provider(settings: Settings) -> TracerProvider:
    """The provider Langfuse must attach its exporter to: the registered one, always.

    OpenTelemetry keeps the first provider a process registers and drops later ones with a
    warning, so building one unconditionally and handing it to the SDK would, on the second
    call or under any library that registered first, attach the exporter to a provider no span
    is ever created from — a trace that silently never arrives. Reading the global back is what
    makes that impossible.
    """
    registered = trace.get_tracer_provider()
    if isinstance(registered, TracerProvider):
        logger.info("tracing: reusing the TracerProvider already registered")
        return registered
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": SERVICE_NAME,
                "deployment.environment": settings.langfuse_environment,
            }
        )
    )
    trace.set_tracer_provider(provider)
    return provider


def reset() -> None:
    """Forget the client. For tests; the provider stays registered, as OTel intends."""
    global _client
    _client = None
