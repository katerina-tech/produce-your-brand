"""Langfuse tracing, wrapped so the product never depends on it.

Why the provider is not used directly at the call sites: every call here can
fail for reasons that have nothing to do with the request being served - an
expired key, a network partition, a provider incident. Those must cost a trace,
never a project. So the two public helpers below are context managers that
always yield, whether or not anything is being recorded.

Why explicit spans rather than Langfuse's LangChain callback handler: that
handler requires the umbrella ``langchain`` package, which this project does not
install (it uses ``langchain_openai`` and ``langgraph`` directly). Adding a
dependency purely to be instrumented would be the wrong trade - and explicit
spans are better here anyway, because they carry this system's own node names
rather than LangChain's internal call structure.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any

from app.config import Settings, get_settings
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

_client: Any = None
_client_resolved = False


def _resolve_client(settings: Settings) -> Any:
    """Build the client once, or decide permanently that there is none.

    Resolution is cached including the negative answer: if credentials are
    absent there is no reason to retry on every span, and a hot path should not
    pay for a decision that cannot change while the process lives.
    """
    global _client, _client_resolved

    if _client_resolved:
        return _client

    _client_resolved = True

    if not settings.tracing_configured:
        return None

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=(
                settings.langfuse_secret_key.get_secret_value()
                if settings.langfuse_secret_key
                else None
            ),
            host=settings.langfuse_host,
            environment=settings.langfuse_environment,
        )
    except Exception as error:  # missing package, bad config, anything
        log_event(
            logger,
            Event.TOOL_ERROR,
            "tracing disabled: client could not be created",
            level=logging.WARNING,
            error_type=type(error).__name__,
        )
        _client = None

    return _client


def tracing_active(settings: Settings | None = None) -> bool:
    """Whether spans are actually being recorded. Safe to call anywhere."""
    return _resolve_client(settings or get_settings()) is not None


def _note_failure(name: str, error: BaseException) -> None:
    log_event(
        logger,
        Event.TOOL_ERROR,
        "tracing span failed",
        level=logging.WARNING,
        span_name=name,
        error_type=type(error).__name__,
    )


@contextmanager
def _observation(name: str, as_type: str, **fields: Any) -> Iterator[Any]:
    """One observation, or nothing at all - the caller cannot tell the difference.

    Yields the live span when tracing is on so a caller may attach an output or
    usage figures, and ``None`` when it is off.

    The distinction this makes is the whole correctness of the module: a
    failure *of the provider* is swallowed, and a failure *of the body* is not
    touched at all. Wrapping the ``yield`` in ``except Exception`` collapses
    those two, and collapsing them broke the product - ``interrupt()`` raises
    ``GraphInterrupt`` to pause at a human gate, which is control flow rather
    than an error. Catching it here reported a healthy pause as a tracing
    failure and then yielded a second time, which Python answers with
    ``RuntimeError: generator didn't stop after throw()``. Every question the
    agent asked became a 500, but only where tracing was configured - which is
    to say only in production.
    """
    client = _resolve_client(get_settings())
    if client is None:
        yield None
        return

    # Entered by hand rather than with ``with``, so that opening, closing and
    # the body each get the handling they need instead of one shared blanket.
    try:
        manager = client.start_as_current_observation(name=name, as_type=as_type, **fields)
        observation = manager.__enter__()
    except Exception as error:
        _note_failure(name, error)
        yield None
        return

    try:
        yield observation
    except BaseException as error:
        # Close the observation, then let the exception continue exactly as it
        # was. Its type, message and traceback all survive, and a provider that
        # returns True from __exit__ does not get to suppress it: no tracing
        # library may decide that the application's exception did not happen.
        with suppress(Exception):
            manager.__exit__(type(error), error, error.__traceback__)
        raise
    else:
        with suppress(Exception):
            manager.__exit__(None, None, None)


@contextmanager
def span(name: str, **fields: Any) -> Iterator[Any]:
    """A unit of work - a graph node, a retrieval, a tool call."""
    with _observation(name, "span", **fields) as obs:
        yield obs


@contextmanager
def generation(name: str, **fields: Any) -> Iterator[Any]:
    """A model call. Carries model name, token usage and cost when known."""
    with _observation(name, "generation", **fields) as obs:
        yield obs


def flush_traces() -> None:
    """Send anything buffered. Called on shutdown so short-lived processes
    (and the tests) do not lose the last few spans."""
    client = _resolve_client(get_settings())
    if client is None:
        return
    try:
        client.flush()
    except Exception as error:
        log_event(
            logger,
            Event.TOOL_ERROR,
            "tracing flush failed",
            level=logging.WARNING,
            error_type=type(error).__name__,
        )


def _reset_for_tests() -> None:
    """Forget the cached client. Only for tests that change configuration."""
    global _client, _client_resolved
    _client = None
    _client_resolved = False
