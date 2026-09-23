# claude-code-statusline

A two-row powerline status line for [Claude Code](https://code.claude.com/docs/en/statusline).
The top row shows the model, effort, repository, git and PR state. The bottom row shows color-graded
gauges for the context window and your plan's usage limits.

![Demo in a dark terminal](docs/demo-dark.png)

[한국어](README.ko.md)

## What it shows

**Row 1**: chips joined by powerline arrows, then session stats.

| Chip | Content | Color |
|---|---|---|
| Model | `Opus 5.5` (the context-size suffix is dropped) | purple Opus, cyan Sonnet, teal Haiku, orange Fable |
| Effort | `max`, `xhigh`, `high`, `medium`, `low`, plus `fast` in fast mode | red, orange, yellow, teal, slate |
| Directory | repository name, the path below the checkout root, and a linked worktree's name when it differs from the branch | blue |
| Git | branch, `⇡` ahead, `⇣` behind, `✘` conflicts, `+` staged, `~` modified, `?` untracked | green when clean, yellow when dirty, red on conflicts |
| PR / MR | `#512` on GitHub, `!512` on GitLab; Cmd/Ctrl+click opens it | teal approved, red changes requested, cyan pending, slate draft |

After the chips come the session cost, duration, lines added and removed, and the time left before the
prompt cache expires.

**Row 2**: gauges.

- `ctx`: context window used, with the token count (`283k/1M`). The count turns yellow past 200k tokens.
- `5h` / `7d`: plan usage limits (Pro and Max plans), with the time until each resets (`↻1h12m`).
- `⚠~45m`: at the window's average pace so far, the limit runs out in about 45 minutes, before it resets.
- Bars are shaded cell by cell from green to red. Percentages turn yellow at 50%, orange at 65%, and red
  at 80%.

On narrow terminals the bars shrink first. Then the cache, lines, duration, cost, PR and effort drop out,
and finally the directory and branch are shortened.

## Install

Requirements: Claude Code, bash 3.2 or later, [jq](https://jqlang.org) (preinstalled on recent macOS),
and git (optional).

```bash
git clone https://github.com/m16khb-org/claude-code-statusline.git
cd claude-code-statusline
./install.sh           # or ./install.sh --plain when your font has no powerline glyphs
```

The installer copies `statusline.sh` to `~/.claude/claude-code-statusline/` (`$CLAUDE_CONFIG_DIR` when it
is set), backs up `settings.json`, and sets its `statusLine` entry:

```json
"statusLine": {
  "type": "command",
  "command": "bash \"/Users/you/.claude/claude-code-statusline/statusline.sh\"",
  "refreshInterval": 30
}
```

Claude Code picks up the change right away. To update, run `git pull && ./install.sh`. To remove it,
run `./uninstall.sh`, which restores the statusLine you had before.

Preview every state without starting Claude Code:

```bash
bash ~/.claude/claude-code-statusline/statusline.sh --demo
```

## Fonts, colors and themes

- **Powerline glyphs** (U+E0A0, U+E0B0, U+E0B1) need a [Nerd Font](https://www.nerdfonts.com) or a
  terminal that draws them itself, such as the xterm.js-based terminal in VS Code. If they show up as
  boxes, reinstall with `./install.sh --plain`, which turns the chips into separate badges:

  ![Plain glyph mode](docs/plain-dark.png)

- **Colors**: 24-bit when `COLORTERM` is `truecolor` or `24bit`, otherwise the nearest 256-color values.
- **Theme**: Tokyo Night on dark backgrounds and Tokyo Night Day on light ones, following the macOS
  appearance. On other systems it defaults to dark.

![Demo in a light terminal](docs/demo-light.png)

## Settings

Put these variables in front of the command in `settings.json`, for example
`"command": "STATUSLINE_THEME=light bash \"/Users/you/.claude/claude-code-statusline/statusline.sh\""`.

| Variable | Values | Default |
|---|---|---|
| `STATUSLINE_THEME` | `dark`, `light` | the macOS appearance, otherwise `dark` |
| `STATUSLINE_GLYPHS` | `powerline`, `plain` | `powerline` |
| `STATUSLINE_COLORS` | `truecolor`, `256` | from `COLORTERM` |

## Speed

A render takes about 20 to 40 ms. One `jq` call reads the session JSON. `git status` runs in the
background and its result is cached for 5 seconds, so a slow repository never delays a render. Claude
Code cancels a render that is still running when the next update arrives, so a slow script would miss
updates.

## Development

```bash
python3 test/test_statusline.py                      # rendering behavior
python3 test/test_install.py                          # install.sh and uninstall.sh
TEST_BASH=/bin/bash python3 test/test_statusline.py   # macOS's bash 3.2
```

`STATUSLINE_GIT_RAW` injects `git status --porcelain=v2 --branch` output, so tests do not depend on a real
repository. The screenshots are rendered with `tools/render_png.py`, which needs Pillow and a monospace
font.

## License

[MIT](LICENSE)
