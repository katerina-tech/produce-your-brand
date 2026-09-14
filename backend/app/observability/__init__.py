"""Tracing: the run's shape, not just a list of things that happened.

The structured log in :mod:`app.logging_config` records *what* occurred. It
cannot record *inside what* it occurred. A project run fans out across fourteen
graph nodes and up to five model calls, and the failure this system most needs
to catch is the quiet one: a confident recommendation built on a retrieval that
returned the wrong passage. Nothing errors, the output simply is not supported.
A flat line per event cannot show that; a tree can.

Two rules govern everything here, and both exist because this is bolted onto a
system whose selling point is that it behaves predictably:

1. **Tracing is optional.** With no credentials configured the whole module
   degrades to a no-op context manager. Behaviour, output and latency are then
   identical to having no tracing at all.
2. **Tracing never breaks a request.** Every call into the provider is wrapped
   so that a failure - bad key, network outage, provider incident - is logged
   and swallowed. An observability tool that can take the product down with it
   is worse than no observability tool.
"""

from app.observability.tracing import (
    flush_traces,
    generation,
    span,
    tracing_active,
)

__all__ = ["flush_traces", "generation", "span", "tracing_active"]
