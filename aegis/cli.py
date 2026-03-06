"""
Aegis CLI

Commands:
    aegis init      -- Create a starter consent-graph.json at the default location
    aegis check     -- Check consent for a domain/action
    aegis summary   -- Print human-readable graph summary
    aegis validate  -- Validate graph against Pydantic schema
    aegis decay     -- Check if the graph needs review
    aegis overrides -- Show override pattern analysis
    aegis mcp       -- Start the MCP server (stdio)
"""

import json
import os
import sys
from pathlib import Path

import click

from aegis.consent import (
    AegisConfig,
    check_consent,
    check_decay,
    get_consent_summary,
    get_override_stats,
    log_override,
)
from aegis.schema import validate_graph

EXAMPLE_GRAPH = {
    "metadata": {
        "version": "0.1.0",
        "description": "Starter Aegis consent graph -- edit to match your agent's capabilities",
    },
    "domains": {
        "messaging": {
            "autonomous": ["read"],
            "requires_approval": ["send", "reply"],
            "blocked": ["bulk_send", "delete_thread"],
            "trust_level": "high",
        },
        "calendar": {
            "autonomous": ["read", "list_events"],
            "requires_approval": ["create_event", "update_event"],
            "blocked": ["delete_all_events"],
            "trust_level": "medium",
        },
        "filesystem": {
            "autonomous": ["read", "list"],
            "requires_approval": ["write", "create"],
            "blocked": ["delete", "format"],
            "trust_level": "low",
        },
        "web_search": {
            "autonomous": ["search", "fetch_page"],
            "requires_approval": ["post_content", "submit_form"],
            "blocked": ["purchase", "create_account"],
            "trust_level": "medium",
        },
        "home_automation": {
            "autonomous": ["read_sensor", "check_status"],
            "requires_approval": ["set_thermostat", "lock_door", "unlock_door"],
            "blocked": ["disable_alarm", "factory_reset"],
            "trust_level": "high",
        },
    },
    "consent_decay": {
        "enabled": True,
        "review_interval_days": 30,
    },
    "last_reviewed": None,
}


def _make_config(ctx: click.Context) -> AegisConfig:
    """Build AegisConfig from context params or defaults."""
    graph_path = ctx.obj.get("graph_path") if ctx.obj else None
    log_dir = ctx.obj.get("log_dir") if ctx.obj else None
    kwargs = {}
    if graph_path:
        kwargs["graph_path"] = graph_path
    if log_dir:
        kwargs["log_dir"] = log_dir
    return AegisConfig(**kwargs)


@click.group()
@click.option(
    "--graph",
    "graph_path",
    envvar="AEGIS_GRAPH_PATH",
    default=None,
    help="Path to consent-graph.json (overrides default ~/.aegis/consent-graph.json)",
)
@click.option(
    "--log-dir",
    envvar="AEGIS_LOG_DIR",
    default=None,
    help="Directory for audit logs (overrides default ~/.aegis/logs/)",
)
@click.pass_context
def cli(ctx: click.Context, graph_path: str | None, log_dir: str | None) -> None:
    """Aegis -- Consent Graph as Code for AI agents."""
    ctx.ensure_object(dict)
    if graph_path:
        ctx.obj["graph_path"] = graph_path
    if log_dir:
        ctx.obj["log_dir"] = log_dir


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Create a starter consent-graph.json at the default (or --graph) location."""
    config = _make_config(ctx)
    path = os.path.expanduser(config.graph_path)

    if os.path.exists(path):
        click.echo(f"Already exists: {path}")
        click.echo("Delete it first if you want to reinitialize.")
        sys.exit(1)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(EXAMPLE_GRAPH, f, indent=2)

    click.echo(f"Created: {path}")
    click.echo("Edit it to match your agent's domains and actions.")


@cli.command()
@click.argument("domain")
@click.argument("action")
@click.option(
    "--confidence",
    "-c",
    default=0.85,
    type=float,
    show_default=True,
    help="Agent confidence in operator intent (0.0-1.0)",
)
@click.pass_context
def check(ctx: click.Context, domain: str, action: str, confidence: float) -> None:
    """Check consent for DOMAIN/ACTION at the given CONFIDENCE level."""
    config = _make_config(ctx)
    tier = check_consent(domain, action, confidence, config=config)

    colors = {
        "SILENT": "green",
        "VISIBLE": "cyan",
        "FORCED": "yellow",
        "BLOCKED": "red",
    }
    guidance = {
        "SILENT": "Proceed silently.",
        "VISIBLE": "Proceed, then notify the operator.",
        "FORCED": "Stop -- request operator approval first.",
        "BLOCKED": "Prohibited -- do not execute, alert operator.",
    }

    click.echo(
        f"{domain}/{action} (confidence={confidence}) → "
        + click.style(tier, fg=colors.get(tier, "white"), bold=True)
    )
    click.echo(f"  {guidance[tier]}")


@cli.command()
@click.pass_context
def summary(ctx: click.Context) -> None:
    """Print a human-readable summary of the consent graph."""
    config = _make_config(ctx)
    click.echo(get_consent_summary(config))


@cli.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate the consent graph against the Aegis Pydantic schema."""
    config = _make_config(ctx)
    path = os.path.expanduser(config.graph_path)

    if not os.path.exists(path):
        click.echo(f"File not found: {path}", err=True)
        click.echo("Run `aegis init` to create a starter graph.", err=True)
        sys.exit(1)

    with open(path) as f:
        raw = json.load(f)

    try:
        graph = validate_graph(raw)
        click.echo(click.style("✓ Valid", fg="green", bold=True))
        click.echo(f"  {len(graph.domains)} domain(s) configured")
        click.echo(f"  Decay: {'enabled' if graph.consent_decay.enabled else 'disabled'}")
    except Exception as e:
        click.echo(click.style("✗ Invalid", fg="red", bold=True))
        click.echo(str(e), err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def decay(ctx: click.Context) -> None:
    """Check whether the consent graph is due for a review."""
    config = _make_config(ctx)
    needs_review, msg = check_decay(config)
    if needs_review:
        click.echo(click.style("⚠  Review needed: ", fg="yellow") + msg)
    else:
        click.echo(click.style("✓  ", fg="green") + msg)


@cli.command()
@click.pass_context
def overrides(ctx: click.Context) -> None:
    """Analyze override patterns and suggest consent graph updates."""
    config = _make_config(ctx)
    click.echo(get_override_stats(config))


@cli.command()
def mcp() -> None:
    """Start the Aegis MCP server on stdio (for use with MCP hosts)."""
    try:
        from aegis.mcp_server import main
        main()
    except ImportError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
