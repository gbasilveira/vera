"""
vera docs — interactive documentation browser.

Commands
--------
vera docs              Interactive tree browser (default)
vera docs list         Flat list, optionally filtered by source
vera docs show <path>  Render a single doc with Rich Markdown
vera docs search <q>   Search title / tags / description / path
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

app = typer.Typer(
    name="docs",
    help="Browse VERA documentation.",
    rich_markup_mode="rich",
    invoke_without_command=True,
)
console = Console()

# ── Source label helpers ─────────────────────────────────────────────────────

_SOURCE_ICONS: dict[str, str] = {
    ".":                "📚",
    "core":             "⚙️ ",
    "core/middleware":  "🔗",
    "core/auth":        "🔑",
    "core/vfs":         "🗄️ ",
    "interfaces/cli":   "💻",
}

_PLUGIN_ICON = "🔌"
_DEFAULT_ICON = "📄"


def _icon(source: str) -> str:
    if source in _SOURCE_ICONS:
        return _SOURCE_ICONS[source]
    if source.startswith("plugins/"):
        return _PLUGIN_ICON
    return _DEFAULT_ICON


def _source_label(source: str) -> str:
    if source == ".":
        return "Project"
    return source.replace("/", " › ").replace("_", " ").title()


# ── Shared manager factory ───────────────────────────────────────────────────

def _get_manager():
    from core.docs import DocsManager
    mgr = DocsManager()
    mgr.load()
    return mgr


# ── Interactive browser ──────────────────────────────────────────────────────

@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Browse all VERA docs interactively.  Use sub-commands for direct access."""
    if ctx.invoked_subcommand is None:
        _browse()


def _browse() -> None:
    """Full-screen interactive tree navigator."""
    mgr = _get_manager()
    tree_data = mgr.get_tree()

    if not tree_data:
        console.print("[yellow]No documentation found.[/yellow]")
        console.print(
            "Add [bold].md[/bold] files inside any [bold]docs/[/bold] "
            "subdirectory in the project."
        )
        raise typer.Exit()

    while True:
        console.clear()
        _print_tree(tree_data)

        # Build an index: number → DocEntry
        index: dict[str, object] = {}
        n = 1
        for source in sorted(tree_data.keys(), key=_source_sort_key):
            for entry in tree_data[source]:
                index[str(n)] = entry
                n += 1

        console.print()
        choice = Prompt.ask(
            "[bold]Enter number to open, [cyan]s[/cyan] to search, "
            "[cyan]q[/cyan] to quit[/bold]",
            default="q",
        )

        if choice.lower() == "q":
            break
        if choice.lower() == "s":
            query = Prompt.ask("[bold]Search query[/bold]")
            _show_search_results(mgr, query)
            Prompt.ask("[dim]Press Enter to return[/dim]", default="")
            continue

        entry = index.get(choice)
        if entry is None:
            console.print(f"[red]No doc numbered {choice!r}.[/red]")
            Prompt.ask("[dim]Press Enter to continue[/dim]", default="")
            continue

        _render_entry(entry)  # type: ignore[arg-type]
        Prompt.ask("[dim]Press Enter to return to the tree[/dim]", default="")


def _source_sort_key(source: str) -> tuple[int, str]:
    """Root docs first, then core, then plugins, then interfaces, then rest."""
    order = {"." : 0, "core": 1}
    for k, v in order.items():
        if source == k:
            return (v, source)
    if source.startswith("core/"):
        return (2, source)
    if source.startswith("plugins/"):
        return (4, source)
    if source.startswith("interfaces/"):
        return (5, source)
    return (3, source)


