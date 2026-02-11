"""Tests for OTA update manager."""
import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from update_manager import get_current_version, UpdatePoller, UpdateManager


class TestGetCurrentVersion:
    def test_returns_tag(self):
        mock_result = MagicMock(returncode=0, stdout="v1.2.0\n")
        with patch("update_manager.subprocess.run", return_value=mock_result):
            assert get_current_version() == "v1.2.0"

    def test_returns_unknown_on_failure(self):
        mock_result = MagicMock(returncode=128, stdout="")
        with patch("update_manager.subprocess.run", return_value=mock_result):
            assert get_current_version() == "unknown"

    def test_returns_unknown_on_exception(self):
        with patch("update_manager.subprocess.run", side_effect=Exception("fail")):
            assert get_current_version() == "unknown"


class TestUpdatePoller:
    def test_fetch_parses_tags(self):
        poller = UpdatePoller(repo="owner/repo", poll_interval=600)
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = [
            {"name": "v1.3.0"},
            {"name": "v1.2.0"},
            {"name": "v1.1.0"},
        ]

        with patch("update_manager.requests.get", return_value=mock_resp), \
             patch("update_manager.get_current_version", return_value="v1.2.0"):
            poller._fetch()

        data = poller.data
        assert data is not None
        assert data["latest_tag"] == "v1.3.0"
        assert data["update_available"] is True
        assert data["available_tags"] == ["v1.3.0", "v1.2.0", "v1.1.0"]

    def test_fetch_no_update_when_current(self):
        poller = UpdatePoller(repo="owner/repo")
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = [{"name": "v1.2.0"}]

        with patch("update_manager.requests.get", return_value=mock_resp), \
             patch("update_manager.get_current_version", return_value="v1.2.0"):
            poller._fetch()

        data = poller.data
        assert data["update_available"] is False

    def test_fetch_handles_api_error(self):
        poller = UpdatePoller(repo="owner/repo")
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 403

        with patch("update_manager.requests.get", return_value=mock_resp):
            poller._fetch()

        assert poller.data is None

    def test_fetch_handles_exception(self):
        poller = UpdatePoller(repo="owner/repo")
        with patch("update_manager.requests.get", side_effect=Exception("timeout")):
            poller._fetch()
        assert poller.data is None

    def test_data_returns_none_before_fetch(self):
        poller = UpdatePoller(repo="owner/repo")
        assert poller.data is None

    def test_force_check_triggers_fetch(self):
        poller = UpdatePoller(repo="owner/repo")
        with patch.object(poller, "_fetch") as mock_fetch:
            with patch("update_manager.threading.Thread") as mock_thread:
                poller.force_check()
                mock_thread.assert_called_once()


class TestUpdateManager:
    def test_is_git_repo_true(self):
        mgr = UpdateManager()
        mock_result = MagicMock(returncode=0)
        with patch("update_manager.subprocess.run", return_value=mock_result):
            assert mgr.is_git_repo() is True

    def test_is_git_repo_false(self):
        mgr = UpdateManager()
        mock_result = MagicMock(returncode=128)
        with patch("update_manager.subprocess.run", return_value=mock_result):
            assert mgr.is_git_repo() is False

    def test_preflight_ok(self):
        mgr = UpdateManager()
        results = {
            0: MagicMock(returncode=0),  # git --version
            1: MagicMock(returncode=0),  # git rev-parse
            2: MagicMock(returncode=0, stdout=""),  # git status
            3: MagicMock(returncode=0),  # sudo systemctl
        }
        call_idx = [0]

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd[0] == "git" and cmd[1] == "--version":
                return results[0]
            elif cmd[0] == "git" and cmd[1] == "rev-parse":
                return results[1]
            elif cmd[0] == "git" and cmd[1] == "status":
                return results[2]
            elif cmd[0] == "sudo":
                return results[3]
            return MagicMock(returncode=0)

        with patch("update_manager.subprocess.run", side_effect=side_effect), \
             patch("update_manager.os.path.isdir", return_value=True):
            ok, issues = mgr.preflight_check()

        assert ok is True
        assert issues == []

    def test_preflight_no_git(self):
        mgr = UpdateManager()
        with patch("update_manager.subprocess.run", side_effect=FileNotFoundError):
            ok, issues = mgr.preflight_check()
        assert ok is False
        assert "git is not installed" in issues

    def test_preflight_uncommitted_changes(self):
        mgr = UpdateManager()

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd[0] == "git" and cmd[1] == "--version":
                return MagicMock(returncode=0)
            elif cmd[0] == "git" and cmd[1] == "rev-parse":
                return MagicMock(returncode=0)
            elif cmd[0] == "git" and cmd[1] == "status":
                return MagicMock(returncode=0, stdout=" M app.py\n")
            elif cmd[0] == "sudo":
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        with patch("update_manager.subprocess.run", side_effect=side_effect), \
             patch("update_manager.os.path.isdir", return_value=True):
            ok, issues = mgr.preflight_check()

        assert ok is False
        assert any("Uncommitted" in i for i in issues)

    def test_requirements_changed(self):
        mgr = UpdateManager()
        mock_result = MagicMock(returncode=0, stdout="requirements.txt\n")
        with patch("update_manager.subprocess.run", return_value=mock_result):
            assert mgr._requirements_changed("v1.3.0") is True

    def test_requirements_unchanged(self):
        mgr = UpdateManager()
        mock_result = MagicMock(returncode=0, stdout="")
        with patch("update_manager.subprocess.run", return_value=mock_result):
            assert mgr._requirements_changed("v1.3.0") is False

    def test_status_default_idle(self):
        mgr = UpdateManager()
        assert mgr.status["state"] == "idle"

    def test_update_to_tag_rejects_concurrent(self):
        mgr = UpdateManager()
        mgr._lock.acquire()
        result = mgr.update_to_tag("v1.0.0")
        assert result is False
        mgr._lock.release()


