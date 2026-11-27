#!/usr/bin/env python3
"""Deterministic git diff & base-branch REVIEW.md context wrapper.

Emits a compact structured JSON (or text) summary of a git diff range so agents
get bounded, machine-readable context instead of raw terminal dumps. Always
reads REVIEW.md strictly from --review-ref (never from the working tree or PR
head) to preserve the anti-gaming base-branch invariant.

Usage:
  python3 scripts/diff_context.py --base origin/main --json
  python3 scripts/diff_context.py --base origin/main --head HEAD --review-ref origin/main --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")
_WORKFLOW_RE = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")


class DiffContextError(RuntimeError):
    """Raised when git inspection fails due to an invalid ref or repository."""


@dataclass(frozen=True)
class FileStat:
    path: str
    additions: int
    deletions: int
    binary: bool = False


@dataclass(frozen=True)
class ReviewRule:
    id: str
    trigger: str
    check: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class TriggeredCheck:
    id: str
    trigger: str
    check: str
    matched_files: list[str]


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _resolve_commit(repo_root: Path, ref: str) -> str:
    if not ref or ref.startswith("-"):
        raise DiffContextError(f"Invalid git ref '{ref}': ref must not be empty or start with '-'")
    proc = _run_git(
        repo_root,
        "rev-parse",
        "--verify",
        "--quiet",
        "--end-of-options",
        f"{ref}^{{commit}}",
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"invalid git ref: {ref}"
        raise DiffContextError(f"Cannot resolve git ref '{ref}': {detail}")
    return proc.stdout.strip()


def _parse_numstat_z(raw: str) -> list[FileStat]:
    if not raw:
        return []
    files: list[FileStat] = []
    for entry in raw.split("\0"):
        if not entry:
            continue
        parts = entry.split("\t", 2)
        if len(parts) != 3:
            continue
        add_s, del_s, path = parts
        if add_s == "-" or del_s == "-":
            files.append(FileStat(path=path, additions=0, deletions=0, binary=True))
        else:
            files.append(
                FileStat(
                    path=path,
                    additions=int(add_s),
                    deletions=int(del_s),
                    binary=False,
                )
            )
    files.sort(key=lambda item: item.path)
    return files


def _normalize_posix_path(raw: str) -> str:
    """Strip leading './' and '/' without stripping leading dots from dotfiles."""
    norm = raw.strip()
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.lstrip("/")


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a POSIX path glob (supporting *, **, ?) into a compiled regex."""
    norm = _normalize_posix_path(pattern)
    if norm.endswith("/"):
        norm = f"{norm}**"

    regex_parts: list[str] = ["^"]
    i = 0
    n = len(norm)
    while i < n:
        if norm.startswith("**/", i):
            regex_parts.append("(?:.*/)?")
            i += 3
        elif norm.startswith("/**", i) and i + 3 == n:
            regex_parts.append("(?:/.*)?")
            i += 3
        elif norm.startswith("**", i):
            regex_parts.append(".*")
            i += 2
        elif norm[i] == "*":
            regex_parts.append("[^/]*")
            i += 1
        elif norm[i] == "?":
            regex_parts.append("[^/]")
            i += 1
        else:
            regex_parts.append(re.escape(norm[i]))
            i += 1
    regex_parts.append("$")
    return re.compile("".join(regex_parts))


def glob_match(path: str, pattern: str) -> bool:
    """Return True if repo-relative path matches POSIX glob pattern."""
    norm_path = _normalize_posix_path(path)
    return bool(glob_to_regex(pattern).match(norm_path))


def parse_review_triggers(markdown: str) -> list[ReviewRule]:
    """Extract diff-trigger table rows from REVIEW.md markdown."""
    rules: list[ReviewRule] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        # Skip markdown table separator rows (|---|---|---|)
        if all(_SEPARATOR_CELL_RE.match(c) for c in cells[:3]):
            continue
        # Skip header rows (non-rule headers like "#" / "Diff Trigger")
        rule_id, trigger_col, check_col = cells[0], cells[1], cells[2]
        if rule_id in {"#", "ID", "Id"} or trigger_col.lower().startswith("diff trigger"):
            continue
        patterns = tuple(p.strip() for p in _CODE_SPAN_RE.findall(trigger_col) if p.strip())
        if not patterns:
            continue
        rules.append(
            ReviewRule(
                id=rule_id,
                trigger=trigger_col,
                check=check_col,
                patterns=patterns,
            )
        )
    return rules


