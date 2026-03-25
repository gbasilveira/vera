"""Unit tests for the template plugin."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from plugins._template.schemas import DoThingInput, DoThingOutput
from plugins._template.tools import do_thing


@pytest.mark.asyncio
async def test_do_thing_returns_output():
    deps = MagicMock()
    deps.run_tool = AsyncMock()
    result = await do_thing(deps, DoThingInput(value="hello"))
    assert isinstance(result, DoThingOutput)
    assert "hello" in result.result


@pytest.mark.asyncio
async def test_do_thing_output_is_pydantic():
    from pydantic import BaseModel
    deps = MagicMock()
    result = await do_thing(deps, DoThingInput(value="test"))
    assert isinstance(result, BaseModel)