def _print_tree(tree_data: dict) -> None:
    console.print()
    root_tree = Tree(
        Text.assemble(
            ("VERA ", "bold cyan"),
            ("Documentation", "bold"),
        )
    )

    n = 1
    for source in sorted(tree_data.keys(), key=_source_sort_key):
        entries = tree_data[source]
        icon = _icon(source)
        branch = root_tree.add(
            Text.assemble(
                (f"{icon} ", ""),
                (_source_label(source), "bold yellow"),
                (f"  [{len(entries)}]", "dim"),
            )
        )
        for entry in entries:
            tags_str = ("  " + " ".join(f"[dim cyan]{t}[/dim cyan]" for t in entry.tags[:3])) if entry.tags else ""
            branch.add(
                Text.assemble(
                    (f"  {n:>3}. ", "dim"),
                    (entry.title, "green"),
                    (f"  {entry.description}" if entry.description else "", "dim"),
                )
            )
            n += 1

    console.print(root_tree)


# ── Subcommands ──────────────────────────────────────────────────────────────

@app.command("list")
def list_docs(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter by source namespace"),
) -> None:
    """List all discovered documentation files."""
    mgr = _get_manager()

    entries = mgr.list_by_source(source) if source else mgr.list_all()

    if not entries:
        msg = f"No docs found for source [bold]{source}[/bold]." if source else "No docs found."
        console.print(f"[yellow]{msg}[/yellow]")
        raise typer.Exit()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Path", style="green")
    table.add_column("Title")
    table.add_column("Source", style="dim yellow")
    table.add_column("Tags", style="dim cyan")

    for e in entries:
        table.add_row(
            e.slug,
            e.title,
            _source_label(e.source),
            ", ".join(e.tags),
        )

    console.print()
    console.print(table)
    console.print()
    console.print(f"[dim]{len(entries)} document(s)[/dim]")
    console.print()


@app.command("show")
def show_doc(
    path: str = typer.Argument(..., help="Doc path e.g. core/kernel or plugins/_template/authoring"),
) -> None:
    """Render a documentation file."""
    mgr = _get_manager()
    entry = mgr.get(path)
    if entry is None:
        console.print(f"[red]Doc not found:[/red] {path!r}")
        console.print("[dim]Run [bold]vera docs list[/bold] to see available paths.[/dim]")
        raise typer.Exit(1)
    _render_entry(entry)


@app.command("search")
def search_docs(
    query: str = typer.Argument(..., help="Search term"),
) -> None:
    """Search documentation by title, tags, description, or path."""
    mgr = _get_manager()
    _show_search_results(mgr, query)


# ── Rendering helpers ────────────────────────────────────────────────────────

def _render_entry(entry) -> None:  # entry: DocEntry
    console.print()
    # Header panel
    meta_parts = []
    if entry.description:
        meta_parts.append(f"[dim]{entry.description}[/dim]")
    if entry.tags:
        meta_parts.append("  ".join(f"[cyan]{t}[/cyan]" for t in entry.tags))
    meta_parts.append(f"[dim]Source:[/dim] [yellow]{_source_label(entry.source)}[/yellow]")
    meta_parts.append(f"[dim]Path:[/dim]   [green]{entry.slug}[/green]")

    console.print(Panel(
        "\n".join(meta_parts),
        title=f"[bold]{entry.title}[/bold]",
        expand=True,
    ))
    console.print()

    body = entry.read_body().strip()
    if body:
        # Strip the H1 if it duplicates the title we already showed
        lines = body.splitlines()
        if lines and lines[0].startswith("# "):
            body = "\n".join(lines[1:]).lstrip("\n")
        console.print(Markdown(body))
    else:
        console.print("[dim](empty document)[/dim]")

    console.print()


def _show_search_results(mgr, query: str) -> None:
    results = mgr.search(query)
    console.print()
    if not results:
        console.print(f"[yellow]No results for[/yellow] [bold]{query!r}[/bold]")
        return

    console.print(
        Panel(
            f"[bold]{len(results)}[/bold] result(s) for [bold cyan]{query!r}[/bold cyan]",
            expand=False,
        )
    )
    console.print()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Path", style="green")
    table.add_column("Title")
    table.add_column("Source", style="dim yellow")
    table.add_column("Description", style="dim")

    for e in results:
        table.add_row(
            e.slug,
            e.title,
            _source_label(e.source),
            e.description,
        )

    console.print(table)
    console.print()
    console.print(f"[dim]Run [bold]vera docs show <path>[/bold] to read any entry.[/dim]")
    console.print()
