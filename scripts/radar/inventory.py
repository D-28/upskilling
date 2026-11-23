"""Deterministic REPO_INVENTORY generator for repo-aware delta filtering.

Summarizes headings, core takeaways, and tracked landscape items across
`playbooks/`, `templates/`, `skills/`, `hooks/`, and `todo.md` into a compact,
stable prefix for Stage 1 triage (~1.5K-2.5K tokens) so we stay inside the
Smart Zone (playbooks/model-effort-economics.md).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import Path

INVENTORY_GLOBS: tuple[str, ...] = (
    "playbooks/*.md",
    "templates/*",
    "skills/*/SKILL.md",
    "hooks/*.md",
)

FULL_REPO_BASELINE_GLOBS: tuple[str, ...] = (
    "playbooks/*.md",
    "skills/*/SKILL.md",
    "templates/*",
    "docs/GLOSSARY.md",
    "docs/adr/*.md",
)

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_QUOTE_RE = re.compile(r"^>\s*(.+?)\s*$")


def list_repo_knowledge_files(
    repo_root: Path,
    exclude_files: Collection[str] = (),
) -> list[Path]:
    """Return sorted repository knowledge files, optionally excluding relative paths."""
    excluded = {p.strip("/") for p in exclude_files}
    found: list[Path] = []
    for pattern in INVENTORY_GLOBS:
        for path in sorted(repo_root.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root).as_posix()
            if rel in excluded:
                continue
            found.append(path)
    return found


def _summarize_markdown_file(path: Path, rel_path: str) -> str:
    """Extract title, leading callout/thesis, and section headings deterministically."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    title = ""
    thesis_lines: list[str] = []
    headings: list[str] = []

    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        m_head = _HEADING_RE.match(line)
        if m_head:
            level = len(m_head.group(1))
            text_part = m_head.group(2)
            if level == 1 and not title:
                title = text_part
            elif level in (2, 3):
                headings.append(text_part)
            continue
        if idx < 12 and len(thesis_lines) < 2:
            m_quote = _QUOTE_RE.match(line)
            if m_quote:
                thesis_lines.append(m_quote.group(1))

    parts = [f"### {rel_path}"]
    if title:
        parts.append(f"- Title: {title}")
    if thesis_lines:
        parts.append(f"- Core thesis: {' '.join(thesis_lines)}")
    if headings:
        parts.append(f"- Covered sections: {' | '.join(headings[:14])}")
    return "\n".join(parts)


def _extract_landscape_items(repo_root: Path) -> list[str]:
    """Extract Landscape Radar items from todo.md if present."""
    todo_path = repo_root / "todo.md"
    if not todo_path.is_file():
        return []
    lines = todo_path.read_text(encoding="utf-8", errors="replace").splitlines()
    in_landscape = False
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("###") and "Landscape Radar" in stripped:
            in_landscape = True
            continue
        if in_landscape and (stripped.startswith("## ") or stripped.startswith("### ")):
            break
        if in_landscape and stripped.startswith("- ["):
            items.append(stripped)
    return items[:12]


def build_repo_inventory(
    repo_root: Path,
    exclude_files: Collection[str] = (),
    max_chars: int = 12_000,
) -> str:
    """Build a deterministic, cache-friendly summary of existing repo coverage."""
    files = list_repo_knowledge_files(repo_root, exclude_files=exclude_files)
    sections: list[str] = [
        "# REPOSITORY KNOWLEDGE INVENTORY (Already Covered — Do NOT Re-Report Unless Net-New Delta)",
        "Target profile: Senior SWE -> Staff SWE / FDE-FDSE using Antigravity, GitHub Copilot CLI, Claude Code, Codex.",
        "",
    ]
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        sections.append(_summarize_markdown_file(path, rel))
        sections.append("")

    landscape = _extract_landscape_items(repo_root)
    if landscape:
        sections.append("### todo.md (Actively Tracked Landscape Radar)")
        sections.extend(landscape)

    inventory = "\n".join(sections).strip()
    if len(inventory) > max_chars:
        return inventory[: max_chars - 3].rstrip() + "..."
    return inventory


def load_target_repo_context(
    repo_root: Path,
    relative_paths: list[str],
    exclude_files: Collection[str] = (),
    max_total_chars: int = 24_000,
) -> str:
    """Load only the relevant repo file(s) flagged by Stage 1 for Stage 2 deep delta comparison.

    Enforces strict path confinement inside `repo_root`.
    """
    excluded = {p.strip("/") for p in exclude_files}
    allowed_roots = {"playbooks", "templates", "skills", "hooks"}
    root_resolved = repo_root.resolve()
    chunks: list[str] = []
    total = 0

    for raw_rel in relative_paths:
        clean_rel = raw_rel.strip().lstrip("/")
        if not clean_rel or clean_rel in excluded:
            continue
        top_dir = clean_rel.split("/", 1)[0]
        if top_dir not in allowed_roots and clean_rel != "todo.md":
            continue
        candidate = (root_resolved / clean_rel).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        content = candidate.read_text(encoding="utf-8", errors="replace").strip()
        block = f"=== EXISTING REPO FILE: {clean_rel} ===\n{content}\n"
        if total + len(block) > max_total_chars:
            remaining = max_total_chars - total
            if remaining > 500:
                chunks.append(block[: remaining - 3].rstrip() + "...")
            break
        chunks.append(block)
        total += len(block)

    if not chunks:
        return build_repo_inventory(repo_root, exclude_files=exclude_files)
    return "\n\n".join(chunks)


def list_full_repo_baseline_files(
    repo_root: Path,
    exclude_files: Collection[str] = (),
) -> list[Path]:
    """Return sorted authoritative baseline files for Stage 3 full-repo coherence audits."""
    excluded = {p.strip("/") for p in exclude_files}
    root_resolved = repo_root.resolve()
    found: list[Path] = []
    seen_rels: set[str] = set()
    for pattern in FULL_REPO_BASELINE_GLOBS:
        for path in sorted(root_resolved.glob(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            try:
                rel = resolved.relative_to(root_resolved).as_posix()
            except ValueError:
                continue
            if rel in excluded or rel in seen_rels:
                continue
            seen_rels.add(rel)
            found.append(resolved)
    return found


def load_full_repo_baseline(
    repo_root: Path,
    exclude_files: Collection[str] = (),
    max_total_chars: int = 120_000,
) -> str:
    """Load the full authoritative repository baseline (~13K-19K tokens) for Stage 3.

    Covers `playbooks/`, `skills/`, `templates/`, `docs/GLOSSARY.md`, and `docs/adr/`
    so Stage 3 audits cross-file harmony, glossary terms, and ADRs in one pass.
    """
    files = list_full_repo_baseline_files(repo_root, exclude_files=exclude_files)
    root_resolved = repo_root.resolve()
    header = (
        "# FULL REPOSITORY BASELINE (Authoritative Current State)\n"
        "Target profile: Senior SWE -> Staff SWE / FDE-FDSE using Antigravity, "
        "GitHub Copilot CLI, Claude Code, Codex.\n"
    )
    chunks: list[str] = [header]
    total = len(header)

    for path in files:
        rel = path.relative_to(root_resolved).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        block = f"=== REPO BASELINE FILE: {rel} ===\n{content}\n"
        if total + len(block) > max_total_chars:
            remaining = max_total_chars - total
            if remaining > 500:
                chunks.append(block[: remaining - 3].rstrip() + "...")
            break
        chunks.append(block)
        total += len(block)

    return "\n\n".join(chunks).strip()
