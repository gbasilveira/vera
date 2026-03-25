"""vera memory — Memory/RAG store and retrieval via the memory_rag plugin."""
import asyncio
import uuid
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from interfaces.cli._session import get_identity

app = typer.Typer(help="Store and retrieve memories (requires memory_rag plugin)", no_args_is_help=True)
console = Console()


async def _make_deps(user_id: str, user_role: str):
    from core.setup import setup_kernel
    kernel, bus, vfs, secrets, security, tracer, factory = await setup_kernel()
    deps = factory.create(user_id=user_id, user_role=user_role, session_id=str(uuid.uuid4()))
    return deps, vfs


@app.command("store")
def memory_store(
    content: str = typer.Argument(..., help="Text content to store"),
    namespace: str = typer.Option("default", "--namespace", "-n"),
) -> None:
    """Store a memory chunk via the memory_rag plugin."""
    user_id, user_role = get_identity()
    asyncio.run(_store(content, namespace, user_id, user_role))


async def _store(content: str, namespace: str, user_id: str, user_role: str) -> None:
    deps, vfs = await _make_deps(user_id, user_role)
    try:
        result = await deps.run_tool("memory.store", content=content, namespace=namespace)
        console.print(f"[green]✓[/green] Stored. chunk_id=[bold]{result}[/bold]")
    except Exception as e:
        console.print(f"[red]{type(e).__name__}:[/red] {e}")
        raise typer.Exit(1)
    finally:
        await vfs.close()


@app.command("retrieve")
def memory_retrieve(
    query: str = typer.Argument(..., help="Search query"),
    namespace: str = typer.Option("default", "--namespace", "-n"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
) -> None:
    """Retrieve relevant memory chunks for a query."""
    user_id, user_role = get_identity()
    asyncio.run(_retrieve(query, namespace, top_k, user_id, user_role))


async def _retrieve(query: str, namespace: str, top_k: int, user_id: str, user_role: str) -> None:
    deps, vfs = await _make_deps(user_id, user_role)
    try:
        results = await deps.run_tool("memory.retrieve", query=query, namespace=namespace, top_k=top_k)
        if not results:
            console.print("[yellow]No results.[/yellow]")
            return
        table = Table(show_header=True, header_style="bold")
        table.add_column("Score", justify="right")
        table.add_column("Chunk ID", style="dim")
        table.add_column("Content")
        for r in results:
            chunk_id = r.get("chunk_id", "?")
            table.add_row(
                f"{r.get('score', 0):.3f}",
                chunk_id[:16] + "…" if len(chunk_id) > 16 else chunk_id,
                r.get("content", "")[:100],
            )
        console.print(table)
    except Exception as e:
        console.print(f"[red]{type(e).__name__}:[/red] {e}")
        raise typer.Exit(1)
    finally:
        await vfs.close()


@app.command("forget")
def memory_forget(
    chunk_ids: Optional[List[str]] = typer.Argument(None, help="Chunk IDs to delete"),
    namespace: Optional[str] = typer.Option(None, "--namespace", "-n", help="Wipe entire namespace"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Forget specific chunks or an entire namespace."""
    if not chunk_ids and not namespace:
        console.print("[red]Provide chunk IDs or --namespace.[/red]")
        raise typer.Exit(1)
    if namespace and not yes:
        typer.confirm(f"Delete all memories in namespace '{namespace}'?", abort=True)
    user_id, user_role = get_identity()
    asyncio.run(_forget(chunk_ids, namespace, user_id, user_role))


async def _forget(chunk_ids, namespace, user_id: str, user_role: str) -> None:
    deps, vfs = await _make_deps(user_id, user_role)
    try:
        kwargs: dict = {}
        if chunk_ids:
            kwargs["chunk_ids"] = chunk_ids
        if namespace:
            kwargs["namespace"] = namespace
        await deps.run_tool("memory.forget", **kwargs)
        console.print("[green]✓[/green] Memory deleted.")
    except Exception as e:
        console.print(f"[red]{type(e).__name__}:[/red] {e}")
        raise typer.Exit(1)
    finally:
        await vfs.close()
