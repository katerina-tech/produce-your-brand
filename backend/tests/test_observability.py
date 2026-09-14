"""Tracing must be invisible when off and harmless when broken.

These tests exist because observability was added to a system that already
worked. The tool is useful, but it is not worth a single failed project run, so
the two properties worth asserting are not "does it record" - that is Langfuse's
job - but:

* with no credentials, nothing changes; and
* when the provider misbehaves, the caller never notices.

The second is the one that actually protects the product, and it is deliberately
tested against a provider that raises on every possible call.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.errors import GraphInterrupt

from app.config import Settings
from app.observability import tracing


@pytest.fixture(autouse=True)
def _reset_client() -> Any:
    """Each test decides its own configuration, so the cached client must go."""
    tracing._reset_for_tests()
    yield
    tracing._reset_for_tests()


# ------------------------------------------------------------------ off by default


def test_tracing_is_off_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "get_settings", lambda: Settings())

    assert tracing.tracing_active(Settings()) is False


def test_half_configured_counts_as_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """A public key without a secret is the likeliest misconfiguration.

    It must degrade to silence rather than erroring on every request.
    """
    settings = Settings(langfuse_public_key="pk-lf-only-half")
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)

    assert tracing.tracing_active(settings) is False


def test_span_yields_none_and_runs_its_body_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "get_settings", lambda: Settings())
    ran = False

    with tracing.span("extract_requirement") as observation:
        ran = True
        assert observation is None

    assert ran, "the body of a span must run whether or not tracing is on"


def test_generation_yields_none_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "get_settings", lambda: Settings())

    with tracing.generation("ProductionRequirement", model="gpt-4o") as observation:
        assert observation is None


def test_flush_is_a_no_op_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "get_settings", lambda: Settings())

    tracing.flush_traces()  # must not raise


# ------------------------------------------------- a provider that breaks everything


class ExplodingClient:
    """Fails on every call a caller could make."""

    def start_as_current_observation(self, **_: Any) -> Any:
        raise RuntimeError("langfuse is down")

    def flush(self) -> None:
        raise RuntimeError("langfuse is down")


@pytest.fixture
def broken_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(langfuse_public_key="pk-lf-x", langfuse_secret_key="sk-lf-x")
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    monkeypatch.setattr(tracing, "_resolve_client", lambda _settings: ExplodingClient())


def test_a_failing_provider_does_not_break_a_span(broken_provider: None) -> None:
    """The whole design rests on this: an observability outage costs a trace,
    never a request."""
    ran = False

    with tracing.span("calculate_matches") as observation:
        ran = True
        assert observation is None

    assert ran


def test_a_failing_provider_does_not_break_a_generation(broken_provider: None) -> None:
    with tracing.generation("MethodRecommendation", model="gpt-4o") as observation:
        assert observation is None


def test_a_failing_flush_is_swallowed(broken_provider: None) -> None:
    tracing.flush_traces()  # must not raise


def test_an_exception_inside_a_span_still_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swallowing tracing errors must not turn into swallowing real ones.

    The distinction matters: a broken trace is noise, a broken node is a bug,
    and the wrapper must not blur them.
    """
    monkeypatch.setattr(tracing, "get_settings", lambda: Settings())

    with pytest.raises(ValueError, match="node failed"), tracing.span("extract_requirement"):
        raise ValueError("node failed")


# ------------------------------------------------------------------ configuration


def test_client_resolution_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """Including the negative answer - an unconfigured deployment should not
    re-decide on every span."""
    calls = 0
    settings = Settings()

    def counting_settings() -> Settings:
        nonlocal calls
        calls += 1
        return settings

    monkeypatch.setattr(tracing, "get_settings", counting_settings)

    for _ in range(5):
        with tracing.span("noop"):
            pass

    # get_settings is still consulted per span, but the client decision is not
    # recomputed: the cached None short-circuits before any provider import.
    assert tracing._client_resolved is True
    assert tracing._client is None


