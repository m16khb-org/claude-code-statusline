#!/usr/bin/env python3
"""Tests for install.sh and uninstall.sh against throwaway Claude config directories.

Usage: python3 test/test_install.py [name-filter]
"""
import filecmp
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
BASH = shutil.which(os.environ.get("TEST_BASH", "bash"))
INSTALL_DIR = "claude-code-statusline"
OLD = {"type": "command", "command": "~/.claude/old-statusline.sh"}


def config_dir(settings=None, name="claude"):
    path = os.path.join(tempfile.mkdtemp(), name)
    os.makedirs(path)
    if settings is not None:
        with open(os.path.join(path, "settings.json"), "w") as f:
            f.write(settings if isinstance(settings, str) else json.dumps(settings, indent=2))
    return path


def sh(script, cfg, *args):
    env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg)
    return subprocess.run([BASH, os.path.join(ROOT, script), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=30)


def settings(cfg):
    with open(os.path.join(cfg, "settings.json")) as f:
        return json.load(f)


def write_settings(cfg, data):
    with open(os.path.join(cfg, "settings.json"), "w") as f:
        json.dump(data, f)


def saved_previous(cfg):
    with open(os.path.join(cfg, INSTALL_DIR, "previous-statusline.json")) as f:
        return json.load(f)


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_install_into_empty_config_creates_settings():
    cfg = config_dir()
    p = sh("install.sh", cfg)
    expect(p.returncode == 0, p.stderr)
    status = settings(cfg)["statusLine"]
    target = os.path.join(cfg, INSTALL_DIR, "statusline.sh")
    expect(status["type"] == "command" and target in status["command"] and status["refreshInterval"] == 30, status)
    expect(filecmp.cmp(target, os.path.join(ROOT, "statusline.sh"), shallow=False), "installed copy differs")
    expect(os.access(target, os.X_OK), "installed script is not executable")


def test_installed_command_renders_even_with_spaces_in_path():
    cfg = config_dir(name="claude config")
    sh("install.sh", cfg)
    command = settings(cfg)["statusLine"]["command"]
    session = {"model": {"display_name": "Opus"}, "workspace": {"current_dir": "/tmp"}}
    env = dict(os.environ, COLUMNS="120", STATUSLINE_GIT_RAW="")
    p = subprocess.run(["sh", "-c", command], input=json.dumps(session), capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=30)
    expect(p.returncode == 0 and "Opus" in p.stdout, f"rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")


def test_install_keeps_other_settings_and_saves_the_previous_statusline():
    cfg = config_dir({"model": "opus", "permissions": {"allow": ["Bash(ls)"]}, "statusLine": OLD})
    sh("install.sh", cfg)
    s = settings(cfg)
    expect(s["model"] == "opus" and s["permissions"] == {"allow": ["Bash(ls)"]}, s)
    expect(INSTALL_DIR in s["statusLine"]["command"], s)
    expect(saved_previous(cfg) == OLD, "previous statusLine not saved")
    expect(glob.glob(os.path.join(cfg, "settings.json.bak-*")), "no settings backup")


def test_reinstall_keeps_the_original_previous_statusline():
    cfg = config_dir({"statusLine": OLD})
    sh("install.sh", cfg)
    sh("install.sh", cfg)
    expect(saved_previous(cfg) == OLD, saved_previous(cfg))


def test_plain_flag_sets_glyph_mode_in_the_command():
    cfg = config_dir()
    sh("install.sh", cfg, "--plain")
    command = settings(cfg)["statusLine"]["command"]
    expect(command.startswith("STATUSLINE_GLYPHS=plain "), command)


def test_unknown_option_is_rejected():
    cfg = config_dir()
    p = sh("install.sh", cfg, "--bogus")
    expect(p.returncode != 0 and not os.path.exists(os.path.join(cfg, "settings.json")), p.stderr)


def test_invalid_settings_json_aborts_without_changes():
    cfg = config_dir("{ not json")
    p = sh("install.sh", cfg)
    expect(p.returncode != 0, "install succeeded on invalid JSON")
    with open(os.path.join(cfg, "settings.json")) as f:
        expect(f.read() == "{ not json", "settings.json was modified")
    expect(not os.path.exists(os.path.join(cfg, INSTALL_DIR)), "files installed despite the error")


def test_uninstall_restores_the_previous_statusline():
    cfg = config_dir({"statusLine": OLD, "model": "opus"})
    sh("install.sh", cfg)
    p = sh("uninstall.sh", cfg)
    expect(p.returncode == 0, p.stderr)
    s = settings(cfg)
    expect(s["statusLine"] == OLD and s["model"] == "opus", s)
    expect(not os.path.exists(os.path.join(cfg, INSTALL_DIR)), "install directory left behind")


def test_uninstall_removes_a_statusline_it_added():
    cfg = config_dir({"model": "opus"})
    sh("install.sh", cfg)
    sh("uninstall.sh", cfg)
    expect("statusLine" not in settings(cfg), settings(cfg))


def test_uninstall_leaves_a_statusline_changed_after_install():
    cfg = config_dir()
    sh("install.sh", cfg)
    s = settings(cfg)
    s["statusLine"] = {"type": "command", "command": "mine.sh"}
    write_settings(cfg, s)
    sh("uninstall.sh", cfg)
    expect(settings(cfg)["statusLine"]["command"] == "mine.sh", settings(cfg))


def main():
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and flt in n]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001 - report every failure kind
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
