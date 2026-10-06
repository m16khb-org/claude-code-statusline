#!/bin/bash
# claude-code-statusline: a two-row powerline status line for Claude Code.
# https://github.com/m16khb-org/claude-code-statusline (MIT)
#
#   Row 1  [model][effort] [dir] [git] [PR/MR]  cost · duration · +added −removed vs HEAD · cache TTL
#   Row 2  ctx / 5h / 7d / per-model weekly (e.g. Fable) gauges: gradient bar, used %, reset countdown (↻), and a red ⚠ time-to-limit
#          warning when the window's average pace would exhaust it before the reset.
# Usage colors: <50% green, 50-64 yellow, 65-79 orange, >=80 red. Narrow terminals ($COLUMNS) shrink
# the bars first, then drop cache → lines → duration → cost → PR → effort, cut dir and branch short,
# and finally drop the dir chip.
#
# With --subagents it draws the agent panel's rows instead (the subagentStatusLine setting):
#   [model][effort] name · activity   ctx gauge, tokens · running time, or ✓/✘ once finished
#
# Settings (environment variables, e.g. prefixed to the statusLine command):
#   STATUSLINE_THEME=dark|light       default: macOS appearance, else dark
#   STATUSLINE_GLYPHS=powerline|plain plain avoids the private-use powerline glyphs, for fonts
#                                     without them (default: powerline)
#   STATUSLINE_COLORS=truecolor|256   default: truecolor when COLORTERM says so, else 256
# Preview every state: bash statusline.sh --demo

E=$'\033'
BEL=$'\007'
# Powerline glyphs live in the private use area; build them from UTF-8 bytes so no editor strips them.
if [ "$STATUSLINE_GLYPHS" = plain ]; then
  PL_ARROW="" PL_THIN="" PL_BRANCH="" UP="↑" DOWN="↓"
else
  PL_ARROW=$'\xee\x82\xb0'  # U+E0B0
  PL_THIN=$'\xee\x82\xb1'   # U+E0B1
  PL_BRANCH=$'\xee\x82\xa0' # U+E0A0
  UP="⇡" DOWN="⇣"
fi
case "${STATUSLINE_COLORS:-$COLORTERM}" in
  truecolor | 24bit) COLOR_MODE=24 ;;
  *) COLOR_MODE=256 ;;
esac
CACHE_DIR="${TMPDIR:-/tmp}/claude-statusline"
GIT_TTL=5
USAGE_TTL=120
THEME_TTL=30

# ${#var} must count characters, not bytes, for the width budget.
case "${LC_ALL:-${LC_CTYPE:-$LANG}}" in
  *[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*) ;;
  *) export LC_ALL=en_US.UTF-8 ;;
esac

# Chip backgrounds are shared by both themes; dark chip text reads on every one of them.
CHIP_FG="26;27;38"
CHIP_FG_LIGHT="192;202;245"
C_PURPLE="187;154;247" C_BLUE="122;162;247" C_CYAN="125;207;255" C_TEAL="115;218;202"
C_GREEN="158;206;106" C_YELLOW="224;175;104" C_ORANGE="255;158;100" C_RED="247;118;142"
C_SLATE="65;72;104" C_SILVER="169;177;214"

