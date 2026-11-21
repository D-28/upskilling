#!/usr/bin/env python3
"""Deterministic STE-80 (Simplified Technical English) linter for agent instructions.

Enforces the structural rules from Andrej Karpathy's ASD-STE100 ("STE-80") output
and instruction standard ([H]) as an automated check ("Write It Twice" [C]):
  1. Sentence length cap: <= 20 words (procedural target) / <= 25 words (hard cap),
     excluding code spans, URLs, and citation tags.
  2. No semicolons outside code spans (split compound clauses into two sentences).
  3. No conversational filler or bloated non-STE vocabulary (e.g., "utilize",
     "in order to", "prior to", "it is worth noting").
  4. Condition-first warning when conditional triggers ("if", "when", "unless")
     are buried late in a long sentence.

Usage:
  python3 scripts/ste_lint.py --stats skills/*/SKILL.md templates/AGENTS.md.template
  python3 scripts/ste_lint.py --check skills/*/SKILL.md
  python3 scripts/ste_lint.py --json skills/*/SKILL.md
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys
from typing import Iterable


BANNED_PHRASES: dict[str, str] = {
    "utilize": "use",
    "utilizes": "uses",
    "utilizing": "using",
    "utilization": "use",
    "facilitate": "help / enable",
    "facilitates": "helps / enables",
    "facilitating": "helping / enabling",
    "commence": "start",
    "commences": "starts",
    "commencing": "starting",
    "prior to": "before",
    "subsequent to": "after",
    "in order to": "to",
    "due to the fact that": "because",
    "at this point in time": "now",
    "it is worth noting": "<delete filler>",
    "it's worth noting": "<delete filler>",
    "it is important to note": "<delete filler>",
    "it's important to note": "<delete filler>",
    "great question": "<delete filler>",
    "i hope this helps": "<delete filler>",
}

CODE_SPAN_RE = re.compile(r"`[^`]+`")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
CITATION_RE = re.compile(
    r"\(\s*(?:`?\[[A-Z]\]`?(?:\s*,\s*`?\[[A-Z]\]`?)*)\s*\)|`?\[[A-Z]\]`?"
)
LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+|>\s+)+")
BOLD_HEADER_PREFIX_RE = re.compile(
    r"^\s*\*\*[^*]{1,80}?(?:(?::|—|--|-)\*\*|\*\*\s*(?::|—|--|-|→))\s*"
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'`(])")
WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")


@dataclass
class Violation:
    file: str
    line: int
    rule: str
    severity: str  # "error" | "warn"
    detail: str
    sentence: str


@dataclass
class FileStats:
    file: str
    sentences: int
    over_20_words: int
    over_25_words: int
    semicolons: int
    banned_phrases: int
    buried_conditions: int
    errors: int
    warnings: int
    ste_score: int


def _clean_for_counting(line: str) -> str:
    """Normalize a single markdown prose line before splitting into sentences."""
    text = LIST_PREFIX_RE.sub("", line.strip())
    # Strip repo citation markers like [B], `[B]`, ([B], [C]) before code spans.
    text = CITATION_RE.sub("", text)
    # Replace inline code spans with a single token so paths/commands count as 1 word
    # and semicolons inside backticks are ignored.
    text = CODE_SPAN_RE.sub("CODESPAN", text)
    # Replace markdown links [label](url) with their visible label.
    text = LINK_RE.sub(r"\1", text)
    # Strip bold header labels at the start of a bullet (e.g. "**Scope:** ...").
    text = BOLD_HEADER_PREFIX_RE.sub("", text)
    # Strip remaining bold/italic markers.
    text = text.replace("**", "").replace("*", "")
    return text.strip()


def _iter_prose_lines(content: str) -> Iterable[tuple[int, str]]:
    """Yield (1-based line_number, raw_line) for non-code, non-table prose lines."""
    lines = content.splitlines()
    in_frontmatter = False
    in_fence = False
    in_html_comment = False

    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()

        if idx == 1 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        if "<!--" in stripped:
            if "-->" not in stripped:
                in_html_comment = True
            continue
        if in_html_comment:
            if "-->" in stripped:
                in_html_comment = False
            continue

        if not stripped:
            continue
        # Skip headings, horizontal rules, and markdown tables.
        if stripped.startswith("#") or stripped.startswith("|") or stripped == "---":
            continue
        # Skip pure checkbox/metadata key-value lines with <= 2 words after label.
        yield idx, raw


def lint_file(
    path: Path,
    warn_words: int = 20,
    max_words: int = 25,
    strict_20: bool = False,
) -> tuple[FileStats, list[Violation]]:
    content = path.read_text(encoding="utf-8")
    violations: list[Violation] = []

    total_sentences = 0
    over_20 = 0
    over_25 = 0
    semicolons = 0
    banned_count = 0
    buried_count = 0

    for line_no, raw_line in _iter_prose_lines(content):
        cleaned = _clean_for_counting(raw_line)
        if not cleaned:
            continue

        # Check semicolons outside code spans on the line level.
        if ";" in cleaned:
            sem_hits = cleaned.count(";")
            semicolons += sem_hits
            violations.append(
                Violation(
                    file=str(path),
                    line=line_no,
                    rule="STE-5.2-NO-SEMICOLON",
                    severity="error",
                    detail="Semicolon joins compound clauses; split into separate sentences.",
                    sentence=cleaned,
                )
            )

        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(cleaned) if s.strip()]
        for sentence in sentences:
            words = WORD_TOKEN_RE.findall(sentence)
            word_count = len(words)
            if word_count == 0:
                continue

            total_sentences += 1

            if word_count > max_words:
                over_25 += 1
                over_20 += 1
                violations.append(
                    Violation(
                        file=str(path),
                        line=line_no,
                        rule="STE-5.1-MAX-25-WORDS",
                        severity="error",
                        detail=f"Sentence has {word_count} words (max {max_words}). Split without deleting conditions.",
                        sentence=sentence,
                    )
                )
            elif word_count > warn_words:
                over_20 += 1
                sev = "error" if strict_20 else "warn"
                violations.append(
                    Violation(
                        file=str(path),
                        line=line_no,
                        rule="STE-5.1-TARGET-20-WORDS",
                        severity=sev,
                        detail=f"Sentence has {word_count} words (procedural target <= {warn_words}, descriptive max {max_words}).",
                        sentence=sentence,
                    )
                )

            lower_sent = sentence.lower()
            for phrase, replacement in BANNED_PHRASES.items():
                pattern = r"\b" + re.escape(phrase) + r"\b"
                if re.search(pattern, lower_sent):
                    banned_count += 1
                    violations.append(
                        Violation(
                            file=str(path),
                            line=line_no,
                            rule="STE-1.1-BANNED-PHRASE",
                            severity="error",
                            detail=f"Avoid '{phrase}'; prefer '{replacement}'.",
                            sentence=sentence,
                        )
                    )

            # Check for buried condition after word 14 in longer sentences.
            if word_count >= 16 and not lower_sent.startswith(("if ", "when ", "unless ", "before ", "after ", "once ", "whenever ")):
                late_tokens = [w.lower() for w in words[12:]]
                if "if" in late_tokens or "unless" in late_tokens:
                    buried_count += 1
                    violations.append(
                        Violation(
                            file=str(path),
                            line=line_no,
                            rule="STE-5.4-CONDITION-FIRST",
                            severity="warn",
                            detail="Condition ('if'/'unless') appears late in sentence; consider placing the condition first.",
                            sentence=sentence,
                        )
                    )

    errors = sum(1 for v in violations if v.severity == "error")
    warnings = sum(1 for v in violations if v.severity == "warn")

    if total_sentences == 0:
        score = 100
    else:
        penalty = (
            (over_25 * 100.0 / total_sentences)
            + (semicolons * 80.0 / total_sentences)
            + (banned_count * 80.0 / total_sentences)
            + ((over_20 - over_25) * 25.0 / total_sentences)
            + (buried_count * 20.0 / total_sentences)
        )
        score = max(0, min(100, round(100 - penalty)))

    stats = FileStats(
        file=str(path),
        sentences=total_sentences,
        over_20_words=over_20,
        over_25_words=over_25,
        semicolons=semicolons,
        banned_phrases=banned_count,
        buried_conditions=buried_count,
        errors=errors,
        warnings=warnings,
        ste_score=score,
    )
    return stats, violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic STE-80 linter for AGENTS.md, SKILL.md, and technical docs."
    )
    parser.add_argument("files", nargs="+", help="Markdown files to lint")
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print summary statistics table per file",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any error violations are found",
    )
    parser.add_argument(
        "--strict-20",
        action="store_true",
        help="Treat sentences > 20 words as errors (strict procedural mode)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit compact JSON output (for programmatic/Code Mode filtering)",
    )
    parser.add_argument(
        "--warn-words",
        type=int,
        default=20,
        help="Word count warning threshold for procedural sentences (default: 20)",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=25,
        help="Hard word count error limit per sentence (default: 25)",
    )
    args = parser.parse_args(argv)

    all_stats: list[FileStats] = []
    all_violations: list[Violation] = []

    for raw_path in args.files:
        p = Path(raw_path)
        if not p.is_file():
            print(f"Error: file not found: {raw_path}", file=sys.stderr)
            return 2
        st, viols = lint_file(
            p,
            warn_words=args.warn_words,
            max_words=args.max_words,
            strict_20=args.strict_20,
        )
        all_stats.append(st)
        all_violations.extend(viols)

    if args.json:
        payload = {
            "stats": [asdict(s) for s in all_stats],
            "violations": [asdict(v) for v in all_violations],
            "total_errors": sum(s.errors for s in all_stats),
            "total_warnings": sum(s.warnings for s in all_stats),
        }
        print(json.dumps(payload, indent=2))
    else:
        if args.stats or not all_violations:
            header = (
                f"{'File':<38} {'Sent':>5} {'>20w':>5} {'>25w':>5} "
                f"{'Semi':>5} {'Ban':>4} {'Err':>4} {'Warn':>5} {'Score':>6}"
            )
            print(header)
            print("-" * len(header))
            for s in all_stats:
                print(
                    f"{s.file:<38} {s.sentences:>5} {s.over_20_words:>5} "
                    f"{s.over_25_words:>5} {s.semicolons:>5} {s.banned_phrases:>4} "
                    f"{s.errors:>4} {s.warnings:>5} {s.ste_score:>5}%"
                )

        if all_violations:
            if args.stats:
                print()
            for v in all_violations:
                tag = "ERROR" if v.severity == "error" else "WARN "
                print(f"[{tag}] {v.file}:{v.line} ({v.rule}) — {v.detail}")
                print(f"        {v.sentence}")

    total_errors = sum(s.errors for s in all_stats)
    if args.check and total_errors > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
