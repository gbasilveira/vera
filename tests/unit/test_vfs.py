"""Tests for LocalFS VFS implementation."""
import asyncio
import time
import pytest
from core.vfs.local_fs import LocalFS


import pytest_asyncio

@pytest_asyncio.fixture
async def vfs(tmp_path):
    db = str(tmp_path / "test_vfs.db")
    fs = LocalFS(db_path=db)
    yield fs
    await fs.close()


@pytest.mark.asyncio
async def test_set_and_get(vfs):
    await vfs.set("k1", b"hello")
    assert await vfs.get("k1") == b"hello"


@pytest.mark.asyncio
async def test_get_missing_returns_none(vfs):
    assert await vfs.get("nonexistent") is None


@pytest.mark.asyncio
async def test_delete(vfs):
    await vfs.set("k2", b"data")
    await vfs.delete("k2")
    assert await vfs.get("k2") is None


@pytest.mark.asyncio
async def test_delete_nonexistent_is_noop(vfs):
    await vfs.delete("ghost")  # Should not raise


@pytest.mark.asyncio
async def test_list_keys_by_prefix(vfs):
    await vfs.set("pii:a", b"1")
    await vfs.set("pii:b", b"2")
    await vfs.set("cost:x", b"3")
    keys = await vfs.list_keys("pii:")
    assert set(keys) == {"pii:a", "pii:b"}


@pytest.mark.asyncio
async def test_list_keys_empty_prefix_returns_all(vfs):
    await vfs.set("a", b"1")
    await vfs.set("b", b"2")
    keys = await vfs.list_keys("")
    assert "a" in keys
    assert "b" in keys


@pytest.mark.asyncio
async def test_ttl_expiry(vfs):
    await vfs.set("expiring", b"value", ttl=1)
    assert await vfs.get("expiring") == b"value"
    await asyncio.sleep(1.1)
    assert await vfs.get("expiring") is None


@pytest.mark.asyncio
async def test_ttl_not_expired(vfs):
    await vfs.set("not_expired", b"value", ttl=60)
    assert await vfs.get("not_expired") == b"value"


@pytest.mark.asyncio
async def test_list_keys_excludes_expired(vfs):
    await vfs.set("exp:a", b"1", ttl=1)
    await vfs.set("exp:b", b"2", ttl=60)
    await asyncio.sleep(1.1)
    keys = await vfs.list_keys("exp:")
    assert "exp:a" not in keys
    assert "exp:b" in keys


@pytest.mark.asyncio
async def test_overwrite(vfs):
    await vfs.set("k", b"old")
    await vfs.set("k", b"new")
    assert await vfs.get("k") == b"new"


@pytest.mark.asyncio
async def test_binary_values(vfs):
    data = bytes(range(256))
    await vfs.set("binary", data)
    assert await vfs.get("binary") == data
