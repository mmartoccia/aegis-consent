"""
Aegis -- Consent Graph as Code for AI agents.

Deterministic, auditable action governance for autonomous agents.
Define what your agent can do autonomously, what requires a human,
and what is permanently off-limits -- in a single JSON file.

Quick start::

    from aegis import check_consent, AegisConfig

    config = AegisConfig(graph_path="./consent-graph.json")
    tier = check_consent("email", "send", confidence=0.9, config=config)

    if tier == "BLOCKED":
        raise PermissionError("Action blocked by consent graph")
    elif tier == "FORCED":
        # request human approval
        ...
    elif tier == "VISIBLE":
        # execute, then notify operator
        ...
    else:  # SILENT
        # execute without notification
        ...
"""

from aegis.consent import (
    AegisConfig,
    check_consent,
    check_decay,
    get_consent_summary,
    get_override_stats,
    load_graph,
    log_override,
    set_default_config,
)
from aegis.schema import ConsentDomain, ConsentGraph, ConsentGraphMetadata, validate_graph

__version__ = "0.1.0"
__all__ = [
    # Core
    "check_consent",
    "log_override",
    "AegisConfig",
    "set_default_config",
    # Graph helpers
    "load_graph",
    "get_consent_summary",
    "get_override_stats",
    "check_decay",
    # Schema
    "ConsentGraph",
    "ConsentDomain",
    "ConsentGraphMetadata",
    "validate_graph",
]
