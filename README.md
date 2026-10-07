# skill-issue

DevCleaner for Xcode, but for AI coding agents. One script that audits what
Claude Code, Codex, Gemini CLI, Cursor, Windsurf, OpenCode and Copilot have
left on your Mac, and lets you move the dead weight to the Trash.

It finds skills, plugins, agents, slash commands, instruction files such as
`CLAUDE.md` and `AGENTS.md`, MCP server configs, hooks, session transcripts
and caches. It shows size, age and last use, flags anything broken or
orphaned, and offers a terminal picker for clearing things out.

> **Use at your own risk.** This tool moves files out of the folders your AI
> tools depend on. It is careful, and everything it moves goes to the Trash
> with a restore manifest, but it is not magic and it can still break a tool
> setup or cost you conversation history. Read the [disclaimer](#disclaimer)
> before cleaning anything. Running the audit on its own is read-only.

## Requirements

- macOS. Linux will mostly work but the Trash locations and some paths are
  Mac-specific.
- Python 3.9 or newer. The copy that ships with macOS and the Xcode Command
  Line Tools is fine. There are no third-party dependencies.

## Install

Clone the repository and run the script directly:

```bash
git clone https://github.com/<you>/skill-issue.git
cd skill-issue
python3 skill_issue.py
```

To run it from anywhere as `skill-issue`, link it into a folder on your PATH:

```bash
chmod +x skill_issue.py
ln -s "$(pwd)/skill_issue.py" /usr/local/bin/skill-issue
```

If `/usr/local/bin` doesn't exist or isn't writable, use `~/.local/bin` and
make sure it is on your PATH.

To uninstall, delete the symlink and the cloned folder. The tool keeps no
state of its own outside the Trash folders it creates during a clean.

## Usage

### Audit

```bash
skill-issue                         # full report, grouped by tool and category
skill-issue --tool codex            # one tool (repeatable)
skill-issue --category mcp          # one category (repeatable)
skill-issue --usage                 # add last-used info from Claude transcripts
skill-issue --older-than 60         # mark items untouched for 60 days as stale
skill-issue --min-size 1M           # hide unflagged items smaller than 1 MB
skill-issue --project ~/src/foo     # also inspect a project directory
skill-issue --json                  # machine-readable output
```

Tools: `claude`, `codex`, `gemini`, `cursor`, `windsurf`, `opencode`, `copilot`.

Categories and what they cover:

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

Flags that can appear next to an item:

- `broken-include`: an instruction file `@includes` a path that no longer exists
- `missing-binary`: an MCP server's command isn't on PATH or at the given path
- `missing-cwd`: an MCP server's working directory is gone
- `disabled`: the server is present but switched off
- `orphan`: a project entry whose directory no longer exists
- `no-SKILL.md`: a skill directory with no manifest
- `used Nd ago` / `no use in window`: from `--usage`, which reads Claude transcripts for Skill, Agent and MCP tool calls. Claude Code deletes transcripts after 30 days by default, so the report states how far back the evidence goes.
- `stale`: older than `--older-than`

### Interactive picker

```bash
skill-issue tui
skill-issue tui --tool codex --usage
```

A curses screen grouped by tool and category.

| Key | Action |
|---|---|
| `↑` `↓` `j` `k` | move |
| `space` | select or deselect an item, or every item in a category |
| `a` | select or deselect everything in the current category |
| `enter` | fold or unfold a category |
| `d` | review and move the selection to Trash |
| `q` | quit |

Report-only categories (mcp, hooks, instructions, projects) are folded and
cannot be selected. Pressing space on one tells you which file to edit.
Pressing `d` shows a confirmation screen listing every item and the warnings
that apply, for example transcripts that will lose resume history, sqlite
files that need the app closed first, skills used in the last 30 days, or
synced skills that will come back on the next sync. Nothing moves until you
press `y`.

### Cleaning from the command line

```bash
skill-issue clean sessions --tool codex --older-than 90
skill-issue clean skills --tool claude                        # interactive pick list
skill-issue clean caches --name generated_images -y
skill-issue clean sessions --tool codex --name 'sessions/2026/0[3-6]' -y
skill-issue restore ~/.Trash/skill-issue-20260918-130501
```

Only file-backed categories can be cleaned: `skills plugins agents commands
sessions caches`. `--name` matches an item name or its last path segment
exactly, with `*` and `?` globs allowed. `--yes` needs at least one of
`--tool`, `--older-than` or `--name`, so a stray command can't empty a whole
category unattended. The command-line path prints the same warnings as the
picker's confirmation screen.

### How cleaning works

Nothing is hard-deleted and nothing is copied. Each item is renamed into a
`skill-issue-<timestamp>/` folder in the Trash of the volume it lives on:
`~/.Trash` for the boot volume, or `/Volumes/<disk>/.Trashes/<uid>` for an
external drive. A `manifest.json` in that folder records where everything
came from, and `restore` renames it all back. A move that would have to cross
volumes is refused rather than copied and deleted. The restore path is
printed after every clean; keep it, because macOS does not let the terminal
list an external drive's `.Trashes` folder.

MCP servers, hooks, instruction files and project entries are report-only.
Removing those means editing a config file that other things depend on, so
the report tells you which file to open instead.

## Disclaimer

**This software is used entirely at your own risk.** It moves files out of
the configuration and cache directories of third-party software. By running
a clean you accept that you, not the author, are responsible for the
outcome. Before you clean anything, understand what you are agreeing to:

- **You are responsible for what you select.** The tool shows sizes, ages,
  descriptions and warnings to help you decide. It does not know which of
  your skills, sessions or caches matter to you.
- **Session transcripts are conversation history.** Removing them means the
  agent can no longer resume or search those conversations. Some tools also
  keep undo history for file edits in their cache folders.
- **Quit the app first.** Codex keeps sqlite databases open while it runs.
  Moving an open database can corrupt it. The same caution applies to any
  agent that is running while you clean.
- **Synced content may come back.** Skills synced from claude.ai will
  re-download on the next sync. Plugin marketplaces and caches will re-fetch.
- **Trash is not a backup.** Emptying the Trash makes the move permanent.
  Restore first if you change your mind.
- **Paths change.** The agent vendors move files and formats between
  releases. The tool reads known locations as of September 2026 and may
  miss, or misclassify, newer ones.
- **No warranty, no liability.** This is provided "as is" under the MIT
  License, used at your own risk. The author accepts no liability for lost
  data, lost conversation history, broken tool installations, or anything
  else that follows from using it. If you can't afford to lose something,
  back it up first. Time Machine or a copy of `~/.claude`, `~/.codex` and
  friends is enough.

This project is not affiliated with or endorsed by Anthropic, OpenAI,
Google, Cursor, Codeium, or any other vendor whose files it reads.

## Safety notes

- The tool never executes anything. MCP commands are checked for existence
  only. There is no subprocess or shell call in the script.
- Everything read from disk is treated as untrusted. Reads are capped at 4 MB
  and only regular files are opened, so an `@include` pointing at a device or
  FIFO can't hang it. Symlinks are followed only when they resolve inside
  your home directory. The `--usage` transcript scan reads newest files first
  and stops after 2 GB. Names and descriptions have control and escape bytes
  stripped before display, so a downloaded skill can't rewrite the report.
- `restore` only accepts manifest entries whose source is inside the given
  Trash folder and whose destination doesn't already exist. From `~/.Trash`
  the destination must be inside your home. From an external volume's
  `.Trashes` it must be on that volume.
- URLs in MCP notes are reduced to scheme and host, so credentials in
  userinfo, paths, query strings or fragments don't end up in pasted reports.
- Each clean gets a Trash folder that did not exist before, so two cleans in
  the same second can't overwrite each other's manifest.

## License

[MIT](LICENSE). Copyright (c) 2026 David John Smailes.
