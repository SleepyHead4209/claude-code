#!/usr/bin/env python3
"""
Compare code analysis results from multiple analysis runs or tools.

This script accepts JSON analysis result files (one per tool/run) and produces
a structured comparison showing common findings, unique findings per tool, and
agreement metrics to help prioritise which issues to fix first.

Usage:
  python3 compare-analysis.py results1.json results2.json [results3.json ...]
  python3 compare-analysis.py --stdin < results1.json   # single tool from stdin

Input JSON format (one file per tool):
  {
    "tool": "tool-name",
    "issues": [
      {
        "description": "Issue description",
        "file": "path/to/file.py",
        "line": 42,
        "severity": "critical|important|suggestion",
        "confidence": 85
      }
    ]
  }

Output:
  - Summary statistics per tool
  - Issues agreed upon by ALL tools  (highest priority)
  - Issues agreed upon by SOME tools (medium priority)
  - Issues unique to each tool       (lowest priority / review manually)
  - Overall agreement score
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    description: str
    file: str = ""
    line: int | None = None
    severity: str = "unknown"
    confidence: int = 0
    tool: str = ""

    def similarity(self, other: "Issue") -> float:
        """Return a 0-1 similarity score between two issues.

        Two issues are considered the same when they refer to the same file/line
        OR when their descriptions are very similar (>=0.7 token ratio).
        """
        # Exact same location → very likely the same issue
        if self.file and other.file and self.file == other.file:
            if self.line is not None and other.line is not None:
                if abs(self.line - other.line) <= 3:
                    return 1.0

        # Fall back to description similarity
        return SequenceMatcher(
            None,
            self.description.lower(),
            other.description.lower(),
        ).ratio()

    def __str__(self) -> str:
        location = self.file
        if self.line is not None:
            location = f"{location}:{self.line}"
        return f"[{self.severity.upper()}] {self.description}" + (
            f" ({location})" if location else ""
        )


@dataclass
class ToolResult:
    tool: str
    issues: list[Issue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_issue(raw: dict[str, Any], tool: str) -> Issue:
    return Issue(
        description=raw.get("description", ""),
        file=raw.get("file", ""),
        line=raw.get("line"),
        severity=raw.get("severity", "unknown"),
        confidence=int(raw.get("confidence", 0)),
        tool=tool,
    )


def load_result(data: dict[str, Any]) -> ToolResult:
    tool = data.get("tool", "unknown")
    issues = [_parse_issue(r, tool) for r in data.get("issues", [])]
    return ToolResult(tool=tool, issues=issues)


def load_file(path: str) -> ToolResult:
    with open(path) as fh:
        return load_result(json.load(fh))


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

DEFAULT_SIMILARITY_THRESHOLD = 0.70  # treat as "same" issue when score >= this


def _group_by_agreement(
    results: list[ToolResult],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> dict[str, list[tuple[Issue, list[str]]]]:
    """Group issues by how many tools reported them.

    Returns a dict with keys: "all", "some", and each tool name (unique).
    Each value is a list of (representative_issue, [tool_names_that_reported_it]).
    """
    n = len(results)
    # Collect every issue tagged with its tool
    all_issues: list[Issue] = []
    for tr in results:
        all_issues.extend(tr.issues)

    # Build clusters: each cluster is a list of equivalent issues
    clusters: list[list[Issue]] = []
    assigned: set[int] = set()

    for idx, issue in enumerate(all_issues):
        if idx in assigned:
            continue
        cluster = [issue]
        assigned.add(idx)
        for jdx in range(idx + 1, len(all_issues)):
            if jdx in assigned:
                continue
            if issue.similarity(all_issues[jdx]) >= threshold:
                cluster.append(all_issues[jdx])
                assigned.add(jdx)
        clusters.append(cluster)

    # Label each cluster
    agreed_all: list[tuple[Issue, list[str]]] = []
    agreed_some: list[tuple[Issue, list[str]]] = []
    unique: dict[str, list[tuple[Issue, list[str]]]] = {tr.tool: [] for tr in results}

    for cluster in clusters:
        tools_reporting = sorted({i.tool for i in cluster})
        representative = cluster[0]  # pick first as representative
        entry = (representative, tools_reporting)
        if len(tools_reporting) == n:
            agreed_all.append(entry)
        elif len(tools_reporting) > 1:
            agreed_some.append(entry)
        else:
            unique[tools_reporting[0]].append(entry)

    return {"all": agreed_all, "some": agreed_some, **unique}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"critical": 0, "important": 1, "suggestion": 2, "unknown": 3}


def _sort_issues(items: list[tuple[Issue, list[str]]]) -> list[tuple[Issue, list[str]]]:
    return sorted(
        items,
        key=lambda t: (_SEVERITY_ORDER.get(t[0].severity.lower(), 3), -t[0].confidence),
    )


def _print_section(title: str, items: list[tuple[Issue, list[str]]], indent: str = "  ") -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title} ({len(items)} issue{'s' if len(items) != 1 else ''})")
    print(f"{'=' * 60}")
    if not items:
        print(f"{indent}(none)")
        return
    for issue, tools in _sort_issues(items):
        tools_str = ", ".join(tools)
        print(f"\n{indent}[{issue.severity.upper()}] {issue.description}")
        if issue.file:
            loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
            print(f"{indent}  Location  : {loc}")
        if issue.confidence:
            print(f"{indent}  Confidence: {issue.confidence}")
        print(f"{indent}  Reported by: {tools_str}")


def print_report(results: list[ToolResult], groups: dict[str, list[tuple[Issue, list[str]]]]) -> None:
    n = len(results)
    total = sum(len(tr.issues) for tr in results)

    print("\n" + "#" * 60)
    print("  CODE ANALYSIS COMPARISON REPORT")
    print("#" * 60)

    # Per-tool summary
    print("\n── Tool Summary ─────────────────────────────────────────")
    for tr in results:
        print(f"  {tr.tool:30s}  {len(tr.issues):3d} issue(s)")
    print(f"  {'TOTAL (raw)':30s}  {total:3d}")

    # Agreement metric
    agreed_all_count = len(groups["all"])
    agreed_some_count = len(groups["some"])
    unique_count = sum(len(groups.get(tr.tool, [])) for tr in results)

    print("\n── Agreement Summary ────────────────────────────────────")
    print(f"  Issues found by ALL  {n} tool(s) : {agreed_all_count}")
    print(f"  Issues found by SOME {n} tool(s) : {agreed_some_count}")
    print(f"  Issues unique to one tool       : {unique_count}")

    if total > 0:
        agreement_score = round(agreed_all_count / total * 100, 1)
        print(f"\n  Agreement score: {agreement_score}% of raw issues corroborated by all tools")

    # Sections ordered by priority
    _print_section(
        f"🔴 HIGH PRIORITY — Reported by ALL {n} tools",
        groups["all"],
    )
    _print_section(
        "🟡 MEDIUM PRIORITY — Reported by MULTIPLE tools",
        groups["some"],
    )
    for tr in results:
        _print_section(
            f"⚪ UNIQUE to '{tr.tool}' — Review manually",
            groups.get(tr.tool, []),
        )

    print("\n" + "#" * 60)
    print("  END OF REPORT")
    print("#" * 60 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare code analysis results from multiple tools or runs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="results.json",
        help="JSON result files to compare (at least 2 recommended).",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read a single JSON result from stdin (can combine with file args).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
        metavar="0-1",
        help=f"Similarity threshold for matching issues (default: {DEFAULT_SIMILARITY_THRESHOLD}).",
    )
    args = parser.parse_args(argv)

    threshold = args.threshold

    results: list[ToolResult] = []

    for path in args.files:
        try:
            results.append(load_file(path))
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            print(f"Error loading '{path}': {exc}", file=sys.stderr)
            return 1

    if args.stdin:
        try:
            results.append(load_result(json.load(sys.stdin)))
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"Error reading stdin: {exc}", file=sys.stderr)
            return 1

    if not results:
        parser.print_help()
        return 1

    if len(results) == 1:
        print(
            "Warning: only one result set provided — comparison will show all issues as unique.",
            file=sys.stderr,
        )

    groups = _group_by_agreement(results, threshold)
    print_report(results, groups)
    return 0


if __name__ == "__main__":
    sys.exit(main())
