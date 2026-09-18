#!/usr/bin/env python3
"""skill-issue: audit and clean AI coding-agent clutter on your Mac.

Like DevCleaner for Xcode, but for skills, plugins, agents, commands, MCP
servers, instruction files (CLAUDE.md / AGENTS.md / GEMINI.md / .cursorrules),
hooks, session transcripts and caches left behind by Claude Code, Codex,
Gemini CLI, Cursor, Windsurf, OpenCode and Copilot.

Usage:
  skill_issue.py                      full audit
  skill_issue.py tui                  interactive picker (curses)
  skill_issue.py --tool claude        one tool
  skill_issue.py --category sessions  one category
  skill_issue.py --usage              also grep Claude transcripts for last use
  skill_issue.py --json               machine-readable
  skill_issue.py clean sessions --older-than 30
  skill_issue.py clean skills --tool claude       interactive pick list

Nothing is hard-deleted. `clean` moves items into ~/.Trash/skill-issue-<ts>/
with a manifest so you can put them back.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional

HOME = Path.home()
NOW = time.time()

CATEGORIES = [
    "skills", "plugins", "agents", "commands", "instructions", "mcp",
    "hooks", "sessions", "caches", "projects",
]
# Categories that `clean` may move to Trash. Config entries (mcp, hooks,
# instructions, projects) are report-only: removing them means editing a file
# that other things depend on, so the tool tells you where instead.
CLEANABLE = {"skills", "plugins", "agents", "commands", "sessions", "caches"}


# --------------------------------------------------------------------------- model
@dataclass(eq=False)
class Item:
    tool: str
    category: str
    name: str
    path: str
    size: int = 0
    mtime: float = 0.0
    kind: str = "dir"            # dir | file | config
    note: str = ""
    flags: list = field(default_factory=list)   # e.g. ["orphan", "broken-include"]
    last_used: Optional[float] = None

    @property
    def age_days(self) -> int:
        return int((NOW - self.mtime) / 86400) if self.mtime else -1

    @property
    def cleanable(self) -> bool:
        return self.category in CLEANABLE and self.kind != "config" and Path(self.path).exists()


# --------------------------------------------------------------------------- helpers
def human(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def dir_size(p: Path) -> tuple[int, float]:
    """Return (bytes, newest mtime) for a file or tree. Never follows symlinks."""
    try:
        st = p.lstat()
    except OSError:
        return 0, 0.0
    if not p.is_dir() or p.is_symlink():
        return st.st_size, st.st_mtime
    total, newest = 0, st.st_mtime
    stack = [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        s = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(Path(e.path))
                    else:
                        total += s.st_size
                    if s.st_mtime > newest:
                        newest = s.st_mtime
        except OSError:
            continue
    return total, newest


def mk(tool, cat, name, path: Path, kind=None, note="", flags=None) -> Item:
    size, mtime = dir_size(path)
    if kind is None:
        kind = "dir" if path.is_dir() else "file"
    return Item(tool, cat, name, str(path), size, mtime, kind, note, list(flags or []))


def skill_dirs(root: Path) -> list[tuple[str, Path]]:
    """Yield (name, dir) for skills, descending through container dirs that
    hold no SKILL.md themselves (e.g. Claude's skills/synced/<id>/)."""
    out = []
    for d in children(root):
        if not d.is_dir():
            continue
        if (d / "SKILL.md").exists():
            out.append((d.name, d))
            continue
        nested = [c for c in d.rglob("SKILL.md") if len(c.relative_to(d).parts) <= 3]
        if nested:
            for c in sorted(nested):
                out.append((f"{d.name[:8]}…/{c.parent.name}", c.parent))
        else:
            out.append((d.name, d))
    return out


def children(p: Path, pattern="*") -> list[Path]:
    if not p.is_dir():
        return []
    return sorted(c for c in p.glob(pattern) if not c.name.startswith("."))


def read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def first_line(p: Path, key="description") -> str:
    """Pull `description:` from YAML frontmatter or the first heading/line."""
    try:
        text = p.read_text(errors="replace")[:4000]
    except OSError:
        return ""
    m = re.search(rf"^{key}:\s*(.+)$", text, re.M)
    if m:
        return m.group(1).strip().strip('"')[:70]
    for line in text.splitlines():
        line = line.strip("# ").strip()
        if line and not line.startswith("---"):
            return line[:70]
    return ""


def which_ok(cmd: str) -> bool:
    if not cmd:
        return True
    if "/" in cmd:
        return Path(os.path.expanduser(cmd)).exists()
    return shutil.which(cmd) is not None


# --------------------------------------------------------------------------- instruction files
INCLUDE_RE = re.compile(r"^@(\S+)", re.M)


def strip_fences(text: str) -> str:
    return re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)


