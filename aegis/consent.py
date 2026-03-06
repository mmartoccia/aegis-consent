"""
Aegis Consent Engine

Core 4-tier consent resolution for AI agent action governance.

Tiers:
  SILENT:  Execute silently. Log only.
  VISIBLE: Execute and notify operator. "I did X because Y."
  FORCED:  Ask operator before executing. Wait for approval.
  BLOCKED: Never execute. Log attempt and alert.

Usage:
    from aegis import check_consent, log_override, AegisConfig

    config = AegisConfig(graph_path="./consent-graph.json")
    tier = check_consent("email", "send", confidence=0.9, config=config)
"""

import os
import json
import datetime
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AegisConfig:
    """
    Configuration for the Aegis consent engine.

    Attributes:
        graph_path: Path to the consent-graph.json file.
        log_dir: Directory where attempt and override logs are written.
        confidence_threshold: Minimum confidence to resolve requires_approval as VISIBLE
                              (vs FORCED). Default: 0.85.
    """
    graph_path: str = field(
        default_factory=lambda: os.path.expanduser("~/.aegis/consent-graph.json")
    )
    log_dir: str = field(
        default_factory=lambda: os.path.expanduser("~/.aegis/logs/")
    )
    confidence_threshold: float = 0.85

    def attempt_log_path(self) -> str:
        return os.path.join(self.log_dir, "consent-attempts.jsonl")

    def override_log_path(self) -> str:
        return os.path.join(self.log_dir, "consent-overrides.jsonl")


# Module-level default config (override per call or set globally)
_default_config: Optional[AegisConfig] = None


def set_default_config(config: AegisConfig) -> None:
    """Set the module-level default config. Useful for one-time setup."""
    global _default_config
    _default_config = config


def _get_config(config: Optional[AegisConfig]) -> AegisConfig:
    if config is not None:
        return config
    if _default_config is not None:
        return _default_config
    return AegisConfig()


def load_graph(config: Optional[AegisConfig] = None) -> dict:
    """Load the consent graph from disk. Returns empty defaults if missing."""
    cfg = _get_config(config)
    path = os.path.expanduser(cfg.graph_path)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"domains": {}, "consent_decay": {"enabled": False}}


def check_consent(
    domain: str,
    action: str,
    confidence: float = 0.5,
    config: Optional[AegisConfig] = None,
) -> str:
    """
    Check consent for an agent action.

    Args:
        domain:     Logical domain, e.g. "email", "calendar", "filesystem".
        action:     Action name, e.g. "send", "delete", "read".
        confidence: Float 0-1. How confident the agent is about operator intent.
                    Values >= AegisConfig.confidence_threshold resolve requires_approval
                    as VISIBLE; below that as FORCED.
        config:     Optional AegisConfig. Falls back to module default or built-in default.

    Returns:
        One of: "SILENT" | "VISIBLE" | "FORCED" | "BLOCKED"

    Resolution order:
        1. blocked list     → BLOCKED  (absolute prohibition)
        2. autonomous list  → SILENT   (no notification needed)
        3. requires_approval list:
             confidence >= threshold → VISIBLE
             confidence <  threshold → FORCED
        4. unlisted action  → same confidence logic as requires_approval
        5. unknown domain   → FORCED
    """
    cfg = _get_config(config)
    graph = load_graph(cfg)
    domain_rules = graph.get("domains", {}).get(domain)

    if not domain_rules:
        _log_attempt(domain, action, confidence, "FORCED", "unknown_domain", cfg)
        return "FORCED"

    # 1. Blocked -- absolute veto
    if action in domain_rules.get("blocked", []):
        _log_attempt(domain, action, confidence, "BLOCKED", "in_blocked_list", cfg)
        return "BLOCKED"

    # 2. Autonomous -- no human needed
    if action in domain_rules.get("autonomous", []):
        _log_attempt(domain, action, confidence, "SILENT", "in_autonomous_list", cfg)
        return "SILENT"

    # 3. Requires approval -- confidence decides notify-after vs ask-before
    if action in domain_rules.get("requires_approval", []):
        if confidence >= cfg.confidence_threshold:
            _log_attempt(domain, action, confidence, "VISIBLE", "high_confidence_approval", cfg)
            return "VISIBLE"
        else:
            _log_attempt(domain, action, confidence, "FORCED", "low_confidence_approval", cfg)
            return "FORCED"

    # 4. Unlisted action in known domain -- treat as requires_approval
    if confidence >= cfg.confidence_threshold:
        _log_attempt(domain, action, confidence, "VISIBLE", "unlisted_action_high_conf", cfg)
        return "VISIBLE"

    _log_attempt(domain, action, confidence, "FORCED", "unlisted_action_low_conf", cfg)
    return "FORCED"


