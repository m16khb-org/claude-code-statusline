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
        colorterm="truecolor", path=None):
    env = dict(os.environ)
    for key in ("STATUSLINE_THEME", "STATUSLINE_GIT_RAW", "STATUSLINE_GLYPHS", "STATUSLINE_COLORS", "COLORTERM"):
        env.pop(key, None)
    env["COLUMNS"] = str(cols)
    for key, value in (("STATUSLINE_THEME", theme), ("STATUSLINE_GIT_RAW", git), ("STATUSLINE_GLYPHS", glyphs),
                       ("STATUSLINE_COLORS", colors), ("COLORTERM", colorterm), ("PATH", path)):
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
    _, out, _, rows = run(full())
    v = visible(rows[0])
    for token in ("$4.21", "23m", "+156", "−23", "cache 42m"):
        expect(token in v, f"missing {token}: {v}")


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
        _, out, _, rows = run(data, cols=cols, git=GIT_DIRTY)
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