def scan_instruction_file(tool: str, path: Path, seen: set, items: list, depth=0, name: str = None):
    """Add an instruction file and recursively follow `@path` includes."""
    if str(path) in seen or depth > 6:
        return
    seen.add(str(path))
    name = name or path.name
    if not path.exists():
        if depth == 0:
            return
        items.append(Item(tool, "instructions", name, str(path), 0, 0, "file",
                          "include target missing", ["broken-include"]))
        return
    it = mk(tool, "instructions", name, path, "file", first_line(path))
    if depth:
        it.note = f"included (depth {depth}): " + it.note
    items.append(it)
    try:
        text = strip_fences(path.read_text(errors="replace"))
    except OSError:
        return
    for m in INCLUDE_RE.finditer(text):
        target = m.group(1)
        if target.startswith(("http://", "https://")):
            continue
        tp = Path(os.path.expanduser(target))
        if not tp.is_absolute():
            tp = path.parent / tp
        scan_instruction_file(tool, tp, seen, items, depth + 1,
                              name=f"{name} -> {tp.name}")


PROJECT_INSTRUCTION_FILES = {
    "claude": ["CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"],
    "codex": ["AGENTS.md", "AGENTS.local.md", ".codex/AGENTS.md"],
    "gemini": ["GEMINI.md"],
    "cursor": [".cursorrules"],
    "windsurf": [".windsurfrules"],
    "copilot": [".github/copilot-instructions.md"],
    "cline": [".clinerules"],
    "opencode": [".opencode/AGENTS.md"],
}


# --------------------------------------------------------------------------- MCP parsing
def mcp_items_from_dict(tool: str, servers: dict, source: Path, scope: str, items: list):
    for name, cfg in (servers or {}).items():
        if not isinstance(cfg, dict):
            continue
        cmd = cfg.get("command") or cfg.get("url") or cfg.get("httpUrl") or ""
        flags, note = [], f"{scope}: {cmd}"
        if cfg.get("disabled") or cfg.get("enabled") is False:
            flags.append("disabled")
        base = source.parent
        cmdv = cfg.get("command") or ""
        if cmdv.startswith("./") or cmdv.startswith("../"):
            cmdv = str(base / cmdv)
        if cmdv and not which_ok(cmdv):
            flags.append("missing-binary")
        cwd = cfg.get("cwd")
        if cwd and not (base / os.path.expanduser(cwd)).exists():
            flags.append("missing-cwd")
        items.append(Item(tool, "mcp", name, str(source), 0, source.stat().st_mtime if source.exists() else 0,
                          "config", note[:90], flags))


TOML_SECTION = re.compile(r"^\[mcp_servers\.([^\].]+)\]\s*$", re.M)
TOML_KV = re.compile(r'^\s*(\w+)\s*=\s*"([^"]*)"', re.M)


