# skill-issue

DevCleaner for Xcode, but for AI coding agents. One script that audits what
Claude Code, Codex, Gemini CLI, Cursor, Windsurf, OpenCode and Copilot have
left on your Mac, and lets you move the dead weight to the Trash.

No dependencies. Python 3.9+ (the one that ships with macOS).

```bash
python3 skill_issue.py                       # full audit
python3 skill_issue.py --tool codex          # one tool
python3 skill_issue.py --category mcp        # one category
python3 skill_issue.py --usage               # grep Claude transcripts for last use
python3 skill_issue.py --older-than 60       # mark items untouched for 60 days
python3 skill_issue.py --project ~/src/foo   # also inspect a project dir
python3 skill_issue.py --json                # machine-readable
```

## What it finds

| Category | Examples |
|---|---|
| skills | `~/.claude/skills/*`, `~/.codex/skills/*`, `~/.gemini/skills/*`, project `.claude/skills` |
| plugins | Claude marketplaces and caches, Codex plugin caches, Gemini extensions, Cursor extensions |
| agents | `~/.claude/agents/*.md`, `~/.codex/agents`, OpenCode agents |
| commands | Claude slash commands, Gemini commands, OpenCode commands |
| instructions | `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.windsurfrules`, `.clinerules`, `copilot-instructions.md`, Codex rules, Cursor rules, and every `@include` they chain to |
| mcp | servers from `~/.claude.json`, Codex `config.toml`, Gemini and Cursor settings, Windsurf, OpenCode, Copilot, project `.mcp.json` |
| hooks | Claude and Codex hook config, project hooks |
| sessions | Claude transcripts per project, Codex sessions per month, archived sessions, Gemini tmp |
| caches | sqlite logs, generated images, shell snapshots, file history, paste caches |
| projects | every project Claude remembers, flagged when the directory is gone |

## Flags

- `broken-include`: an instruction file `@includes` a path that no longer exists
- `missing-binary`: an MCP server's command isn't on PATH or at the given path
- `missing-cwd`: an MCP server's working directory is gone
- `disabled`: the server is present but switched off
- `orphan`: a project entry whose directory no longer exists
- `no-SKILL.md`: a skill directory with no manifest
- `never used` / `used Nd ago`: from `--usage`, which greps Claude transcripts for Skill, Agent and MCP tool calls
- `stale`: older than `--older-than`

## Cleaning

```bash
python3 skill_issue.py clean sessions --tool codex --older-than 90
python3 skill_issue.py clean skills --tool claude            # interactive pick list
python3 skill_issue.py clean caches --name generated_images -y
python3 skill_issue.py restore ~/.Trash/skill-issue-20260918-130501
```

Only file-backed categories can be cleaned: `skills plugins agents commands
sessions caches`. Nothing is hard-deleted. Items move to
`~/.Trash/skill-issue-<timestamp>/` with a `manifest.json`, and `restore`
puts them back.

MCP servers, hooks, instruction files and project entries are report-only.
Removing those means editing a config file that other things depend on, so the
report tells you which file to open instead.

Quit Codex before cleaning its sqlite files. They're locked while it runs.
