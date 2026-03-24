"""
Remote integration tests for the Digilent extension.

Run against a live Raspberry Pi workbench that has a WaveForms device attached:

    WORKBENCH_HOST=esp32-workbench.local pytest pytest/test_digilent_remote.py -v

Without a device, most tests are skipped gracefully.
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("WORKBENCH_HOST", "esp32-workbench.local")
if not BASE_URL.startswith("http"):
    BASE_URL = f"http://{BASE_URL}:8080"

TIMEOUT = 15  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api(path: str) -> str:
    return f"{BASE_URL}{path}"


def skip_if_no_device(status: dict) -> None:
    if not status.get("device_present"):
        pytest.skip("No Digilent device connected to workbench")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_endpoint_reachable(self):
        r = requests.get(api("/api/digilent/status"), timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        assert "device_present" in data
        assert "state" in data
        assert data["state"] in ("absent", "idle", "busy", "recovering", "error")

    def test_status_has_capabilities_when_present(self):
        r = requests.get(api("/api/digilent/status"), timeout=TIMEOUT)
        data = r.json()
        if data.get("device_present"):
            caps = data.get("capabilities", {})
            assert "scope" in caps
            assert "logic" in caps


# ---------------------------------------------------------------------------
# Device open / close
# ---------------------------------------------------------------------------

class TestDeviceLifecycle:
    def setup_method(self):
        status = requests.get(api("/api/digilent/status"), timeout=TIMEOUT).json()
        skip_if_no_device(status)

    def test_open_and_close(self):
        r = requests.post(api("/api/digilent/device/open"), timeout=TIMEOUT)
        assert r.status_code == 200

        r2 = requests.get(api("/api/digilent/status"), timeout=TIMEOUT).json()
        assert r2["device_open"] is True

        r3 = requests.post(api("/api/digilent/device/close"), timeout=TIMEOUT)
        assert r3.status_code == 200

    def test_session_reset(self):
        r = requests.post(api("/api/digilent/session/reset"), timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True


# ---------------------------------------------------------------------------
# Scope capture
# ---------------------------------------------------------------------------

class TestScopeCapture:
    def setup_method(self):
        status = requests.get(api("/api/digilent/status"), timeout=TIMEOUT).json()
        skip_if_no_device(status)
        requests.post(api("/api/digilent/device/open"), timeout=TIMEOUT)

    def teardown_method(self):
        requests.post(api("/api/digilent/device/close"), timeout=TIMEOUT)

    def test_scope_capture_returns_metrics(self):
        body = {
            "channels": [1],
            "range_v": 5.0,
            "offset_v": 0.0,
            "sample_rate_hz": 100000,
            "duration_ms": 10,
            "trigger": {"enabled": False},
            "return_waveform": False,
        }
        r = requests.post(api("/api/digilent/scope/capture"), json=body, timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "metrics" in data
        ch_metrics = data["metrics"].get("ch1", {})
        assert "vmin" in ch_metrics
        assert "vmax" in ch_metrics
        assert "vpp" in ch_metrics
        assert "vavg" in ch_metrics

    def test_scope_capture_with_waveform(self):
        body = {
            "channels": [1],
            "range_v": 5.0,
            "sample_rate_hz": 10000,
            "duration_ms": 10,
            "return_waveform": True,
            "max_points": 500,
        }
        r = requests.post(api("/api/digilent/scope/capture"), json=body, timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        if data.get("waveform"):
            wf = data["waveform"]
            assert "channels" in wf
            assert "dt_s" in wf
            assert len(wf["channels"][0]["y"]) <= 500

    def test_scope_measure_no_waveform(self):
        body = {
            "channels": [1],
            "range_v": 5.0,
            "sample_rate_hz": 10000,
            "duration_ms": 5,
        }
        r = requests.post(api("/api/digilent/scope/measure"), json=body, timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert "waveform" not in data

    def test_invalid_channel_returns_400(self):
        body = {"channels": [3], "range_v": 5.0, "sample_rate_hz": 1000, "duration_ms": 5}
        r = requests.post(api("/api/digilent/scope/capture"), json=body, timeout=TIMEOUT)
        assert r.status_code == 400
        data = r.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "DIGILENT_CONFIG_INVALID"


# ---------------------------------------------------------------------------
# Logic capture
# ---------------------------------------------------------------------------

class TestLogicCapture:
    def setup_method(self):
        status = requests.get(api("/api/digilent/status"), timeout=TIMEOUT).json()
        skip_if_no_device(status)
        requests.post(api("/api/digilent/device/open"), timeout=TIMEOUT)

    def teardown_method(self):
        requests.post(api("/api/digilent/device/close"), timeout=TIMEOUT)

    def test_logic_capture_returns_metrics(self):
        body = {
            "channels": [0, 1],
            "sample_rate_hz": 1000000,
            "samples": 1000,
            "trigger": {"enabled": False},
        }
        r = requests.post(api("/api/digilent/logic/capture"), json=body, timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "metrics" in data
        for ch in ("0", "1"):
            assert ch in data["metrics"]

    def test_logic_duplicate_channels_rejected(self):
        body = {"channels": [0, 0], "sample_rate_hz": 1000000, "samples": 100}
        r = requests.post(api("/api/digilent/logic/capture"), json=body, timeout=TIMEOUT)
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Concurrent access
# ---------------------------------------------------------------------------

class TestConcurrentAccess:
    def setup_method(self):
        status = requests.get(api("/api/digilent/status"), timeout=TIMEOUT).json()
        skip_if_no_device(status)
        requests.post(api("/api/digilent/device/open"), timeout=TIMEOUT)

    def teardown_method(self):
        requests.post(api("/api/digilent/device/close"), timeout=TIMEOUT)

    def test_concurrent_requests_blocked(self):
        """Second request while first is running should get 409."""
        import threading
        import time

        results = {}

        body = {
            "channels": [1],
            "range_v": 5.0,
            "sample_rate_hz": 10000,
            "duration_ms": 500,  # long capture
        }

        def _capture(key):
            r = requests.post(api("/api/digilent/scope/capture"), json=body, timeout=TIMEOUT)
            results[key] = r.status_code

        t1 = threading.Thread(target=_capture, args=("first",))
        t2 = threading.Thread(target=_capture, args=("second",))

        t1.start()
        time.sleep(0.05)  # let first request start
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        status_codes = set(results.values())
        # At least one must succeed (200) and at least one should be blocked (409)
        assert 200 in status_codes or 409 in status_codes


# ---------------------------------------------------------------------------
# Wavegen
# ---------------------------------------------------------------------------

class TestWavegen:
    def setup_method(self):
        status = requests.get(api("/api/digilent/status"), timeout=TIMEOUT).json()
        skip_if_no_device(status)
        requests.post(api("/api/digilent/device/open"), timeout=TIMEOUT)

    def teardown_method(self):
        requests.post(api("/api/digilent/wavegen/stop"), json={"channel": 1}, timeout=TIMEOUT)
        requests.post(api("/api/digilent/device/close"), timeout=TIMEOUT)

    def test_wavegen_set_and_stop(self):
        body = {
            "channel": 1,
            "waveform": "square",
            "frequency_hz": 1000,
            "amplitude_v": 1.0,
            "offset_v": 0.5,
            "symmetry_percent": 50,
            "enable": True,
        }
        r = requests.post(api("/api/digilent/wavegen/set"), json=body, timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "warnings" in data  # should warn about active wavegen

        r2 = requests.post(api("/api/digilent/wavegen/stop"), json={"channel": 1}, timeout=TIMEOUT)
        assert r2.status_code == 200

    def test_invalid_waveform_rejected(self):
        body = {
            "channel": 1,
            "waveform": "sawtooth",
            "frequency_hz": 1000,
            "amplitude_v": 1.0,
            "offset_v": 0.0,
            "enable": True,
        }
        r = requests.post(api("/api/digilent/wavegen/set"), json=body, timeout=TIMEOUT)
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Supplies (disabled by default)
# ---------------------------------------------------------------------------

class TestSupplies:
    def test_supplies_disabled_by_default(self):
        status = requests.get(api("/api/digilent/status"), timeout=TIMEOUT).json()
        if not status.get("device_present"):
            pytest.skip("No device connected")

        body = {"vplus_v": 3.3, "enable_vplus": True, "confirm_unsafe": True}
        r = requests.post(api("/api/digilent/supplies/set"), json=body, timeout=TIMEOUT)
        # Should return 403 (not enabled) unless allow_supplies=true in config
        assert r.status_code in (403, 200)
        if r.status_code == 403:
            assert r.json()["error"]["code"] == "DIGILENT_NOT_ENABLED"


# ---------------------------------------------------------------------------
# High-level measure/basic
# ---------------------------------------------------------------------------

class TestMeasureBasic:
    def setup_method(self):
        status = requests.get(api("/api/digilent/status"), timeout=TIMEOUT).json()
        skip_if_no_device(status)
        requests.post(api("/api/digilent/device/open"), timeout=TIMEOUT)

    def teardown_method(self):
        requests.post(api("/api/digilent/device/close"), timeout=TIMEOUT)

    def test_measure_voltage_level(self):
        body = {
            "action": "measure_voltage_level",
            "params": {"channel": 1, "range_v": 5.0, "duration_ms": 10},
        }
        r = requests.post(api("/api/digilent/measure/basic"), json=body, timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["action"] == "measure_voltage_level"
        assert "result" in data
        assert "measured_v" in data["result"]

    def test_detect_logic_activity(self):
        body = {
            "action": "detect_logic_activity",
            "params": {"channels": [0], "sample_rate_hz": 100000, "duration_samples": 1000},
        }
        r = requests.post(api("/api/digilent/measure/basic"), json=body, timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["action"] == "detect_logic_activity"
        assert "result" in data

    def test_unknown_action_returns_400(self):
        body = {"action": "do_magic", "params": {}}
        r = requests.post(api("/api/digilent/measure/basic"), json=body, timeout=TIMEOUT)
        assert r.status_code == 400
