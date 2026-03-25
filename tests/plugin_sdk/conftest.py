import pytest
from pathlib import Path

def pytest_addoption(parser):
    parser.addoption("--plugin", action="store", default="plugins/_template",
                     help="Path to plugin directory to verify")

@pytest.fixture
def plugin_path(request) -> Path:
    plugin = request.config.getoption("--plugin", default="plugins/_template")
    return Path(plugin)
