#!/usr/bin/env bash
# Uninstall claude-code-statusline: put back the statusLine and subagentStatusLine entries that
# install.sh replaced (or drop an entry when there was none) and delete the installed files. An entry
# changed since installing is left alone. The config directory is $CLAUDE_CONFIG_DIR, or ~/.claude when
# that is unset.
set -euo pipefail

command -v jq > /dev/null || { echo "jq is required: brew install jq, or apt install jq" >&2; exit 1; }

config="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
dir="$config/claude-code-statusline"
settings="$config/settings.json"

restore() {  # restore <settings key> <file>: put back the saved entry if the current one is ours
  local previous=null tmp
  if [ -f "$settings" ] && jq -e --arg key "$1" \
    '(.[$key].command? // "") | contains("claude-code-statusline/statusline.sh")' "$settings" > /dev/null 2>&1; then
    [ -f "$dir/$2" ] && previous=$(cat "$dir/$2")
    [ -n "$backup" ] || { backup="$settings.bak-$(date +%Y%m%d-%H%M%S)"; cp "$settings" "$backup"; }
    tmp=$(mktemp "$settings.XXXXXX")
    jq --arg key "$1" --argjson previous "$previous" \
      'if $previous == null then del(.[$key]) else .[$key] = $previous end' "$settings" > "$tmp"
    cat "$tmp" > "$settings"
    rm -f "$tmp"
    echo "Restored the previous $1 in $settings (backup: $backup)"
  else
    echo "The $1 in $settings does not point at claude-code-statusline; left it unchanged."
  fi
}

backup=""
restore statusLine previous-statusline.json
restore subagentStatusLine previous-subagent-statusline.json

rm -rf "$dir"
echo "Removed $dir"
