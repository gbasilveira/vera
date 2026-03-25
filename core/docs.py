"""
VERA Docs Manager — discover, index, and read documentation files.

Documentation is **decentralised**: every subsystem (core, middleware, each
plugin, each interface) can carry its own ``docs/`` directory.  The manager
walks the project tree, finds every ``docs/`` folder, and aggregates all
``.md`` files into a single searchable index.

Typical project layout::

    vera/
    ├── docs/                        ← project-level docs
    ├── core/
    │   ├── docs/                    ← core service docs
    │   └── middleware/
    │       └── docs/                ← middleware docs
    ├── plugins/
    │   ├── llm_driver/
    │   │   └── docs/                ← plugin-specific docs
    │   └── memory_rag/
    │       └── docs/
    └── interfaces/
        └── cli/
            └── docs/                ← CLI docs

Each ``.md`` file may include optional YAML front-matter::

    ---
    title: "VeraKernel"
    description: "Plugin loader, tool registry, and execution engine."
    tags: [kernel, plugins, tools]
    ---

Without front-matter the title defaults to the file stem (Title-cased) and
all other fields are inferred from the directory path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Frontmatter parser (zero extra deps) ───────────────────────────────────

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return ``(meta dict, body)`` from a Markdown string."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text

    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
        else:
            meta[key] = val.strip("\"'")

    return meta, text[m.end():]


# ── DocEntry ────────────────────────────────────────────────────────────────

@dataclass
class DocEntry:
    """A single documentation file discovered anywhere in the project."""

    # Path of the file relative to its owning ``docs/`` directory.
    # e.g. ``"kernel.md"`` or ``"auth/providers.md"``
    rel_path: str

    # Absolute filesystem path.
    abs_path: Path

    # Human-readable title (from front-matter or derived from file stem).
    title: str

    # The source namespace: the path of the parent of the ``docs/`` dir,
    # relative to the project root.  Examples:
    #   "."                → project-level docs/
    #   "core"             → core/docs/
    #   "core/middleware"  → core/middleware/docs/
    #   "plugins/llm_driver" → plugins/llm_driver/docs/
    source: str

    description: str = ""
    tags: list[str] = field(default_factory=list)

    # ── Convenience ─────────────────────────────────────────────────────────

    @property
    def full_path(self) -> str:
        """Unique human-readable path: ``<source>/<rel_path>``."""
        if self.source == ".":
            return self.rel_path
        return f"{self.source}/{self.rel_path}"

    @property
    def slug(self) -> str:
        """``full_path`` without the ``.md`` extension."""
        return self.full_path.removesuffix(".md")

    def read_body(self) -> str:
        """Markdown body with front-matter stripped."""
        raw = self.abs_path.read_text(encoding="utf-8")
        _, body = _parse_frontmatter(raw)
        return body

    def read_raw(self) -> str:
        """Full raw Markdown including front-matter."""
        return self.abs_path.read_text(encoding="utf-8")


# ── DocsManager ─────────────────────────────────────────────────────────────

#: Directory names that are never walked into during discovery.
_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache"}


class DocsManager:
    """Discover and query VERA documentation files across the whole project.

    Parameters
    ----------
    project_root:
        Root of the VERA project.  All ``docs/`` subdirectories found under
        this root are indexed.  Defaults to the directory containing this
        file's package (i.e. the project root).
    """

    def __init__(self, project_root: Optional[Path] = None) -> None:
        if project_root is None:
            # core/docs.py  →  parent = core/  →  parent = project root
            project_root = Path(__file__).parent.parent
        self._root = Path(project_root).resolve()
        self._entries: list[DocEntry] = []
        self._loaded = False

    # ── Discovery ───────────────────────────────────────────────────────────

    def load(self) -> None:
        """Walk the project tree, find every ``docs/`` dir, and index its files."""
        self._entries = []

        for docs_dir in self._find_docs_dirs(self._root):
            # source = path of docs_dir's *parent* relative to project root
            parent = docs_dir.parent
            try:
                source = parent.relative_to(self._root).as_posix()
            except ValueError:
                source = parent.as_posix()
            if source == "":
                source = "."

            for md_file in sorted(docs_dir.rglob("*.md")):
                rel = md_file.relative_to(docs_dir).as_posix()
                raw = md_file.read_text(encoding="utf-8")
                meta, _ = _parse_frontmatter(raw)

                default_title = Path(rel).stem.replace("_", " ").replace("-", " ").title()
                tags = meta.get("tags", [])
                if not isinstance(tags, list):
                    tags = []

                entry = DocEntry(
                    rel_path=rel,
                    abs_path=md_file,
                    title=meta.get("title", default_title),
                    source=source,
                    description=meta.get("description", ""),
                    tags=tags,
                )
                self._entries.append(entry)

        self._loaded = True

    @staticmethod
    def _find_docs_dirs(root: Path) -> list[Path]:
        """Return all directories named ``docs`` under *root*, depth-first."""
        found: list[Path] = []
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                children = sorted(current.iterdir())
            except PermissionError:
                continue
            for child in children:
                if not child.is_dir():
                    continue
                if child.name in _SKIP_DIRS:
                    continue
                if child.name == "docs":
                    found.append(child)
                    # Don't recurse into docs/ itself — files inside are docs,
                    # not containers for further docs/ dirs.
                else:
                    stack.append(child)
        return found

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # ── Queries ─────────────────────────────────────────────────────────────

    def list_all(self) -> list[DocEntry]:
        """Return every discovered doc entry."""
        self._ensure_loaded()
        return list(self._entries)

    def list_sources(self) -> list[str]:
        """Return unique source namespaces in stable discovery order."""
        self._ensure_loaded()
        seen: list[str] = []
        for e in self._entries:
            if e.source not in seen:
                seen.append(e.source)
        return seen

    def list_by_source(self, source: str) -> list[DocEntry]:
        """Return all entries belonging to *source*."""
        self._ensure_loaded()
        return [e for e in self._entries if e.source == source]

    def get(self, path: str) -> Optional[DocEntry]:
        """Look up a doc by its ``full_path`` (with or without ``.md``)."""
        self._ensure_loaded()
        normalized = path if path.endswith(".md") else path + ".md"
        # Match against full_path
        for e in self._entries:
            if e.full_path == normalized:
                return e
        # Fallback: match rel_path only (for bare filenames)
        for e in self._entries:
            if e.rel_path == normalized:
                return e
        return None

    def search(self, query: str) -> list[DocEntry]:
        """Return entries whose title, tags, description, or path contain *query*."""
        self._ensure_loaded()
        q = query.lower()
        results: list[DocEntry] = []
        for e in self._entries:
            haystack = " ".join([
                e.title,
                e.description,
                e.full_path,
                " ".join(e.tags),
            ]).lower()
            if q in haystack:
                results.append(e)
        return results

    # ── Tree ────────────────────────────────────────────────────────────────

    def get_tree(self) -> dict[str, list[DocEntry]]:
        """Return docs grouped by source namespace.

        Example::

            {
              ".":                   [DocEntry(index.md), ...],
              "core":                [DocEntry(kernel.md), ...],
              "core/middleware":     [DocEntry(overview.md), ...],
              "plugins/llm_driver":  [DocEntry(usage.md), ...],
            }
        """
        self._ensure_loaded()
        tree: dict[str, list[DocEntry]] = {}
        for e in self._entries:
            tree.setdefault(e.source, []).append(e)
        return tree
