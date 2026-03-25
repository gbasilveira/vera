"""
Plugin SDK contract tests.

Run against any plugin directory to verify it meets the VERA plugin spec:
  pytest tests/plugin_sdk/ --plugin=plugins/gmail_driver

These tests are the gate for `vera plugin verify`.
"""
import ast
import importlib
import inspect
import sys
from pathlib import Path

import pytest
import yaml





@pytest.fixture
def manifest(plugin_path):
    manifest_file = plugin_path / "manifest.yaml"
    assert manifest_file.exists(), f"No manifest.yaml found in {plugin_path}"
    with open(manifest_file) as f:
        return yaml.safe_load(f)


class TestManifestStructure:
    def test_required_fields_present(self, manifest):
        for field in ("name", "version", "external", "core", "tools"):
            assert field in manifest, f"Missing required manifest field: {field}"

    def test_name_is_snake_case(self, manifest):
        name = manifest["name"]
        assert name == name.lower().replace("-", "_"), f"Plugin name must be snake_case: {name}"

    def test_tools_is_list(self, manifest):
        assert isinstance(manifest["tools"], list)

    def test_tool_names_follow_convention(self, manifest):
        for tool in manifest["tools"]:
            assert "." in tool, f"Tool name must follow 'plugin.action' pattern: {tool}"

    def test_external_is_bool(self, manifest):
        assert isinstance(manifest["external"], bool)

    def test_version_is_semver(self, manifest):
        parts = manifest["version"].split(".")
        assert len(parts) == 3, f"Version must be semver (x.y.z): {manifest['version']}"
        for part in parts:
            assert part.isdigit()


class TestPluginClass:
    def test_plugin_py_exists(self, plugin_path):
        assert (plugin_path / "plugin.py").exists()

    def test_schemas_py_exists(self, plugin_path):
        assert (plugin_path / "schemas.py").exists()

    def test_tools_py_exists(self, plugin_path):
        assert (plugin_path / "tools.py").exists()

    def test_plugin_class_is_vera_plugin(self, plugin_path):
        from core.kernel import VeraPlugin
        sys.path.insert(0, str(plugin_path.parent.parent))
        module_name = f"{plugin_path.parent.name}.{plugin_path.name}.plugin"
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            pytest.skip(f"Cannot import plugin (dependencies may be missing): {e}")
        plugin_classes = [
            obj for name, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, VeraPlugin) and obj is not VeraPlugin
        ]
        assert len(plugin_classes) >= 1, "No VeraPlugin subclass found in plugin.py"

    def test_plugin_has_name_attr(self, plugin_path):
        sys.path.insert(0, str(plugin_path.parent.parent))
        module_name = f"{plugin_path.parent.name}.{plugin_path.name}.plugin"
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            pytest.skip("Cannot import plugin")
        from core.kernel import VeraPlugin
        plugin_classes = [
            obj for name, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, VeraPlugin) and obj is not VeraPlugin
        ]
        for cls in plugin_classes:
            assert hasattr(cls, "name"), f"{cls.__name__} missing 'name' class attribute"
            assert hasattr(cls, "version"), f"{cls.__name__} missing 'version' class attribute"


class TestToolCodeStandards:
    """AST-based checks matching vera lint rules."""

    def _load_tools_ast(self, plugin_path: Path) -> ast.Module:
        tools_file = plugin_path / "tools.py"
        if not tools_file.exists():
            pytest.skip("No tools.py")
        return ast.parse(tools_file.read_text())

    def test_all_tool_functions_are_async(self, plugin_path):
        tree = self._load_tools_ast(plugin_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                pytest.fail(f"Synchronous tool function found: {node.name} (must be async def)")

    def test_no_direct_llm_sdk_imports(self, plugin_path):
        tree = self._load_tools_ast(plugin_path)
        forbidden = {"openai", "anthropic", "ollama"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden, \
                        f"Direct LLM SDK import forbidden in tools.py: {alias.name}"
            if isinstance(node, ast.ImportFrom):
                if node.module and any(node.module.startswith(f) for f in forbidden):
                    pytest.fail(f"Direct LLM SDK import forbidden in tools.py: {node.module}")

    def test_no_os_environ_access(self, plugin_path):
        tree = self._load_tools_ast(plugin_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if (isinstance(node.value, ast.Attribute) and
                        node.value.attr == "environ" and
                        isinstance(node.value.value, ast.Name) and
                        node.value.value.id == "os"):
                    pytest.fail("Direct os.environ access forbidden in tools.py — use deps.secrets.get()")