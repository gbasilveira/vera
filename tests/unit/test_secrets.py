"""Tests for SecretsManager (sqlite backend — no OS keyring required in CI)."""
import os
import pytest
from core.secrets import SecretsManager
from core.middleware.base import SecretNotFound


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    """Use sqlite backend with a temp master key for tests."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("VERA_MASTER_KEY", key)
    sm = SecretsManager(backend="sqlite")
    sm._sqlite_path = str(tmp_path / "test_secrets.db")
    return sm


@pytest.mark.asyncio
async def test_set_and_get(secrets):
    await secrets.set("gmail.oauth_token", "tok_abc123")
    result = await secrets.get("gmail.oauth_token")
    assert result == "tok_abc123"


@pytest.mark.asyncio
async def test_get_missing_raises(secrets):
    with pytest.raises(SecretNotFound):
        await secrets.get("nonexistent.key")


@pytest.mark.asyncio
async def test_get_optional_missing_returns_none(secrets):
    result = await secrets.get_optional("missing.key")
    assert result is None


@pytest.mark.asyncio
async def test_delete(secrets):
    await secrets.set("temp.key", "value")
    await secrets.delete("temp.key")
    with pytest.raises(SecretNotFound):
        await secrets.get("temp.key")


@pytest.mark.asyncio
async def test_delete_nonexistent_is_noop(secrets):
    await secrets.delete("ghost.key")  # Should not raise


@pytest.mark.asyncio
async def test_list_keys(secrets):
    await secrets.set("gmail.token", "a")
    await secrets.set("gmail.client_id", "b")
    await secrets.set("openai.api_key", "c")
    keys = await secrets.list_keys("gmail.")
    assert "gmail.token" in keys
    assert "gmail.client_id" in keys
    assert "openai.api_key" not in keys


@pytest.mark.asyncio
async def test_values_are_encrypted_at_rest(secrets, tmp_path):
    """Verify the raw SQLite file does not contain plaintext secrets."""
    await secrets.set("sensitive.key", "supersecretpassword")
    raw = (tmp_path / "test_secrets.db").read_bytes()
    assert b"supersecretpassword" not in raw


@pytest.mark.asyncio
async def test_overwrite(secrets):
    await secrets.set("k", "old_value")
    await secrets.set("k", "new_value")
    assert await secrets.get("k") == "new_value"