def parse_codex_toml_mcp(p: Path) -> dict:
    """Minimal parser for [mcp_servers.NAME] tables (py3.9 has no tomllib)."""
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return {}
    out = {}
    matches = list(TOML_SECTION.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = text.find("\n[", start)
        block = text[start:end if end != -1 else None]
        cfg = {k: v for k, v in TOML_KV.findall(block)}
        # bare booleans
        if re.search(r"^\s*enabled\s*=\s*false", block, re.M):
            cfg["enabled"] = False
        out[m.group(1)] = cfg
    return out


# --------------------------------------------------------------------------- tool scanners
def scan_claude(items: list, projects: set):
    root = HOME / ".claude"
    if not root.exists():
        return
    for name, d in skill_dirs(root / "skills"):
        it = mk("claude", "skills", name, d, note=first_line(d / "SKILL.md"))
        if not (d / "SKILL.md").exists():
            it.flags.append("no-SKILL.md")
        items.append(it)
    for f in children(root / "agents", "*.md"):
        items.append(mk("claude", "agents", f.stem, f, note=first_line(f)))
    for f in children(root / "commands", "**/*.md"):
        items.append(mk("claude", "commands", f.relative_to(root / "commands").with_suffix("").as_posix(), f, note=first_line(f)))

    plug = root / "plugins"
    installed = read_json(plug / "installed_plugins.json")
    enabled_names = set()
    for key, meta in (installed.get("plugins") or installed).items() if isinstance(installed, dict) else []:
        if isinstance(meta, dict):
            enabled_names.add(key.split("@")[0])
    for sub in ("marketplaces", "cache", "synced", "repos"):
        for d in children(plug / sub):
            it = mk("claude", "plugins", f"{sub}/{d.name}", d)
            items.append(it)

    seen = set()
    scan_instruction_file("claude", root / "CLAUDE.md", seen, items)

    cj = read_json(HOME / ".claude.json")
    mcp_items_from_dict("claude", cj.get("mcpServers"), HOME / ".claude.json", "global", items)
    for pdir, pcfg in (cj.get("projects") or {}).items():
        exists = Path(pdir).exists()
        if exists:
            projects.add(Path(pdir))
        flags = [] if exists else ["orphan"]
        n_mcp = len(pcfg.get("mcpServers") or {}) if isinstance(pcfg, dict) else 0
        items.append(Item("claude", "projects", pdir, str(HOME / ".claude.json"), 0, 0, "config",
                          f"{n_mcp} project mcp" if n_mcp else "", flags))
        if isinstance(pcfg, dict) and exists:
            mcp_items_from_dict("claude", pcfg.get("mcpServers"), HOME / ".claude.json", f"project {Path(pdir).name}", items)

    settings = read_json(root / "settings.json")
    hooks = settings.get("hooks") or {}
    for event, entries in hooks.items():
        n = sum(len(e.get("hooks", [])) if isinstance(e, dict) else 1 for e in entries) if isinstance(entries, list) else 1
        items.append(Item("claude", "hooks", event, str(root / "settings.json"), 0,
                          (root / "settings.json").stat().st_mtime, "config", f"{n} hook(s)"))
    for f in children(root / "hooks"):
        items.append(mk("claude", "hooks", f"hooks/{f.name}", f))

    # transcripts: one item per project dir under ~/.claude/projects
    encoded_known = {str(p).replace("/", "-") for p in projects}
    for d in children(root / "projects"):
        it = mk("claude", "sessions", d.name, d, note=f"{len(list(d.glob('*.jsonl')))} transcripts")
        if d.name not in encoded_known and d.name not in {str(p).replace("/", "-") for p in projects}:
            it.flags.append("orphan?")
        items.append(it)
    for name in ("cache", "paste-cache", "shell-snapshots", "session-env", "file-history",
                 "backups", "debug", "statsig", "todos", "sessions", "plans"):
        p = root / name
        if p.exists():
            items.append(mk("claude", "caches", name, p))
    for name in ("history.jsonl",):
        if (root / name).exists():
            items.append(mk("claude", "caches", name, root / name))


def scan_codex(items: list, projects: set):
    root = HOME / ".codex"
    if not root.exists():
        return
    for name, d in skill_dirs(root / "skills"):
        it = mk("codex", "skills", name, d, note=first_line(d / "SKILL.md"))
        if not (d / "SKILL.md").exists():
            it.flags.append("no-SKILL.md")
        items.append(it)
    for d in children(root / "plugins"):
        for sub in children(d) if d.is_dir() else []:
            items.append(mk("codex", "plugins", f"{d.name}/{sub.name}", sub))
    for d in children(root / "agents"):
        items.append(mk("codex", "agents", d.name, d, note=first_line(d) if d.is_file() else ""))
    for f in children(root / "rules"):
        items.append(mk("codex", "instructions", f"rules/{f.name}", f, note=first_line(f)))
    seen = set()
    scan_instruction_file("codex", root / "AGENTS.md", seen, items)
    mcp_items_from_dict("codex", parse_codex_toml_mcp(root / "config.toml"), root / "config.toml", "global", items)
    hooks = read_json(root / "hooks.json")
    for event, entries in (hooks.get("hooks") or hooks or {}).items():
        if isinstance(entries, list):
            items.append(Item("codex", "hooks", event, str(root / "hooks.json"), 0,
                              (root / "hooks.json").stat().st_mtime, "config", f"{len(entries)} hook(s)"))
    for f in children(root / "hooks"):
        items.append(mk("codex", "hooks", f"hooks/{f.name}", f))
    for name in ("sessions", "archived_sessions"):
        p = root / name
        if p.exists():
            # one item per month/day bucket if present, else the whole dir
            buckets = children(p)
            if buckets and all(b.is_dir() and re.fullmatch(r"\d{4}", b.name) for b in buckets):
                for y in buckets:
                    for mth in children(y):
                        items.append(mk("codex", "sessions", f"{name}/{y.name}/{mth.name}", mth))
            else:
                items.append(mk("codex", "sessions", name, p))
    for name in ("generated_images", "attachments", "cache", "tmp", "shell_snapshots", "log",
                 "visualizations", "vendor_imports", "dictation-history", "node_repl",
                 "computer-use", "models_cache.json", "transcription-history.jsonl", "history.jsonl"):
        p = root / name
        if p.exists():
            items.append(mk("codex", "caches", name, p))
    for f in children(root, "*.sqlite*"):
        items.append(mk("codex", "caches", f.name, f, note="sqlite (in use while Codex runs)"))
    for d in children(root / "memories"):
        items.append(mk("codex", "caches", f"memories/{d.name}", d))


def scan_gemini(items: list, projects: set):
    root = HOME / ".gemini"
    if not root.exists():
        return
    seen = set()
    scan_instruction_file("gemini", root / "GEMINI.md", seen, items)
    s = read_json(root / "settings.json")
    mcp_items_from_dict("gemini", s.get("mcpServers"), root / "settings.json", "global", items)
    for d in children(root / "skills"):
        items.append(mk("gemini", "skills", d.name, d, note=first_line(d / "SKILL.md")))
    for d in children(root / "extensions"):
        items.append(mk("gemini", "plugins", d.name, d))
    for f in children(root / "commands", "**/*.toml"):
        items.append(mk("gemini", "commands", f.stem, f))
    for name in ("tmp", "history", "antigravity-cli"):
        if (root / name).exists():
            items.append(mk("gemini", "sessions" if name in ("tmp", "history") else "caches", name, root / name))


def scan_cursor(items: list, projects: set):
    root = HOME / ".cursor"
    if not root.exists():
        return
    mcp_items_from_dict("cursor", read_json(root / "mcp.json").get("mcpServers"), root / "mcp.json", "global", items)
    for f in children(root / "rules"):
        items.append(mk("cursor", "instructions", f"rules/{f.name}", f, note=first_line(f)))
    for d in children(root / "extensions"):
        items.append(mk("cursor", "plugins", d.name, d))
    for name in ("projects", "logs"):
        if (root / name).exists():
            items.append(mk("cursor", "caches", name, root / name))


def scan_windsurf(items: list, projects: set):
    root = HOME / ".codeium" / "windsurf"
    if not root.exists():
        return
    mcp_items_from_dict("windsurf", read_json(root / "mcp_config.json").get("mcpServers"), root / "mcp_config.json", "global", items)
    for name in ("global_rules.md", "memories"):
        p = root / name
        if p.exists():
            items.append(mk("windsurf", "instructions", name, p, note=first_line(p) if p.is_file() else ""))


def scan_opencode(items: list, projects: set):
    root = HOME / ".config" / "opencode"
    if not root.exists():
        return
    cfg = read_json(root / "opencode.json") or read_json(root / "config.json")
    mcp_items_from_dict("opencode", cfg.get("mcp"), root / "opencode.json", "global", items)
    for sub, cat in (("agent", "agents"), ("agents", "agents"), ("command", "commands"), ("commands", "commands"), ("skill", "skills"), ("skills", "skills")):
        for f in children(root / sub):
            items.append(mk("opencode", cat, f.stem if f.is_file() else f.name, f, note=first_line(f) if f.is_file() else ""))
    seen = set()
    scan_instruction_file("opencode", root / "AGENTS.md", seen, items)
    store = HOME / ".local" / "share" / "opencode"
    if store.exists():
        items.append(mk("opencode", "sessions", "storage", store))


def scan_copilot(items: list, projects: set):
    root = HOME / ".copilot"
    if not root.exists():
        return
    mcp_items_from_dict("copilot", read_json(root / "mcp-config.json").get("mcpServers"), root / "mcp-config.json", "global", items)
    for name in ("session-state", "logs", "history-session-state"):
        if (root / name).exists():
            items.append(mk("copilot", "sessions" if "session" in name else "caches", name, root / name))


def scan_projects(items: list, projects: Iterable[Path]):
    """Per-project instruction files, skills, agents, commands and MCP configs."""
    for proj in sorted(set(projects)):
        if not proj.is_dir():
            continue
        tag = proj.name
        for tool, names in PROJECT_INSTRUCTION_FILES.items():
            for n in names:
                p = proj / n
                if p.exists():
                    scan_instruction_file(tool, p, set(), items, name=f"{tag}/{n}")
        for d in children(proj / ".cursor" / "rules"):
            items.append(mk("cursor", "instructions", f"{tag}/.cursor/rules/{d.name}", d, note=first_line(d)))
        for sub, cat in (("skills", "skills"), ("agents", "agents"), ("commands", "commands")):
            for d in children(proj / ".claude" / sub):
                items.append(mk("claude", cat, f"{tag}/{d.stem if d.is_file() else d.name}", d,
                                note=first_line(d / "SKILL.md" if d.is_dir() else d)))
        for name in (".mcp.json", ".cursor/mcp.json", ".vscode/mcp.json"):
            p = proj / name
            if p.exists():
                tool = "cursor" if "cursor" in name else ("copilot" if "vscode" in name else "claude")
                mcp_items_from_dict(tool, read_json(p).get("mcpServers") or read_json(p).get("servers"), p, f"project {tag}", items)
        for name in (".claude/settings.json", ".claude/settings.local.json"):
            p = proj / name
            hooks = read_json(p).get("hooks") or {}
            for event in hooks:
                items.append(Item("claude", "hooks", f"{tag}/{event}", str(p), 0, p.stat().st_mtime, "config", "project hook"))


# --------------------------------------------------------------------------- usage from Claude transcripts
USE_RE = re.compile(r'"name":"(Skill|Agent|Task|mcp__[^"]+)"|"skill":"([^"]+)"|"subagent_type":"([^"]+)"|"timestamp":"([^"]+)"')


def usage_from_claude_transcripts() -> dict:
    """Return {('skills'|'agents'|'mcp', name): last_used_epoch} by grepping jsonl."""
    last: dict = {}
    root = HOME / ".claude" / "projects"
    for f in root.glob("*/*.jsonl"):
        try:
            with open(f, errors="replace") as fh:
                for line in fh:
                    if "tool_use" not in line:
                        continue
                    ts = None
                    m = re.search(r'"timestamp":"([^"]+)"', line)
                    if m:
                        try:
                            ts = dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp()
                        except ValueError:
                            ts = None
                    if ts is None:
                        ts = f.stat().st_mtime
                    for m in re.finditer(r'"skill":"([^"]+)"', line):
                        k = ("skills", m.group(1).split(":")[-1])
                        last[k] = max(last.get(k, 0), ts)
                    for m in re.finditer(r'"subagent_type":"([^"]+)"', line):
                        k = ("agents", m.group(1))
                        last[k] = max(last.get(k, 0), ts)
                    for m in re.finditer(r'"name":"mcp__([^_"]+(?:_[^_"]+)*?)__', line):
                        k = ("mcp", m.group(1))
                        last[k] = max(last.get(k, 0), ts)
                    for m in re.finditer(r'"name":"/?([\w-]+)"', line):
                        pass
        except OSError:
            continue
    return last


# --------------------------------------------------------------------------- reporting
def fmt_age(days: int) -> str:
    if days < 0:
        return "-"
    if days < 1:
        return "today"
    if days < 60:
        return f"{days}d"
    if days < 730:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def print_report(items: list[Item], older_than: Optional[int], min_size: int):
    by_tool: dict = {}
    for it in items:
        by_tool.setdefault(it.tool, {}).setdefault(it.category, []).append(it)
    grand = 0
    for tool in sorted(by_tool):
        tool_total = sum(i.size for c in by_tool[tool].values() for i in c)
        grand += tool_total
        print(f"\n\033[1m== {tool.upper()}  ({human(tool_total)})\033[0m")
        for cat in CATEGORIES:
            rows = by_tool[tool].get(cat)
            if not rows:
                continue
            rows.sort(key=lambda i: -i.size)
            total = sum(i.size for i in rows)
            print(f"\n  {cat:<13}{len(rows):>4} items  {human(total):>8}")
            for it in rows:
                if it.size < min_size and not it.flags:
                    continue
                stale = older_than is not None and it.age_days >= older_than and it.kind != "config"
                marks = list(it.flags)
                if it.last_used:
                    marks.append(f"used {fmt_age(int((NOW - it.last_used) / 86400))} ago")
                elif it.category in ("skills", "agents", "mcp") and it.tool == "claude" and _usage_scanned:
                    marks.append("never used")
                if stale:
                    marks.append("stale")
                mark = ("  \033[33m[" + ", ".join(marks) + "]\033[0m") if marks else ""
                name = it.name if len(it.name) <= 44 else "…" + it.name[-43:]
                size = human(it.size) if it.kind != "config" else ""
                print(f"    {name:<45}{size:>8}  {fmt_age(it.age_days):>6}  {it.note[:60]}{mark}")
    print(f"\n\033[1mTotal on disk: {human(grand)}\033[0m")
    print("Report-only categories (edit the listed file to remove): mcp, hooks, instructions, projects.")


_usage_scanned = False


# --------------------------------------------------------------------------- clean
def unique_dest(dest: Path) -> Path:
    """Avoid nesting a moved dir inside an existing one of the same name."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cand, n = dest, 1
    while cand.exists():
        n += 1
        cand = dest.with_name(f"{dest.name}~{n}")
    return cand


def do_clean(items: list[Item], category: str, tool: Optional[str], older_than: Optional[int],
             names: list[str], yes: bool):
    if category not in CLEANABLE:
        sys.exit(f"'{category}' is report-only. Cleanable: {', '.join(sorted(CLEANABLE))}")
    cands = [i for i in items if i.category == category and i.cleanable
             and (tool is None or i.tool == tool)
             and (older_than is None or i.age_days >= older_than)
             and (not names or any(n in i.name for n in names))]
    if not cands:
        print("Nothing matches.")
        return
    cands.sort(key=lambda i: -i.size)
    print(f"\nCandidates ({category}):")
    for n, it in enumerate(cands, 1):
        print(f"  {n:>3}. {it.tool:<9}{it.name:<45}{human(it.size):>8}  {fmt_age(it.age_days):>6}  {it.path}")
    print(f"       total {human(sum(i.size for i in cands))}")
    if not yes:
        sel = input("\nMove which to Trash? [all / 1,3,5 / q]: ").strip().lower()
        if sel in ("", "q", "n"):
            print("Aborted.")
            return
        if sel != "all":
            try:
                idx = {int(x) for x in re.split(r"[,\s]+", sel) if x}
            except ValueError:
                sys.exit("Bad selection.")
            cands = [it for n, it in enumerate(cands, 1) if n in idx]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_root = HOME / ".Trash" / f"skill-issue-{stamp}"
    dest_root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for it in cands:
        src = Path(it.path)
        dest = unique_dest(dest_root / it.tool / it.category / src.name)
        try:
            shutil.move(str(src), str(dest))
            manifest.append({"from": str(src), "to": str(dest), "size": it.size})
            print(f"  moved  {src}")
        except OSError as e:
            print(f"  FAILED {src}: {e}")
    (dest_root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nMoved {len(manifest)} item(s), {human(sum(m['size'] for m in manifest))}, to {dest_root}")
    print("Restore with:  skill_issue.py restore " + str(dest_root))


def do_restore(trash_dir: Path):
    manifest = read_json(trash_dir / "manifest.json")
    if not manifest:
        sys.exit("No manifest found.")
    for m in manifest:
        src, dst = Path(m["to"]), Path(m["from"])
        if not src.exists():
            print(f"  missing {src}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        print(f"  restored {dst}")



# --------------------------------------------------------------------------- warnings
def warnings_for(it: Item) -> list[str]:
    """Human-readable cautions shown before an item is moved to Trash."""
    w = []
    if it.category == "sessions":
        w.append("session transcripts: resume/history for these conversations will be lost")
    if it.category == "caches" and ".sqlite" in it.name:
        w.append("sqlite database: quit " + it.tool.title() + " first, it is locked while running")
    if it.category == "caches" and it.name in ("file-history", "backups"):
        w.append("file-history/backups: used to undo agent edits")
    if it.category in ("skills", "agents", "commands"):
        w.append(f"{it.category[:-1]} will be unavailable in every project")
        if "synced" in it.path:
            w.append("synced from claude.ai: it will probably come back on the next sync")
        if it.last_used and (NOW - it.last_used) < 30 * 86400:
            w.append("used within the last 30 days")
    if it.category == "plugins":
        if "marketplaces" in it.name or "cache" in it.name:
            w.append("plugin cache/marketplace: installed plugins may break until re-synced")
        else:
            w.append("plugin will be removed")
    if it.mtime and it.age_days < 7:
        w.append("modified within the last 7 days")
    if "orphan?" in it.flags:
        w.append("project dir not in ~/.claude.json (may be orphaned, or just opened elsewhere)")
    return w


# --------------------------------------------------------------------------- TUI
def do_tui(items: list[Item]):
    import curses

    def run(scr):
        curses.curs_set(0)
        curses.use_default_colors()
        has_color = curses.has_colors()
        if has_color:
            curses.init_pair(1, curses.COLOR_YELLOW, -1)   # flags / warnings
            curses.init_pair(2, curses.COLOR_GREEN, -1)    # selected
            curses.init_pair(3, curses.COLOR_RED, -1)      # danger
            curses.init_pair(4, curses.COLOR_CYAN, -1)     # headers
            curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE)  # cursor bar
        C = (lambda n: curses.color_pair(n)) if has_color else (lambda n: 0)

        # rows: ("tool", name) | ("cat", tool, cat, [items]) | ("item", Item)
        by_tool: dict = {}
        for it in items:
            by_tool.setdefault(it.tool, {}).setdefault(it.category, []).append(it)
        collapsed = {(t, c) for t in by_tool for c in by_tool[t] if c not in CLEANABLE}
        selected: set = set()
        cursor, top = 0, 0
        status = ""

        def build_rows():
            rows = []
            for tool in sorted(by_tool):
                tsize = sum(i.size for c in by_tool[tool].values() for i in c)
                rows.append(("tool", tool, tsize))
                for cat in CATEGORIES:
                    its = by_tool[tool].get(cat)
                    if not its:
                        continue
                    its.sort(key=lambda i: -i.size)
                    rows.append(("cat", tool, cat, its))
                    if (tool, cat) not in collapsed:
                        for it in its:
                            rows.append(("item", it))
            return rows

        def draw(rows):
            nonlocal top
            scr.erase()
            h, w = scr.getmaxyx()
            body = h - 3
            if cursor < top:
                top = cursor
            elif cursor >= top + body:
                top = cursor - body + 1
            sel_size = sum(i.size for i in selected)
            title = f" skill-issue  {len(selected)} selected, {human(sel_size)} "
            scr.addnstr(0, 0, title.ljust(w), w - 1, curses.A_BOLD | C(4))
            for y, row in enumerate(rows[top:top + body], start=1):
                is_cur = (top + y - 1) == cursor
                attr = C(5) if is_cur else 0
                if row[0] == "tool":
                    line = f"== {row[1].upper()}  ({human(row[2])})"
                    scr.addnstr(y, 0, line.ljust(w), w - 1, attr | curses.A_BOLD)
                elif row[0] == "cat":
                    _, tool, cat, its = row
                    n_sel = sum(1 for i in its if i in selected)
                    mark = "▸" if (tool, cat) in collapsed else "▾"
                    tag = "" if cat in CLEANABLE else "   (report-only)"
                    line = f"  {mark} {cat:<13}{len(its):>4} items  {human(sum(i.size for i in its)):>8}{tag}"
                    if n_sel:
                        line += f"   [{n_sel} selected]"
                    scr.addnstr(y, 0, line.ljust(w), w - 1, attr | C(4))
                else:
                    it = row[1]
                    box = "[x]" if it in selected else ("[ ]" if it.cleanable else "   ")
                    namew = max(20, w - 46)
                    name = it.name if len(it.name) <= namew else "…" + it.name[-(namew - 1):]
                    size = human(it.size) if it.kind != "config" else ""
                    marks = list(it.flags)
                    if it.last_used:
                        marks.append(f"used {fmt_age(int((NOW - it.last_used) / 86400))} ago")
                    left = f"     {box} {name:<{namew}}{size:>8} {fmt_age(it.age_days):>6}  "
                    scr.addnstr(y, 0, left.ljust(w), w - 1, attr | (C(2) if it in selected else 0))
                    x = len(left)
                    rest = (it.note[:40] + ("  " if it.note else "") + (("[" + ", ".join(marks) + "]") if marks else ""))
                    if x < w - 1 and rest:
                        scr.addnstr(y, x, rest, w - 1 - x, attr | (C(1) if marks else 0))
            help_ = "↑↓/jk move  space select  a all-in-category  enter fold  d delete selected  q quit"
            scr.addnstr(h - 2, 0, help_.ljust(w), w - 1, curses.A_DIM)
            scr.addnstr(h - 1, 0, status.ljust(w), w - 1, C(1))
            scr.refresh()

        def confirm(chosen: list[Item]) -> bool:
            h, w = scr.getmaxyx()
            scr.erase()
            total = sum(i.size for i in chosen)
            scr.addnstr(0, 0, f" Move {len(chosen)} item(s), {human(total)}, to Trash? ".ljust(w), w - 1, curses.A_BOLD | C(3))
            y = 2
            warn: dict = {}
            for it in chosen:
                for wtext in warnings_for(it):
                    warn.setdefault(wtext, []).append(it.name)
            if warn:
                scr.addnstr(y, 0, "Warnings:", w - 1, curses.A_BOLD | C(1)); y += 1
                for wtext, names in warn.items():
                    scr.addnstr(y, 0, f"  ! {wtext}  ({len(names)} item{'s' if len(names) > 1 else ''})", w - 1, C(1)); y += 1
                    if y >= h - 6:
                        break
                y += 1
            scr.addnstr(y, 0, "Items:", w - 1, curses.A_BOLD); y += 1
            for n, it in enumerate(chosen):
                if y >= h - 4:
                    scr.addnstr(y, 0, f"  … and {len(chosen) - n} more", w - 1); y += 1
                    break
                nm = it.name if len(it.name) <= 40 else "…" + it.name[-39:]
                scr.addnstr(y, 0, f"  {it.tool:<9}{nm:<40} {human(it.size):>8}  {it.path}", w - 1); y += 1
            scr.addnstr(h - 2, 0, "Nothing is hard-deleted; a manifest lets you restore. Press y to confirm, any other key to cancel.".ljust(w), w - 1, curses.A_DIM)
            scr.refresh()
            return scr.getch() in (ord("y"), ord("Y"))

        def perform(chosen: list[Item]):
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            dest_root = HOME / ".Trash" / f"skill-issue-{stamp}"
            dest_root.mkdir(parents=True, exist_ok=True)
            manifest, failed = [], []
            for it in chosen:
                src = Path(it.path)
                dest = unique_dest(dest_root / it.tool / it.category / src.name)
                try:
                    shutil.move(str(src), str(dest))
                    manifest.append({"from": str(src), "to": str(dest), "size": it.size})
                except OSError as e:
                    failed.append(f"{src}: {e}")
            (dest_root / "manifest.json").write_text(json.dumps(manifest, indent=2))
            for it in chosen:
                if not Path(it.path).exists():
                    for cat in by_tool[it.tool].values():
                        if it in cat:
                            cat.remove(it)
            moved = human(sum(m["size"] for m in manifest))
            return f"Moved {len(manifest)} item(s), {moved}, to {dest_root}" + (f"  FAILED: {len(failed)}" if failed else ""), failed

        rows = build_rows()
        while True:
            cursor = max(0, min(cursor, len(rows) - 1))
            draw(rows)
            k = scr.getch()
            row = rows[cursor] if rows else None
            if k in (ord("q"), 27):
                break
            elif k in (curses.KEY_DOWN, ord("j")):
                cursor += 1
            elif k in (curses.KEY_UP, ord("k")):
                cursor -= 1
            elif k == curses.KEY_NPAGE:
                cursor += scr.getmaxyx()[0] - 4
            elif k == curses.KEY_PPAGE:
                cursor -= scr.getmaxyx()[0] - 4
            elif k == ord("g"):
                cursor = 0
            elif k == ord("G"):
                cursor = len(rows) - 1
            elif k == ord(" ") and row:
                if row[0] == "item" and row[1].cleanable:
                    selected.symmetric_difference_update({row[1]})
                    cursor += 1
                elif row[0] == "item":
                    status = f"report-only: edit {row[1].path} to remove this"
                elif row[0] == "cat":
                    its = [i for i in row[3] if i.cleanable]
                    if not its:
                        status = "report-only category"
                    elif all(i in selected for i in its):
                        selected.difference_update(its)
                    else:
                        selected.update(its)
            elif k == ord("a") and row and row[0] in ("cat", "item"):
                tool, cat = (row[1], row[2]) if row[0] == "cat" else (row[1].tool, row[1].category)
                its = [i for i in by_tool[tool][cat] if i.cleanable]
                if not its:
                    status = "report-only category"
                elif all(i in selected for i in its):
                    selected.difference_update(its)
                else:
                    selected.update(its)
            elif k in (10, 13, curses.KEY_ENTER, curses.KEY_LEFT, curses.KEY_RIGHT) and row:
                key = None
                if row[0] == "cat":
                    key = (row[1], row[2])
                elif row[0] == "item":
                    key = (row[1].tool, row[1].category)
                if key:
                    collapsed.symmetric_difference_update({key})
                    rows = build_rows()
                    if row[0] == "item":
                        cursor = next(i for i, r in enumerate(rows) if r[0] == "cat" and (r[1], r[2]) == key)
            elif k in (ord("d"), ord("D"), curses.KEY_DC):
                chosen = [i for i in items if i in selected]
                if not chosen:
                    status = "nothing selected"
                elif confirm(chosen):
                    status, failed = perform(chosen)
                    selected.clear()
                    rows = build_rows()
                else:
                    status = "cancelled"
            elif k == curses.KEY_RESIZE:
                pass

    curses.wrapper(run)

# --------------------------------------------------------------------------- main
SCANNERS = {
    "claude": scan_claude, "codex": scan_codex, "gemini": scan_gemini, "cursor": scan_cursor,
    "windsurf": scan_windsurf, "opencode": scan_opencode, "copilot": scan_copilot,
}


def collect(tools: Optional[list[str]], extra_projects: list[str], usage: bool) -> list[Item]:
    global _usage_scanned
    items: list[Item] = []
    projects: set = {Path(p).expanduser().resolve() for p in extra_projects}
    for name, fn in SCANNERS.items():
        if tools and name not in tools:
            continue
        fn(items, projects)
    scan_projects(items, projects)
    if tools:
        items = [i for i in items if i.tool in tools]
    if usage:
        last = usage_from_claude_transcripts()
        _usage_scanned = True
        for it in items:
            if it.tool == "claude":
                base = it.name.split("/")[-1]
                it.last_used = last.get((it.category, base)) or last.get((it.category, it.name))
    return items


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skill-issue", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="scan", choices=["scan", "tui", "clean", "restore"])
    ap.add_argument("target", nargs="?", help="clean: category. restore: trash dir")
    ap.add_argument("--tool", action="append", choices=list(SCANNERS), help="limit to a tool (repeatable)")
    ap.add_argument("--category", action="append", choices=CATEGORIES, help="limit report to a category")
    ap.add_argument("--older-than", type=int, metavar="DAYS", help="flag/select items not modified in DAYS")
    ap.add_argument("--min-size", default="0", help="hide unflagged items smaller than this, e.g. 1M")
    ap.add_argument("--project", action="append", default=[], help="extra project dir to inspect")
    ap.add_argument("--name", action="append", default=[], help="clean: substring filter on item name")
    ap.add_argument("--usage", action="store_true", help="grep Claude transcripts for last use of skills/agents/mcp")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-y", "--yes", action="store_true", help="clean without prompting")
    a = ap.parse_args(argv)

    if a.command == "restore":
        if not a.target:
            sys.exit("restore needs the trash directory path")
        do_restore(Path(a.target))
        return

    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmg]?)", a.min_size.lower())
    min_size = int(float(m.group(1)) * {"": 1, "k": 1 << 10, "m": 1 << 20, "g": 1 << 30}[m.group(2)]) if m else 0

    items = collect(a.tool, a.project, a.usage)
    if a.category:
        items = [i for i in items if i.category in a.category]

    if a.command == "tui":
        do_tui(items)
        return

    if a.command == "clean":
        if not a.target:
            sys.exit("clean needs a category: " + ", ".join(sorted(CLEANABLE)))
        do_clean(items, a.target, a.tool[0] if a.tool else None, a.older_than, a.name, a.yes)
        return

    if a.json:
        out = [dict(asdict(i), age_days=i.age_days, cleanable=i.cleanable) for i in items]
        print(json.dumps(out, indent=1))
        return
    print_report(items, a.older_than, min_size)


if __name__ == "__main__":
    main()
