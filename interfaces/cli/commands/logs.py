"""vera logs — Audit and cost log viewing."""
import asyncio
import json as _json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from interfaces.cli._session import require_session

app = typer.Typer(help="View audit and cost logs", no_args_is_help=True)
console = Console()

_AUDIT_PATH = Path("data/logs/audit.jsonl")


@app.command("audit")
def logs_audit(
    tail: int = typer.Option(50, "--tail", "-n", help="Show last N entries"),
    tool_filter: Optional[str] = typer.Option(None, "--tool", help="Filter by tool name prefix"),
    status_filter: Optional[str] = typer.Option(None, "--status", help="success | failure"),
    since: Optional[str] = typer.Option(None, "--since", help="e.g. 1h, 30m, 7d"),
) -> None:
    """Show recent audit log entries from data/logs/audit.jsonl."""
    require_session()

    if not _AUDIT_PATH.exists():
        console.print("[yellow]No audit log at data/logs/audit.jsonl[/yellow]")
        return

    since_dt: Optional[datetime] = None
    if since:
        try:
            unit = since[-1]
            val = float(since[:-1])
            since_dt = datetime.now(timezone.utc) - {
                "h": timedelta(hours=val),
                "m": timedelta(minutes=val),
                "d": timedelta(days=val),
            }[unit]
        except (KeyError, ValueError):
            console.print(f"[red]Invalid --since '{since}'. Use e.g. 1h, 30m, 7d.[/red]")
            raise typer.Exit(1)

    entries = []
    with open(_AUDIT_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(_json.loads(line))
            except Exception:
                continue

    if since_dt:
        entries = [e for e in entries if _parse_ts(e.get("timestamp", "")) >= since_dt]
    if tool_filter:
        entries = [e for e in entries if e.get("tool_name", "").startswith(tool_filter)]
    if status_filter:
        entries = [e for e in entries if e.get("status") == status_filter]

    entries = entries[-tail:]

    table = Table(
        title=f"Audit Log  ({len(entries)} entries)",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Timestamp", style="dim")
    table.add_column("Tool", style="cyan")
    table.add_column("User")
    table.add_column("Role", style="dim")
    table.add_column("Status")
    table.add_column("ms", justify="right")
    table.add_column("Error", style="red")

    for e in entries:
        status = e.get("status", "?")
        status_str = "[green]ok[/green]" if status == "success" else "[red]fail[/red]"
        table.add_row(
            e.get("timestamp", "")[:19],
            e.get("tool_name", "?"),
            e.get("user_id", "?"),
            e.get("user_role", "?"),
            status_str,
            str(e.get("duration_ms", "?")),
            e.get("error", "") or "",
        )

    console.print(table)


def _parse_ts(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


@app.command("cost")
def logs_cost(
    date: Optional[str] = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)"),
) -> None:
    """Show cost and token usage aggregated from VFS."""
    require_session()
    asyncio.run(_cost_async(date))


async def _cost_async(date: Optional[str]) -> None:
    from core.vfs import create_vfs
    target = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    vfs = create_vfs()
    try:
        all_keys = await vfs.list_keys("cost:")
        day_keys = [k for k in all_keys if f":{target}:" in k]

        if not day_keys:
            console.print(f"[yellow]No cost records for {target}.[/yellow]")
            return

        table = Table(title=f"Cost Summary — {target}", show_header=True, header_style="bold")
        table.add_column("Agent")
        table.add_column("Tool", style="cyan")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Cost USD", justify="right", style="green")

        total_calls = total_tokens = 0
        total_cost = 0.0

        for key in sorted(day_keys):
            raw = await vfs.get(key)
            if not raw:
                continue
            try:
                record = _json.loads(raw)
                parts = key.split(":")   # cost:{agent}:{date}:{tool}
                agent = parts[1] if len(parts) > 1 else "?"
                tool  = parts[3] if len(parts) > 3 else "?"
                calls  = record.get("calls", 0)
                tokens = record.get("total_tokens", 0)
                cost   = record.get("total_cost_usd", 0.0)
                total_calls  += calls
                total_tokens += tokens
                total_cost   += cost
                table.add_row(agent, tool, str(calls), f"{tokens:,}", f"${cost:.4f}")
            except Exception:
                continue

        console.print(table)
        console.print(
            f"\n[bold]Total:[/bold] {total_calls} calls  "
            f"{total_tokens:,} tokens  [green]${total_cost:.4f}[/green]"
        )
    finally:
        await vfs.close()
