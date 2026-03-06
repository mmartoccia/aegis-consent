"""
Aegis Schema

Pydantic v2 models for the consent-graph.json format.
Use validate_graph() to verify a graph dict against these models.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, model_validator


class ConsentDomain(BaseModel):
    """
    Rules for a single domain (e.g. "email", "calendar").

    Lists are matched by exact string. The resolution order is:
        blocked > autonomous > requires_approval > unlisted
    """
    autonomous: list[str] = Field(
        default_factory=list,
        description="Actions the agent may execute without notification.",
    )
    requires_approval: list[str] = Field(
        default_factory=list,
        description=(
            "Actions that require notification (high confidence) or explicit "
            "approval (low confidence) before execution."
        ),
    )
    blocked: list[str] = Field(
        default_factory=list,
        description="Actions the agent must never execute, regardless of confidence.",
    )
    trust_level: str = Field(
        default="medium",
        description="Informational trust label: low | medium | high | critical",
    )

    @model_validator(mode="after")
    def no_overlap(self) -> "ConsentDomain":
        """Warn if any action appears in multiple lists (last-wins in runtime, but is a config bug)."""
        auto_set = set(self.autonomous)
        approval_set = set(self.requires_approval)
        blocked_set = set(self.blocked)

        overlap_ab = auto_set & blocked_set
        overlap_aa = auto_set & approval_set
        overlap_ba = blocked_set & approval_set

        issues = []
        if overlap_ab:
            issues.append(f"Actions in both autonomous and blocked: {overlap_ab}")
        if overlap_aa:
            issues.append(f"Actions in both autonomous and requires_approval: {overlap_aa}")
        if overlap_ba:
            issues.append(f"Actions in both blocked and requires_approval: {overlap_ba}")

        if issues:
            raise ValueError("Overlapping action lists: " + "; ".join(issues))
        return self


class ConsentDecay(BaseModel):
    """Configuration for periodic consent graph review."""
    enabled: bool = False
    review_interval_days: int = Field(
        default=30,
        ge=1,
        description="Days between mandatory reviews of the consent graph.",
    )


class ConsentGraphMetadata(BaseModel):
    """Optional metadata block for documentation and tooling."""
    version: str = "0.1.0"
    description: Optional[str] = None
    owner: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConsentGraph(BaseModel):
    """
    Root model for consent-graph.json.

    Example minimal graph::

        {
          "domains": {
            "email": {
              "autonomous": ["read", "archive_promo"],
              "requires_approval": ["send"],
              "blocked": ["delete_all"],
              "trust_level": "high"
            }
          },
          "consent_decay": {"enabled": true, "review_interval_days": 30}
        }
    """
    domains: dict[str, ConsentDomain] = Field(
        default_factory=dict,
        description="Map of domain name → domain rules.",
    )
    consent_decay: ConsentDecay = Field(default_factory=ConsentDecay)
    last_reviewed: Optional[str] = Field(
        default=None,
        description="ISO date (YYYY-MM-DD) of last human review.",
    )
    metadata: Optional[ConsentGraphMetadata] = None


def validate_graph(graph: dict) -> ConsentGraph:
    """
    Validate a consent graph dict against the Aegis schema.

    Args:
        graph: Raw dict (e.g. from json.load()).

    Returns:
        Validated ConsentGraph instance.

    Raises:
        pydantic.ValidationError if the graph is malformed.
    """
    return ConsentGraph.model_validate(graph)
