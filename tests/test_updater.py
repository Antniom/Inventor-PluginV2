"""Tests for LMInventor safe background auto-updater.

Verifies:
- ZERO stdout writes (never corrupts stdio MCP transport)
- Non-blocking startup & background thread execution
- 7-day throttle behavior & force bypass
- Private repo auth resolution hierarchy (INVENTOR_MCP_GITHUB_TOKEN -> GITHUB_TOKEN -> gh auth token)
- Git install update flow, pre-flight safety (clean working tree, branch main, ancestry)
- Automatic rollback on verification failure (git reset --keep / zip backup restore)
- Zip/folder install update flow via simulated archive download
- INVENTOR_MCP_AUTOUPDATE modes: off, check, apply
- pyproject.toml & skills/ change detection
"""

import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from src import updater


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Fixture providing clean environment and temporary state directory."""
    monkeypatch.delenv("INVENTOR_MCP_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("INVENTOR_MCP_AUTOUPDATE", raising=False)
    
    # Isolate state directory to tmp_path
    state_file = tmp_path / "updater.json"
    monkeypatch.setattr(updater, "get_state_file_path", lambda: str(state_file))
    return tmp_path


def test_stdout_is_never_written(clean_env, capsys):
    """STRICT INVARIANT: updater MUST NEVER write to stdout.
    Any stdout write breaks JSON-RPC protocol framing for stdio MCP clients.
    """
    # 1. Test logger
    updater._log_err("Test error output strictly to stderr")
    captured = capsys.readouterr()
    assert captured.out == "", "Updater wrote to stdout via _log_err!"
    assert "Test error output" in captured.err

    # 2. Test status summary
    summary = updater.get_updater_status_summary()
    assert isinstance(summary, dict)
    captured = capsys.readouterr()
    assert captured.out == "", "get_updater_status_summary wrote to stdout!"

    # 3. Test load_state and save_state
    st = updater.load_state()
    st["test_key"] = "test_val"
    updater.save_state(st)
    captured = capsys.readouterr()
    assert captured.out == "", "save_state or load_state wrote to stdout!"


def test_get_github_token_hierarchy(clean_env, monkeypatch):
    """Verify 3-tier auth token lookup hierarchy:
    1. INVENTOR_MCP_GITHUB_TOKEN
    2. GITHUB_TOKEN
    3. `gh auth token`
    """
    # Tier 1: INVENTOR_MCP_GITHUB_TOKEN
    monkeypatch.setenv("INVENTOR_MCP_GITHUB_TOKEN", "token_inv_123")
    monkeypatch.setenv("GITHUB_TOKEN", "token_gh_456")
    assert updater.get_github_token() == "token_inv_123"

    # Tier 2: GITHUB_TOKEN fallback
    monkeypatch.delenv("INVENTOR_MCP_GITHUB_TOKEN", raising=False)
    assert updater.get_github_token() == "token_gh_456"

    # Tier 3: `gh auth token` fallback
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def mock_run_gh(args, **kwargs):
        if args[0] == "gh" and args[1:] == ["auth", "token"]:
            return subprocess.CompletedProcess(args, 0, stdout="token_from_gh_cli\n", stderr="")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="command not found")

    monkeypatch.setattr(subprocess, "run", mock_run_gh)
    assert updater.get_github_token() == "token_from_gh_cli"

    # Fallback to None when no auth available
    def mock_run_gh_fail(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="not logged in")

    monkeypatch.setattr(subprocess, "run", mock_run_gh_fail)
    assert updater.get_github_token() is None


def test_throttle_respected_less_than_7_days(clean_env, tmp_path, monkeypatch):
    """Auto-update check must skip remote queries if last check occurred < 7 days ago."""
    fake_plugin_root = tmp_path / "plugin"
    fake_plugin_root.mkdir()
    (fake_plugin_root / "plugin.json").write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")

    # Save state recorded 2 days ago
    two_days_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).isoformat()
    updater.save_state({
        "last_check_utc": two_days_ago,
        "latest_sha": "abc1234",
        "update_available": False,
    })

    # Unforced check -> throttled
    res = updater.check_for_updates(force=False, plugin_root=str(fake_plugin_root))
    assert res["checked"] is False
    assert res["throttled"] is True
    assert "7 days" in res["reason"]

    # Forced check -> bypasses throttle
    # Mock network call for zip install
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"sha": "abc1234"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res_forced = updater.check_for_updates(force=True, plugin_root=str(fake_plugin_root))
        assert res_forced["checked"] is True
        assert res_forced["throttled"] is False


def test_offline_behavior_network_failure(clean_env, tmp_path, monkeypatch, capsys):
    """Network failure or offline state must not raise exceptions or crash the server."""
    fake_plugin_root = tmp_path / "plugin_git"
    fake_plugin_root.mkdir()
    (fake_plugin_root / ".git").mkdir()

    # Mock git fetch timeout / network error
    def mock_run_git(args, **kwargs):
        if "fetch" in args:
            return subprocess.CompletedProcess(["git"] + args, 128, stdout="", stderr="fatal: unable to access: Could not resolve host")
        if "rev-parse" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="main\n", stderr="")
        return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")

    monkeypatch.setattr(updater, "run_git", mock_run_git)

    res = updater.check_for_updates(force=True, plugin_root=str(fake_plugin_root))
    assert res["checked"] is True
    assert res["update_available"] is False
    assert "git fetch failed" in res["error"]

    captured = capsys.readouterr()
    assert captured.out == "", "Offline check wrote to stdout!"


def test_refuse_dirty_working_tree(clean_env, tmp_path, monkeypatch):
    """Update must be refused if local git working tree has uncommitted modifications."""
    fake_git_root = tmp_path / "git_repo"
    fake_git_root.mkdir()
    (fake_git_root / ".git").mkdir()

    # Mock check_for_updates to report update_available=True
    monkeypatch.setattr(updater, "check_for_updates", lambda force=True, plugin_root=None: {
        "checked": True,
        "update_available": True,
        "install_type": "git",
        "latest_sha": "def5678",
        "installed_sha": "abc1234",
        "incoming_commits": ["def5678 feat: new feature"],
    })

    # Mock git status returning dirty files
    def mock_run_git(args, **kwargs):
        if "status" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout=" M src/inventor_api.py\n", stderr="")
        if "rev-parse" in args and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="main\n", stderr="")
        return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")

    monkeypatch.setattr(updater, "run_git", mock_run_git)

    res = updater.update_plugin(confirm=True, plugin_root=str(fake_git_root))
    assert res["success"] is False
    assert res["action"] == "refused"
    assert "uncommitted local changes" in res["reason"]
    assert "M src/inventor_api.py" in res["dirty_files"]


def test_refuse_non_main_branch_or_diverged(clean_env, tmp_path, monkeypatch):
    """Update must be refused if current branch is not 'main' or local has commits ahead."""
    fake_git_root = tmp_path / "git_repo"
    fake_git_root.mkdir()
    (fake_git_root / ".git").mkdir()

    monkeypatch.setattr(updater, "check_for_updates", lambda force=True, plugin_root=None: {
        "checked": True,
        "update_available": True,
        "install_type": "git",
        "latest_sha": "def5678",
        "installed_sha": "abc1234",
        "incoming_commits": ["def5678 feat: new feature"],
    })

    # 1. Non-main branch test
    def mock_run_git_feature_branch(args, **kwargs):
        if "rev-parse" in args and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="feature/my-work\n", stderr="")
        return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")

    monkeypatch.setattr(updater, "run_git", mock_run_git_feature_branch)
    res = updater.update_plugin(confirm=True, plugin_root=str(fake_git_root))
    assert res["success"] is False
    assert res["action"] == "refused"
    assert "feature/my-work" in res["reason"]

    # 2. Local commits ahead of remote test
    def mock_run_git_diverged(args, **kwargs):
        if "rev-parse" in args and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="main\n", stderr="")
        if "status" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")
        if "rev-list" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="local_sha_ahead\n", stderr="")
        return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")

    monkeypatch.setattr(updater, "run_git", mock_run_git_diverged)
    res_div = updater.update_plugin(confirm=True, plugin_root=str(fake_git_root))
    assert res_div["success"] is False
    assert res_div["action"] == "refused"
    assert "local commits exist" in res_div["reason"]


def test_fast_forward_success_git(clean_env, tmp_path, monkeypatch):
    """Verify clean fast-forward merge update flow and dry-run preview."""
    fake_git_root = tmp_path / "git_repo"
    fake_git_root.mkdir()
    (fake_git_root / ".git").mkdir()

    monkeypatch.setattr(updater, "check_for_updates", lambda force=True, plugin_root=None: {
        "checked": True,
        "update_available": True,
        "install_type": "git",
        "latest_sha": "def5678",
        "installed_sha": "abc1234",
        "incoming_commits": ["def5678 feat: new tools added"],
    })

    # Dry-run test (confirm=False)
    dry = updater.update_plugin(confirm=False, plugin_root=str(fake_git_root))
    assert dry["success"] is True
    assert dry["action"] == "dry_run"
    assert dry["confirm_required"] is True

    # Real run test (confirm=True)
    def mock_run_git_success(args, **kwargs):
        if "rev-parse" in args and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="main\n", stderr="")
        if "status" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")
        if "rev-list" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")
        if "rev-parse" in args and "HEAD" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="abc1234\n", stderr="")
        if "merge" in args and "--ff-only" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="Updating abc1234..def5678\nFast-forward\n", stderr="")
        if "diff" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="pyproject.toml\nskills/kinematics.md\n", stderr="")
        return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")

    monkeypatch.setattr(updater, "run_git", mock_run_git_success)
    # Mock verify_installation to pass
    monkeypatch.setattr(updater, "verify_installation", lambda root: (True, "OK"))

    res = updater.update_plugin(confirm=True, plugin_root=str(fake_git_root))
    assert res["success"] is True
    assert res["action"] == "applied"
    assert res["restart_required"] is True
    assert res["dependencies_changed"] is True
    assert res["skills_changed"] is True
    assert any("pip install -e ." in note for note in res["notes"])
    assert any("skills" in note for note in res["notes"])


def test_verification_failure_automatic_rollback_git(clean_env, tmp_path, monkeypatch):
    """If post-update verification fails, git reset --keep must execute to restore pre-update commit."""
    fake_git_root = tmp_path / "git_repo"
    fake_git_root.mkdir()
    (fake_git_root / ".git").mkdir()

    monkeypatch.setattr(updater, "check_for_updates", lambda force=True, plugin_root=None: {
        "checked": True,
        "update_available": True,
        "install_type": "git",
        "latest_sha": "bad5678",
        "installed_sha": "good1234",
        "incoming_commits": ["bad5678 broken commit"],
    })

    reset_called_with = []

    def mock_run_git(args, **kwargs):
        if "rev-parse" in args and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="main\n", stderr="")
        if "status" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")
        if "rev-list" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")
        if "rev-parse" in args and "HEAD" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="good1234\n", stderr="")
        if "merge" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="Fast-forward\n", stderr="")
        if "reset" in args:
            reset_called_with.append(args)
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="HEAD is now at good1234\n", stderr="")
        return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")

    monkeypatch.setattr(updater, "run_git", mock_run_git)
    # Simulate verification failure (e.g., syntax error in new code)
    monkeypatch.setattr(updater, "verify_installation", lambda root: (False, "SyntaxError in src/server.py"))

    res = updater.update_plugin(confirm=True, plugin_root=str(fake_git_root))
    assert res["success"] is False
    assert res["action"] == "rolled_back"
    assert "SyntaxError in src/server.py" in res["reason"]
    assert "good123" in res["reason"]
    assert len(reset_called_with) == 1
    assert reset_called_with[0] == ["reset", "--keep", "good1234"]


def test_zip_install_path_and_rollback(clean_env, tmp_path, monkeypatch):
    """Test update and rollback flow for zip/folder installations (no .git)."""
    fake_plugin_root = tmp_path / "zip_plugin"
    fake_plugin_root.mkdir()
    (fake_plugin_root / "src").mkdir()
    (fake_plugin_root / "src" / "server.py").write_text("# server v1", encoding="utf-8")
    (fake_plugin_root / "plugin.json").write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")

    monkeypatch.setenv("INVENTOR_MCP_GITHUB_TOKEN", "mock_token")

    monkeypatch.setattr(updater, "check_for_updates", lambda force=True, plugin_root=None: {
        "checked": True,
        "update_available": True,
        "install_type": "zip",
        "latest_sha": "new_sha_999",
        "installed_sha": "old_sha_111",
        "incoming_commits": ["new_sha_999 Release v2.1.0"],
    })

    # Prepare an in-memory zip archive mimicking GitHub repo zipball
    zip_bytes_io = io.BytesIO()
    with zipfile.ZipFile(zip_bytes_io, "w") as z:
        z.writestr("Antniom-LMInventor-plugin-new_sha_999/src/server.py", "# server v2 updated")
        z.writestr("Antniom-LMInventor-plugin-new_sha_999/plugin.json", json.dumps({"version": "2.1.0"}))
    zip_bytes = zip_bytes_io.getvalue()

    # 1. Success case
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [zip_bytes]
        # Allow copyfileobj to read
        mock_resp.__enter__.return_value = io.BytesIO(zip_bytes)
        mock_urlopen.return_value = mock_resp

        monkeypatch.setattr(updater, "verify_installation", lambda root: (True, "OK"))

        res = updater.update_plugin(confirm=True, plugin_root=str(fake_plugin_root))
        assert res["success"] is True
        assert res["action"] == "applied"
        assert res["restart_required"] is True
        assert (fake_plugin_root / "src" / "server.py").read_text(encoding="utf-8") == "# server v2 updated"

    # 2. Failure & Rollback case
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = io.BytesIO(zip_bytes)
        mock_urlopen.return_value = mock_resp

        # Fail verification -> must restore backup
        monkeypatch.setattr(updater, "verify_installation", lambda root: (False, "Corrupted import"))

        res_fail = updater.update_plugin(confirm=True, plugin_root=str(fake_plugin_root))
        assert res_fail["success"] is False
        assert res_fail["action"] == "rolled_back"
        assert "Backup restored" in res_fail["reason"]


def test_autoupdate_env_modes(monkeypatch):
    """Verify INVENTOR_MCP_AUTOUPDATE settings (off, check, apply)."""
    check_called = False
    update_called = False

    def mock_check(force=False):
        nonlocal check_called
        check_called = True
        return {"update_available": True, "throttled": False}

    def mock_update(confirm=False):
        nonlocal update_called
        update_called = True
        return {"success": True}

    monkeypatch.setattr(updater, "check_for_updates", mock_check)
    monkeypatch.setattr(updater, "update_plugin", mock_update)

    # Mode: off
    monkeypatch.setenv("INVENTOR_MCP_AUTOUPDATE", "off")
    check_called = update_called = False
    updater._background_worker()
    assert not check_called and not update_called

    # Mode: check
    monkeypatch.setenv("INVENTOR_MCP_AUTOUPDATE", "check")
    check_called = update_called = False
    updater._background_worker()
    assert check_called and not update_called

    # Mode: apply
    monkeypatch.setenv("INVENTOR_MCP_AUTOUPDATE", "apply")
    check_called = update_called = False
    updater._background_worker()
    assert check_called and update_called


def test_server_mcp_updater_tools_and_status(clean_env, monkeypatch, capsys):
    """Test check_for_updates, update_plugin, and status() exposed via server.py."""
    from src import server

    # Mock updater responses
    monkeypatch.setattr(updater, "check_for_updates", lambda force=False: {
        "checked": True,
        "throttled": False,
        "installed_sha": "sha_local_111",
        "latest_sha": "sha_remote_222",
        "update_available": True,
        "incoming_commits": ["sha_remote_222 feat: new kinematics"],
    })
    monkeypatch.setattr(updater, "update_plugin", lambda confirm=False: {
        "success": True,
        "action": "dry_run" if not confirm else "applied",
        "restart_required": confirm,
    })

    # 1. Test check_for_updates tool
    raw_chk = server.check_for_updates(force=True)
    res_chk = json.loads(raw_chk)
    assert res_chk["update_available"] is True
    assert res_chk["latest_sha"] == "sha_remote_222"

    # 2. Test update_plugin tool dry-run
    raw_dry = server.update_plugin(confirm=False)
    res_dry = json.loads(raw_dry)
    assert res_dry["action"] == "dry_run"
    assert res_dry["restart_required"] is False

    # 3. Test update_plugin tool confirm
    raw_apply = server.update_plugin(confirm=True)
    res_apply = json.loads(raw_apply)
    assert res_apply["action"] == "applied"
    assert res_apply["restart_required"] is True

    # 4. Test status() tool includes updater summary
    status_raw = server.status()
    status_data = json.loads(status_raw)
    assert "updater" in status_data
    assert "installed_sha" in status_data["updater"]

    # 5. Test inventor://status resource includes updater summary
    res_status_raw = server.get_status_resource()
    res_status = json.loads(res_status_raw)
    assert "updater" in res_status

    # 6. Verify zero writes to stdout
    captured = capsys.readouterr()
    assert captured.out == "", f"Server tool/resource wrote to stdout: {captured.out}"


def test_untracked_files_do_not_block_update(clean_env, tmp_path, monkeypatch):
    """Untracked files (e.g. .mcp.json, .pytest_cache) must NOT block updates."""
    fake_git_root = tmp_path / "git_repo"
    fake_git_root.mkdir()
    (fake_git_root / ".git").mkdir()

    monkeypatch.setattr(updater, "check_for_updates", lambda force=True, plugin_root=None: {
        "checked": True,
        "update_available": True,
        "install_type": "git",
        "latest_sha": "def5678",
        "installed_sha": "abc1234",
        "incoming_commits": ["def5678 feat: new feature"],
    })

    def mock_run_git(args, **kwargs):
        if "rev-parse" in args and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="main\n", stderr="")
        if "status" in args:
            # When --untracked-files=no is used, untracked files are excluded
            assert "--untracked-files=no" in args
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")
        if "rev-list" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")
        if "rev-parse" in args and "HEAD" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="abc1234\n", stderr="")
        if "merge" in args and "--ff-only" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="Fast-forward\n", stderr="")
        if "diff" in args:
            return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(["git"] + args, 0, stdout="", stderr="")

    monkeypatch.setattr(updater, "run_git", mock_run_git)
    monkeypatch.setattr(updater, "verify_installation", lambda root: (True, "OK"))

    res = updater.update_plugin(confirm=True, plugin_root=str(fake_git_root))
    assert res["success"] is True
    assert res["action"] == "applied"


def test_run_git_token_in_temp_config_not_command_line(clean_env, monkeypatch):
    """Auth tokens must NEVER be passed as raw command line arguments (process inspection safety).
    GCM_INTERACTIVE must be set to 'never' to prevent modal popup windows.
    """
    secret = "secret_pat_xyz_12345"
    captured_calls = []

    real_run = subprocess.run

    def mock_subprocess_run(cmd, **kwargs):
        captured_calls.append((cmd, kwargs))
        # Ensure token is NOT in command-line arguments
        for arg in cmd:
            assert secret not in arg, f"Secret token leaked into command line argument: {arg}"
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    res = updater.run_git(["fetch", "origin", "main"], auth_token=secret)
    assert len(captured_calls) == 1
    called_cmd, called_kwargs = captured_calls[0]

    # Verify include.path was used
    assert any(arg.startswith("include.path=") for arg in called_cmd)
    # Verify environment flags
    env = called_kwargs["env"]
    assert env["GCM_INTERACTIVE"] == "never"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_reload_api_refuses_when_restart_required(clean_env, monkeypatch):
    """reload_api must refuse to reload inventor_api if a pending update requires server restart."""
    from src import server

    # 1. restart_required = True -> refused
    monkeypatch.setattr(updater, "load_state", lambda: {"restart_required": True})
    msg = server.reload_api()
    assert "Refusing reload" in msg
    assert "restart" in msg

    # 2. restart_required = False -> allowed
    monkeypatch.setattr(updater, "load_state", lambda: {"restart_required": False})
    msg_ok = server.reload_api()
    assert "reloaded" in msg_ok


def test_connect_raises_when_pywin32_missing(monkeypatch):
    """connect() must raise an informative RuntimeError if pywin32 is not installed."""
    from src import inventor_api
    monkeypatch.setattr(inventor_api, "win32com", None)
    monkeypatch.setattr(inventor_api, "pythoncom", None)
    
    conn = inventor_api.InventorConnection()
    with pytest.raises(RuntimeError) as exc_info:
        conn.connect()
    assert "pywin32 is not installed" in str(exc_info.value)
    assert "pip install pywin32" in str(exc_info.value)


def test_zip_rollback_preserves_untracked_files_and_tracked_assets(clean_env, tmp_path, monkeypatch):
    """Rollback on verification failure must NEVER delete untracked files
    (scratch.ipt, render.png, OldVersions/, gen_py/, *.log), and must preserve
    tracked binary assets (assets/logo.png).
    """
    fake_plugin_root = tmp_path / "zip_plugin"
    fake_plugin_root.mkdir()
    (fake_plugin_root / "src").mkdir()
    (fake_plugin_root / "src" / "server.py").write_text("# server v1", encoding="utf-8")
    (fake_plugin_root / "plugin.json").write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")

    # Tracked asset that should be backed up and preserved
    (fake_plugin_root / "assets").mkdir()
    (fake_plugin_root / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nfake_logo_data")

    # Untracked files and folders that the update should NEVER touch or wipe
    (fake_plugin_root / "scratch.ipt").write_bytes(b"inventor_part_binary")
    (fake_plugin_root / "render.png").write_bytes(b"render_image_binary")
    (fake_plugin_root / "run.log").write_text("local log lines", encoding="utf-8")
    (fake_plugin_root / "OldVersions").mkdir()
    (fake_plugin_root / "OldVersions" / "scratch.0001.ipt").write_bytes(b"old_binary")
    (fake_plugin_root / "gen_py").mkdir()
    (fake_plugin_root / "gen_py" / "cache.dat").write_text("com cache", encoding="utf-8")

    monkeypatch.setenv("INVENTOR_MCP_GITHUB_TOKEN", "mock_token")
    monkeypatch.setattr(updater, "check_for_updates", lambda force=True, plugin_root=None: {
        "checked": True,
        "update_available": True,
        "install_type": "zip",
        "latest_sha": "new_sha_999",
        "installed_sha": "old_sha_111",
        "incoming_commits": ["new_sha_999 Release v2.1.0"],
    })

    # Prepare archive that contains updated code
    zip_bytes_io = io.BytesIO()
    with zipfile.ZipFile(zip_bytes_io, "w") as z:
        z.writestr("Antniom-LMInventor-plugin-new_sha_999/src/server.py", "# broken server v2")
        z.writestr("Antniom-LMInventor-plugin-new_sha_999/plugin.json", json.dumps({"version": "2.1.0"}))
        z.writestr("Antniom-LMInventor-plugin-new_sha_999/assets/logo.png", b"\x89PNG\r\n\x1a\nnew_logo_data")
    zip_bytes = zip_bytes_io.getvalue()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = io.BytesIO(zip_bytes)
        mock_urlopen.return_value = mock_resp

        # Force a verification failure
        monkeypatch.setattr(updater, "verify_installation", lambda root: (False, "Corrupted syntax error in update"))

        res = updater.update_plugin(confirm=True, plugin_root=str(fake_plugin_root))
        assert res["success"] is False
        assert res["action"] == "rolled_back"
        assert "Backup restored" in res["reason"]

    # Assert that ALL untracked files and folders still exist completely intact
    assert (fake_plugin_root / "scratch.ipt").exists()
    assert (fake_plugin_root / "scratch.ipt").read_bytes() == b"inventor_part_binary"
    assert (fake_plugin_root / "render.png").exists()
    assert (fake_plugin_root / "render.png").read_bytes() == b"render_image_binary"
    assert (fake_plugin_root / "run.log").exists()
    assert (fake_plugin_root / "run.log").read_text(encoding="utf-8") == "local log lines"
    assert (fake_plugin_root / "OldVersions").exists()
    assert (fake_plugin_root / "OldVersions" / "scratch.0001.ipt").read_bytes() == b"old_binary"
    assert (fake_plugin_root / "gen_py").exists()
    assert (fake_plugin_root / "gen_py" / "cache.dat").read_text(encoding="utf-8") == "com cache"

    # Assert that tracked asset was restored to its original pre-update state
    assert (fake_plugin_root / "assets" / "logo.png").exists()
    assert (fake_plugin_root / "assets" / "logo.png").read_bytes() == b"\x89PNG\r\n\x1a\nfake_logo_data"
    assert (fake_plugin_root / "src" / "server.py").read_text(encoding="utf-8") == "# server v1"


def test_zip_update_dirs_exist_ok_when_directory_deletion_fails(clean_env, tmp_path, monkeypatch):
    """On Windows, if a folder cannot be deleted due to a transient file lock,
    shutil.rmtree(..., ignore_errors=True) leaves the folder in place.
    shutil.copytree with dirs_exist_ok=True must merge/overwrite successfully
    without throwing FileExistsError."""
    fake_plugin_root = tmp_path / "zip_plugin_locked"
    fake_plugin_root.mkdir()
    (fake_plugin_root / "src").mkdir()
    (fake_plugin_root / "src" / "server.py").write_text("# server v1", encoding="utf-8")
    (fake_plugin_root / "plugin.json").write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")

    monkeypatch.setenv("INVENTOR_MCP_GITHUB_TOKEN", "mock_token")
    monkeypatch.setattr(updater, "check_for_updates", lambda force=True, plugin_root=None: {
        "checked": True,
        "update_available": True,
        "install_type": "zip",
        "latest_sha": "new_sha_dirs_exist",
        "installed_sha": "old_sha",
        "incoming_commits": ["new_sha_dirs_exist Update"],
    })

    zip_bytes_io = io.BytesIO()
    with zipfile.ZipFile(zip_bytes_io, "w") as z:
        z.writestr("Antniom-LMInventor-plugin-new_sha_dirs_exist/src/server.py", "# server v2 updated")
        z.writestr("Antniom-LMInventor-plugin-new_sha_dirs_exist/plugin.json", json.dumps({"version": "2.1.0"}))
    zip_bytes = zip_bytes_io.getvalue()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = io.BytesIO(zip_bytes)
        mock_urlopen.return_value = mock_resp

        # Mock shutil.rmtree to be a no-op so the existing destination folder is never deleted
        monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: None)
        monkeypatch.setattr(updater, "verify_installation", lambda root: (True, "OK"))

        res = updater.update_plugin(confirm=True, plugin_root=str(fake_plugin_root))
        assert res["success"] is True
        assert res["action"] == "applied"
        assert (fake_plugin_root / "src" / "server.py").read_text(encoding="utf-8") == "# server v2 updated"




