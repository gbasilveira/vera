"""vera config — View, export, import and apply VERA configuration."""
import os
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from interfaces.cli._session import require_role, require_session

app = typer.Typer(help="View, export, import and apply VERA configuration", no_args_is_help=True)
console = Console()

_VARS: list[tuple[str, str, str]] = [
    ("VERA_BUS_BACKEND",     "blinker",                     "blinker | redis | nats"),
    ("VERA_LLM_PROVIDER",    "ollama",                      "ollama | openai | anthropic"),
    ("VERA_LLM_MODEL",       "llama3",                      "model string"),
    ("VERA_VECTOR_BACKEND",  "chroma",                      "chroma | lancedb | pgvector"),
    ("VERA_SECRETS_BACKEND", "keyring",                     "keyring | sqlite"),
    ("VERA_MASTER_KEY",      "",                            "master key for sqlite backend"),
    ("VERA_VFS_PATH",        "data/vera_vfs.db",            "SQLite VFS database path"),
    ("VERA_CASBIN_MODEL",    "data/casbin/rbac_model.conf", "Casbin model.conf path"),
    ("VERA_CASBIN_POLICY",   "data/casbin/policy.csv",      "Casbin policy.csv path"),
    ("VERA_PLUGINS_DIR",     "plugins",                     "plugins directory"),
]


@app.command("show")
def config_show() -> None:
    """Show all VERA environment variables with current values and defaults."""
    require_session()

    table = Table(title="VERA Configuration", show_header=True, header_style="bold")
    table.add_column("Variable", style="cyan")
    table.add_column("Value")
    table.add_column("Source", style="dim")
    table.add_column("Options", style="dim")

    for var, default, options in _VARS:
        env_val = os.environ.get(var)
        if var == "VERA_MASTER_KEY" and env_val:
            display = "****"
        else:
            display = env_val if env_val is not None else default
        source = "[green]env[/green]" if env_val is not None else "[dim]default[/dim]"
        table.add_row(var, display or "[dim](unset)[/dim]", source, options)

    console.print(table)


@app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Environment variable name"),
    value: str = typer.Argument(..., help="New value"),
    env_file: str = typer.Option(".env", "--file", "-f", help=".env file to write"),
) -> None:
    """Write or update a variable in the .env file. Requires owner role."""
    require_role("owner")

    env_path = Path(env_file)
    lines: list[str] = []
    found = False
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            stripped = line.split("=", 1)[0].strip()
            if stripped == key:
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")
    console.print(f"[green]✓[/green] {key}={value}  →  [bold]{env_file}[/bold]")
    console.print("[dim]Restart VERA for changes to take effect.[/dim]")


# ── Resource management (export / apply / diff) ─────────────────────────────

_VALID_KINDS = ["MiddlewareChain", "Policy", "EnvConfig"]


@app.command("export")
def config_export(
    kind: Optional[List[str]] = typer.Option(
        None, "--kind", "-k",
        help=f"Resource kind(s) to export.  Repeat for multiple.  "
             f"Valid: {', '.join(_VALID_KINDS)}.  Default: all.",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Write to a file instead of stdout.",
    ),
) -> None:
    """Export current VERA configuration as YAML resource(s).

    Examples:

    \b
        vera config export
        vera config export --kind MiddlewareChain --kind Policy
        vera config export -o snapshot.yaml
    """
    require_session()

    from core.config_manager import ConfigManager
    mgr = ConfigManager()

    try:
        resources = mgr.export_all(list(kind) if kind else None)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    yaml_text = ConfigManager.to_yaml(resources)

    if output:
        output.write_text(yaml_text, encoding="utf-8")
        console.print(
            f"[green]✓[/green] Exported {len(resources)} resource(s) → [bold]{output}[/bold]"
        )
    else:
        console.print(Syntax(yaml_text, "yaml", theme="ansi_dark", line_numbers=False))


