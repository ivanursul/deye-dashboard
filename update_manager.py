"""OTA update manager for Deye Dashboard.

Polls GitHub for new tagged releases and manages git-based updates.
"""
import logging
import os
import subprocess
import threading
import time
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


def get_current_version():
    """Get the current version from git describe --tags --always."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        logger.debug("Failed to get git version")
    return "unknown"


class UpdatePoller:
    """Polls GitHub API for new tagged releases."""

    def __init__(self, repo, poll_interval=600):
        self.repo = repo
        self.poll_interval = poll_interval
        self._cache = {}
        self._lock = threading.Lock()

    def _fetch(self):
        try:
            url = f"https://api.github.com/repos/{self.repo}/tags"
            resp = requests.get(url, timeout=15, params={"per_page": 20})
            if not resp.ok:
                logger.warning("GitHub tags API returned %s", resp.status_code)
                return
            tags = resp.json()
            if not isinstance(tags, list):
                logger.warning("Unexpected GitHub API response format")
                return

            tag_names = [t["name"] for t in tags if "name" in t]
            current = get_current_version()
            latest = tag_names[0] if tag_names else None

            update_available = False
            if latest and current != "unknown":
                update_available = latest != current and not current.startswith(latest)

            result = {
                "current_version": current,
                "latest_tag": latest,
                "update_available": update_available,
                "available_tags": tag_names,
                "last_checked": datetime.now().isoformat(),
            }
            with self._lock:
                self._cache = result
            logger.info("Update check: current=%s latest=%s update_available=%s",
                        current, latest, update_available)
        except Exception:
            logger.exception("Error checking for updates")

    @property
    def data(self):
        with self._lock:
            return dict(self._cache) if self._cache else None

    def force_check(self):
        """Trigger an immediate update check in a background thread."""
        threading.Thread(target=self._fetch, daemon=True).start()

    def _run(self):
        while True:
            self._fetch()
            time.sleep(self.poll_interval)

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()


class UpdateManager:
    """Handles git-based update and rollback operations."""

    def __init__(self):
        self._lock = threading.Lock()
        self._status = {
            "state": "idle",
            "message": "",
            "error": None,
            "timestamp": None,
        }
        self._status_lock = threading.Lock()

    @property
    def status(self):
        with self._status_lock:
            return dict(self._status)

    def _set_status(self, state, message="", error=None):
        with self._status_lock:
            self._status = {
                "state": state,
                "message": message,
                "error": error,
                "timestamp": datetime.now().isoformat(),
            }

    def is_git_repo(self):
        """Check if the current directory is a git repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def preflight_check(self):
        """Run preflight checks before update. Returns (ok, issues_list)."""
        issues = []

        # Check git is installed
        try:
            subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        except FileNotFoundError:
            issues.append("git is not installed")
            return False, issues

        # Check is git repo
        if not self.is_git_repo():
            issues.append("Not a git repository")
            return False, issues

        # Check venv exists
        venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv")
        if not os.path.isdir(venv_path):
            issues.append("Virtual environment (venv) not found")

        # Check sudo systemctl works
        try:
            result = subprocess.run(
                ["sudo", "-n", "systemctl", "is-active", "--quiet", "deye-dashboard"],
                capture_output=True, timeout=5,
            )
            # returncode 0 = active, 3 = inactive; both are fine (sudo works)
            # returncode 1 with stderr about sudo = sudo not configured
            if result.returncode not in (0, 3) and b"sudo" in (result.stderr or b""):
                issues.append("sudo systemctl not configured (passwordless)")
        except Exception:
            issues.append("Cannot run sudo systemctl")

        return len(issues) == 0, issues

    def _requirements_changed(self, tag):
        """Check if requirements.txt differs between current HEAD and target tag."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD", tag, "--", "requirements.txt"],
                capture_output=True, text=True, timeout=10,
            )
            return "requirements.txt" in result.stdout
        except Exception:
            return True  # assume changed if we can't check

    def update_to_tag(self, tag):
        """Start an update to the specified tag in a background thread."""
        if not self._lock.acquire(blocking=False):
            self._set_status("error", error="Update already in progress")
            return False
        threading.Thread(target=self._do_update, args=(tag,), daemon=True).start()
        return True

    def _do_update(self, tag):
        try:
            self._set_status("updating", f"Fetching tags...")

            # Fetch all tags
            result = subprocess.run(
                ["git", "fetch", "--tags", "--force"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                self._set_status("error", error=f"git fetch failed: {result.stderr.strip()}")
                return

            # Check if requirements changed
            needs_pip = self._requirements_changed(tag)

            self._set_status("updating", f"Checking out {tag}...")

            # Checkout the tag (force to discard local changes)
            result = subprocess.run(
                ["git", "checkout", "-f", tag],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                self._set_status("error", error=f"git checkout failed: {result.stderr.strip()}")
                return

            # Install requirements if changed
            if needs_pip:
                self._set_status("updating", "Installing updated dependencies...")
                venv_pip = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "pip"
                )
                result = subprocess.run(
                    [venv_pip, "install", "-r", "requirements.txt"],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    self._set_status("error", error=f"pip install failed: {result.stderr.strip()}")
                    return

            # Restart the service
            self._set_status("restarting", f"Restarting service after update to {tag}...")
            subprocess.run(
                ["sudo", "systemctl", "restart", "deye-dashboard"],
                capture_output=True, timeout=15,
            )
            # If we get here, the restart hasn't killed us yet
            self._set_status("idle", f"Updated to {tag}")
        except Exception as e:
            self._set_status("error", error=str(e))
        finally:
            self._lock.release()