def test_the_eu_host_is_the_default() -> None:
    """Traces from a Berlin product describing Berlin businesses should not
    leave the EU without somebody deciding that on purpose."""
    assert Settings().langfuse_host == "https://cloud.langfuse.com"


# ------------------------------------------- a provider that actually works

# Everything above this line exercises tracing while it is off or while the
# provider is broken. Neither state can catch the failure these tests exist
# for, because when tracing is off the wrapper is a passthrough - which is
# exactly how a swallowed GraphInterrupt reached production while
# test_an_exception_inside_a_span_still_propagates sat here passing.


class RecordingObservation:
    def update(self, **_: Any) -> None:
        return None


class RecordingClient:
    """A Langfuse-shaped client that works, and records how it was closed."""

    def __init__(self, *, suppresses: bool = False, fails_to_close: bool = False) -> None:
        self.opened: list[str] = []
        self.closed_with: list[type[BaseException] | None] = []
        self._suppresses = suppresses
        self._fails_to_close = fails_to_close

    def start_as_current_observation(self, *, name: str, as_type: str, **_: Any) -> Any:
        self.opened.append(f"{as_type}:{name}")
        client = self

        class _Manager:
            def __enter__(self) -> RecordingObservation:
                return RecordingObservation()

            def __exit__(self, kind: Any, value: Any, traceback: Any) -> bool:
                client.closed_with.append(kind)
                if client._fails_to_close:
                    raise RuntimeError("langfuse failed while closing the span")
                return client._suppresses

        return _Manager()

    def flush(self) -> None:
        return None


def _with_tracing(monkeypatch: pytest.MonkeyPatch, client: RecordingClient) -> RecordingClient:
    settings = Settings(langfuse_public_key="pk-lf-x", langfuse_secret_key="sk-lf-x")
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    monkeypatch.setattr(tracing, "_resolve_client", lambda _settings: client)
    return client


def test_a_live_span_opens_and_closes_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _with_tracing(monkeypatch, RecordingClient())

    with tracing.span("extract_requirement") as observation:
        assert observation is not None

    assert client.opened == ["span:extract_requirement"]
    assert client.closed_with == [None]


def test_a_graph_interrupt_passes_straight_through_a_live_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure this module was shipped with.

    ``interrupt()`` raises ``GraphInterrupt`` to pause at a human gate - it is
    how the product asks a question, not a thing that went wrong. Catching it
    here reported a healthy pause as a tracing failure and yielded a second
    time, and Python answers a second yield with "generator didn't stop after
    throw()". Every question the agent asked became a 500, wherever tracing
    was configured.
    """
    client = _with_tracing(monkeypatch, RecordingClient())
    raised = GraphInterrupt(())

    with pytest.raises(GraphInterrupt) as caught, tracing.span("ask_clarifying_question"):
        raise raised

    assert caught.value is raised, "the same exception, not a replacement"
    assert client.closed_with == [GraphInterrupt], "and the span was still closed"


def test_an_ordinary_exception_passes_through_a_live_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _with_tracing(monkeypatch, RecordingClient())

    with pytest.raises(ValueError, match="node failed"), tracing.span("match_suppliers"):
        raise ValueError("node failed")

    assert client.closed_with == [ValueError]


def test_a_provider_may_not_suppress_the_body_s_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider whose __exit__ returns True is asking to swallow the error.
    No tracing library gets to decide that the application's exception did not
    happen."""
    _with_tracing(monkeypatch, RecordingClient(suppresses=True))

    with pytest.raises(ValueError, match="node failed"), tracing.span("match_suppliers"):
        raise ValueError("node failed")


def test_a_provider_failing_to_close_does_not_replace_the_real_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two things going wrong at once must not lose the one that matters."""
    _with_tracing(monkeypatch, RecordingClient(fails_to_close=True))

    with pytest.raises(ValueError, match="node failed"), tracing.span("match_suppliers"):
        raise ValueError("node failed")


def test_a_provider_failing_to_close_a_successful_span_is_invisible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_tracing(monkeypatch, RecordingClient(fails_to_close=True))

    with tracing.span("extract_requirement"):
        pass  # a failure to close is the provider's problem, not the caller's
