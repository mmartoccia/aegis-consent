# aegis-consent

AI agents break trust when they act without permission. Not because they're malicious -- because the authorization boundary was never made explicit. `aegis-consent` gives you a simple, auditable way to define exactly what your agent can do autonomously, what requires human approval, and what is permanently off-limits -- in a single JSON file that travels with your deployment.

```python
from aegis import check_consent, AegisConfig

config = AegisConfig(graph_path="./consent-graph.json")
tier = check_consent("email", "send", confidence=0.9, config=config)
# → "VISIBLE"  (execute, then notify operator)
```

---

## Install

```bash
pip install aegis-consent
# With MCP server support:
pip install "aegis-consent[mcp]"
```

---

## The 4-Tier Model

Every action resolves to exactly one tier. The engine checks lists in priority order: **blocked → autonomous → requires_approval → unlisted**.

| Tier | What it means | Agent behavior |
|------|--------------|----------------|
| **SILENT** | Pre-approved. Operator trusts this unconditionally. | Execute. Log it. No notification. |
| **VISIBLE** | Allowed at high confidence (≥ 0.85). | Execute, then notify operator: "I did X because Y." |
| **FORCED** | Allowed but needs explicit approval. | Stop. Surface to operator. Wait for response. |
| **BLOCKED** | Absolute prohibition. Never execute. | Refuse. Alert operator that the attempt was made. |

The `confidence` parameter is the agent's self-reported confidence that the action matches operator intent. High confidence on a `requires_approval` action yields VISIBLE; low confidence yields FORCED. Blocked actions are always blocked, regardless of confidence.

---

## consent-graph.json

Define your domains and actions in a single JSON file:

```json
{
  "domains": {
    "email": {
      "autonomous": ["read", "archive_promo"],
      "requires_approval": ["send", "reply"],
      "blocked": ["delete_all", "bulk_send"],
      "trust_level": "high"
    },
    "filesystem": {
      "autonomous": ["read", "list"],
      "requires_approval": ["write", "create"],
      "blocked": ["delete", "format"],
      "trust_level": "low"
    }
  },
  "consent_decay": {
    "enabled": true,
    "review_interval_days": 30
  }
}
```

See [`examples/consent-graph.example.json`](examples/consent-graph.example.json) for a full 5-domain example with design rationale notes.

**Note on JSON comments:** JSON doesn't support comments natively. The example file uses `"_design_note"` keys for inline documentation -- Aegis ignores unknown keys.

---

## Python API

```python
from aegis import check_consent, log_override, AegisConfig

# Configure once
config = AegisConfig(
    graph_path="./consent-graph.json",
    log_dir="./logs/",
    confidence_threshold=0.85,  # default
)

# Check before any external action
tier = check_consent("calendar", "create_event", confidence=0.9, config=config)

if tier == "BLOCKED":
    raise PermissionError("Action blocked by consent graph")
elif tier == "FORCED":
    # surface approval UI to operator, await response
    ...
elif tier == "VISIBLE":
    do_action()
    notify_operator("Created calendar event because user requested it.")
else:  # SILENT
    do_action()

# Log when a human overrides a consent decision
log_override(
    domain="calendar",
    action="create_event",
    reason="Operator approved via Slack button",
    operator_decision="approved",
    config=config,
)
```

### AegisConfig defaults

| Parameter | Default | Description |
|-----------|---------|-------------|
| `graph_path` | `~/.aegis/consent-graph.json` | Path to consent graph |
| `log_dir` | `~/.aegis/logs/` | Audit log directory |
| `confidence_threshold` | `0.85` | Min confidence for VISIBLE vs FORCED |

---

## CLI

```bash
# Create a starter consent-graph.json
aegis init

# Check consent for an action
aegis check email send --confidence 0.9

# Print graph summary
aegis summary

# Validate graph schema
aegis validate

# Check if graph needs review (decay)
aegis decay

# Analyze override patterns
aegis overrides

# Override graph location
aegis --graph /path/to/consent-graph.json summary
```

---

## MCP Server

Aegis ships an MCP server that exposes `check_consent` as a native tool. Any MCP-compatible framework (LangChain, CrewAI, Claude Desktop, custom) can call it.

**Start the server:**
```bash
aegis mcp
# or
python -m aegis.mcp_server
```

**MCP client config (e.g. Claude Desktop):**
```json
{
  "mcpServers": {
    "aegis": {
      "command": "aegis",
      "args": ["mcp"],
      "env": {
        "AEGIS_GRAPH_PATH": "/path/to/consent-graph.json"
      }
    }
  }
}
```

**Tool: `check_consent`**

Input:
```json
{
  "domain": "email",
  "action": "send",
  "confidence": 0.9
}
```

Output:
```json
{
  "tier": "VISIBLE",
  "domain": "email",
  "action": "send",
  "confidence": 0.9,
  "guidance": "Proceed, then notify the operator."
}
```

---

## Schema Validation

```python
from aegis import validate_graph
import json

with open("consent-graph.json") as f:
    raw = json.load(f)

graph = validate_graph(raw)  # raises pydantic.ValidationError if invalid
print(f"{len(graph.domains)} domains configured")
```

Or via CLI:
```bash
aegis validate
```

---

## Audit Trail

Every consent check is logged to `{log_dir}/consent-attempts.jsonl`. Every human override is logged to `{log_dir}/consent-overrides.jsonl`.

```jsonl
{"timestamp": "2025-01-15T14:23:01", "domain": "email", "action": "send", "confidence": 0.9, "tier": "VISIBLE", "reason": "high_confidence_approval"}
```

Use the override log to identify patterns and refine your graph:

```bash
aegis overrides
# → "email/send: approved 5x → consider upgrading to autonomous"
```

---

## Why This Matters

Enterprise and government deployments of AI agents face a common failure mode: the authorization boundary is implicit, embedded in prompts or agent code, invisible to auditors, and impossible to update without a code deploy. When something goes wrong -- and it will -- there's no audit trail and no clear policy to point to.

Aegis makes the boundary explicit, version-controlled, human-readable, and independently auditable. The consent graph is the policy. The audit log is the evidence. The override log is the feedback loop that improves the policy over time.

For regulated industries, this pattern maps directly onto existing control frameworks (SOC 2 access controls, FedRAMP least-privilege, NIST AI RMF). The consent graph is a machine-readable policy artifact that compliance teams can review without reading agent code.

---

## Project Status

v0.1.0 -- production logic extracted and packaged. API is stable. MCP server is functional. Breaking changes will be versioned.

**Roadmap:**
- Async support for `check_consent`
- Time-window constraints (e.g., "only during business hours")
- Graph inheritance (base + environment overrides)
- Web UI for graph editing

Contributions welcome.
