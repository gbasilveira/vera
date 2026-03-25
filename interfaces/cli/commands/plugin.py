"""vera plugin — Plugin management subcommands."""
import asyncio
import subprocess
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from interfaces.cli._session import require_role, require_session

app = typer.Typer(help="Manage VERA plugins", no_args_is_help=True)
console = Console()


def _bare_kernel():
    """Lightweight kernel with no plugins loaded — for discovery/scaffold only."""
    from core.kernel import VeraKernel
    VeraKernel.reset()
    return VeraKernel.get_instance()


async def _full_kernel():
    """Full kernel with all plugins loaded."""
    from core.setup import setup_kernel
    return await setup_kernel()


@app.command("list")
def plugin_list() -> None:
    """List all available plugins (discovered + load status)."""
    require_session()
    kernel = _bare_kernel()
    plugins = kernel.discover_plugins()

    if not plugins:
        console.print("[yellow]No plugins found.[/yellow]")
        return

    table = Table(title="VERA Plugins", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Version")
    table.add_column("Core")
    table.add_column("External")
    table.add_column("Tools", justify="right")
    table.add_column("Description", style="dim")

    for m in plugins:
        if "_error" in m:
            table.add_row(m["_dir"], "?", "?", "?", "?", f"[red]{m['_error']}[/red]")
            continue
        core_str = "[bold red]yes[/bold red]" if m.get("core") else "no"
        ext_str = "[yellow]yes[/yellow]" if m.get("external") else "no"
        table.add_row(
            m.get("name", m["_dir"]),
            m.get("version", "?"),
            core_str,
            ext_str,
            str(len(m.get("tools", []))),
            m.get("description", ""),
        )
    console.print(table)


@app.command("info")
def plugin_info(
    name: str = typer.Argument(..., help="Plugin name"),
) -> None:
    """Show full manifest for a plugin."""
    require_session()
    kernel = _bare_kernel()
    plugins = kernel.discover_plugins()
    manifest = next((m for m in plugins if m.get("name") == name or m.get("_dir") == name), None)

    if not manifest or "_error" in manifest:
        console.print(f"[red]Plugin '{name}' not found or manifest invalid.[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold cyan]{manifest.get('name')}[/bold cyan]  v{manifest.get('version')}",
        title="Plugin Info",
        expand=False,
    ))
    console.print()
    skip = {"_dir", "_loaded", "_error", "extension_points", "contributes"}
    for key, val in manifest.items():
        if key not in skip:
            console.print(f"  [bold]{key}:[/bold] {val}")

    # Extension points this plugin exposes
    ext_points = manifest.get("extension_points", [])
    if ext_points:
        console.print()
        console.print("  [bold]extension_points:[/bold]")
        for ep in ext_points:
            console.print(
                f"    [cyan]{ep.get('id', '?')}[/cyan]"
                f"  [dim]type: {ep.get('type', '?')}[/dim]"
                f"  {ep.get('description', '')}"
            )

    # What this plugin contributes to others
    contributes = manifest.get("contributes", [])
    if contributes:
        console.print()
        console.print("  [bold]contributes:[/bold]")
        for c in contributes:
            params = c.get("params", {})
            name_hint = (
                params.get("name") or params.get("title") or
                params.get("path") or params.get("id") or ""
            )
            console.print(
                f"    → [yellow]{c.get('point', '?')}[/yellow]"
                f"  [dim]type: {c.get('type', '?')}[/dim]"
                + (f"  [green]{name_hint}[/green]" if name_hint else "")
            )

    console.print()


@app.command("new")
def plugin_new(
    name: str = typer.Argument(..., help="New plugin name (snake_case)"),
) -> None:
    """Scaffold a new plugin from the _template directory."""
    require_role("owner")
    kernel = _bare_kernel()
    try:
        dest = kernel.scaffold_plugin(name)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except FileExistsError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Created [bold]{dest}[/bold]")
    console.print(f"  Edit  [cyan]{dest}/manifest.yaml[/cyan]")
    console.print(f"  Edit  [cyan]{dest}/plugin.py[/cyan]")
    console.print(f"  Run   [cyan]vera plugin verify {dest}[/cyan]")


@app.command("verify")
def plugin_verify(
    path: str = typer.Argument(..., help="Path to plugin directory"),
) -> None:
    """Run plugin SDK contract tests against a plugin directory."""
    require_role("owner")
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/plugin_sdk/", f"--plugin={path}", "-v"],
    )
    raise typer.Exit(result.returncode)


@app.command("load")
def plugin_load(
    name: str = typer.Argument(..., help="Plugin directory name"),
) -> None:
    """Load a plugin (validates it starts cleanly against the running kernel)."""
    require_role("owner")
    asyncio.run(_plugin_load_async(name))


async def _plugin_load_async(name: str) -> None:
    try:
        kernel, bus, vfs, secrets, security, tracer, factory = await _full_kernel()
    except Exception as e:
        console.print(f"[red]Kernel setup failed:[/red] {e}")
        raise typer.Exit(1)
    try:
        if name not in kernel._active_plugins:
            kernel.load_plugin(name)
        console.print(f"[green]✓[/green] Plugin [bold]{name}[/bold] loaded.")
    except Exception as e:
        console.print(f"[red]Failed to load '{name}':[/red] {e}")
        raise typer.Exit(1)
    finally:
        await vfs.close()


@app.command("unload")
def plugin_unload(
    name: str = typer.Argument(..., help="Plugin name (non-core only)"),
) -> None:
    """Unload a non-core plugin."""
    require_role("owner")
    asyncio.run(_plugin_unload_async(name))


async def _plugin_unload_async(name: str) -> None:
    try:
        kernel, bus, vfs, secrets, security, tracer, factory = await _full_kernel()
    except Exception as e:
        console.print(f"[red]Kernel setup failed:[/red] {e}")
        raise typer.Exit(1)
    try:
        kernel.unload_plugin(name)
        console.print(f"[green]✓[/green] Plugin [bold]{name}[/bold] unloaded.")
    except Exception as e:
        console.print(f"[red]Failed to unload '{name}':[/red] {e}")
        raise typer.Exit(1)
    finally:
        await vfs.close()
