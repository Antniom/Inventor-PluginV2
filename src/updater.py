"""Safe Auto-Updater for Autodesk Inventor AI Studio Plugin (LMInventor-plugin).

Self-contained module for checking and applying updates from GitHub.
No Autodesk Inventor COM dependencies.

HARD CONSTRAINTS (stdio transport):
- NEVER print to stdout. Logging is directed to sys.stderr only.
- NEVER block startup. Background checks run in a daemon thread with <=10s timeouts.
- No shell=True. Git runs with argument lists and GIT_TERMINAL_PROMPT=0.
- Cross-platform Windows (and Python 3.12+) compatibility.
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from typing import Any

# Hardcoded repository — NEVER take from env or config
REPO_OWNER = "Antniom"
REPO_NAME = "LMInventor-plugin"
REPO_FULL = f"{REPO_OWNER}/{REPO_NAME}"
GITHUB_API_COMMITS_URL = f"https://api.github.com/repos/{REPO_FULL}/commits/main"
GITHUB_API_ZIPBALL_URL = f"https://api.github.com/repos/{REPO_FULL}/zipball/main"

# 7 days throttle interval in seconds
CHECK_INTERVAL_SECONDS = 7 * 24 * 3600  # 604800s


def _log_err(msg: str) -> None:
    """Log to stderr only. Never print to stdout to protect stdio JSON-RPC transport."""
    try:
        sys.stderr.write(f"[inventor-updater] {msg}\n")
        sys.stderr.flush()
    except Exception:
        pass


def get_plugin_root() -> str:
    """Resolve the root directory of the installed plugin."""
    # src/updater.py -> parent of src/ is plugin root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_state_file_path() -> str:
    """Resolve the path to updater.json under user config dir, NOT in repo."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        dir_path = os.path.join(base, "inventor-mcp")
    else:
        base = os.path.expanduser("~/.config")
        dir_path = os.path.join(base, "inventor-mcp")
    return os.path.join(dir_path, "updater.json")


def load_state() -> dict[str, Any]:
    """Load updater state from the user config directory."""
    path = get_state_file_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            _log_err(f"Failed to read state file: {e}")
    return {
        "last_check_utc": None,
        "installed_sha": None,
        "latest_sha": None,
        "update_available": False,
        "restart_required": False,
        "last_result": None,
        "last_error": None,
    }


def save_state(state: dict[str, Any]) -> None:
    """Atomically write updater state to the user config directory."""
    path = get_state_file_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix="updater_", suffix=".tmp", dir=os.path.dirname(path)
        )
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as e:
        _log_err(f"Failed to save state file: {e}")


def get_github_token() -> str | None:
    """Retrieve private repository auth token in strict hierarchy order.
    1. INVENTOR_MCP_GITHUB_TOKEN
    2. GITHUB_TOKEN
    3. gh auth token
    Never log, print, or store the token.
    """
    token = os.environ.get("INVENTOR_MCP_GITHUB_TOKEN")
    if token and token.strip():
        return token.strip()

    token = os.environ.get("GITHUB_TOKEN")
    if token and token.strip():
        return token.strip()

    try:
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        res = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=env,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    return None


def detect_install_type(plugin_root: str | None = None) -> str:
    """Detect whether plugin is a Git clone or a copied folder/zip install."""
    root = plugin_root or get_plugin_root()
    git_dir = os.path.join(root, ".git")
    if os.path.isdir(git_dir):
        return "git"
    return "zip"


