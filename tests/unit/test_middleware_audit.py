"""Tests for AuditLoggerMiddleware."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.middleware.auditor import AuditLoggerMiddleware
from core.middleware.base import ToolCallContext


def make_ctx():
    return ToolCallContext(
        call_id="audit-c1", tool_name="gmail.check_inbox", plugin_name="gmail_driver",
        agent_id="agent1", user_role="manager", user_id="user@test.com", tenant_id="default",
        payload={}, is_external=True, vfs=MagicMock(),
        secrets=MagicMock(), enforcer=MagicMock(), bus=MagicMock(),
    )


@pytest.fixture
def auditor(tmp_path):
    log_file = str(tmp_path / "audit.jsonl")
    return AuditLoggerMiddleware(log_path=log_file), log_file


@pytest.mark.asyncio
async def test_success_writes_log(auditor):
    mw, log_file = auditor
    ctx = make_ctx()
    await mw.before_call(ctx)
    await mw.after_call(ctx, {"emails": []})
    lines = Path(log_file).read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["status"] == "success"
    assert record["tool_name"] == "gmail.check_inbox"
    assert record["user_role"] == "manager"
    assert "duration_ms" in record


@pytest.mark.asyncio
async def test_failure_writes_error_log(auditor):
    mw, log_file = auditor
    ctx = make_ctx()
    await mw.before_call(ctx)
    await mw.on_error(ctx, ValueError("something broke"))
    lines = Path(log_file).read_text().strip().split("\n")
    record = json.loads(lines[0])
    assert record["status"] == "failure"
    assert record["error_type"] == "ValueError"
    assert "something broke" in record["error"]


@pytest.mark.asyncio
async def test_no_payload_in_log(auditor):
    """Audit log must NOT contain payload values (PII safety)."""
    mw, log_file = auditor
    ctx = make_ctx()
    await mw.before_call(ctx)
    await mw.after_call(ctx, {"result": "sensitive_data"})
    record = json.loads(Path(log_file).read_text().strip())
    assert "payload" not in record
    assert "result" not in record


@pytest.mark.asyncio
async def test_missing_log_dir_created_automatically(tmp_path):
    nested = str(tmp_path / "nested" / "dir" / "audit.jsonl")
    mw = AuditLoggerMiddleware(log_path=nested)
    ctx = make_ctx()
    await mw.before_call(ctx)
    await mw.after_call(ctx, "ok")
    assert Path(nested).exists()