def match_review_rules(
    changed_paths: list[str],
    rules: list[ReviewRule],
) -> list[TriggeredCheck]:
    """Match changed repo-relative file paths against parsed REVIEW.md rules."""
    triggered: list[TriggeredCheck] = []
    for rule in rules:
        matched = sorted(
            {
                path
                for path in changed_paths
                if any(glob_match(path, pat) for pat in rule.patterns)
            }
        )
        if matched:
            triggered.append(
                TriggeredCheck(
                    id=rule.id,
                    trigger=rule.trigger,
                    check=rule.check,
                    matched_files=matched,
                )
            )
    return triggered


def collect_diff_context(
    repo_root: Path,
    base_ref: str,
    head_ref: str = "HEAD",
    review_ref: str | None = None,
) -> dict[str, object]:
    """Collect deterministic diff metadata and base-branch REVIEW.md triggers."""
    effective_review_ref = review_ref or base_ref

    base_sha = _resolve_commit(repo_root, base_ref)
    head_sha = _resolve_commit(repo_root, head_ref)
    review_sha = _resolve_commit(repo_root, effective_review_ref)

    diff_proc = _run_git(
        repo_root,
        "diff",
        "--numstat",
        "--no-renames",
        "-z",
        f"{base_sha}...{head_sha}",
    )
    if diff_proc.returncode != 0:
        detail = diff_proc.stderr.strip() or "git diff failed"
        raise DiffContextError(f"git diff failed for {base_ref}...{head_ref}: {detail}")

    files = _parse_numstat_z(diff_proc.stdout)
    changed_paths = [f.path for f in files]

    review_md_modified = "REVIEW.md" in changed_paths
    workflow_files_modified = sorted(
        path for path in changed_paths if _WORKFLOW_RE.match(path)
    )

    # Anti-gaming invariant: read REVIEW.md strictly from --review-ref via git show.
    show_proc = _run_git(repo_root, "show", f"{review_sha}:REVIEW.md")
    if show_proc.returncode == 0:
        review_md_present = True
        review_md_source: str | None = f"{effective_review_ref}:REVIEW.md"
        rules = parse_review_triggers(show_proc.stdout)
        triggered_checks = match_review_rules(changed_paths, rules)
    else:
        review_md_present = False
        review_md_source = None
        triggered_checks = []

    return {
        "base_ref": base_ref,
        "base_sha": base_sha,
        "head_ref": head_ref,
        "head_sha": head_sha,
        "review_ref": effective_review_ref,
        "review_sha": review_sha,
        "review_md_present_on_ref": review_md_present,
        "review_md_source": review_md_source,
        "review_md_modified": review_md_modified,
        "workflow_files_modified": workflow_files_modified,
        "totals": {
            "files_changed": len(files),
            "additions": sum(f.additions for f in files),
            "deletions": sum(f.deletions for f in files),
        },
        "files": [asdict(f) for f in files],
        "triggered_checks": [asdict(c) for c in triggered_checks],
    }


def _format_text(payload: dict[str, object]) -> str:
    totals = payload["totals"]
    assert isinstance(totals, dict)
    lines = [
        f"Diff Context: {payload['base_ref']} ({str(payload['base_sha'])[:10]})"
        f" ... {payload['head_ref']} ({str(payload['head_sha'])[:10]})",
        f"Rubric Source: {payload['review_md_source'] or 'missing on review ref'}",
        f"Totals: {totals['files_changed']} files "
        f"(+{totals['additions']} / -{totals['deletions']})",
        f"REVIEW.md Modified: {payload['review_md_modified']}",
    ]
    workflows = payload["workflow_files_modified"]
    assert isinstance(workflows, list)
    if workflows:
        lines.append(f"NO UNDO Workflows Modified: {', '.join(workflows)}")

    checks = payload["triggered_checks"]
    assert isinstance(checks, list)
    if checks:
        lines.append("Triggered Checks:")
        for item in checks:
            matched = ", ".join(item["matched_files"])
            lines.append(f"  - [#{item['id']}] ({matched}) {item['check']}")
    else:
        lines.append("Triggered Checks: none")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect deterministic git diff stats and base-branch REVIEW.md "
            "diff-triggered checks."
        )
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base git ref for merge-base diff (default: origin/main).",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Head git ref to review (default: HEAD).",
    )
    parser.add_argument(
        "--review-ref",
        default=None,
        help="Git ref to read REVIEW.md strictly from (default: same as --base).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Path to the git repository root (default: current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit compact machine-readable JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = collect_diff_context(
            repo_root=args.repo_root,
            base_ref=args.base,
            head_ref=args.head,
            review_ref=args.review_ref,
        )
    except DiffContextError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(_format_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