def get_installed_info(plugin_root: str | None = None) -> dict[str, Any]:
    """Retrieve installed version and commit SHA."""
    root = plugin_root or get_plugin_root()
    install_type = detect_install_type(root)
    version = "2.0.0"
    sha = None

    plugin_json_path = os.path.join(root, "plugin.json")
    if os.path.isfile(plugin_json_path):
        try:
            with open(plugin_json_path, "r", encoding="utf-8") as f:
                pj = json.load(f)
                version = pj.get("version", version)
        except Exception:
            pass

    if install_type == "git":
        try:
            res = run_git(["rev-parse", "HEAD"], cwd=root, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                sha = res.stdout.strip()
        except Exception:
            pass

    if not sha:
        state = load_state()
        sha = state.get("installed_sha")

    return {
        "install_type": install_type,
        "version": version,
        "sha": sha,
    }


def run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 10,
    auth_token: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute git with argument list, timeout, and terminal prompts disabled.
    Never uses shell=True. Passes credentials via temporary config to avoid
    exposing tokens on the process command line.
    """
    root = cwd or get_plugin_root()
    cmd = ["git"]
    temp_cfg_path = None
    try:
        if auth_token:
            # Use Basic auth with x-access-token for GitHub git-over-HTTPS.
            # Store in a temporary .gitconfig so the token NEVER shows in command line arguments.
            auth_b64 = base64.b64encode(f"x-access-token:{auth_token}".encode("utf-8")).decode("ascii")
            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".gitconfig", encoding="utf-8"
            ) as f:
                f.write(f"[http]\n    extraHeader = Authorization: Basic {auth_b64}\n")
                temp_cfg_path = f.name
            normalized_cfg = temp_cfg_path.replace("\\", "/")
            cmd.extend(["-c", f"include.path={normalized_cfg}"])

        cmd.extend(args)

        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
        env["GIT_ASKPASS"] = ""

        return subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    finally:
        if temp_cfg_path and os.path.exists(temp_cfg_path):
            try:
                os.remove(temp_cfg_path)
            except OSError:
                pass


def check_for_updates(
    force: bool = False,
    plugin_root: str | None = None,
) -> dict[str, Any]:
    """Check whether installed plugin is behind remote repository main branch.
    Respects 7-day throttle unless force=True.
    Safe read-only check; does not modify files.
    """
    root = plugin_root or get_plugin_root()
    installed = get_installed_info(root)
    state = load_state()
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Throttle check
    last_check_str = state.get("last_check_utc")
    if not force and last_check_str:
        try:
            last_dt = datetime.datetime.fromisoformat(last_check_str)
            if (now - last_dt).total_seconds() < CHECK_INTERVAL_SECONDS:
                return {
                    "checked": False,
                    "throttled": True,
                    "reason": "Throttled: checked less than 7 days ago (use force=True to bypass)",
                    "installed_sha": installed.get("sha"),
                    "installed_version": installed.get("version"),
                    "latest_sha": state.get("latest_sha"),
                    "update_available": state.get("update_available", False),
                    "restart_required": state.get("restart_required", False),
                    "install_type": installed.get("install_type"),
                    "last_check_utc": last_check_str,
                }
        except Exception:
            pass

    token = get_github_token()
    install_type = installed["install_type"]
    latest_sha = None
    update_available = False
    incoming_commits: list[str] = []
    error_msg = None

    if install_type == "git":
        # Check current branch
        branch_res = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root, timeout=5)
        current_branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "unknown"

        # Fetch remote main
        fetch_res = run_git(["fetch", "origin", "main"], cwd=root, timeout=10, auth_token=token)
        if fetch_res.returncode != 0:
            if not token:
                _log_err("No GitHub authentication found. Skipping auto-update check.")
            error_msg = f"git fetch failed: {fetch_res.stderr.strip() or 'network/auth error'}"
        else:
            rev_remote = run_git(["rev-parse", "FETCH_HEAD"], cwd=root, timeout=5)
            rev_local = run_git(["rev-parse", "HEAD"], cwd=root, timeout=5)
            if rev_remote.returncode == 0 and rev_local.returncode == 0:
                latest_sha = rev_remote.stdout.strip()
                local_sha = rev_local.stdout.strip()

                if local_sha != latest_sha:
                    # Check if local is ancestor of remote (fast-forwardable)
                    anc_res = run_git(
                        ["merge-base", "--is-ancestor", local_sha, latest_sha],
                        cwd=root,
                        timeout=5,
                    )
                    if anc_res.returncode == 0:
                        update_available = True
                        log_res = run_git(
                            ["log", f"{local_sha}..{latest_sha}", "--oneline", "-n", "20"],
                            cwd=root,
                            timeout=5,
                        )
                        if log_res.returncode == 0 and log_res.stdout.strip():
                            incoming_commits = [
                                line.strip()
                                for line in log_res.stdout.strip().splitlines()
                                if line.strip()
                            ]
                    else:
                        error_msg = "Local repository branch has diverged from origin/main."
                else:
                    update_available = False

    else:
        # Zip / folder install: query GitHub API
        headers = {
            "User-Agent": "LMInventor-AutoUpdater/2.0",
            "Accept": "application/vnd.github.v3+json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(GITHUB_API_COMMITS_URL, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latest_sha = data.get("sha")
                local_sha = installed.get("sha")
                if latest_sha and local_sha != latest_sha:
                    update_available = True
                    commit_msg = data.get("commit", {}).get("message", "").splitlines()
                    first_line = commit_msg[0] if commit_msg else ""
                    incoming_commits = [f"{latest_sha[:7]} {first_line}".strip()]
                else:
                    update_available = False
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404) and not token:
                _log_err("No GitHub authentication found. Skipping auto-update check.")
            error_msg = f"GitHub API request failed (HTTP {e.code}): {e.reason}"
        except Exception as e:
            error_msg = f"GitHub API check failed: {e}"

    # Update state file
    now_str = now.isoformat()
    state.update(
        {
            "last_check_utc": now_str,
            "installed_sha": installed.get("sha"),
            "latest_sha": latest_sha or state.get("latest_sha"),
            "update_available": update_available,
            "last_error": error_msg,
        }
    )
    save_state(state)

    return {
        "checked": True,
        "throttled": False,
        "installed_sha": installed.get("sha"),
        "installed_version": installed.get("version"),
        "latest_sha": latest_sha,
        "update_available": update_available,
        "incoming_commits": incoming_commits,
        "restart_required": state.get("restart_required", False),
        "install_type": install_type,
        "last_check_utc": now_str,
        "error": error_msg,
    }


def verify_installation(plugin_root: str) -> tuple[bool, str]:
    """Verify integrity of updated installation:
    1. py_compile on all src/*.py files
    2. Subprocess import of src.server
    Returns (success, error_description).
    """
    # 1. py_compile check
    src_dir = os.path.join(plugin_root, "src")
    if os.path.isdir(src_dir):
        for fname in os.listdir(src_dir):
            if fname.endswith(".py"):
                fpath = os.path.join(src_dir, fname)
                try:
                    py_compile.compile(fpath, doraise=True)
                except Exception as e:
                    return False, f"py_compile failed on {fname}: {e}"

    # 2. Subprocess import check (isolated from current process)
    env = dict(os.environ)
    env["INVENTOR_MCP_AUTOUPDATE"] = "off"  # Avoid recursive check during verification
    # On Windows, explicitly verify that the required COM dependency pywin32 is present
    verify_script = (
        "import sys\n"
        "if sys.platform == 'win32':\n"
        "    try:\n"
        "        import win32com.client, pythoncom\n"
        "    except ImportError as e:\n"
        "        raise ImportError(f'Missing required pywin32 dependency: {e}')\n"
        "import src.server\n"
    )
    try:
        res = subprocess.run(
            [sys.executable, "-c", verify_script],
            cwd=plugin_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=env,
        )
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip() or f"exit code {res.returncode}"
            return False, f"Subprocess import verification failed: {err}"
    except Exception as e:
        return False, f"Subprocess verification failed to execute: {e}"

    return True, "Verification succeeded"


def update_plugin(
    confirm: bool = False,
    plugin_root: str | None = None,
) -> dict[str, Any]:
    """Apply plugin update with strict safety guarantees:
    - Dry-run by default (confirm=False).
    - Refuses dirty working tree, diverged history, or non-main branch.
    - Fast-forward only.
    - Automatic rollback if py_compile or subprocess import verification fails.
    - Reports if pyproject.toml dependencies or skills/ changed.
    """
    root = plugin_root or get_plugin_root()
    check_res = check_for_updates(force=True, plugin_root=root)

    if check_res.get("error"):
        return {
            "success": False,
            "action": "aborted",
            "reason": f"Update check failed: {check_res['error']}",
            "details": check_res,
        }

    if not check_res.get("update_available"):
        return {
            "success": True,
            "action": "up_to_date",
            "message": "Plugin is already up to date with remote repository.",
            "details": check_res,
        }

    install_type = check_res["install_type"]
    incoming = check_res.get("incoming_commits", [])

    # If dry-run, show what would change
    if not confirm:
        return {
            "success": True,
            "action": "dry_run",
            "message": (
                f"Update available: {len(incoming)} commit(s) on origin/main. "
                f"Call update_plugin(confirm=True) to apply safely."
            ),
            "installed_sha": check_res.get("installed_sha"),
            "latest_sha": check_res.get("latest_sha"),
            "incoming_commits": incoming,
            "install_type": install_type,
            "confirm_required": True,
        }

    # --- APPLY MODE (confirm=True) ---

    token = get_github_token()
    state = load_state()

    if install_type == "git":
        # 1. Branch check: must be main
        branch_res = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root, timeout=5)
        current_branch = branch_res.stdout.strip() if branch_res.returncode == 0 else ""
        if current_branch != "main":
            return {
                "success": False,
                "action": "refused",
                "reason": f"Refusing update: current branch is '{current_branch}', expected 'main'.",
            }

        # 2. Dirty tree check: must be clean (ignoring untracked files)
        status_res = run_git(["status", "--porcelain", "--untracked-files=no"], cwd=root, timeout=5)
        if status_res.returncode != 0 or status_res.stdout.strip():
            dirty_files = [line.strip() for line in status_res.stdout.splitlines() if line.strip()]
            return {
                "success": False,
                "action": "refused",
                "reason": "Refusing update: working tree has uncommitted local changes to tracked files.",
                "dirty_files": dirty_files,
            }

        # 3. Local commits not on origin check
        rev_ahead = run_git(["rev-list", "FETCH_HEAD..HEAD"], cwd=root, timeout=5)
        if rev_ahead.returncode == 0 and rev_ahead.stdout.strip():
            return {
                "success": False,
                "action": "refused",
                "reason": "Refusing update: local commits exist that are not on origin/main.",
            }

        # 4. Record pre-update commit SHA for rollback
        pre_sha = run_git(["rev-parse", "HEAD"], cwd=root, timeout=5).stdout.strip()

        # 5. Fast-forward merge
        merge_res = run_git(["merge", "--ff-only", "FETCH_HEAD"], cwd=root, timeout=10)
        if merge_res.returncode != 0:
            return {
                "success": False,
                "action": "failed",
                "reason": f"Fast-forward merge failed: {merge_res.stderr.strip()}",
            }

        # 6. Post-update verification
        ok, verify_msg = verify_installation(root)
        if not ok:
            # ROLLBACK: reset back to pre_sha safely
            _log_err(f"Post-update verification failed ({verify_msg}). Rolling back...")
            rollback_res = run_git(["reset", "--keep", pre_sha], cwd=root, timeout=10)
            state["last_error"] = f"Verification failed after update ({verify_msg}); rolled back to {pre_sha[:7]}."
            save_state(state)
            return {
                "success": False,
                "action": "rolled_back",
                "reason": f"Post-update verification failed ({verify_msg}). Automatically rolled back to {pre_sha[:7]}.",
                "rollback_status": rollback_res.returncode == 0,
            }

        # 7. Check for pyproject dependencies or skills changes
        diff_res = run_git(["diff", "--name-only", pre_sha, "HEAD"], cwd=root, timeout=5)
        changed_files = diff_res.stdout.splitlines() if diff_res.returncode == 0 else []
        dep_changed = any("pyproject.toml" in f for f in changed_files)
        skills_changed = any(f.startswith("skills") for f in changed_files)

        new_sha = run_git(["rev-parse", "HEAD"], cwd=root, timeout=5).stdout.strip()
        state.update(
            {
                "installed_sha": new_sha,
                "update_available": False,
                "restart_required": True,
                "last_error": None,
            }
        )
        save_state(state)

        notes = ["Update applied successfully. Server restart is required."]
        if dep_changed:
            notes.append("Dependencies changed in pyproject.toml. Run 'pip install -e .' to update.")
        if skills_changed:
            notes.append(
                "Skills directory updated. If you have external skill copies "
                "(e.g. in ~/.claude/skills or Antigravity config), re-sync them manually."
            )

        return {
            "success": True,
            "action": "applied",
            "previous_sha": pre_sha,
            "new_sha": new_sha,
            "restart_required": True,
            "dependencies_changed": dep_changed,
            "skills_changed": skills_changed,
            "notes": notes,
        }

    else:
        # Zip / folder install apply
        if not token:
            return {
                "success": False,
                "action": "refused",
                "reason": "Authentication token required to download zipball for private repository.",
            }

        # Create temporary backup directory of the plugin folder (skipping heavy CAD/media scratch files)
        backup_dir = tempfile.mkdtemp(prefix="inventor_mcp_backup_")
        ignored_exts = (
            ".ipt", ".iam", ".idw", ".dwg", ".step", ".stp", ".sat",
            ".png", ".jpg", ".jpeg", ".zip", ".log", ".tmp",
        )
        ignored_names = {
            ".git", "__pycache__", ".pytest_cache", ".gemini", "OldVersions", "gen_py",
        }
        cad_ignore_filter = shutil.ignore_patterns(
            "*.ipt", "*.iam", "*.idw", "*.dwg", "*.step", "*.stp", "*.sat",
            "*.png", "*.jpg", "*.jpeg", "*.zip", "*.log", "*.tmp",
            "OldVersions", "gen_py", "__pycache__", ".pytest_cache",
        )

        for item in os.listdir(root):
            if item in ignored_names or item.lower().endswith(ignored_exts):
                continue
            src_item = os.path.join(root, item)
            dst_item = os.path.join(backup_dir, item)
            if os.path.isdir(src_item):
                shutil.copytree(src_item, dst_item, ignore=cad_ignore_filter)
            elif os.path.isfile(src_item):
                shutil.copy2(src_item, dst_item)

        staging_dir = tempfile.mkdtemp(prefix="inventor_mcp_stage_")
        zip_path = os.path.join(staging_dir, "release.zip")

        try:
            target_sha = check_res.get("latest_sha")
            # Target the exact commit that was checked to avoid race conditions with main
            target_url = (
                f"https://api.github.com/repos/{REPO_FULL}/zipball/{target_sha}"
                if target_sha
                else GITHUB_API_ZIPBALL_URL
            )
            headers = {
                "User-Agent": "LMInventor-AutoUpdater/2.0",
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"Bearer {token}",
            }
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                with open(zip_path, "wb") as f_out:
                    shutil.copyfileobj(resp, f_out)

            import zipfile
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(staging_dir)

            # Find extracted inner folder (GitHub creates e.g. Antniom-LMInventor-plugin-sha)
            inner_dirs = [
                d for d in os.listdir(staging_dir)
                if os.path.isdir(os.path.join(staging_dir, d)) and d != "__MACOSX"
            ]
            if not inner_dirs:
                raise RuntimeError("Extracted archive did not contain expected root directory")
            inner_root = os.path.join(staging_dir, inner_dirs[0])

            # Replace files in root: remove obsolete installed directories/files
            # while preserving user untracked files (e.g. .mcp.json, .env, *.log)
            archive_items = set(os.listdir(inner_root))
            managed_items = archive_items | {
                "src", "skills", "docs", "tests", "assets",
                "plugin.json", "pyproject.toml", "README.md", "LICENSE", "inventor_mcp_server.py"
            }

            for item in os.listdir(root):
                if item in (".git", "__pycache__", ".pytest_cache", ".gemini", ".mcp.json", ".env"):
                    continue
                if item in managed_items and item not in archive_items:
                    # File/dir deleted upstream
                    d_path = os.path.join(root, item)
                    if os.path.isdir(d_path):
                        shutil.rmtree(d_path)
                    elif os.path.isfile(d_path):
                        os.remove(d_path)

            for item in archive_items:
                if item in (".git", "__pycache__"):
                    continue
                s_path = os.path.join(inner_root, item)
                d_path = os.path.join(root, item)
                if os.path.isdir(s_path):
                    if os.path.exists(d_path):
                        shutil.rmtree(d_path)
                    shutil.copytree(s_path, d_path)
                else:
                    shutil.copy2(s_path, d_path)

            # Verification
            ok, verify_msg = verify_installation(root)
            if not ok:
                _log_err(f"Zip update verification failed ({verify_msg}). Restoring backup...")
                # Clean current files before restoring backup
                for item in os.listdir(root):
                    if item in (".git", "__pycache__", ".pytest_cache", ".gemini", ".mcp.json", ".env"):
                        continue
                    p = os.path.join(root, item)
                    if os.path.isdir(p):
                        shutil.rmtree(p)
                    elif os.path.isfile(p):
                        os.remove(p)
                for item in os.listdir(backup_dir):
                    s_path = os.path.join(backup_dir, item)
                    d_path = os.path.join(root, item)
                    if os.path.isdir(s_path):
                        shutil.copytree(s_path, d_path)
                    else:
                        shutil.copy2(s_path, d_path)
                return {
                    "success": False,
                    "action": "rolled_back",
                    "reason": f"Post-update verification failed ({verify_msg}). Backup restored.",
                }

            # Update state
            new_sha = check_res.get("latest_sha")
            state.update(
                {
                    "installed_sha": new_sha,
                    "update_available": False,
                    "restart_required": True,
                    "last_error": None,
                }
            )
            save_state(state)

            return {
                "success": True,
                "action": "applied",
                "new_sha": new_sha,
                "restart_required": True,
                "notes": [
                    "Update applied successfully from repository archive. Server restart is required.",
                    "If dependencies or skills changed, update them manually.",
                ],
            }

        except Exception as e:
            # Restore backup on exception
            for item in os.listdir(backup_dir):
                s_path = os.path.join(backup_dir, item)
                d_path = os.path.join(root, item)
                if os.path.isdir(s_path):
                    if os.path.exists(d_path):
                        shutil.rmtree(d_path)
                    shutil.copytree(s_path, d_path)
                else:
                    shutil.copy2(s_path, d_path)
            return {
                "success": False,
                "action": "failed",
                "reason": f"Zip update failed: {e}. Backup restored.",
            }
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
            shutil.rmtree(backup_dir, ignore_errors=True)


def get_updater_status_summary() -> dict[str, Any]:
    """Provide a compact status snapshot for the status tool and resource."""
    state = load_state()
    installed = get_installed_info()
    return {
        "installed_sha": installed.get("sha"),
        "installed_version": installed.get("version"),
        "install_type": installed.get("install_type"),
        "update_available": state.get("update_available", False),
        "restart_required": state.get("restart_required", False),
        "last_check_utc": state.get("last_check_utc"),
    }


def _background_worker() -> None:
    """Daemon thread worker running on startup.
    Swallows every exception and never prints to stdout.
    """
    mode = os.environ.get("INVENTOR_MCP_AUTOUPDATE", "apply").lower().strip()
    if mode == "off":
        return

    try:
        if mode == "check":
            check_for_updates(force=False)
        elif mode == "apply":
            res = check_for_updates(force=False)
            if res.get("update_available") and not res.get("throttled"):
                update_plugin(confirm=True)
    except Exception as e:
        _log_err(f"Background update check encountered an unexpected error: {e}")


_autoupdate_started = False
_autoupdate_lock = threading.Lock()


def start_background_autoupdate() -> None:
    """Launch background update thread without blocking startup."""
    global _autoupdate_started
    with _autoupdate_lock:
        if _autoupdate_started:
            return
        _autoupdate_started = True
    try:
        thread = threading.Thread(
            target=_background_worker,
            name="inventor-autoupdate-worker",
            daemon=True,
        )
        thread.start()
    except Exception as e:
        _log_err(f"Failed to start background autoupdate thread: {e}")

