#!/usr/bin/env python3
"""
Analyze the Claude Code plugin ecosystem.

Reads the marketplace registry and each plugin directory, then produces a
structured report covering:
  - Category and author breakdowns
  - Per-plugin component inventory (commands, agents, skills, hooks)
  - File-type and line-count statistics
  - Complexity ranking

Usage:
  python3 scripts/analyze-plugins.py
  python3 scripts/analyze-plugins.py --plugins-dir plugins --marketplace .claude-plugin/marketplace.json
  python3 scripts/analyze-plugins.py --json        # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PluginStats:
    name: str
    version: str
    description: str
    category: str
    author: str
    root: Path

    # component counts
    commands: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)

    # file inventory
    total_files: int = 0
    total_lines: int = 0
    file_types: dict[str, int] = field(default_factory=dict)  # ext -> count


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

# Extensions treated as "source" when counting lines
_SOURCE_EXTS = {
    ".md", ".py", ".ts", ".js", ".sh", ".json",
    ".yaml", ".yml", ".txt",
}


def _count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("rb"))
    except OSError:
        return 0


def _collect_files(root: Path) -> tuple[int, int, dict[str, int]]:
    """Return (file_count, line_count, ext_freq_dict) for a directory tree."""
    total_files = 0
    total_lines = 0
    ext_freq: dict[str, int] = {}

    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower() or "(none)"
            total_files += 1
            ext_freq[ext] = ext_freq.get(ext, 0) + 1
            if fpath.suffix.lower() in _SOURCE_EXTS:
                total_lines += _count_lines(fpath)

    return total_files, total_lines, ext_freq


def _names_in(directory: Path) -> list[str]:
    """Return sorted stem names of files directly inside *directory*."""
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.iterdir() if p.is_file())


def _skill_names(skills_dir: Path) -> list[str]:
    """Return sorted top-level subdirectory names in the skills/ dir."""
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir())


def _hook_event_names(hooks_dir: Path) -> list[str]:
    """Return hook event names found in hooks.json or inferred from filenames."""
    if not hooks_dir.is_dir():
        return []

    hooks_json = hooks_dir / "hooks.json"
    if hooks_json.exists():
        try:
            data = json.loads(hooks_json.read_text())
            return sorted(data.keys())
        except (json.JSONDecodeError, AttributeError):
            pass

    # Fallback: use script stem names that look like hook events
    return _names_in(hooks_dir)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def analyze_plugin(plugin_entry: dict[str, Any], plugin_root: Path) -> PluginStats:
    """Collect statistics for a single plugin entry from the marketplace."""
    name = plugin_entry.get("name", "unknown")
    source = plugin_entry.get("source", f"./plugins/{name}")
    # Normalize relative paths like "./plugins/foo"
    root = (plugin_root / source.lstrip("./")).resolve()

    author_info = plugin_entry.get("author", {})
    author = (
        author_info.get("name", "")
        if isinstance(author_info, dict)
        else str(author_info)
    )

    stats = PluginStats(
        name=name,
        version=plugin_entry.get("version", "—"),
        description=plugin_entry.get("description", ""),
        category=plugin_entry.get("category", "uncategorized"),
        author=author,
        root=root,
    )

    if not root.is_dir():
        return stats  # plugin directory not found – return empty stats

    stats.commands = _names_in(root / "commands")
    stats.agents = _names_in(root / "agents")
    stats.skills = _skill_names(root / "skills")
    stats.hooks = _hook_event_names(root / "hooks")

    stats.total_files, stats.total_lines, stats.file_types = _collect_files(root)

    return stats


def analyze_all(
    marketplace_path: Path,
    plugins_dir: Path,
) -> list[PluginStats]:
    data = json.loads(marketplace_path.read_text())
    results: list[PluginStats] = []
    for entry in data.get("plugins", []):
        results.append(analyze_plugin(entry, plugins_dir.parent))
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_WIDTH = 60


def _hr(char: str = "─") -> str:
    return char * _WIDTH


def _section(title: str) -> None:
    print(f"\n{'=' * _WIDTH}")
    print(f"  {title}")
    print("=" * _WIDTH)


def print_report(all_stats: list[PluginStats]) -> None:  # noqa: C901
    n = len(all_stats)

    print("\n" + "#" * _WIDTH)
    print("  CLAUDE CODE PLUGIN ECOSYSTEM ANALYSIS")
    print("#" * _WIDTH)

    # ── 1. Top-level summary ──────────────────────────────────────────────
    _section("1. Overview")
    total_files = sum(s.total_files for s in all_stats)
    total_lines = sum(s.total_lines for s in all_stats)
    total_commands = sum(len(s.commands) for s in all_stats)
    total_agents = sum(len(s.agents) for s in all_stats)
    total_skills = sum(len(s.skills) for s in all_stats)
    plugins_with_hooks = sum(1 for s in all_stats if s.hooks)

    print(f"  Total plugins           : {n}")
    print(f"  Total files             : {total_files}")
    print(f"  Total lines (src)       : {total_lines:,}")
    print(f"  Total commands          : {total_commands}")
    print(f"  Total agents            : {total_agents}")
    print(f"  Total skills            : {total_skills}")
    print(f"  Plugins with hooks      : {plugins_with_hooks} / {n}")

    # ── 2. Category breakdown ─────────────────────────────────────────────
    _section("2. Category Breakdown")
    categories: dict[str, list[str]] = {}
    for s in all_stats:
        categories.setdefault(s.category, []).append(s.name)

    for cat, names in sorted(categories.items()):
        bar = "█" * len(names)
        print(f"  {cat:<20s} {bar}  ({len(names)} plugin{'s' if len(names) != 1 else ''})")
        for name in sorted(names):
            print(f"    - {name}")

    # ── 3. Author breakdown ───────────────────────────────────────────────
    _section("3. Author Breakdown")
    authors: dict[str, list[str]] = {}
    for s in all_stats:
        key = s.author or "Unknown"
        authors.setdefault(key, []).append(s.name)

    for author, names in sorted(authors.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"  {author}")
        for name in sorted(names):
            print(f"    - {name}")

    # ── 4. Per-plugin inventory ───────────────────────────────────────────
    _section("4. Per-Plugin Inventory")
    header = f"  {'Plugin':<30s} {'Cmds':>4} {'Agts':>4} {'Skls':>4} {'Hooks':>5} {'Files':>5} {'Lines':>7}"
    print(header)
    print("  " + _hr())
    for s in sorted(all_stats, key=lambda x: x.name):
        print(
            f"  {s.name:<30s}"
            f" {len(s.commands):>4d}"
            f" {len(s.agents):>4d}"
            f" {len(s.skills):>4d}"
            f" {len(s.hooks):>5d}"
            f" {s.total_files:>5d}"
            f" {s.total_lines:>7,}"
        )

    # ── 5. Component detail ───────────────────────────────────────────────
    _section("5. Component Detail")
    for s in sorted(all_stats, key=lambda x: x.name):
        if not (s.commands or s.agents or s.skills or s.hooks):
            continue
        print(f"\n  {s.name}  (v{s.version}, {s.category})")
        if s.commands:
            print(f"    Commands : {', '.join(s.commands)}")
        if s.agents:
            print(f"    Agents   : {', '.join(s.agents)}")
        if s.skills:
            print(f"    Skills   : {', '.join(s.skills)}")
        if s.hooks:
            print(f"    Hooks    : {', '.join(s.hooks)}")

    # ── 6. File-type distribution ─────────────────────────────────────────
    _section("6. File-Type Distribution (across all plugins)")
    combined: dict[str, int] = {}
    for s in all_stats:
        for ext, cnt in s.file_types.items():
            combined[ext] = combined.get(ext, 0) + cnt
    for ext, cnt in sorted(combined.items(), key=lambda kv: -kv[1]):
        bar = "▪" * min(cnt, 40)
        print(f"  {ext:<10s} {bar}  {cnt}")

    # ── 7. Complexity ranking ─────────────────────────────────────────────
    _section("7. Complexity Ranking (by source lines)")
    ranked = sorted(all_stats, key=lambda s: -s.total_lines)
    for rank, s in enumerate(ranked, 1):
        bar = "▮" * min(s.total_lines // 100, 30)
        print(f"  {rank:2d}. {s.name:<30s} {s.total_lines:>6,} lines  {bar}")

    print("\n" + "#" * _WIDTH)
    print("  END OF REPORT")
    print("#" * _WIDTH + "\n")


def print_json_report(all_stats: list[PluginStats]) -> None:
    output = []
    for s in all_stats:
        output.append(
            {
                "name": s.name,
                "version": s.version,
                "description": s.description,
                "category": s.category,
                "author": s.author,
                "commands": s.commands,
                "agents": s.agents,
                "skills": s.skills,
                "hooks": s.hooks,
                "total_files": s.total_files,
                "total_lines": s.total_lines,
                "file_types": s.file_types,
            }
        )
    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk upward from CWD to find the repository root (contains .claude-plugin)."""
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / ".claude-plugin" / "marketplace.json").exists():
            return candidate
    return here


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze the Claude Code plugin ecosystem.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--plugins-dir",
        default=None,
        metavar="DIR",
        help="Path to the plugins/ directory (auto-detected from CWD if omitted).",
    )
    parser.add_argument(
        "--marketplace",
        default=None,
        metavar="FILE",
        help="Path to marketplace.json (auto-detected if omitted).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON instead of the human-readable report.",
    )
    args = parser.parse_args(argv)

    repo_root = _find_repo_root()

    marketplace_path = (
        Path(args.marketplace) if args.marketplace else repo_root / ".claude-plugin" / "marketplace.json"
    )
    plugins_dir = (
        Path(args.plugins_dir) if args.plugins_dir else repo_root / "plugins"
    )

    if not marketplace_path.exists():
        print(f"Error: marketplace.json not found at {marketplace_path}", file=sys.stderr)
        return 1

    all_stats = analyze_all(marketplace_path, plugins_dir)

    if not all_stats:
        print("No plugins found in marketplace.json.", file=sys.stderr)
        return 1

    if args.json_output:
        print_json_report(all_stats)
    else:
        print_report(all_stats)

    return 0


if __name__ == "__main__":
    sys.exit(main())
