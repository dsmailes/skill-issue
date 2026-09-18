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

## Interactive picker

```bash
python3 skill_issue.py tui
python3 skill_issue.py tui --tool codex --usage
```

A curses screen grouped by tool and category. Keys:

| Key | Action |
|---|---|
| `↑` `↓` `j` `k` | move |
| `space` | select / deselect an item, or every item in a category |
| `a` | select / deselect everything in the current category |
| `enter` | fold / unfold a category |
| `d` | review and move the selection to Trash |
| `q` | quit |

Report-only categories (mcp, hooks, instructions, projects) are folded and
cannot be selected; pressing space on one tells you which file to edit.
Pressing `d` shows a confirmation screen that lists every item and the
warnings that apply, for example transcripts that will lose resume history,
sqlite files that need the app closed first, skills used in the last 30 days,
or synced skills that will come back on the next sync. Nothing moves until you
press `y`.

## Cleaning from the command line

```bash
python3 skill_issue.py clean sessions --tool codex --older-than 90
python3 skill_issue.py clean skills --tool claude            # interactive pick list
python3 skill_issue.py clean caches --name generated_images -y
python3 skill_issue.py restore ~/.Trash/skill-issue-20260918-130501
```

Only file-backed categories can be cleaned: `skills plugins agents commands
sessions caches`. Nothing is hard-deleted and nothing is copied. Each item is
renamed into a `skill-issue-<timestamp>/` folder in the Trash of the volume it
lives on (`~/.Trash`, or `/Volumes/<disk>/.Trashes/<uid>` for an external
drive), with a `manifest.json`. `restore` renames them back. A move that
would have to cross volumes is refused rather than copied and deleted.

`clean --yes` needs at least one of `--tool`, `--older-than` or `--name`, so
a stray command can't empty a whole category unattended. The command-line
path prints the same warnings as the TUI's confirmation screen.

## Safety notes

- The tool never executes anything. MCP commands are checked for existence
  only, and there is no subprocess or shell call in the script.
- Everything read from disk is treated as untrusted. Reads are capped at 4 MB
  and only regular files are opened, so an `@include` pointing at a device or
  FIFO can't hang it. Symlinks are followed only when they resolve inside
  your home directory, which keeps dotfile-manager setups working without
  letting a config file point the tool at arbitrary files. The `--usage`
  transcript scan reads newest files first and stops after 2 GB. Names and descriptions have control and escape bytes
  stripped before display, so a downloaded skill can't rewrite the report.
- `restore` only accepts manifest entries whose source is inside the given
  Trash folder and whose destination doesn't already exist. From `~/.Trash`
  the destination must be inside your home; from an external volume's
  `.Trashes` it must be on that volume.
- URLs in MCP notes are reduced to scheme and host, so credentials in
  userinfo, paths, query strings or fragments don't end up in pasted reports.
- Each clean gets a Trash folder that did not exist before, so two cleans in
  the same second can't overwrite each other's manifest.

MCP servers, hooks, instruction files and project entries are report-only.
Removing those means editing a config file that other things depend on, so the
report tells you which file to open instead.

Quit Codex before cleaning its sqlite files. They're locked while it runs.
