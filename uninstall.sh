#!/usr/bin/env bash
# Uninstall claude-code-statusline: put back the statusLine entry that install.sh replaced (or drop the
# entry when there was none) and delete the installed files. A statusLine changed since installing is
# left alone. The config directory is $CLAUDE_CONFIG_DIR, or ~/.claude when that is unset.
set -euo pipefail

command -v jq > /dev/null || { echo "jq is required: brew install jq, or apt install jq" >&2; exit 1; }

config="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
dir="$config/claude-code-statusline"
settings="$config/settings.json"

if [ -f "$settings" ] &&
  jq -e '(.statusLine.command? // "") | contains("claude-code-statusline/statusline.sh")' "$settings" > /dev/null 2>&1; then
  previous=null
  [ -f "$dir/previous-statusline.json" ] && previous=$(cat "$dir/previous-statusline.json")
  backup="$settings.bak-$(date +%Y%m%d-%H%M%S)"
  cp "$settings" "$backup"
  tmp=$(mktemp "$settings.XXXXXX")
  jq --argjson previous "$previous" \
    'if $previous == null then del(.statusLine) else .statusLine = $previous end' "$settings" > "$tmp"
  cat "$tmp" > "$settings"
  rm -f "$tmp"
  echo "Restored the previous statusLine in $settings (backup: $backup)"
else
  echo "The statusLine in $settings does not point at claude-code-statusline; left it unchanged."
fi

rm -rf "$dir"
echo "Removed $dir"