@app.command("apply")
def config_apply(
    file: Path = typer.Option(
        ..., "--file", "-f",
        help="YAML resource file to apply.",
        exists=True, readable=True, resolve_path=True,
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show what would change without writing anything.",
    ),
) -> None:
    """Apply a YAML configuration file to the running VERA instance.

    Idempotent: resources that are already in the desired state are skipped.

    Examples:

    \b
        vera config apply -f infra/middleware.yaml
        vera config apply -f infra/policy.yaml --dry-run
    """
    require_role("owner")

    from core.config_manager import ConfigManager
    mgr = ConfigManager()

    try:
        resources = mgr.load_file(file)
    except Exception as exc:
        console.print(f"[red]Failed to parse {file}:[/red] {exc}")
        raise typer.Exit(1)

    if not resources:
        console.print("[yellow]No resources found in file.[/yellow]")
        raise typer.Exit()

    if dry_run:
        console.print(Panel(f"[bold yellow]Dry run[/bold yellow] — {file}", expand=False))
        console.print()
        any_change = False
        for r in resources:
            diff_lines = mgr.diff(r)
            header = f"[cyan]{r.kind}[/cyan]/[green]{r.name}[/green]"
            if diff_lines:
                any_change = True
                console.print(f"  {header}  [yellow]would change[/yellow]")
                for line in diff_lines:
                    console.print(f"    {line}")
            else:
                console.print(f"  {header}  [dim]unchanged[/dim]")
        console.print()
        if not any_change:
            console.print("[dim]Nothing would change.[/dim]")
        return

    console.print(Panel(f"Applying [bold]{file}[/bold]", expand=False))
    console.print()

    all_ok = True
    for r in resources:
        try:
            result = mgr.apply(r)
        except Exception as exc:
            console.print(
                f"  [red]✗[/red]  [cyan]{r.kind}[/cyan]/[green]{r.name}[/green]  "
                f"[red]{exc}[/red]"
            )
            all_ok = False
            continue

        icon = "[green]✓[/green]" if result.changed else "[dim]–[/dim]"
        status_colour = {
            "created":   "green",
            "updated":   "yellow",
            "unchanged": "dim",
        }.get(result.status, "white")

        console.print(
            f"  {icon}  [cyan]{result.kind}[/cyan]/[green]{result.name}[/green]"
            f"  [{status_colour}]{result.status}[/{status_colour}]"
        )
        for change in result.changes:
            console.print(f"       [dim]{change}[/dim]")

    console.print()
    if all_ok:
        console.print("[green]Done.[/green]")
    else:
        console.print("[red]Completed with errors (see above).[/red]")
        raise typer.Exit(1)


@app.command("diff")
def config_diff(
    file: Path = typer.Option(
        ..., "--file", "-f",
        help="YAML resource file to compare against current state.",
        exists=True, readable=True, resolve_path=True,
    ),
) -> None:
    """Show what would change if a configuration file were applied.

    Examples:

    \b
        vera config diff -f infra/policy.yaml
    """
    require_session()

    from core.config_manager import ConfigManager
    mgr = ConfigManager()

    try:
        resources = mgr.load_file(file)
    except Exception as exc:
        console.print(f"[red]Failed to parse {file}:[/red] {exc}")
        raise typer.Exit(1)

    if not resources:
        console.print("[yellow]No resources found in file.[/yellow]")
        raise typer.Exit()

    console.print()
    any_change = False
    for r in resources:
        diff_lines = mgr.diff(r)
        header = f"[cyan]{r.kind}[/cyan]/[green]{r.name}[/green]"
        if diff_lines:
            any_change = True
            console.print(Panel(f"{header}  [yellow]will change[/yellow]", expand=False))
            for line in diff_lines:
                if line.strip().startswith("[+]"):
                    console.print(f"  [green]{line}[/green]")
                elif line.strip().startswith("[-]"):
                    console.print(f"  [red]{line}[/red]")
                else:
                    console.print(f"  [yellow]{line}[/yellow]")
        else:
            console.print(Panel(f"{header}  [dim]unchanged[/dim]", expand=False))
        console.print()

    if not any_change:
        console.print("[dim]No differences found.  Nothing would change.[/dim]")


@app.command("validate")
def config_validate(
    file: Path = typer.Option(
        ..., "--file", "-f",
        help="YAML resource file to validate.",
        exists=True, readable=True, resolve_path=True,
    ),
) -> None:
    """Validate the structure of a YAML configuration file without applying it.

    Examples:

    \b
        vera config validate -f infra/middleware.yaml
    """
    require_session()

    from core.config_manager import ConfigManager

    try:
        resources = ConfigManager.from_yaml(file.read_text(encoding="utf-8"))
    except Exception as exc:
        console.print(f"[red]✗  Invalid YAML or schema error:[/red] {exc}")
        raise typer.Exit(1)

    if not resources:
        console.print("[yellow]No resources found in file.[/yellow]")
        raise typer.Exit()

    console.print()
    for r in resources:
        console.print(
            f"  [green]✓[/green]  [cyan]{r.kind}[/cyan]/[green]{r.name}[/green]"
        )
    console.print()
    console.print(f"[green]{len(resources)} resource(s) valid.[/green]")
    console.print()
