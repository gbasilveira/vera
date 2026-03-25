"""vera api — Manage and run the VERA REST & WebSocket server."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from interfaces.cli._session import require_session

app = typer.Typer(
    name="api",
    help="Run and inspect the VERA REST & WebSocket API server.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()


@app.command("serve")
def api_serve(
    host: str  = typer.Option("127.0.0.1", "--host", "-h", help="Bind address"),
    port: int  = typer.Option(8000,        "--port", "-p", help="Port"),
    reload: bool = typer.Option(False,     "--reload",     help="Hot-reload on code changes (dev only)"),
    workers: int = typer.Option(1,         "--workers",    help="Number of worker processes (production)"),
) -> None:
    """Start the VERA API server (REST + WebSocket).

    Examples:

    \b
        vera api serve                          # dev: localhost:8000
        vera api serve --host 0.0.0.0 --port 9000
        vera api serve --reload                 # hot-reload for development
        vera api serve --workers 4              # production multi-process
    """
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn is not installed.[/red]  Run: pip install 'uvicorn[standard]'")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold cyan]VERA API[/bold cyan]  "
        f"[green]http://{host}:{port}[/green]\n"
        f"[dim]Docs → http://{host}:{port}/vera/docs[/dim]\n"
        f"[dim]WS   → ws://{host}:{port}/vera/ws/{{namespace}}?token=...[/dim]",
        title="[bold]Starting API Server[/bold]",
        expand=False,
    ))
    console.print()

    uvicorn.run(
        "interfaces.api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,  # uvicorn disallows workers+reload
        log_level="info",
    )


@app.command("routes")
def api_routes() -> None:
    """List all routes that will be mounted (built-in + plugin contributions)."""
    require_session()

    from core.extensions import ExtensionRegistry
    import os

    plugins_dir = os.getenv("VERA_PLUGINS_DIR", "plugins")
    reg = ExtensionRegistry()
    for manifest in ExtensionRegistry.scan_manifests(plugins_dir):
        reg.register_from_manifest(manifest)

    console.print()

    # Built-in routes
    builtin_table = Table(title="Built-in Routes", show_header=True, header_style="bold", box=None, padding=(0, 2))
    builtin_table.add_column("Method", style="green")
    builtin_table.add_column("Path", style="cyan")
    builtin_table.add_column("Description", style="dim")

    builtin_routes = [
        ("GET",       "/health",                    "Liveness probe"),
        ("GET",       "/vera/info",                 "Kernel metadata"),
        ("POST",      "/vera/auth/login",            "Obtain session token"),
        ("POST",      "/vera/auth/logout",           "Revoke session token"),
        ("GET",       "/vera/tools",                 "List all tools"),
        ("POST",      "/vera/tools/{tool_name}",     "Execute a tool"),
        ("WS",        "/vera/ws/{namespace}",        "WebSocket endpoint"),
        ("GET",       "/vera/docs",                  "OpenAPI UI (Swagger)"),
        ("GET",       "/vera/redoc",                 "OpenAPI UI (ReDoc)"),
    ]
    for method, path, desc in builtin_routes:
        method_colour = {
            "GET": "green", "POST": "yellow", "WS": "cyan",
        }.get(method, "white")
        builtin_table.add_row(f"[{method_colour}]{method}[/{method_colour}]", path, desc)
    console.print(builtin_table)

    # Plugin contributions
    contribs = reg.get_contributions("interfaces.api.routes")
    if contribs:
        console.print()
        plugin_table = Table(
            title="Plugin Routes", show_header=True, header_style="bold",
            box=None, padding=(0, 2),
        )
        plugin_table.add_column("Plugin", style="cyan")
        plugin_table.add_column("Prefix", style="yellow")
        plugin_table.add_column("Handler", style="dim")

        for c in sorted(contribs, key=lambda x: x.plugin):
            plugin_table.add_row(
                c.plugin,
                c.params.get("prefix", f"/{c.plugin}"),
                c.params.get("handler", ""),
            )
        console.print(plugin_table)

    # WS namespaces
    ws_contribs = reg.get_contributions("interfaces.api.websocket")
    if ws_contribs:
        console.print()
        ws_table = Table(
            title="WebSocket Namespaces", show_header=True, header_style="bold",
            box=None, padding=(0, 2),
        )
        ws_table.add_column("Plugin", style="cyan")
        ws_table.add_column("Namespace", style="yellow")
        ws_table.add_column("Description", style="dim")

        for c in sorted(ws_contribs, key=lambda x: x.plugin):
            ws_table.add_row(
                c.plugin,
                c.params.get("namespace", ""),
                c.params.get("description", ""),
            )
        console.print(ws_table)

    console.print()
