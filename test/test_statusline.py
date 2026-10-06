#!/usr/bin/env python3
"""Behavioral tests for statusline.sh.

Usage: python3 test/test_statusline.py [name-filter]

Environment:
  SL_SCRIPT             script under test (default: ../statusline.sh)
  TEST_BASH             bash binary to run it with (default: bash on PATH; CI also runs /bin/bash 3.2)
  STATUSLINE_SKIP_PERF  set to 1 to skip the timing budgets, which shared CI runners cannot hold
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.environ.get("SL_SCRIPT", os.path.join(HERE, "..", "statusline.sh"))
BASH = shutil.which(os.environ.get("TEST_BASH", "bash"))
NOW = int(time.time())


def make_repo():
    """A real, empty git repository named my-app on branch main, for the tests that run git."""
    path = os.path.join(tempfile.mkdtemp(), "my-app")
    subprocess.run(["git", "init", "-q", "-b", "main", path], check=True)
    return path


REPO = make_repo()

CSI = re.compile(r"\x1b\[[0-9;]*m")
OSC8 = re.compile(r"\x1b\]8;[^\x07\x1b]*(?:\x07|\x1b\\)")
SGR_RUN_BEFORE = r"((?:\x1b\[[0-9;]*m)+)"

# Tokyo Night (dark) palette as SGR "R;G;B" triples.
PURPLE, BLUE, TEAL = "187;154;247", "122;162;247", "115;218;202"
GREEN, YELLOW, ORANGE, RED = "158;206;106", "224;175;104", "255;158;100", "247;118;142"
DIM, FAINT = "115;122;162", "84;92;126"
# Tokyo Night Day (light) palette.
L_DIM, L_GREEN = "104;112;154", "88;117;57"

# Powerline private-use glyphs, built from code points so no editor or pipeline can strip them.
PL_ARROW, PL_THIN, PL_BRANCH = chr(0xE0B0), chr(0xE0B1), chr(0xE0A0)

GIT_CLEAN = "# branch.oid ca8cb99\n# branch.head main\n# branch.upstream origin/main\n# branch.ab +0 -0\n"
GIT_DIRTY = (
    "# branch.oid ca8cb99\n# branch.head main\n# branch.upstream origin/main\n# branch.ab +1 -0\n"
    "1 M. N... 100644 100644 100644 a b staged.txt\n"
    "1 .M N... 100644 100644 100644 a b mod1.txt\n"
    "1 .M N... 100644 100644 100644 a b mod2.txt\n"
    "? new.txt\n"
)
GIT_EDITED = GIT_DIRTY + "# diff.lines 12 4\n"
GIT_CONFLICT = GIT_CLEAN + "u UU N... 100644 100644 100644 100644 a b c conflict.txt\n"
GIT_DETACHED = "# branch.oid ca8cb9954662e18d96c1e10ff130d4249a0c8b6e\n# branch.head (detached)\n"
GIT_BRANCH = "# branch.oid ca8cb99\n# branch.head octocat/issue-9\n"

PR_URL = "https://github.com/octocat/my-app/pull/512"
DELETE = object()


class Skip(Exception):
    pass


def visible(s):
    return OSC8.sub("", CSI.sub("", s))


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in visible(s))


def private_use(s):
    return [c for c in s if 0xE000 <= ord(c) <= 0xF8FF]


def full(overrides=None):
    d = {
        "cwd": REPO,
        "session_id": "t",
        "model": {"id": "claude-opus-5-5[1m]", "display_name": "Opus 5.5 (1M context)"},
        "workspace": {
            "current_dir": REPO,
            "project_dir": REPO,
            "added_dirs": [],
            "repo": {"host": "github.com", "owner": "octocat", "name": "my-app"},
        },
        "version": "2.1.280",
        "output_style": {"name": "default"},
        "cost": {
            "total_cost_usd": 4.2137,
            "total_duration_ms": 1380000,
            "total_api_duration_ms": 420000,
            "total_lines_added": 156,
            "total_lines_removed": 23,
        },
        "context_window": {
            "total_input_tokens": 283000,
            "total_output_tokens": 1200,
            "context_window_size": 1000000,
            "used_percentage": 28.3,
            "remaining_percentage": 71.7,
        },
        "exceeds_200k_tokens": True,
        "prompt_cache": {"warm": True, "caching_observed": True, "ttl": "1h", "expires_at": NOW + 42 * 60 + 30},
        "fast_mode": False,
        "effort": {"level": "max"},
        "thinking": {"enabled": True},
        "rate_limits": {
            "five_hour": {"used_percentage": 41, "resets_at": NOW + 72 * 60 + 30},
            "seven_day": {"used_percentage": 18, "resets_at": NOW + 3 * 86400 + 5 * 3600 + 1800},
        },
        "pr": {"number": 512, "url": PR_URL, "review_state": "approved"},
    }
    for path, value in (overrides or {}).items():
        node = d
        keys = path.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        if value is DELETE:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return d


def run(data, cols=200, theme="dark", git=GIT_CLEAN, raw_stdin=None, args=(), glyphs=None, colors=None,
        colorterm="truecolor", path=None, usage=""):
    env = dict(os.environ)
    for key in ("STATUSLINE_THEME", "STATUSLINE_GIT_RAW", "STATUSLINE_GLYPHS", "STATUSLINE_COLORS", "COLORTERM",
                "STATUSLINE_USAGE_RAW"):
        env.pop(key, None)
    env["COLUMNS"] = str(cols)
    for key, value in (("STATUSLINE_THEME", theme), ("STATUSLINE_GIT_RAW", git), ("STATUSLINE_GLYPHS", glyphs),
                       ("STATUSLINE_COLORS", colors), ("COLORTERM", colorterm), ("PATH", path),
                       ("STATUSLINE_USAGE_RAW", usage)):
        if value is not None:
            env[key] = value
    stdin = raw_stdin if raw_stdin is not None else json.dumps(data)
    p = subprocess.run([BASH, SCRIPT, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                       cwd=REPO, env=env, timeout=10)
    rows = p.stdout.split("\n") if p.stdout else []
    return p.returncode, p.stdout, p.stderr, rows


def color_before(raw, text):
    """The last SGR escape run before the first `text` (the style that text is drawn in)."""
    idx = raw.find(text)
    if idx < 0:
        return ""
    runs = re.findall(SGR_RUN_BEFORE, raw[:idx])
    return runs[-1] if runs else ""


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


# --- layout ---------------------------------------------------------------

def test_full_session_prints_two_rows():
    rc, out, err, rows = run(full())
    expect(rc == 0, f"rc={rc} err={err!r}")
    expect(len(rows) == 2, f"expected 2 rows, got {len(rows)}: {visible(out)!r}")


def test_output_never_contains_null():
    _, out, _, _ = run(full())
    expect("null" not in visible(out), visible(out))


# --- row 1: chips ---------------------------------------------------------

def test_model_chip_strips_context_suffix():
    _, out, _, rows = run(full())
    v = visible(rows[0])
    expect("Opus 5.5" in v and "(1M context)" not in v, v)


def test_opus_model_chip_is_purple():
    _, out, _, rows = run(full())
    expect(f"48;2;{PURPLE}" in color_before(rows[0], "Opus 5.5"), repr(rows[0][:80]))


def test_effort_chip_shows_max_in_red():
    _, out, _, rows = run(full())
    expect("max" in visible(rows[0]), visible(rows[0]))
    expect(f"48;2;{RED}" in color_before(rows[0], "max"), repr(rows[0]))


def test_no_effort_chip_without_effort_field():
    _, out, _, rows = run(full({"effort": DELETE}))
    expect("max" not in visible(rows[0]), visible(rows[0]))


def test_fast_mode_is_marked_next_to_effort():
    _, out, _, rows = run(full({"fast_mode": True}))
    expect("max·fast" in visible(rows[0]), visible(rows[0]))


def test_chips_are_joined_by_powerline_arrows():
    _, out, _, rows = run(full())
    # model → effort → dir → git → PR, plus the tail arrow after the PR chip
    expect(rows[0].count(PL_ARROW) == 5, f"{rows[0].count(PL_ARROW)} arrows: {visible(rows[0])!r}")


def test_same_colored_neighbors_use_thin_separator():
    # conflicted git (red) next to changes-requested PR (red)
    pr = {"number": 5, "url": "https://github.com/octocat/my-app/pull/5", "review_state": "changes_requested"}
    _, out, _, rows = run(full({"pr": pr}), git=GIT_CONFLICT)
    expect(PL_THIN in rows[0], visible(rows[0]))


def test_dir_chip_shows_repo_name_in_blue():
    _, out, _, rows = run(full())
    expect("my-app" in visible(rows[0]), visible(rows[0]))
    expect(f"48;2;{BLUE}" in color_before(rows[0], "my-app"), repr(rows[0]))


def test_dir_chip_shows_subdir_relative_to_project():
    sub = REPO + "/cmd/io"
    _, out, _, rows = run(full({"cwd": sub, "workspace.current_dir": sub}))
    expect("my-app/cmd/io" in visible(rows[0]), visible(rows[0]))


def test_dir_chip_elides_deep_subdir():
    sub = REPO + "/a/b/c/d"
    _, out, _, rows = run(full({"cwd": sub, "workspace.current_dir": sub}))
    expect("my-app/…/c/d" in visible(rows[0]), visible(rows[0]))


def test_worktree_name_shown_when_it_differs_from_branch():
    _, out, _, rows = run(full({"workspace.git_worktree": "wt-feature"}), git=GIT_BRANCH)
    expect("wt-feature" in visible(rows[0]), visible(rows[0]))


def test_worktree_name_not_duplicated_when_equal_to_branch():
    _, out, _, rows = run(full({"workspace.git_worktree": "octocat/issue-9"}), git=GIT_BRANCH)
    expect(visible(rows[0]).count("octocat/issue-9") == 1, visible(rows[0]))


def repo_layout():
    """tmp/proj (main checkout) and tmp/proj.worktrees/wt-dir (linked worktree)."""
    base = tempfile.mkdtemp()
    main = os.path.join(base, "proj")
    os.makedirs(os.path.join(main, ".git", "worktrees", "wt-dir"))
    os.makedirs(os.path.join(main, "src", "app"))
    wt = os.path.join(base, "proj.worktrees", "wt-dir")
    os.makedirs(os.path.join(wt, "sub"))
    with open(os.path.join(wt, ".git"), "w") as f:
        f.write(f"gitdir: {main}/.git/worktrees/wt-dir\n")
    return main, wt


def at(cwd, project_dir=None):
    return full({"cwd": cwd, "workspace.current_dir": cwd, "workspace.project_dir": project_dir or cwd,
                 "workspace.repo": DELETE, "workspace.git_worktree": None, "pr": DELETE})


def test_linked_worktree_shows_main_repo_name():
    main, wt = repo_layout()
    _, out, _, rows = run(at(wt), git="# branch.head wt-dir\n")
    v = visible(rows[0])
    expect(" proj " in v, v)
    expect(v.count("wt-dir") == 1, f"worktree name repeats the branch: {v}")


def test_linked_worktree_name_shown_when_it_differs_from_branch():
    main, wt = repo_layout()
    _, out, _, rows = run(at(wt), git="# branch.head octocat/feature\n")
    expect("proj·wt-dir" in visible(rows[0]), visible(rows[0]))


def test_subdir_path_is_relative_to_repository_root():
    main, wt = repo_layout()
    _, out, _, rows = run(at(os.path.join(main, "src", "app"), os.path.join(main, "src")), git=GIT_CLEAN)
    expect("proj/src/app" in visible(rows[0]), visible(rows[0]))


LONG_BRANCH = "octocat/1234-add-rate-limit-aware-retry-logic"


def test_long_branch_shows_forty_chars_when_wide():
    _, out, _, rows = run(full(), git=f"# branch.head {LONG_BRANCH}\n")
    expect(f"{LONG_BRANCH[:39]}…" in visible(rows[0]), visible(rows[0]))


def test_long_branch_shrinks_to_twenty_chars_when_narrow():
    _, out, _, rows = run(full(), cols=50, git=f"# branch.head {LONG_BRANCH}\n")
    expect(f"{LONG_BRANCH[:19]}…" in visible(rows[0]), visible(rows[0]))


def test_clean_git_chip_is_green():
    _, out, _, rows = run(full(), git=GIT_CLEAN)
    expect(f"{PL_BRANCH} main" in visible(rows[0]), visible(rows[0]))
    expect(f"48;2;{GREEN}" in color_before(rows[0], " main"), repr(rows[0]))


def test_dirty_git_chip_is_yellow_with_counts():
    _, out, _, rows = run(full(), git=GIT_DIRTY)
    expect("main ⇡1 +1 ~2 ?1" in visible(rows[0]), visible(rows[0]))
    expect(f"48;2;{YELLOW}" in color_before(rows[0], " main"), repr(rows[0]))


def test_conflicted_git_chip_is_red():
    _, out, _, rows = run(full(), git=GIT_CONFLICT)
    expect("main ✘1" in visible(rows[0]), visible(rows[0]))
    expect(f"48;2;{RED}" in color_before(rows[0], " main"), repr(rows[0]))


def test_detached_head_shows_short_sha():
    _, out, _, rows = run(full(), git=GIT_DETACHED)
    expect("ca8cb99" in visible(rows[0]), visible(rows[0]))


def test_no_git_chip_outside_repository():
    _, out, _, rows = run(full(), git="")
    expect(PL_BRANCH not in visible(rows[0]), visible(rows[0]))


def test_github_pr_chip_links_to_pr():
    _, out, _, rows = run(full())
    expect("#512" in visible(rows[0]) and "✓" in visible(rows[0]), visible(rows[0]))
    expect(f"\x1b]8;;{PR_URL}\x07" in rows[0], repr(rows[0]))


def test_gitlab_mr_uses_bang_prefix():
    pr = {"number": 77, "url": "https://gitlab.com/g/p/-/merge_requests/77", "review_state": "pending", "kind": "mr"}
    _, out, _, rows = run(full({"pr": pr}))
    expect("!77" in visible(rows[0]) and "#77" not in visible(rows[0]), visible(rows[0]))


# --- row 1: session stats -------------------------------------------------

def test_session_stats_follow_chips():
    _, out, _, rows = run(full(), git=GIT_EDITED)
    v = visible(rows[0])
    for token in ("$4.21", "23m", "+12 −4", "cache 42m"):
        expect(token in v, f"missing {token}: {v}")


def test_line_counts_ignore_the_session_edit_counters():
    # cost.total_lines_* counts every Edit/Write this session, even outside the repository or since undone.
    _, out, _, rows = run(full(), git=GIT_CLEAN)
    v = visible(rows[0])
    for token in ("+156", "−23"):
        expect(token not in v, f"unexpected {token}: {v}")


def test_line_counts_come_from_the_working_tree_diff():
    path = make_repo()
    git = ["git", "-C", path, "-c", "user.name=t", "-c", "user.email=t@t"]
    with open(os.path.join(path, "a.txt"), "w") as f:
        f.write("one\ntwo\nthree\n")
    subprocess.run(git + ["add", "a.txt"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
    with open(os.path.join(path, "a.txt"), "w") as f:
        f.write("one\n2\nthree\nfour\n")  # unstaged: +2 −1
    with open(os.path.join(path, "b.txt"), "w") as f:
        f.write("x\ny\n")
    subprocess.run(git + ["add", "b.txt"], check=True)  # staged: +2
    data = full({"cwd": path, "workspace.current_dir": path, "workspace.project_dir": path})
    env_tmp = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = tempfile.mkdtemp()
    try:
        _, out, _, rows = run(data, git=None)
    finally:
        if env_tmp is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = env_tmp
    expect("+4 −1" in visible(rows[0]), visible(rows[0]))


def test_zero_stats_are_hidden():
    over = {"cost.total_cost_usd": 0, "cost.total_duration_ms": 0, "cost.total_lines_added": 0,
            "cost.total_lines_removed": 0, "prompt_cache": DELETE}
    _, out, _, rows = run(full(over))
    v = visible(rows[0])
    for token in ("$", "+0", "−0", "0m", "cache"):
        expect(token not in v, f"unexpected {token}: {v}")


# --- row 2: gauges --------------------------------------------------------

def test_ctx_gauge_shows_used_percent_and_tokens():
    _, out, _, rows = run(full())
    v = visible(rows[1])
    expect("ctx" in v and "28%" in v and "283k/1M" in v, v)
    expect("72%" not in v, f"shows remaining instead of used: {v}")


def test_ctx_bar_has_ten_cells_with_faint_track_when_wide():
    _, out, _, rows = run(full())
    ctx_raw = rows[1].split("│")[0]
    expect(visible(ctx_raw).count("▆") == 10, visible(ctx_raw))
    expect(ctx_raw.count(f"38;2;{FAINT}m▆") == 7, repr(ctx_raw))


def test_ctx_percent_color_follows_thresholds():
    for pct, color in ((28.3, GREEN), (55, YELLOW), (70, ORANGE), (85, RED)):
        _, out, _, rows = run(full({"context_window.used_percentage": pct, "exceeds_200k_tokens": False}))
        label = f"{round(pct)}%"
        expect(f"38;2;{color}" in color_before(rows[1], label), f"{label}: {rows[1]!r}")


def test_token_count_turns_yellow_past_200k():
    _, out, _, rows = run(full())
    expect(f"38;2;{YELLOW}" in color_before(rows[1], "283k"), repr(rows[1]))
    _, out, _, rows = run(full({"exceeds_200k_tokens": False, "context_window.total_input_tokens": 150000}))
    expect(f"38;2;{YELLOW}" not in color_before(rows[1], "150k"), repr(rows[1]))


def test_rate_limits_show_percent_and_reset_countdown():
    _, out, _, rows = run(full())
    v = visible(rows[1])
    for token in ("5h", "41%", "↻1h12m", "7d", "18%", "↻3d5h"):
        expect(token in v, f"missing {token}: {v}")


def test_projection_warns_when_limit_hit_before_reset():
    _, out, _, rows = run(full({"rate_limits.five_hour": {"used_percentage": 80, "resets_at": NOW + 7200}}))
    expect("⚠~45m" in visible(rows[1]), visible(rows[1]))


def test_no_projection_warning_when_on_pace():
    _, out, _, rows = run(full())
    expect("⚠" not in visible(rows[1]), visible(rows[1]))


def test_expired_reset_hides_countdown():
    _, out, _, rows = run(full({"rate_limits.five_hour": {"used_percentage": 41, "resets_at": NOW - 60}}))
    v = visible(rows[1])
    expect("5h" in v and "↻-" not in v and "↻1" not in v.split("7d")[0], v)


FABLE = f"Fable 250 {NOW + 280000}"


def test_model_scoped_weekly_limit_follows_7d_gauge():
    _, out, _, rows = run(full(), usage=FABLE)
    v = visible(rows[1])
    expect("Fable" in v and v.index("Fable") > v.index("7d"), v)
    expect("25%" in v.split("Fable")[1] and "↻3d5h" in v.split("Fable")[1], v)


def test_no_model_scoped_gauge_without_usage():
    _, out, _, rows = run(full())
    expect("Fable" not in visible(rows[1]), visible(rows[1]))


def test_malformed_usage_lines_are_skipped():
    _, out, _, rows = run(full(), usage=f"Broken x y\nFable 250 {NOW + 280000}\n")
    v = visible(rows[1])
    expect("Broken" not in v and "Fable" in v, v)


def test_model_scoped_gauge_reads_fresh_cache():
    tmp = tempfile.mkdtemp()
    cache_dir = os.path.join(tmp, "claude-statusline")
    os.makedirs(cache_dir)
    with open(os.path.join(cache_dir, "usage"), "w") as f:
        f.write(f"{NOW}\n{FABLE}\n")
    env_tmp = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = tmp
    try:
        _, out, _, rows = run(full(), usage=None)
        expect("Fable" in visible(rows[1]), visible(rows[1]))
    finally:
        if env_tmp is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = env_tmp


def test_missing_context_percentage_omits_ctx_gauge():
    _, out, _, rows = run(full({"context_window.used_percentage": None}))
    expect("ctx" not in visible(out) and "null" not in visible(out), visible(out))


# --- glyphs, colors, theme ------------------------------------------------

def test_plain_glyphs_avoid_private_use_characters():
    _, out, _, rows = run(full(), git=GIT_DIRTY, glyphs="plain")
    expect(not private_use(out), f"private-use glyphs in plain mode: {visible(out)!r}")
    expect("main ↑1 +1 ~2 ?1" in visible(rows[0]), visible(rows[0]))


def test_plain_glyphs_keep_chip_colors_with_space_gaps():
    _, out, _, rows = run(full(), glyphs="plain")
    v = visible(rows[0])
    expect(" Opus 5.5   max   my-app " in v, v)
    expect(f"48;2;{PURPLE}" in color_before(rows[0], "Opus 5.5"), repr(rows[0][:80]))


def test_256_color_fallback_without_truecolor_support():
    _, out, _, rows = run(full(), colorterm=None)
    expect("38;5;" in out and "48;5;" in out, repr(out[:160]))
    expect("38;2;" not in out and "48;2;" not in out, repr(out[:160]))


def test_colors_setting_forces_truecolor():
    _, out, _, rows = run(full(), colorterm=None, colors="truecolor")
    expect("38;2;" in out and "48;2;" in out, repr(out[:160]))


def test_light_theme_uses_light_palette():
    _, out, _, rows = run(full(), theme="light")
    expect(f"38;2;{L_DIM}" in rows[1] and f"38;2;{L_GREEN}" in rows[1], repr(rows[1]))
    expect(f"38;2;{DIM}" not in rows[1], repr(rows[1]))


def test_unset_theme_still_renders():
    rc, out, err, rows = run(full(), theme=None)
    expect(rc == 0 and len(rows) == 2, f"rc={rc} err={err!r}")


# --- width, robustness ----------------------------------------------------

def test_rows_fit_narrow_terminals():
    data = full()
    for cols in (100, 80, 60, 45):
        _, out, _, rows = run(data, cols=cols, git=GIT_DIRTY, usage=FABLE)
        for i, row in enumerate(rows):
            expect(width(row) <= cols - 4, f"cols={cols} row{i + 1} width={width(row)}: {visible(row)!r}")


def test_minimal_input_prints_single_row():
    rc, out, err, rows = run({"model": {"display_name": "Opus"}, "workspace": {"current_dir": "/tmp"}}, git="")
    expect(rc == 0 and len(rows) == 1, f"rc={rc} rows={rows!r} err={err!r}")
    expect("Opus" in visible(out) and "null" not in visible(out), visible(out))


def test_empty_input_exits_zero():
    rc, out, err, rows = run(None, raw_stdin="", git="")
    expect(rc == 0 and out.strip() != "", f"rc={rc} out={out!r} err={err!r}")


def test_missing_jq_prints_install_hint():
    rc, out, err, rows = run(full(), path="/nonexistent")
    expect(rc == 0 and "jq" in visible(out), f"rc={rc} out={out!r} err={err!r}")


def test_demo_renders_several_states_in_english():
    rc, out, err, rows = run(None, raw_stdin="", args=("--demo",))
    expect(rc == 0 and visible(out).count("ctx") >= 3, f"rc={rc} err={err!r} out={visible(out)!r}")
    expect(not any(0xAC00 <= ord(c) <= 0xD7A3 for c in out), "Korean text in the demo")


# --- subagent panel rows (--subagents) ------------------------------------

def task(overrides=None, **fields):
    d = {
        "id": "a1",
        "name": "reviewer",
        "type": "local_agent",
        "status": "running",
        "description": "Review the diff",
        "label": "Reading statusline.sh",
        "startTime": (NOW - 200) * 1000,
        "model": "claude-opus-5-5[1m]",
        "effort": "high",
        "contextWindowSize": 1000000,
        "tokenCount": 312000,
        "tokenSamples": [300000, 312000],
        "cwd": REPO,
    }
    d.update(fields)
    for key, value in (overrides or {}).items():
        if value is DELETE:
            d.pop(key, None)
        else:
            d[key] = value
    return d


SHELL_TASK = {"id": "b1", "type": "local_bash", "status": "running", "description": "npm test",
              "startTime": NOW * 1000, "tokenCount": 0, "tokenSamples": [], "cwd": REPO}


def run_sub(tasks, cols=120, **kw):
    """Rows the --subagents mode prints, as {id: content}; asserts every line is a valid row object."""
    data = {"session_id": "t", "cwd": REPO, "columns": cols, "tasks": tasks}
    rc, out, err, _ = run(data, args=("--subagents",), **kw)
    expect(rc == 0, f"rc={rc} err={err!r}")
    rows = {}
    for line in out.splitlines():
        obj = json.loads(line)
        expect(set(obj) == {"id", "content"} and isinstance(obj["content"], str), line)
        rows[obj["id"]] = obj["content"]
    return rows


def test_subagent_rows_replace_only_tasks_with_a_model():
    rows = run_sub([task(), SHELL_TASK])
    expect(list(rows) == ["a1"], rows)


def test_subagent_row_shows_model_effort_name_and_label():
    v = visible(run_sub([task()])["a1"])
    expect(re.search(r"Opus 5\.5 .*high .*reviewer · Reading statusline\.sh", v), v)


def test_subagent_model_ids_become_family_and_version():
    cases = {
        "claude-opus-5-5[1m]": "Opus 5.5",
        "claude-haiku-4-5-20251001": "Haiku 4.5",
        "claude-sonnet-4-20250514": "Sonnet 4",
        "claude-3-5-sonnet-20241022": "Sonnet 3.5",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "Sonnet 4.5",
        "claude-opus-4-1@20250805": "Opus 4.1",
        "my-custom-model": "my-custom-model",
    }
    for model, label in cases.items():
        v = visible(run_sub([task(model=model)])["a1"])
        expect(v.startswith(f" {label} "), f"{model}: {v!r}")


def test_subagent_model_chip_uses_family_color():
    content = run_sub([task(model="claude-haiku-4-5-20251001")])["a1"]
    expect(f"48;2;{TEAL}" in color_before(content, "Haiku 4.5"), repr(content[:80]))


def test_subagent_ctx_gauge_shows_its_own_usage():
    v = visible(run_sub([task(tokenCount=148000, contextWindowSize=200000)])["a1"])
    expect("ctx" in v and "74%" in v and "148k/200k" in v, v)


def test_subagent_without_window_size_shows_token_count_only():
    v = visible(run_sub([task({"contextWindowSize": DELETE}, tokenCount=5000)])["a1"])
    expect("ctx" not in v and "5k tok" in v, v)


def test_subagent_effort_chip_is_absent_when_inherited():
    v = visible(run_sub([task({"effort": DELETE})])["a1"])
    expect("high" not in v and "Opus 5.5" in v, v)


def test_subagent_numeric_effort_shows_token_budget():
    v = visible(run_sub([task(effort=32000)])["a1"])
    expect(" 32k " in v, v)


def test_subagent_status_marks_and_running_time():
    rows = run_sub([task(id="run"), task(id="ok", status="completed"), task(id="bad", status="failed"),
                    task(id="new", startTime=(int(time.time()) - 42) * 1000)])
    expect(visible(rows["run"]).endswith("· 3m"), visible(rows["run"]))
    expect(re.search(r"· 4[23]s$", visible(rows["new"])), visible(rows["new"]))
    expect(visible(rows["ok"]).endswith("· ✓"), visible(rows["ok"]))
    expect(visible(rows["bad"]).endswith("· ✘") and RED in color_before(rows["bad"], "✘"), repr(rows["bad"]))


def test_subagent_gauges_line_up_in_one_column():
    rows = run_sub([task(id="x"), task(id="y", name="", label="코드베이스에서 인증 핸들러 찾기",
                                        model="claude-haiku-4-5-20251001")])
    cols = [width(r[:r.find("ctx")]) for r in rows.values()]
    expect(len(set(cols)) == 1, f"ctx columns {cols}: {[visible(r) for r in rows.values()]!r}")


def test_subagent_rows_fit_the_given_columns():
    tasks = [task(), task(id="k", name="", model="claude-haiku-4-5-20251001", effort="max",
                          label="코드베이스에서 인증 핸들러 위치를 찾아서 정리하고 요약하기"),
             task(id="c", status="completed", label="x" * 300)]
    for cols in (200, 100, 80, 60, 45, 32):
        for content in run_sub(tasks, cols=cols).values():
            expect(width(content) <= cols, f"cols={cols} width={width(content)}: {visible(content)!r}")


def test_subagent_narrow_rows_drop_details_before_the_gauge():
    v = visible(run_sub([task()], cols=34)["a1"])
    expect("Opus 5.5" in v and "ctx 31%" in v and "high" not in v, v)


def test_subagent_too_narrow_keeps_the_default_rows():
    expect(run_sub([task()], cols=12) == {}, "rows printed at 12 columns")


def test_subagent_label_is_sanitized_into_one_line():
    rows = run_sub([task(label='say "hi"\n\tthen\x1b[31m \\ leave')])
    v = visible(rows["a1"])
    expect('say "hi" then [31m \\ leave' in v and "\n" not in rows["a1"], v)


def test_subagent_label_equal_to_name_is_not_repeated():
    v = visible(run_sub([task({"label": DELETE}, name="Review the diff")])["a1"])
    expect(v.count("Review the diff") == 1, v)


def test_subagent_plain_glyphs_avoid_private_use_characters():
    content = run_sub([task()], glyphs="plain")["a1"]
    expect(not private_use(content), visible(content))


def test_subagent_mode_prints_nothing_without_tasks_or_jq():
    expect(run_sub([]) == {}, "rows for an empty task list")
    expect(run_sub([SHELL_TASK]) == {}, "rows for shell tasks only")
    rc, out, err, _ = run({"columns": 80, "tasks": [task()]}, args=("--subagents",), path="/nonexistent")
    expect(rc == 0 and out == "", f"rc={rc} out={out!r} err={err!r}")
    rc, out, err, _ = run(None, raw_stdin="", args=("--subagents",))
    expect(rc == 0 and out == "", f"rc={rc} out={out!r} err={err!r}")


def test_demo_includes_subagent_rows():
    _, out, _, _ = run(None, raw_stdin="", args=("--demo",))
    expect("Subagent panel rows" in out and "Haiku 4.5" in visible(out), visible(out)[-400:])


# --- speed and caching ----------------------------------------------------

def skip_perf():
    if os.environ.get("STATUSLINE_SKIP_PERF") == "1":
        raise Skip("STATUSLINE_SKIP_PERF=1")


def wait_for(condition, timeout):
    """Poll until condition() holds or the timeout passes; the caller asserts afterwards."""
    deadline = time.time() + timeout
    while time.time() < deadline and not condition():
        time.sleep(0.05)


def median_ms(fn, n=7):
    samples = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1000)
    return sorted(samples)[n // 2]


def test_renders_within_budget():
    skip_perf()
    data = full()
    run(data)  # warm-up
    ms = median_ms(lambda: run(data, git=GIT_DIRTY))
    expect(ms < 60, f"median {ms:.1f}ms")


def test_real_git_is_cached_between_renders():
    skip_perf()
    data = full()
    run(data, git=None)  # populate cache
    ms = median_ms(lambda: run(data, git=None), n=5)
    expect(ms < 80, f"median {ms:.1f}ms")


def test_stale_git_cache_renders_immediately_and_refreshes_in_background():
    tmp = tempfile.mkdtemp()
    cache_dir = os.path.join(tmp, "claude-statusline")
    os.makedirs(cache_dir)
    cache = os.path.join(cache_dir, "git" + re.sub(r"[^A-Za-z0-9._-]", "_", REPO))
    with open(cache, "w") as f:
        f.write(f"{NOW - 600}\n# branch.oid ca8cb99\n# branch.head cached-branch\n")
    env_tmp = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = tmp
    try:
        t = time.perf_counter()
        _, out, _, rows = run(full(), git=None)
        ms = (time.perf_counter() - t) * 1000
        expect("cached-branch" in visible(rows[0]), f"stale cache not used: {visible(rows[0])!r}")
        if os.environ.get("STATUSLINE_SKIP_PERF") != "1":
            expect(ms < 150, f"render waited for git: {ms:.1f}ms")

        def refresh_finished():
            # The refresher replaces the cache first and releases the lock a moment later.
            with open(cache) as f:
                return "cached-branch" not in f.read() and not os.path.exists(cache + ".lock")

        wait_for(refresh_finished, timeout=10)
        with open(cache) as f:
            refreshed = f.read()
        expect("# branch.head main" in refreshed, f"cache not refreshed: {refreshed[:120]!r}")
        expect(not os.path.exists(cache + ".lock"), "refresh lock left behind")
    finally:
        if env_tmp is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = env_tmp


def main():
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and flt in n]
    failed = skipped = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Skip as e:
            skipped += 1
            print(f"SKIP {name}: {e}")
        except Exception as e:  # noqa: BLE001 - report every failure kind
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(tests) - failed - skipped}/{len(tests)} passed, {skipped} skipped")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
