"""
Aegis Quickstart -- 10-line integration example.

This shows the minimal integration pattern: check before you act.
"""

from aegis import AegisConfig, check_consent, log_override

# Point Aegis at your consent graph
config = AegisConfig(graph_path="./consent-graph.example.json")

# Check before any external action
tier = check_consent("messaging", "send", confidence=0.9, config=config)

if tier == "BLOCKED":
    print("Action blocked by consent graph -- aborting.")
elif tier == "FORCED":
    print("Need operator approval before sending. Surfacing to user...")
    # In production: show approval UI, wait for response
elif tier == "VISIBLE":
    print("Sending message (high confidence). Will notify operator after.")
    # do_send()
    # notify_operator("Sent message because ...")
else:  # SILENT
    print("Sending message autonomously (pre-approved action).")
    # do_send()

# Log a human override (e.g. operator approved a FORCED action)
log_override(
    domain="messaging",
    action="send",
    reason="User explicitly asked agent to send the draft",
    operator_decision="approved",
    config=config,
)
print("Override logged to audit trail.")
