"""
VERA CLI — root application.
Entry point: vera = "interfaces.cli.main:app"
"""
import asyncio
import json as _json
import os
import sys
import uuid
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from interfaces.cli.commands import api as api_cmd
from interfaces.cli.commands import auth as auth_cmd
from interfaces.cli.commands import config as config_cmd
from interfaces.cli.commands import docs as docs_cmd
from interfaces.cli.commands import logs as logs_cmd
from interfaces.cli.commands import memory as memory_cmd
from interfaces.cli.commands import middleware as middleware_cmd
from interfaces.cli.commands import plugin as plugin_cmd
from interfaces.cli.commands import policy as policy_cmd
from interfaces.cli.commands import secrets as secrets_cmd
from interfaces.cli.commands import tool as tool_cmd

app = typer.Typer(
    name="vera",
    help="[bold]VERA[/bold] — Visible Edge Reasoning Architecture",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()

app.add_typer(api_cmd.app,        name="api",        help="Run the REST & WebSocket API server")
app.add_typer(auth_cmd.app,       name="auth",       help="Authenticate and manage users")
app.add_typer(plugin_cmd.app,     name="plugin",     help="Manage plugins")
app.add_typer(middleware_cmd.app, name="middleware",  help="Manage the middleware chain")
app.add_typer(secrets_cmd.app,    name="secrets",    help="Manage secrets")
app.add_typer(tool_cmd.app,       name="tool",       help="List and run tools")
app.add_typer(policy_cmd.app,     name="policy",     help="Manage Casbin policies")
app.add_typer(logs_cmd.app,       name="logs",       help="View audit and cost logs")
app.add_typer(config_cmd.app,     name="config",     help="View and update configuration")
app.add_typer(memory_cmd.app,     name="memory",     help="Store and retrieve memories")
app.add_typer(docs_cmd.app,       name="docs",       help="Browse VERA documentation")

from interfaces.cli.commands import extensions as ext_cmd  # noqa: E402
app.add_typer(ext_cmd.app,        name="ext",        help="Browse extension points and contributions")

# ── Plugin CLI contributions ────────────────────────────────────────────────
# Scan manifests at import time (no kernel needed) so contributed commands
# show up in `vera --help` alongside first-party commands.

def _wire_plugin_cli_contributions() -> None:
    """Dynamically register Typer apps contributed to interfaces.cli.commands."""
    import os as _os
    from core.extensions import ExtensionRegistry
    plugins_dir = _os.getenv("VERA_PLUGINS_DIR", "plugins")
    for manifest in ExtensionRegistry.scan_manifests(plugins_dir):
        plugin_name = manifest.get("name", "?")
        for contrib in manifest.get("contributes", []):
            if contrib.get("point") != "interfaces.cli.commands":
                continue
            params = contrib.get("params", {})
            handler_path = params.get("handler", "")
            cmd_name     = params.get("name", "")
            cmd_help     = params.get("help", f"Commands from plugin '{plugin_name}'")
            if not handler_path or not cmd_name:
                continue
            try:
                handler = ExtensionRegistry.resolve_import(handler_path)
                app.add_typer(handler, name=cmd_name, help=cmd_help)
            except Exception as _exc:
                # Never crash the whole CLI over a bad plugin contribution.
                pass

_wire_plugin_cli_contributions()


# ── Top-level commands ─────────────────────────────────────────────────────────

@app.command()
def status() -> None:
    """Show kernel health, loaded plugins, middleware chain, and today's audit summary."""
    from interfaces.cli._session import require_session
    require_session()
    asyncio.run(_status())


async def _status() -> None:
    from core.setup import setup_kernel
    import json as j
    from datetime import datetime

    console.print()
    try:
        kernel, bus, vfs, secrets, security, tracer, factory = await setup_kernel()
    except Exception as e:
        console.print(f"[red]Kernel setup failed:[/red] {e}")
        raise typer.Exit(1)

    llm_provider = os.getenv("VERA_LLM_PROVIDER", "ollama")
    llm_model    = os.getenv("VERA_LLM_MODEL", "llama3")
    bus_backend  = os.getenv("VERA_BUS_BACKEND", "blinker")
    vfs_backend  = os.getenv("VERA_VFS_BACKEND", "local")

    try:
        from importlib.metadata import version as _v
        vera_ver = _v("vera")
    except Exception:
        vera_ver = "dev"

    console.print(Panel(
        f"[bold cyan]VERA[/bold cyan] v{vera_ver}  |  Python {sys.version.split()[0]}  |  "
        f"LLM [green]{llm_provider}/{llm_model}[/green]  |  "
        f"Bus [green]{bus_backend}[/green]  |  VFS [green]{vfs_backend}[/green]",
        title="[bold]System Status[/bold]",
        expand=False,
    ))
    console.print()

    # Plugins
    plugins = kernel.list_plugins()
    if plugins:
        p_table = Table(title="Loaded Plugins", show_header=True, header_style="bold")
        p_table.add_column("Name", style="cyan")
        p_table.add_column("Version")
        p_table.add_column("Type")
        p_table.add_column("Tools")
        for p in plugins:
            ptype = "[bold red]core[/bold red]" if p["core"] else "external"
            tools = p["tools"]
            tools_str = ", ".join(tools[:3]) + ("…" if len(tools) > 3 else "")
            p_table.add_row(p["name"], p["version"], ptype, tools_str)
        console.print(p_table)
    else:
        console.print("[yellow]No plugins loaded.[/yellow]")

    console.print()

    # Middleware
    mw_table = Table(title="Middleware Chain", show_header=True, header_style="bold")
    mw_table.add_column("Order", justify="right", style="dim")
    mw_table.add_column("Name", style="cyan")
    for mw in kernel._middleware:
        mw_table.add_row(str(mw.order), type(mw).__name__)
    console.print(mw_table)
    console.print()

    # Audit summary (today)
    audit_path = Path("data/logs/audit.jsonl")
    if audit_path.exists():
        today = datetime.utcnow().strftime("%Y-%m-%d")
        total = success = failure = 0
        with open(audit_path) as f:
            for line in f:
                try:
                    entry = j.loads(line)
                    if entry.get("timestamp", "").startswith(today):
                        total += 1
                        if entry.get("status") == "success":
                            success += 1
                        else:
                            failure += 1
                except Exception:
                    continue
        console.print(
            f"[bold]Today's Audit:[/bold]  {total} calls  "
            f"[green]{success} ok[/green]  [red]{failure} failed[/red]"
        )
    else:
        console.print("[dim]No audit log yet.[/dim]")

    console.print()
    await vfs.close()


@app.command()
def init() -> None:
    """Bootstrap a new VERA instance: create required directories and validate prerequisites."""
    dirs = ["data/logs", "data/casbin", "data/vector_store", "plugins"]
    console.print()
    console.print(Panel("[bold cyan]VERA Init[/bold cyan]", expand=False))
    console.print()

    all_ok = True
    for d in dirs:
        p = Path(d)
        if p.exists():
            console.print(f"  [green]✓[/green] {d}  [dim](exists)[/dim]")
        else:
            p.mkdir(parents=True, exist_ok=True)
            console.print(f"  [green]+[/green] {d}  [dim](created)[/dim]")

    for f in ["data/casbin/rbac_model.conf", "data/casbin/policy.csv"]:
        if Path(f).exists():
            console.print(f"  [green]✓[/green] {f}")
        else:
            console.print(f"  [yellow]![/yellow] {f} [yellow]— missing, Casbin will not work[/yellow]")
            all_ok = False

    console.print()
    if all_ok:
        console.print("[green]Ready.[/green]  Run [bold]vera status[/bold] to verify.")
    else:
        console.print("[yellow]Some prerequisites are missing (see above).[/yellow]")
    console.print()


@app.command()
def doctor() -> None:
    """Run diagnostics: Python version, env vars, files, and key imports."""
    console.print()
    console.print(Panel("[bold]VERA Doctor[/bold]", expand=False))
    console.print()

    checks: list[tuple[str, bool, str]] = []

    major, minor = sys.version_info[:2]
    checks.append(("Python >= 3.11", major >= 3 and minor >= 11, f"{major}.{minor}"))

    for var, default in [
        ("VERA_LLM_PROVIDER",    "ollama"),
        ("VERA_BUS_BACKEND",     "blinker"),
        ("VERA_SECRETS_BACKEND", "keyring"),
        ("VERA_VFS_PATH",        "data/vera_vfs.db"),
    ]:
        val = os.environ.get(var)
        display = val if val else f"{default} [dim](default)[/dim]"
        checks.append((f"${var}", True, display))

    for fname in ["data/casbin/rbac_model.conf", "data/casbin/policy.csv"]:
        ok = Path(fname).exists()
        checks.append((fname, ok, "found" if ok else "[red]missing[/red]"))

    plugins_dir = os.getenv("VERA_PLUGINS_DIR", "plugins")
    ok = Path(plugins_dir).exists()
    checks.append((f"VERA_PLUGINS_DIR ({plugins_dir})", ok, "found" if ok else "[red]missing[/red]"))

    for pkg in ["typer", "rich", "casbin", "yaml", "aiosqlite", "casbin"]:
        try:
            __import__(pkg)
            checks.append((f"import {pkg}", True, "ok"))
        except ImportError:
            checks.append((f"import {pkg}", False, "[red]not installed[/red]"))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check")
    table.add_column("", justify="center")
    table.add_column("Detail")
    for label, ok, detail in checks:
        table.add_row(label, "[green]✓[/green]" if ok else "[red]✗[/red]", str(detail))

    console.print(table)
    failed = sum(1 for _, ok, _ in checks if not ok)
    console.print()
    if failed == 0:
        console.print("[green]All checks passed.[/green]")
    else:
        console.print(f"[red]{failed} check(s) failed.[/red]")
    console.print()


@app.command("run-tool")
def run_tool(
    tool_name: str = typer.Argument(..., help="Tool name  e.g. llm.generate_structured"),
    kv_args: Optional[List[str]] = typer.Argument(None, help="key=value payload pairs"),
    tenant_id: str = typer.Option("default", "--tenant-id"),
    json_payload: Optional[str] = typer.Option(None, "--json", help="Full JSON payload"),
) -> None:
    """Execute a tool through the full middleware chain (shortcut for vera tool run)."""
    from interfaces.cli._session import get_identity
    user_id, user_role = get_identity()
    asyncio.run(tool_cmd._tool_run(tool_name, kv_args, user_id, user_role, tenant_id, json_payload))