def log_override(
    domain: str,
    action: str,
    reason: str,
    operator_decision: str,
    config: Optional[AegisConfig] = None,
) -> None:
    """
    Log a human override of a consent decision.

    Args:
        domain:            The action domain.
        action:            The action that was overridden.
        reason:            Why the override happened.
        operator_decision: "approved" | "denied" | "modified"
        config:            Optional AegisConfig.
    """
    cfg = _get_config(config)
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "domain": domain,
        "action": action,
        "reason": reason,
        "operator_decision": operator_decision,
    }
    log_path = cfg.override_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _log_attempt(
    domain: str,
    action: str,
    confidence: float,
    tier: str,
    reason: str,
    config: AegisConfig,
) -> None:
    """Internal: append every consent check to the audit log."""
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "domain": domain,
        "action": action,
        "confidence": confidence,
        "tier": tier,
        "reason": reason,
    }
    log_path = config.attempt_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_consent_summary(config: Optional[AegisConfig] = None) -> str:
    """Return a human-readable summary of the loaded consent graph."""
    graph = load_graph(_get_config(config))
    lines = ["# Consent Graph Summary", ""]

    domains = graph.get("domains", {})
    if not domains:
        lines.append("No domains configured.")
        return "\n".join(lines)

    for domain, rules in domains.items():
        trust = rules.get("trust_level", "unknown")
        auto = rules.get("autonomous", [])
        approval = rules.get("requires_approval", [])
        blocked = rules.get("blocked", [])

        lines.append(f"## {domain.upper()} (trust: {trust})")
        lines.append(f"  ✅ Autonomous:  {', '.join(auto) if auto else 'none'}")
        lines.append(f"  ⚠️  Approval:    {', '.join(approval) if approval else 'none'}")
        lines.append(f"  🚫 Blocked:     {', '.join(blocked) if blocked else 'none'}")
        lines.append("")

    decay = graph.get("consent_decay", {})
    if decay.get("enabled"):
        last = graph.get("last_reviewed", "never")
        interval = decay.get("review_interval_days", 30)
        lines.append(f"Consent Decay: enabled ({interval}-day review cycle)")
        lines.append(f"Last Reviewed: {last}")

    return "\n".join(lines)


def get_override_stats(config: Optional[AegisConfig] = None) -> str:
    """Analyze override patterns to suggest consent graph updates."""
    cfg = _get_config(config)
    log_path = cfg.override_log_path()

    if not os.path.exists(log_path):
        return "No overrides logged yet."

    overrides = []
    with open(log_path) as f:
        for line in f:
            try:
                overrides.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue

    if not overrides:
        return "No overrides logged yet."

    from collections import Counter
    approved: Counter = Counter()
    denied: Counter = Counter()

    for o in overrides:
        key = f"{o['domain']}/{o['action']}"
        decision = o.get("operator_decision", "")
        if decision == "approved":
            approved[key] += 1
        elif decision == "denied":
            denied[key] += 1

    lines = ["# Override Analysis", ""]

    if approved:
        lines.append("Frequently approved (consider upgrading to autonomous):")
        for key, count in approved.most_common(5):
            if count >= 3:
                lines.append(f"  - {key}: approved {count}x")

    if denied:
        lines.append("Frequently denied (consider moving to blocked):")
        for key, count in denied.most_common(5):
            if count >= 3:
                lines.append(f"  - {key}: denied {count}x")

    return "\n".join(lines)


def check_decay(config: Optional[AegisConfig] = None) -> tuple[bool, str]:
    """
    Check if the consent graph is due for a review (decay check).

    Returns:
        (needs_review: bool, message: str)
    """
    graph = load_graph(_get_config(config))
    decay = graph.get("consent_decay", {})

    if not decay.get("enabled"):
        return False, "Decay disabled"

    last_reviewed = graph.get("last_reviewed")
    if not last_reviewed:
        return True, "Never reviewed"

    try:
        last_date = datetime.date.fromisoformat(last_reviewed)
        days_since = (datetime.date.today() - last_date).days
        interval = decay.get("review_interval_days", 30)

        if days_since >= interval:
            return True, f"Last reviewed {days_since} days ago (interval: {interval})"
        return False, f"Reviewed {days_since} days ago (next in {interval - days_since} days)"
    except (ValueError, AttributeError, TypeError):
        return True, "Invalid last_reviewed date"