# One jq pass flattens the session JSON into shell assignments (percentages in tenths).
JQ_PROG='
def num: if type == "number" then . elif type == "string" then (tonumber? // null) else null end;
def int: (num // 0) | floor;
def tenths: num | if . == null then "" else . * 10 | round end;
(now | floor) as $now
| {
    now: $now,
    cwd: (.workspace.current_dir // .cwd // ""),
    project_dir: (.workspace.project_dir // ""),
    repo_name: (.workspace.repo.name // ""),
    worktree: (.workspace.git_worktree // ""),
    model_name: ((.model.display_name // .model.id // "") | sub(" *\\([^)]*\\)$"; "")),
    model_id: (.model.id // ""),
    effort: (.effort.level // ""),
    fast: (if .fast_mode == true then 1 else 0 end),
    ctx_pct: (.context_window.used_percentage | tenths),
    ctx_tokens: (.context_window.total_input_tokens | int),
    ctx_size: (.context_window.context_window_size | int),
    over200k: (if .exceeds_200k_tokens == true then 1 else 0 end),
    h5_pct: (.rate_limits.five_hour.used_percentage | tenths),
    h5_reset: (.rate_limits.five_hour.resets_at | int),
    d7_pct: (.rate_limits.seven_day.used_percentage | tenths),
    d7_reset: (.rate_limits.seven_day.resets_at | int),
    cost_cents: (((.cost.total_cost_usd | num) // 0) * 100 | round),
    dur_s: (((.cost.total_duration_ms | num) // 0) / 1000 | floor),
    cache_left: (if .prompt_cache.warm == true then (.prompt_cache.expires_at | int) - $now else 0 end),
    pr_num: (.pr.number // "" | tostring),
    pr_url: (.pr.url // ""),
    pr_state: (.pr.review_state // ""),
    pr_kind: (.pr.kind // "")
  }
| to_entries[] | "\(.key)=\(.value | tostring | @sh)"'

set_palette() {  # ink colors for text drawn on the terminal's own background
  if [ "$1" = light ]; then
    I_DIM="104;112;154" I_FAINT="168;174;203" I_TEAL="17;140;116"
    I_GREEN="88;117;57" I_YELLOW="140;108;62" I_ORANGE="177;92;0" I_RED="245;42;101"
  else
    I_DIM="115;122;162" I_FAINT="84;92;126" I_TEAL="115;218;202"
    I_GREEN="158;206;106" I_YELLOW="224;175;104" I_ORANGE="255;158;100" I_RED="247;118;142"
  fi
}

pick_theme() {  # STATUSLINE_THEME, else macOS appearance cached for THEME_TTL seconds
  local theme=$STATUSLINE_THEME stamp="" cached=""
  if [ -z "$theme" ]; then
    [ -r "$CACHE_DIR/theme" ] && read -r stamp cached < "$CACHE_DIR/theme"
    case $stamp in '' | *[!0-9]*) stamp=0 ;; esac
    if [ -n "$cached" ] && [ "$now" -ge "$stamp" ] && [ $(( now - stamp )) -lt "$THEME_TTL" ]; then
      theme=$cached
    else
      theme=dark
      if command -v defaults >/dev/null 2>&1; then
        [ "$(defaults read -g AppleInterfaceStyle 2>/dev/null)" = Dark ] || theme=light
      fi
      printf '%s %s\n' "$now" "$theme" > "$CACHE_DIR/theme" 2>/dev/null
    fi
  fi
  set_palette "$theme"
}

load_git() {  # GIT_RAW = `git status --porcelain=v2 --branch` plus a "# diff.lines" line for cwd, cached per directory
  if [ -n "${STATUSLINE_GIT_RAW+x}" ]; then GIT_RAW=$STATUSLINE_GIT_RAW; return 0; fi
  local key=${cwd//[^A-Za-z0-9._-]/_} f stamp=""
  [ ${#key} -gt 180 ] && key=${key: -180}
  f="$CACHE_DIR/git$key"
  GIT_RAW=""
  if [ -r "$f" ]; then
    { IFS= read -r stamp; IFS= read -r -d '' GIT_RAW; } < "$f"
    case $stamp in '' | *[!0-9]*) stamp=0 ;; esac
    [ "$now" -ge "$stamp" ] && [ $(( now - stamp )) -lt "$GIT_TTL" ] && return 0
    # Stale: draw the cached state now and refresh in the background. `git status` takes
    # 0.3s+ in a busy repo, and a render still running when the next update arrives is cancelled.
    refresh_git "$f" < /dev/null > /dev/null 2>&1 &
    return 0
  fi
  refresh_git "$f"  # first render in this directory has nothing to show yet, so wait
  [ -r "$f" ] && { IFS= read -r stamp; IFS= read -r -d '' GIT_RAW; } < "$f"
  return 0
}

refresh_git() {  # refresh_git <cache-file>: one refresher at a time; a lock older than 30s is taken over
  local f=$1 lock="$1.lock" held="" out stat add=0 del=0 re_add='([0-9]+) insertion' re_del='([0-9]+) deletion'
  if ! ( set -o noclobber; printf '%s' "$now" > "$lock" ) 2>/dev/null; then
    read -r held < "$lock" 2>/dev/null
    case $held in '' | *[!0-9]*) held=0 ;; esac
    [ $(( now - held )) -gt 30 ] || return 0
    printf '%s' "$now" > "$lock" 2>/dev/null
  fi
  out=$(git -C "$cwd" --no-optional-locks status --porcelain=v2 --branch 2>/dev/null)
  if [ -n "$out" ]; then
    # Staged and unstaged lines against HEAD (the empty tree before the first commit); untracked files
    # are not counted. The session's cost.total_lines_* is not used: it counts every Edit/Write,
    # including files outside the repository and edits since undone or committed.
    stat=$(git -C "$cwd" --no-optional-locks diff HEAD --shortstat --no-ext-diff 2>/dev/null ||
      git -C "$cwd" --no-optional-locks diff "$(git -C "$cwd" hash-object -t tree /dev/null)" \
        --shortstat --no-ext-diff 2>/dev/null)
    [[ $stat =~ $re_add ]] && add=${BASH_REMATCH[1]}
    [[ $stat =~ $re_del ]] && del=${BASH_REMATCH[1]}
    out+=$'\n'"# diff.lines $add $del"
  fi
  printf '%s\n%s' "$now" "$out" > "$f.$$" 2>/dev/null && mv -f "$f.$$" "$f" 2>/dev/null
  rm -f "$lock"
}

load_usage() {  # USAGE_RAW = "<label> <pct-tenths> <resets_at>" per model-scoped weekly limit
  # The statusLine input carries no per-model windows (Fable), so they come from the OAuth usage
  # endpoint, cached for USAGE_TTL seconds and always refreshed in the background.
  if [ -n "${STATUSLINE_USAGE_RAW+x}" ]; then USAGE_RAW=$STATUSLINE_USAGE_RAW; return 0; fi
  local f="$CACHE_DIR/usage" stamp=""
  USAGE_RAW=""
  [ -r "$f" ] && { IFS= read -r stamp; IFS= read -r -d '' USAGE_RAW; } < "$f"
  case $stamp in '' | *[!0-9]*) stamp=0 ;; esac
  [ "$now" -ge "$stamp" ] && [ $(( now - stamp )) -lt "$USAGE_TTL" ] && return 0
  refresh_usage "$f" < /dev/null > /dev/null 2>&1 &
  return 0
}

refresh_usage() {  # refresh_usage <cache-file>: like refresh_git; a failed fetch keeps the old cache
  local f=$1 lock="$1.lock" held="" token out
  if ! ( set -o noclobber; printf '%s' "$now" > "$lock" ) 2>/dev/null; then
    read -r held < "$lock" 2>/dev/null
    case $held in '' | *[!0-9]*) held=0 ;; esac
    [ $(( now - held )) -gt 30 ] || return 0
    printf '%s' "$now" > "$lock" 2>/dev/null
  fi
  token=$(jq -r '.claudeAiOauth.accessToken // empty' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.credentials.json" 2>/dev/null)
  [ -z "$token" ] && command -v security > /dev/null 2>&1 &&
    token=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null)
  if [ -n "$token" ] && out=$(curl -sf -m 5 https://api.anthropic.com/api/oauth/usage \
      -H "Authorization: Bearer $token" -H "anthropic-beta: oauth-2025-04-20" | jq -r '
        .limits[]? | select(.kind == "weekly_scoped" and (.scope.model.display_name // "") != "")
        | "\(.scope.model.display_name | gsub("[[:space:]]"; ""))"
          + " \(.percent * 10 | round)"
          + " \(.resets_at // "" | sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdateiso8601? // 0)"'); then
    printf '%s\n%s' "$now" "$out" > "$f.$$" 2>/dev/null && mv -f "$f.$$" "$f" 2>/dev/null
  fi
  rm -f "$lock"
}

parse_git() {  # GIT_RAW -> G_BRANCH, G_AHEAD/G_BEHIND, G_STAGED/G_MOD/G_UNTR/G_CONF, G_ADD/G_DEL; fails outside a repo
  local line oid="" xy
  G_BRANCH="" G_AHEAD=0 G_BEHIND=0 G_STAGED=0 G_MOD=0 G_UNTR=0 G_CONF=0 G_ADD=0 G_DEL=0
  [ -n "$GIT_RAW" ] || return 1
  while IFS= read -r line; do
    case $line in
      "# branch.oid "*) oid=${line#\# branch.oid } ;;
      "# branch.head "*) G_BRANCH=${line#\# branch.head } ;;
      "# branch.ab "*) set -- ${line#\# branch.ab }; G_AHEAD=${1#+} G_BEHIND=${2#-} ;;
      "# diff.lines "*) set -- ${line#\# diff.lines }; G_ADD=${1:-0} G_DEL=${2:-0} ;;
      "1 "* | "2 "*)
        xy=${line:2:2}
        [ "${xy:0:1}" != . ] && G_STAGED=$(( G_STAGED + 1 ))
        [ "${xy:1:1}" != . ] && G_MOD=$(( G_MOD + 1 )) ;;
      "u "*) G_CONF=$(( G_CONF + 1 )) ;;
      "? "*) G_UNTR=$(( G_UNTR + 1 )) ;;
    esac
  done <<< "$GIT_RAW"
  [ "$G_BRANCH" = "(detached)" ] && G_BRANCH=${oid:0:7}
  case $G_ADD$G_DEL in '' | *[!0-9]*) G_ADD=0 G_DEL=0 ;; esac
  [ -n "$G_BRANCH" ]
}

find_git_root() {  # walk up from cwd: G_TOP = checkout root, G_MAIN = main checkout (differs in a linked worktree)
  local d=$cwd line
  G_TOP="" G_MAIN=""
  while :; do
    if [ -d "$d/.git" ]; then G_TOP=$d G_MAIN=$d; return 0; fi
    if [ -f "$d/.git" ]; then  # linked worktree: "gitdir: <main>/.git/worktrees/<name>"
      G_TOP=$d G_MAIN=$d
      read -r line < "$d/.git"
      case $line in "gitdir: "*/.git/worktrees/*) line=${line#gitdir: }; G_MAIN=${line%/.git/worktrees/*} ;; esac
      return 0
    fi
    case $d in '' | /) return 1 ;; esac
    d=${d%/*}
  done
}

put() {  # put <sgr> <text>: append styled text to ROW and count its width in ROW_W
  local sgr=$1
  if [ "$COLOR_MODE" = 256 ]; then sgr_256 "$sgr"; sgr=$REPLY; fi
  ROW+="${E}[0;${sgr}m${2}"
  ROW_W=$(( ROW_W + ${#2} ))
}

sgr_256() {  # rewrite each "38;2;R;G;B" / "48;2;R;G;B" in an SGR parameter list as "38;5;N" -> REPLY
  local IFS=';' out=""
  set -- $1
  while [ $# -gt 0 ]; do
    if [ $# -ge 5 ] && [ "$2" = 2 ] && { [ "$1" = 38 ] || [ "$1" = 48 ]; }; then
      rgb_256 "$3" "$4" "$5"
      out+="${out:+;}$1;5;$REPLY"
      shift 5
    else
      out+="${out:+;}$1"
      shift
    fi
  done
  REPLY=$out
}

rgb_256() {  # rgb_256 <r> <g> <b>: REPLY = nearest xterm-256 color (6x6x6 cube, or the gray ramp)
  local r=$1 g=$2 b=$3 hi lo v
  hi=$(( r > g ? r : g )) lo=$(( r < g ? r : g ))
  hi=$(( hi > b ? hi : b )) lo=$(( lo < b ? lo : b ))
  if [ $(( hi - lo )) -le 12 ]; then
    v=$(( (r + g + b) / 3 ))
    if [ "$v" -lt 8 ]; then REPLY=16
    elif [ "$v" -gt 238 ]; then REPLY=231
    else REPLY=$(( 232 + (v - 8) / 10 )); fi
    return 0
  fi
  REPLY=$(( 16 + 36 * (r < 48 ? 0 : r < 115 ? 1 : (r - 35) / 40)
               + 6 * (g < 48 ? 0 : g < 115 ? 1 : (g - 35) / 40)
               + (b < 48 ? 0 : b < 115 ? 1 : (b - 35) / 40) ))
}

chip() {  # chip <bg> <fg> <text> [<url>] [<bold>]: append one powerline segment
  local sgr="38;2;$2;48;2;$1"
  [ "$5" = 1 ] && sgr="1;$sgr"
  if [ -n "$PREV_BG" ]; then
    if [ -z "$PL_ARROW" ]; then put 0 " "  # plain glyphs: chips sit apart like badges
    elif [ "$PREV_BG" = "$1" ]; then put "38;2;$2;48;2;$1" "$PL_THIN"
    else put "38;2;$PREV_BG;48;2;$1" "$PL_ARROW"; fi
  fi
  [ -n "$4" ] && ROW+="${E}]8;;$4$BEL"
  put "$sgr" " $3 "
  [ -n "$4" ] && ROW+="${E}]8;;$BEL"
  PREV_BG=$1
}

end_chips() {
  [ -n "$PREV_BG" ] && [ -n "$PL_ARROW" ] && put "38;2;$PREV_BG" "$PL_ARROW"
  PREV_BG=""
}

fmt_dur() {  # seconds -> REPLY: 3d5h, 1h12m, 42m, <1m
  local s=$1
  if [ "$s" -ge 86400 ]; then
    REPLY="$(( s / 86400 ))d"; [ $(( s % 86400 / 3600 )) -gt 0 ] && REPLY+="$(( s % 86400 / 3600 ))h"
  elif [ "$s" -ge 3600 ]; then
    REPLY="$(( s / 3600 ))h"; [ $(( s % 3600 / 60 )) -gt 0 ] && REPLY+="$(( s % 3600 / 60 ))m"
  elif [ "$s" -ge 60 ]; then
    REPLY="$(( s / 60 ))m"
  else
    REPLY="<1m"
  fi
  return 0
}

fmt_tokens() {  # 283000 -> 283k, 1000000 -> 1M, 1500000 -> 1.5M
  local n=$1
  if [ "$n" -ge 1000000 ]; then
    REPLY="$(( n / 1000000 ))"; [ $(( n % 1000000 / 100000 )) -gt 0 ] && REPLY+=".$(( n % 1000000 / 100000 ))"
    REPLY+="M"
  elif [ "$n" -ge 1000 ]; then
    REPLY="$(( n / 1000 ))k"
  else
    REPLY=$n
  fi
}

level_color() {  # whole percent -> REPLY: threshold ink color
  if [ "$1" -ge 80 ]; then REPLY=$I_RED
  elif [ "$1" -ge 65 ]; then REPLY=$I_ORANGE
  elif [ "$1" -ge 50 ]; then REPLY=$I_YELLOW
  else REPLY=$I_GREEN; fi
}

mix() {  # mix <rgb-a> <rgb-b> <percent>: REPLY = a blended toward b
  local r1="${1%%;*}" b1="${1##*;}" r2="${2%%;*}" b2="${2##*;}" g1="${1#*;}" g2="${2#*;}"
  g1=${g1%%;*} g2=${g2%%;*}
  REPLY="$(( r1 + (r2 - r1) * $3 / 100 ));$(( g1 + (g2 - g1) * $3 / 100 ));$(( b1 + (b2 - b1) * $3 / 100 ))"
}

grad() {  # bar position in tenths of a percent (0-1000) -> REPLY: gradient color, green until 35%
  local p=$1
  if [ "$p" -lt 350 ]; then REPLY=$I_GREEN
  elif [ "$p" -lt 500 ]; then mix "$I_GREEN" "$I_YELLOW" $(( (p - 350) * 100 / 150 ))
  elif [ "$p" -lt 650 ]; then mix "$I_YELLOW" "$I_ORANGE" $(( (p - 500) * 100 / 150 ))
  elif [ "$p" -lt 800 ]; then mix "$I_ORANGE" "$I_RED" $(( (p - 650) * 100 / 150 ))
  else REPLY=$I_RED; fi
}

bar() {  # bar <percent-tenths> <cells>: gradient cells over a faint track, trailing space; no-op at 0 cells
  # ▆ is a block element, which terminals draw to fill the cell; ▰▱ render small in many fonts.
  local n=$2 fill i
  [ "$n" -gt 0 ] || return 0
  fill=$(( ($1 * n + 500) / 1000 ))
  [ "$fill" -gt "$n" ] && fill=$n
  for (( i = 0; i < n; i++ )); do
    if [ "$i" -lt "$fill" ]; then
      grad $(( (2 * i + 1) * 1000 / (2 * n) ))
      put "38;2;$REPLY" "▆"
    else
      put "38;2;$I_FAINT" "▆"
    fi
  done
  put 0 " "
}

eta_limit() {  # eta_limit <pct-tenths> <resets_at> <window-s>: REPLY = seconds until 100% at the
               # window's average pace when that comes before the reset (0 = already at 100%)
  local u=$1 left elapsed t
  REPLY=""
  [ "$u" -gt 0 ] && [ "$2" -gt "$now" ] || return 0
  left=$(( $2 - now )) elapsed=$(( $3 - $2 + now ))
  [ "$elapsed" -ge $(( $3 / 20 )) ] || return 0
  [ "$u" -ge 1000 ] && { REPLY=0; return 0; }
  t=$(( (1000 - u) * elapsed / u ))
  [ "$t" -lt "$left" ] && REPLY=$t
  return 0
}

gauge() {  # gauge <label> <pct-tenths> <cells> [<resets_at> <window-s> <show-reset>]
  local p=$(( ($2 + 5) / 10 ))
  [ -n "$ROW" ] && put "38;2;$I_FAINT" " │ "
  put "38;2;$I_DIM" "$1 "
  bar "$2" "$3"
  level_color "$p"
  put "1;38;2;$REPLY" "$p%"
  [ -n "$4" ] || return 0
  eta_limit "$2" "$4" "$5"
  if [ "$REPLY" = 0 ]; then
    put "1;38;2;$I_RED" " ⚠"
  elif [ -n "$REPLY" ]; then
    fmt_dur "$REPLY"; put "1;38;2;$I_RED" " ⚠~$REPLY"
  fi
  if [ "$6" = 1 ] && [ "$4" -gt "$now" ]; then
    fmt_dur $(( $4 - now )); put "38;2;$I_DIM" " ↻$REPLY"
  fi
  return 0
}

model_color() {  # model id or name -> REPLY: chip background for its family
  case $1 in
    *[Oo]pus*) REPLY=$C_PURPLE ;;
    *[Ss]onnet*) REPLY=$C_CYAN ;;
    *[Hh]aiku*) REPLY=$C_TEAL ;;
    *[Ff]able*) REPLY=$C_ORANGE ;;
    *) REPLY=$C_SILVER ;;
  esac
}

effort_colors() {  # effort level -> effort_bg, effort_fg
  effort_fg=$CHIP_FG
  case $1 in
    max) effort_bg=$C_RED ;;
    xhigh) effort_bg=$C_ORANGE ;;
    high) effort_bg=$C_YELLOW ;;
    medium) effort_bg=$C_TEAL ;;
    *) effort_bg=$C_SLATE effort_fg=$CHIP_FG_LIGHT ;;
  esac
}

prepare() {  # derive chip texts and colors once; build_row1 only chooses which to show
  model_color "$model_id $model_name"; model_bg=$REPLY

  effort_txt=$effort
  effort_colors "$effort"
  # Braces matter: bash 3.2 reads the first byte of a following multibyte char as part of the name.
  [ "$fast" = 1 ] && effort_txt="${effort_txt:+${effort_txt}·}fast"

  has_git=0 git_counts="" lines_add=0 lines_del=0
  if parse_git; then
    has_git=1 lines_add=$G_ADD lines_del=$G_DEL
    [ "$G_AHEAD" -gt 0 ] && git_counts+=" $UP$G_AHEAD"
    [ "$G_BEHIND" -gt 0 ] && git_counts+=" $DOWN$G_BEHIND"
    [ "$G_CONF" -gt 0 ] && git_counts+=" ✘$G_CONF"
    [ "$G_STAGED" -gt 0 ] && git_counts+=" +$G_STAGED"
    [ "$G_MOD" -gt 0 ] && git_counts+=" ~$G_MOD"
    [ "$G_UNTR" -gt 0 ] && git_counts+=" ?$G_UNTR"
    if [ "$G_CONF" -gt 0 ]; then git_bg=$C_RED
    elif [ $(( G_STAGED + G_MOD + G_UNTR )) -gt 0 ]; then git_bg=$C_YELLOW
    else git_bg=$C_GREEN; fi
  fi

  # Directory: the repository name (self-hosted remotes leave workspace.repo empty, so fall back to
  # the main checkout's folder), the path below the checkout root (last two segments), and the
  # linked worktree's name when it differs from the branch.
  find_git_root
  local root=${G_TOP:-${project_dir:-$cwd}} rel="" slashes last wt=$worktree
  dir_name=$repo_name
  [ -z "$dir_name" ] && dir_name=${G_MAIN##*/}
  [ -z "$dir_name" ] && dir_name=${root##*/}
  if [ "$cwd" != "$root" ]; then
    case $cwd in
      "$root"/*) rel=${cwd#"$root"/} ;;
      *) dir_name=${cwd##*/} ;;
    esac
  fi
  [ -z "$dir_name" ] && dir_name=/
  slashes=${rel//[!\/]/}
  if [ ${#slashes} -ge 2 ]; then
    last=${rel##*/} rel=${rel%/*}
    rel="…/${rel##*/}/$last"
  fi
  dir_full=$dir_name${rel:+/$rel}
  [ -z "$wt" ] && [ "$G_TOP" != "$G_MAIN" ] && wt=${G_TOP##*/}
  [ -n "$wt" ] && [ "$wt" != "$G_BRANCH" ] && dir_full+="·$wt"

  pr_txt=""
  if [ -n "$pr_num" ]; then
    if [ "$pr_kind" = mr ]; then pr_txt="!$pr_num"; else pr_txt="#$pr_num"; fi
    pr_fg=$CHIP_FG
    case $pr_state in
      approved) pr_bg=$C_TEAL pr_txt+=" ✓" ;;
      changes_requested) pr_bg=$C_RED pr_txt+=" ✗" ;;
      draft) pr_bg=$C_SLATE pr_fg=$CHIP_FG_LIGHT pr_txt+=" draft" ;;
      *) pr_bg=$C_CYAN ;;
    esac
  fi
}

stat_gap() {  # two spaces after the chips, " · " between session stats
  if [ "$STAT_N" -eq 0 ]; then put 0 "  "; else put "38;2;$I_FAINT" " · "; fi
  STAT_N=$(( STAT_N + 1 ))
}

build_row1() {  # build_row1 <level>: 0 shows everything; each level drops the next least important part
  local lvl=$1
  ROW="" ROW_W=0 PREV_BG="" STAT_N=0
  [ -n "$model_name" ] && chip "$model_bg" "$CHIP_FG" "$model_name" "" 1
  [ "$lvl" -lt 6 ] && [ -n "$effort_txt" ] && chip "$effort_bg" "$effort_fg" "$effort_txt"
  if [ "$lvl" -lt 7 ]; then chip "$C_BLUE" "$CHIP_FG" "$dir_full"
  elif [ "$lvl" -lt 8 ]; then chip "$C_BLUE" "$CHIP_FG" "$dir_name"; fi
  if [ "$has_git" = 1 ]; then
    local branch=$G_BRANCH max=40
    [ "$lvl" -ge 7 ] && max=20
    [ ${#branch} -gt "$max" ] && branch="${branch:0:$(( max - 1 ))}…"
    chip "$git_bg" "$CHIP_FG" "${PL_BRANCH:+$PL_BRANCH }$branch$git_counts"
  fi
  [ "$lvl" -lt 5 ] && [ -n "$pr_txt" ] && chip "$pr_bg" "$pr_fg" "$pr_txt" "$pr_url"
  end_chips

  if [ "$lvl" -lt 4 ] && [ "$cost_cents" -gt 0 ]; then
    stat_gap; printf -v REPLY '$%d.%02d' $(( cost_cents / 100 )) $(( cost_cents % 100 )); put "38;2;$I_DIM" "$REPLY"
  fi
  if [ "$lvl" -lt 3 ] && [ "$dur_s" -gt 0 ]; then
    stat_gap; fmt_dur "$dur_s"; put "38;2;$I_DIM" "$REPLY"
  fi
  if [ "$lvl" -lt 2 ] && [ $(( lines_add + lines_del )) -gt 0 ]; then
    stat_gap
    [ "$lines_add" -gt 0 ] && put "38;2;$I_GREEN" "+$lines_add"
    [ "$lines_add" -gt 0 ] && [ "$lines_del" -gt 0 ] && put 0 " "
    [ "$lines_del" -gt 0 ] && put "38;2;$I_RED" "−$lines_del"
  fi
  if [ "$lvl" -lt 1 ] && [ "$cache_left" -gt 0 ]; then
    stat_gap; fmt_dur "$cache_left"; put "38;2;$I_DIM" "cache "; put "38;2;$I_TEAL" "$REPLY"
  fi
  ROW+="${E}[0m"
}

build_row2() {  # build_row2 <ctx-cells> <limit-cells> <show-tokens> <show-resets> <show-model-limits>
  ROW="" ROW_W=0
  if [ -n "$ctx_pct" ]; then
    gauge ctx "$ctx_pct" "$1"
    if [ "$3" = 1 ] && [ "$ctx_size" -gt 0 ]; then
      fmt_tokens "$ctx_tokens"
      if [ "$over200k" = 1 ]; then put "38;2;$I_YELLOW" " $REPLY"; else put "38;2;$I_DIM" " $REPLY"; fi
      fmt_tokens "$ctx_size"; put "38;2;$I_DIM" "/$REPLY"
    fi
  fi
  [ -n "$h5_pct" ] && gauge 5h "$h5_pct" "$2" "$h5_reset" 18000 "$4"
  [ -n "$d7_pct" ] && gauge 7d "$d7_pct" "$2" "$d7_reset" 604800 "$4"
  if [ "$5" = 1 ]; then
    local label pct reset
    while read -r label pct reset; do
      case $pct$reset in '' | *[!0-9]*) continue ;; esac
      gauge "$label" "$pct" "$2" "$reset" 604800 "$4"
    done <<< "$USAGE_RAW"
  fi
  [ -n "$ROW" ] && ROW+="${E}[0m"
  return 0
}

main() {
  if ! command -v jq > /dev/null 2>&1; then
    printf '%s' "statusline: jq not found (brew install jq, or apt install jq)"
    return 0
  fi
  local now="" cwd="" project_dir="" repo_name="" worktree="" model_name="" model_id="" effort="" fast=0 \
    ctx_pct="" ctx_tokens=0 ctx_size=0 over200k=0 h5_pct="" h5_reset=0 d7_pct="" d7_reset=0 \
    cost_cents=0 dur_s=0 lines_add=0 lines_del=0 cache_left=0 pr_num="" pr_url="" pr_state="" pr_kind=""
  local cols=${COLUMNS:-120} avail lvl row1
  eval "$(jq -r "$JQ_PROG" 2>/dev/null)"
  case $now in '' | *[!0-9]*) now=$(date +%s) ;; esac
  [ -n "$cwd" ] || cwd=$PWD
  [ -d "$CACHE_DIR" ] || mkdir -p "$CACHE_DIR" 2>/dev/null
  pick_theme
  load_git
  load_usage
  prepare

  case $cols in '' | *[!0-9]*) cols=120 ;; esac
  avail=$(( cols - 4 ))
  for lvl in 0 1 2 3 4 5 6 7 8; do
    build_row1 "$lvl"
    [ "$ROW_W" -le "$avail" ] && break
  done
  row1=$ROW
  for lvl in "10 8 1 1 1" "8 6 1 1 1" "6 4 1 1 1" "0 0 1 1 1" "0 0 0 1 1" "0 0 0 0 1" "0 0 0 0 0"; do
    build_row2 $lvl
    [ "$ROW_W" -le "$avail" ] && break
  done
  if [ -n "$ROW" ]; then printf '%s\n%s' "$row1" "$ROW"; else printf '%s' "$row1"; fi
}

# --- subagent panel rows (--subagents, for the subagentStatusLine setting) -------------------------
# Claude Code passes every visible task as {columns, tasks: [...]} and reads back one
# {"id", "content"} line per row to replace. Tasks without a model (shells, monitors) keep the
# default row. Labels arrive with a string of per-character cell widths (0, 1, or 2 for CJK and
# emoji) so they can be cut to fit; bash cannot tell a wide character from a narrow one.
SUB_JQ='
def num: if type == "number" then . elif type == "string" then (tonumber? // null) else null end;
def int: (num // 0) | floor;
def oneline: tostring | gsub("[[:cntrl:]]+"; " ") | gsub("^ +| +$"; "") | .[:200];
def cells: [explode[] |
  if (. >= 768 and . < 880) or (. >= 8203 and . <= 8207) or (. >= 65024 and . <= 65039) then "0"
  elif (. >= 4352 and . <= 4447) or (. >= 11904 and . <= 42191) or (. >= 44032 and . <= 55203)
    or (. >= 63744 and . <= 64255) or (. >= 65072 and . <= 65103) or (. >= 65280 and . <= 65376)
    or (. >= 65504 and . <= 65510) or (. >= 127744 and . <= 129791) or (. >= 131072 and . <= 262141) then "2"
  else "1" end] | join("");
def digits($t; $i; $step):
  if $i >= 0 and ($t[$i] // "" | test("^[0-9]{1,2}$")) then [$t[$i]] + digits($t; $i + $step; $step) else [] end;
# claude-haiku-4-5-20251001 -> Haiku 4.5, claude-3-5-sonnet-20241022 -> Sonnet 3.5, else the id itself
def model_label:
  sub("\\[[^\\]]*\\]$"; "") as $raw
  | [$raw | ascii_downcase | splits("[-.:@_/]")] as $t
  | ([$t | to_entries[] | select(.value | test("^(opus|sonnet|haiku|fable)$")) | .key] | first) as $f
  | if $f == null then $raw
    else (digits($t; $f + 1; 1) | if length > 0 then . else (digits($t; $f - 1; -1) | reverse) end) as $v
      | ($t[$f][:1] | ascii_upcase) + $t[$f][1:] + (if $v == [] then "" else " " + ($v | join(".")) end)
    end;
(now | floor) as $now
| "now=\($now)", "cols=\(.columns | int)",
  ([.tasks[]? | select(type == "object" and (.model // "") != "")] | to_entries[]
   | .key as $i | .value
   | (.startTime | num // 0) as $st
   | (.name // "" | oneline) as $name
   | {
       id: (.id // "" | tostring),
       model: (.model | tostring | model_label),
       effort: (.effort | if type == "number" then (if . >= 1000 then "\(. / 1000 | floor)k" else tostring end)
                else (. // "" | tostring) end),
       name: $name,
       label: (.label // .description // "" | oneline | if . == $name then "" else . end),
       tokens: (.tokenCount | int),
       size: (.contextWindowSize | int),
       status: (.status // "" | tostring),
       age: (if $st <= 0 then -1 else $now - (if $st > 100000000000 then $st / 1000 else $st end | floor) end)
     }
   | .label_cells = (.label | cells)
   | .name_w = (.name | cells | explode | map(. - 48) | add // 0)
   | .label_w = (.label_cells | explode | map(. - 48) | add // 0)
   | to_entries[] | "s_\(.key)[\($i)]=\(.value | tostring | @sh)")'

clip() {  # clip <text> <cell widths> <max cells>: REPLY = text, cut with a trailing … to fit; REPLY_W = its width
  local s=$1 w=$2 max=$3 i used=0 c
  REPLY="" REPLY_W=0
  [ "$max" -gt 0 ] || return 0
  for (( i = 0; i < ${#w}; i++ )); do
    c=${w:i:1}
    [ $(( used + c )) -le "$max" ] || break
    used=$(( used + c ))
  done
  if [ "$i" -ge ${#w} ]; then REPLY=$s REPLY_W=$used; return 0; fi
  while [ "$i" -gt 0 ] && [ $(( used + 1 )) -gt "$max" ]; do  # make room for the …
    i=$(( i - 1 )) used=$(( used - ${w:i:1} ))
  done
  REPLY="${s:0:i}…" REPLY_W=$(( used + 1 ))
}

fmt_age() {  # seconds -> REPLY: 42s below a minute, else fmt_dur
  if [ "$1" -lt 60 ]; then REPLY="$1s"; else fmt_dur "$1"; fi
}

sub_parts() {  # sub_parts <row> <level>: CH/CH_W = chips, RT/RT_W = gauge and status; each level drops more
  local i=$1 lvl=$2 cells=0
  ROW="" ROW_W=0 PREV_BG=""
  model_color "${s_model[i]}"
  chip "$REPLY" "$CHIP_FG" "${s_model[i]}" "" 1
  if [ "$lvl" -lt 4 ] && [ -n "${s_effort[i]}" ]; then
    effort_colors "${s_effort[i]}"
    chip "$effort_bg" "$effort_fg" "${s_effort[i]}"
  fi
  end_chips
  CH=$ROW CH_W=$ROW_W
  ROW="" ROW_W=0
  if [ "${s_size[i]}" -gt 0 ]; then
    case $lvl in 0) cells=8 ;; 1) cells=5 ;; esac
    gauge ctx $(( s_tokens[i] * 1000 / s_size[i] )) "$cells"
    if [ "$lvl" -lt 3 ]; then
      fmt_tokens "${s_tokens[i]}"; put "38;2;$I_DIM" " $REPLY"
      fmt_tokens "${s_size[i]}"; put "38;2;$I_DIM" "/$REPLY"
    fi
  elif [ "${s_tokens[i]}" -gt 0 ]; then
    fmt_tokens "${s_tokens[i]}"; put "38;2;$I_DIM" "$REPLY tok"
  fi
  if [ "$lvl" -lt 5 ]; then  # a finished task gets a mark, a live one its running time
    local sgr="38;2;$I_DIM" mark=""
    case ${s_status[i]} in
      completed) sgr="1;38;2;$I_GREEN" mark="✓" ;;
      failed) sgr="1;38;2;$I_RED" mark="✘" ;;
      killed) mark="✘" ;;
      paused) mark="paused" ;;
      *) [ "${s_age[i]}" -ge 0 ] && { fmt_age "${s_age[i]}"; mark=$REPLY; } ;;
    esac
    if [ -n "$mark" ]; then
      [ -n "$ROW" ] && put "38;2;$I_FAINT" " · "
      put "$sgr" "$mark"
    fi
  fi
  RT=$ROW RT_W=$ROW_W
}

sub_left() {  # sub_left <row>: LEFT_W = chips plus name; SEP_W = width of the separator before the label
  LEFT_W=$CH_W SEP_W=1
  if [ -n "${s_name[$1]}" ]; then LEFT_W=$(( LEFT_W + 1 + s_name_w[$1] )) SEP_W=3; fi
}

subagents() {
  command -v jq > /dev/null 2>&1 || return 0  # the default rows stay
  local now="" cols=0 n i lvl fit want label col cap out="" start budget
  local -a s_id s_model s_effort s_name s_label s_tokens s_size s_status s_age s_label_cells \
    s_name_w s_label_w ch ch_w rt rt_w
  eval "$(jq -r "$SUB_JQ" 2>/dev/null)"
  n=${#s_id[@]}
  [ "$n" -gt 0 ] || return 0
  case $now in '' | *[!0-9]*) now=$(date +%s) ;; esac
  case $cols in '' | *[!0-9]*) cols=0 ;; esac
  [ -d "$CACHE_DIR" ] || mkdir -p "$CACHE_DIR" 2>/dev/null
  pick_theme

  # One level for every row keeps their gauges in one column: the first at which each row fits with
  # at least 12 cells of its label (or, at the last level, without it).
  for lvl in 0 1 2 3 4 5; do
    fit=1
    for (( i = 0; i < n; i++ )); do
      sub_parts "$i" "$lvl"; sub_left "$i"
      label=${s_label_w[i]}
      [ "$label" -gt 12 ] && label=12
      [ "$lvl" = 5 ] && label=0
      want=$(( LEFT_W + 2 + RT_W ))
      [ "$label" -gt 0 ] && want=$(( want + SEP_W + label ))
      [ "$want" -le "$cols" ] || { fit=0; break; }
    done
    [ "$fit" = 1 ] && break
  done
  [ "$fit" = 1 ] || return 0  # too narrow even for the model and ctx: the default rows stay

  # The gauge column: just past the widest name and label, but far enough left for every gauge.
  col=0 cap=$cols
  for (( i = 0; i < n; i++ )); do
    sub_parts "$i" "$lvl"; sub_left "$i"
    ch[i]=$CH ch_w[i]=$CH_W rt[i]=$RT rt_w[i]=$RT_W
    want=$(( LEFT_W + 2 ))
    [ "${s_label_w[i]}" -gt 0 ] && want=$(( want + SEP_W + s_label_w[i] ))
    [ "$want" -gt "$col" ] && col=$want
    [ $(( cols - RT_W )) -lt "$cap" ] && cap=$(( cols - RT_W ))
  done
  [ "$col" -gt "$cap" ] && col=$cap

  for (( i = 0; i < n; i++ )); do
    CH_W=${ch_w[i]}
    sub_left "$i"
    ROW=${ch[i]} ROW_W=$CH_W
    if [ -n "${s_name[i]}" ]; then put 0 " "; put 1 "${s_name[i]}"; ROW_W=$LEFT_W; fi
    start=$col
    [ "$start" -lt $(( ROW_W + 2 )) ] && start=$(( ROW_W + 2 ))
    budget=$(( start - 2 - ROW_W - SEP_W ))
    if [ "${s_label_w[i]}" -gt 0 ] && { [ "$budget" -ge "${s_label_w[i]}" ] || [ "$budget" -ge 4 ]; }; then
      if [ "$SEP_W" = 3 ]; then put "38;2;$I_FAINT" " · "; else put 0 " "; fi
      clip "${s_label[i]}" "${s_label_cells[i]}" "$budget"
      put "38;2;$I_DIM" "$REPLY"; ROW_W=$(( ROW_W - ${#REPLY} + REPLY_W ))
    fi
    [ -n "${rt[i]}" ] && printf -v REPLY '%*s' $(( start - ROW_W )) '' && put 0 "$REPLY"
    ROW+="${rt[i]}${E}[0m"
    out+="${s_id[i]}"$'\t'"$ROW"$'\n'
  done
  printf '%s' "$out" | jq -Rc 'split("\t") | {id: .[0], content: (.[1:] | join("\t"))}'
}

demo_case() {  # demo_case <title> <columns, 0 = current> <git porcelain> <jq filter over $base>
  local cols=$2
  [ "$cols" = 0 ] && cols=${COLUMNS:-120}
  printf '\n%s[2m── %s ──%s[0m\n' "$E" "$1" "$E"
  jq -n --argjson now "$now" "$base | $4" |
    COLUMNS=$cols STATUSLINE_GIT_RAW=$3 STATUSLINE_USAGE_RAW="Fable 250 $(( now + 280000 ))" bash "$0"
  printf '\n'
}

demo() {  # render representative states with fake session data
  local now base clean dirty conflict
  now=$(date +%s)
  base='{
    cwd: "/home/you/src/my-app",
    model: {id: "claude-opus-5-5[1m]", display_name: "Opus 5.5 (1M context)"},
    workspace: {current_dir: "/home/you/src/my-app", project_dir: "/home/you/src/my-app",
                repo: {host: "github.com", owner: "octocat", name: "my-app"}},
    effort: {level: "max"},
    cost: {total_cost_usd: 4.21, total_duration_ms: 1380000},
    context_window: {used_percentage: 28, total_input_tokens: 283000, context_window_size: 1000000},
    exceeds_200k_tokens: true,
    prompt_cache: {warm: true, expires_at: ($now + 2520)},
    rate_limits: {five_hour: {used_percentage: 41, resets_at: ($now + 4320)},
                  seven_day: {used_percentage: 18, resets_at: ($now + 280000)}},
    pr: {number: 512, url: "https://github.com/octocat/my-app/pull/512", review_state: "approved"}
  }'
  clean=$'# branch.oid ca8cb99\n# branch.head main\n# branch.ab +0 -0'
  dirty=$'# branch.oid ca8cb99\n# branch.head main\n# branch.ab +2 -0\n1 M. N... a\n1 .M N... b\n1 .M N... c\n? d\n# diff.lines 156 23'
  conflict=$'# branch.oid ca8cb99\n# branch.head main\n# branch.ab +0 -3\nu UU N... a'
  demo_case "Normal" 0 "$clean" '.'
  demo_case "Warning: ctx 58%, 5h limit on pace to run out before it resets" 0 "$dirty" \
    '.context_window.used_percentage = 58 | .context_window.total_input_tokens = 580000
     | .rate_limits.five_hour = {used_percentage: 72, resets_at: ($now + 7200)}
     | .effort.level = "xhigh" | .pr.review_state = "pending"'
  demo_case "Critical: ctx 88%, 5h 95%, 7d 83%, merge conflict" 0 "$conflict" \
    '.context_window.used_percentage = 88 | .context_window.total_input_tokens = 880000
     | .rate_limits.five_hour = {used_percentage: 95, resets_at: ($now + 2400)}
     | .rate_limits.seven_day.used_percentage = 83 | .pr.review_state = "changes_requested"'
  demo_case "Narrow terminal (COLUMNS=60)" 60 "$dirty" '.'

  printf '\n%s[2m── %s ──%s[0m\n' "$E" "Subagent panel rows (--subagents)" "$E"
  jq -n --argjson now "$now" --argjson cols "${COLUMNS:-120}" '{columns: ($cols - 4), tasks: [
    {id: "a", name: "reviewer", type: "local_agent", status: "running", description: "Review the diff",
     label: "Reading statusline.sh", startTime: (($now - 200) * 1000), model: "claude-opus-5-5[1m]",
     effort: "high", contextWindowSize: 1000000, tokenCount: 312000},
    {id: "b", type: "local_agent", status: "running", description: "Find the auth handlers",
     startTime: (($now - 42) * 1000), model: "claude-haiku-4-5-20251001", contextWindowSize: 200000,
     tokenCount: 148000},
    {id: "c", type: "local_agent", status: "completed", description: "Summarize the open issues",
     startTime: (($now - 600) * 1000), model: "claude-sonnet-5-5", effort: "medium",
     contextWindowSize: 1000000, tokenCount: 61000}]}' | bash "$0" --subagents | jq -r '.content'
}

case $1 in
  --demo) demo ;;
  --subagents) subagents ;;
  *) main ;;
esac