class TestOtaApiEndpoints:
    @pytest.fixture
    def client(self):
        """Create a Flask test client with mocked pollers."""
        import app as app_module

        app_module.app.config["TESTING"] = True

        orig_inverter_poller = app_module.inverter_poller
        orig_outage_poller = app_module.outage_poller
        orig_weather_poller = app_module.weather_poller
        orig_inverter_config = app_module.inverter_config
        orig_update_poller = app_module.update_poller
        orig_update_manager = app_module.update_manager

        mock_inv_poller = MagicMock()
        mock_weather_poller = MagicMock()

        app_module.inverter_poller = mock_inv_poller
        app_module.weather_poller = mock_weather_poller

        with app_module.app.test_client() as c:
            yield c, app_module

        app_module.inverter_poller = orig_inverter_poller
        app_module.outage_poller = orig_outage_poller
        app_module.weather_poller = orig_weather_poller
        app_module.inverter_config = orig_inverter_config
        app_module.update_poller = orig_update_poller
        app_module.update_manager = orig_update_manager

    def test_update_status_returns_version(self, client):
        c, app_module = client
        mock_poller = MagicMock()
        type(mock_poller).data = PropertyMock(return_value={
            "current_version": "v1.0.0",
            "latest_tag": "v1.1.0",
            "update_available": True,
            "available_tags": ["v1.1.0", "v1.0.0"],
            "last_checked": "2025-01-01T00:00:00",
        })
        mock_mgr = MagicMock()
        type(mock_mgr).status = PropertyMock(return_value={
            "state": "idle", "message": "", "error": None, "timestamp": None,
        })
        mock_mgr.is_git_repo.return_value = True
        app_module.update_poller = mock_poller
        app_module.update_manager = mock_mgr

        resp = c.get("/api/update/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["current_version"] == "v1.0.0"
        assert data["update_available"] is True
        assert data["is_git_repo"] is True

    def test_check_for_updates(self, client):
        c, app_module = client
        mock_poller = MagicMock()
        app_module.update_poller = mock_poller
        resp = c.post("/api/update/check")
        assert resp.status_code == 200
        mock_poller.force_check.assert_called_once()

    def test_apply_missing_tag(self, client):
        c, _ = client
        resp = c.post("/api/update/apply", json={})
        assert resp.status_code == 400

    def test_apply_update(self, client):
        c, app_module = client
        mock_mgr = MagicMock()
        mock_mgr.update_to_tag.return_value = True
        app_module.update_manager = mock_mgr
        resp = c.post("/api/update/apply", json={"tag": "v1.1.0"})
        assert resp.status_code == 200
        mock_mgr.update_to_tag.assert_called_once_with("v1.1.0")

    def test_apply_concurrent_rejected(self, client):
        c, app_module = client
        mock_mgr = MagicMock()
        mock_mgr.update_to_tag.return_value = False
        app_module.update_manager = mock_mgr
        resp = c.post("/api/update/apply", json={"tag": "v1.1.0"})
        assert resp.status_code == 409

    def test_rollback_missing_tag(self, client):
        c, _ = client
        resp = c.post("/api/update/rollback", json={})
        assert resp.status_code == 400

    def test_rollback_ok(self, client):
        c, app_module = client
        mock_mgr = MagicMock()
        mock_mgr.update_to_tag.return_value = True
        app_module.update_manager = mock_mgr
        resp = c.post("/api/update/rollback", json={"tag": "v1.0.0"})
        assert resp.status_code == 200
        mock_mgr.update_to_tag.assert_called_once_with("v1.0.0")

    def test_preflight(self, client):
        c, app_module = client
        mock_mgr = MagicMock()
        mock_mgr.preflight_check.return_value = (True, [])
        app_module.update_manager = mock_mgr
        resp = c.get("/api/update/preflight")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["issues"] == []
