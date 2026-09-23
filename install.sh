#!/usr/bin/env bash
# Install claude-code-statusline: copy statusline.sh into the Claude config directory and point the
# statusLine entry of settings.json at it. The entry it replaces is kept for uninstall.sh.
#
#   ./install.sh           powerline glyphs (a Nerd Font, or a terminal that draws them itself)
#   ./install.sh --plain   no private-use glyphs, for any other font
#
# The config directory is $CLAUDE_CONFIG_DIR, or ~/.claude when that is unset.
set -euo pipefail

glyphs=""
case "${1:-}" in
  "") ;;
  --plain) glyphs=plain ;;
  -h | --help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
esac

command -v jq > /dev/null || { echo "jq is required: brew install jq, or apt install jq" >&2; exit 1; }

src="$(cd "$(dirname "$0")" && pwd)/statusline.sh"
config="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
dir="$config/claude-code-statusline"
settings="$config/settings.json"

mkdir -p "$config"
[ -f "$settings" ] || printf '{}\n' > "$settings"
if ! jq -e 'type == "object"' "$settings" > /dev/null 2>&1; then
  echo "$settings is not a JSON object; fix it, or add the statusLine entry by hand (see README)." >&2
  exit 1
fi

mkdir -p "$dir"
cp "$src" "$dir/statusline.sh"
chmod +x "$dir/statusline.sh"

# Keep the statusLine being replaced, unless it is already ours (a reinstall or an upgrade).
if [ ! -f "$dir/previous-statusline.json" ]; then
  jq '.statusLine // null | if (.command? // "") | contains("claude-code-statusline/statusline.sh")
      then null else . end' "$settings" > "$dir/previous-statusline.json"
fi

command="bash \"$dir/statusline.sh\""
[ -n "$glyphs" ] && command="STATUSLINE_GLYPHS=$glyphs $command"

backup="$settings.bak-$(date +%Y%m%d-%H%M%S)"
cp "$settings" "$backup"
tmp=$(mktemp "$settings.XXXXXX")
jq --arg command "$command" '.statusLine = {type: "command", command: $command, refreshInterval: 30}' \
  "$settings" > "$tmp"
cat "$tmp" > "$settings"  # write through, keeping the file's permissions and any symlink
rm -f "$tmp"

echo "Installed $dir/statusline.sh"
echo "Updated statusLine in $settings (backup: $backup)"
echo "Preview every state with: bash \"$dir/statusline.sh\" --demo"
