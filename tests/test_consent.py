"""
Aegis test suite -- covers all 4 tiers and edge cases.
"""

import json
import os
import tempfile

import pytest

from aegis import AegisConfig, check_consent, log_override
from aegis.schema import validate_graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_GRAPH = {
    "domains": {
        "email": {
            "autonomous": ["read", "archive_promo"],
            "requires_approval": ["send", "reply"],
            "blocked": ["delete_all", "bulk_send"],
            "trust_level": "high",
        },
        "filesystem": {
            "autonomous": ["list", "read"],
            "requires_approval": ["write", "create"],
            "blocked": ["delete", "format"],
            "trust_level": "low",
        },
    },
    "consent_decay": {"enabled": True, "review_interval_days": 30},
}


@pytest.fixture
def config(tmp_path):
    graph_path = tmp_path / "consent-graph.json"
    graph_path.write_text(json.dumps(SAMPLE_GRAPH))
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return AegisConfig(graph_path=str(graph_path), log_dir=str(log_dir))


# ---------------------------------------------------------------------------
# Tier: SILENT
# ---------------------------------------------------------------------------

class TestSilent:
    def test_autonomous_action_returns_silent(self, config):
        assert check_consent("email", "read", confidence=0.5, config=config) == "SILENT"

    def test_autonomous_action_any_confidence(self, config):
        """Confidence is irrelevant for autonomous actions."""
        assert check_consent("email", "archive_promo", confidence=0.1, config=config) == "SILENT"
        assert check_consent("email", "archive_promo", confidence=1.0, config=config) == "SILENT"

    def test_filesystem_autonomous(self, config):
        assert check_consent("filesystem", "list", confidence=0.0, config=config) == "SILENT"


# ---------------------------------------------------------------------------
# Tier: VISIBLE
# ---------------------------------------------------------------------------

class TestVisible:
    def test_requires_approval_high_confidence(self, config):
        assert check_consent("email", "send", confidence=0.9, config=config) == "VISIBLE"

    def test_requires_approval_exact_threshold(self, config):
        assert check_consent("email", "send", confidence=0.85, config=config) == "VISIBLE"

    def test_filesystem_write_high_confidence(self, config):
        assert check_consent("filesystem", "write", confidence=0.95, config=config) == "VISIBLE"

    def test_unlisted_action_high_confidence(self, config):
        """Actions not in any list but domain exists => same confidence logic."""
        assert check_consent("email", "label", confidence=0.9, config=config) == "VISIBLE"


# ---------------------------------------------------------------------------
# Tier: FORCED
# ---------------------------------------------------------------------------

class TestForced:
    def test_requires_approval_low_confidence(self, config):
        assert check_consent("email", "send", confidence=0.5, config=config) == "FORCED"

    def test_requires_approval_below_threshold(self, config):
        assert check_consent("email", "reply", confidence=0.84, config=config) == "FORCED"

    def test_unknown_domain_always_forced(self, config):
        assert check_consent("telephony", "call", confidence=0.99, config=config) == "FORCED"

    def test_unlisted_action_low_confidence(self, config):
        assert check_consent("email", "label", confidence=0.5, config=config) == "FORCED"


# ---------------------------------------------------------------------------
# Tier: BLOCKED
# ---------------------------------------------------------------------------

class TestBlocked:
    def test_blocked_action(self, config):
        assert check_consent("email", "delete_all", confidence=0.99, config=config) == "BLOCKED"

    def test_blocked_regardless_of_confidence(self, config):
        """Blocked is absolute -- confidence cannot override it."""
        for conf in [0.0, 0.5, 0.85, 1.0]:
            assert check_consent("email", "bulk_send", confidence=conf, config=config) == "BLOCKED"

    def test_filesystem_blocked(self, config):
        assert check_consent("filesystem", "format", confidence=1.0, config=config) == "BLOCKED"


# ---------------------------------------------------------------------------
# Custom confidence threshold
# ---------------------------------------------------------------------------

class TestCustomThreshold:
    def test_custom_threshold_higher(self, tmp_path):
        graph_path = tmp_path / "consent-graph.json"
        graph_path.write_text(json.dumps(SAMPLE_GRAPH))
        # Threshold at 0.95 -- 0.9 should now be FORCED
        config = AegisConfig(
            graph_path=str(graph_path),
            log_dir=str(tmp_path / "logs"),
            confidence_threshold=0.95,
        )
        assert check_consent("email", "send", confidence=0.9, config=config) == "FORCED"
        assert check_consent("email", "send", confidence=0.95, config=config) == "VISIBLE"


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

class TestLogging:
    def test_attempt_logged(self, config):
        check_consent("email", "read", confidence=0.9, config=config)
        log_path = config.attempt_log_path()
        assert os.path.exists(log_path)
        with open(log_path) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        assert len(entries) >= 1
        last = entries[-1]
        assert last["domain"] == "email"
        assert last["action"] == "read"
        assert last["tier"] == "SILENT"

    def test_override_logged(self, config):
        log_override("email", "send", "user approved", "approved", config=config)
        log_path = config.override_log_path()
        assert os.path.exists(log_path)
        with open(log_path) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        assert entries[-1]["operator_decision"] == "approved"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchema:
    def test_valid_graph(self):
        result = validate_graph(SAMPLE_GRAPH)
        assert "email" in result.domains
        assert result.consent_decay.enabled is True

    def test_invalid_graph_overlap(self):
        bad_graph = {
            "domains": {
                "test": {
                    "autonomous": ["send"],
                    "blocked": ["send"],  # overlap!
                }
            }
        }
        with pytest.raises(Exception):
            validate_graph(bad_graph)

    def test_missing_domain_key(self):
        """Missing domains key should produce an empty graph, not error."""
        result = validate_graph({})
        assert result.domains == {}
