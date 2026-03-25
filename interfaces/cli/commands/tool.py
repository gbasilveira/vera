"""vera tool — Tool listing, introspection, and execution."""
import asyncio
import json as _json
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from interfaces.cli._session import get_identity, require_session

app = typer.Typer(help="List, inspect, and execute registered tools", no_args_is_help=True)
console = Console()


@app.command("list")
def tool_list(
    plugin: Optional[str] = typer.Option(None, "--plugin", "-p", help="Filter by plugin name"),
) -> None:
    """List all tools registered across loaded plugins."""
    require_session()
    asyncio.run(_tool_list(plugin))


async def _tool_list(plugin_filter: Optional[str]) -> None:
    from core.setup import setup_kernel
    try:
        kernel, bus, vfs, secrets, security, tracer, factory = await setup_kernel()
    except Exception as e:
        console.print(f"[red]Kernel setup failed:[/red] {e}")
        raise typer.Exit(1)

    tools = kernel.list_tool_details()
    if plugin_filter:
        tools = [t for t in tools if t["plugin"] == plugin_filter]

    if not tools:
        console.print("[yellow]No tools registered.[/yellow]")
        await vfs.close()
        return

    table = Table(title="Registered Tools", show_header=True, header_style="bold")
    table.add_column("Tool", style="cyan")
    table.add_column("Plugin")
    table.add_column("Ext")
    table.add_column("Description", style="dim")
    for t in sorted(tools, key=lambda x: x["name"]):
        ext = "[yellow]⬡[/yellow]" if t["is_external"] else ""
        table.add_row(t["name"], t["plugin"], ext, t.get("doc", ""))

    console.print(table)
    await vfs.close()


@app.command("info")
def tool_info(
    tool_name: str = typer.Argument(..., help="Tool name  e.g. flow.run"),
) -> None:
    """Show full signature, docstring, and metadata for a tool."""
    require_session()
    asyncio.run(_tool_info(tool_name))


async def _tool_info(tool_name: str) -> None:
    from core.setup import setup_kernel
    try:
        kernel, bus, vfs, secrets, security, tracer, factory = await setup_kernel()
    except Exception as e:
        console.print(f"[red]Kernel setup failed:[/red] {e}")
        raise typer.Exit(1)

    try:
        info = kernel.get_tool_info(tool_name)
    except KeyError:
        console.print(f"[red]Tool '{tool_name}' not found.[/red]")
        console.print("  Run [cyan]vera tool list[/cyan] to see available tools.")
        await vfs.close()
        raise typer.Exit(1)

    ext_label = "[yellow]yes — PII masking active[/yellow]" if info["is_external"] else "no"
    console.print()
    console.print(Panel(
        f"[bold cyan]{info['name']}[/bold cyan]   plugin=[bold]{info['plugin']}[/bold]   external={ext_label}",
        title="Tool Info",
        expand=False,
    ))

    if info["doc"]:
        console.print()
        console.print("[bold]Description[/bold]")
        for line in info["doc"].splitlines():
            console.print(f"  {line}")

    params = info.get("params", [])
    if params:
        console.print()
        p_table = Table(title="Parameters", show_header=True, header_style="bold")
        p_table.add_column("Name", style="cyan")
        p_table.add_column("Type", style="dim")
        p_table.add_column("Required", justify="center")
        p_table.add_column("Default", style="dim")
        for p in params:
            req = "[green]✓[/green]" if p.get("required") else ""
            p_table.add_row(p["name"], p.get("type", ""), req, p.get("default", ""))
        console.print(p_table)
        console.print()
        required = [p["name"] for p in params if p.get("required")]
        optional = [p["name"] for p in params if not p.get("required")]
        parts = [f"{n}=<value>" for n in required] + [f"[{n}=<value>]" for n in optional]
        console.print(f"[dim]Usage:[/dim]  vera tool run {tool_name} {' '.join(parts)}")
    else:
        console.print("\n[dim]No parameters.[/dim]")

    console.print()
    await vfs.close()


@app.command("run")
def tool_run(
    tool_name: str = typer.Argument(..., help="Tool name  e.g. llm.generate_structured"),
    kv_args: Optional[List[str]] = typer.Argument(None, help="key=value payload pairs"),
    tenant_id: str = typer.Option("default", "--tenant-id"),
    json_payload: Optional[str] = typer.Option(None, "--json", help="Full JSON payload"),
) -> None:
    """Execute a tool through the full middleware chain (auth, PII, audit, cost)."""
    user_id, user_role = get_identity()
    asyncio.run(_tool_run(tool_name, kv_args, user_id, user_role, tenant_id, json_payload))


async def _tool_run(
    tool_name: str,
    kv_args: Optional[List[str]],
    user_id: str,
    user_role: str,
    tenant_id: str,
    json_payload: Optional[str],
) -> None:
    import uuid
    from core.setup import setup_kernel
    try:
        kernel, bus, vfs, secrets, security, tracer, factory = await setup_kernel()
    except Exception as e:
        console.print(f"[red]Kernel setup failed:[/red] {e}")
        raise typer.Exit(1)

    kwargs: dict = {}
    if json_payload:
        try:
            kwargs = _json.loads(json_payload)
        except _json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON:[/red] {e}")
            raise typer.Exit(1)
    for arg in kv_args or []:
        if "=" not in arg:
            console.print(f"[red]Invalid argument (expected key=value):[/red] {arg}")
            raise typer.Exit(1)
        k, v = arg.split("=", 1)
        kwargs[k] = v

    deps = factory.create(
        user_id=user_id,
        user_role=user_role,
        session_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
    )

    try:
        result = await deps.run_tool(tool_name, **kwargs)
        console.print("[bold green]Result:[/bold green]")
        if isinstance(result, (dict, list)):
            console.print_json(_json.dumps(result, default=str))
        else:
            console.print(result)
    except KeyError as e:
        console.print(f"[red]Tool not found:[/red] {e}")
        console.print("  Run [cyan]vera tool list[/cyan] to see available tools.")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]{type(e).__name__}:[/red] {e}")
        raise typer.Exit(1)
    finally:
        await vfs.close()
