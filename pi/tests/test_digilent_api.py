"""
Unit tests for the Digilent extension.

These tests use mocking and do not require a physical device.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Mock the dwf_adapter at import time so tests run without libdwf.so
# ---------------------------------------------------------------------------

def _make_dwf_mock():
    mod = types.ModuleType("digilent.dwf_adapter")
    mod.HDWF_NONE = MagicMock()
    mod.HDWF_NONE.value = -1
    mod.enumerate_devices = MagicMock(return_value=1)
    mod.get_device_name = MagicMock(return_value="Analog Discovery 2 (mock)")
    mock_hdwf = MagicMock()
    mock_hdwf.value = 1
    mod.open_device = MagicMock(return_value=mock_hdwf)
    mod.close_device = MagicMock()
    mod.read_temperature = MagicMock(return_value=38.5)
    mod.scope_capture_raw = MagicMock()
    mod.logic_capture_raw = MagicMock()
    mod.wavegen_apply = MagicMock()
    mod.wavegen_stop = MagicMock()
    mod.supplies_apply = MagicMock()
    mod.supplies_off = MagicMock()
    mod.static_io_apply = MagicMock(return_value={})
    mod.is_available = MagicMock(return_value=True)
    return mod


# Inject mock before any digilent import
_dwf_mock = _make_dwf_mock()
sys.modules["digilent.dwf_adapter"] = _dwf_mock

# Now import the actual modules under test
sys.path.insert(0, ".")
from digilent.config import DigilentConfig, SafeLimits
from digilent.device_manager import DeviceManager
from digilent.errors import (
    DigilentBusyError,
    DigilentConfigInvalidError,
    DigilentNotEnabledError,
    DigilentRangeViolationError,
)
from digilent.models import (
    LogicCaptureRequest,
    ScopeCaptureRequest,
    StaticIoPin,
    StaticIoRequest,
    SuppliesRequest,
    TriggerConfig,
    WavegenRequest,
)
from digilent.scope_service import ScopeService
from digilent.logic_service import LogicService
from digilent.wavegen_service import WavegenService
from digilent.supplies_service import SuppliesService, StaticIoService
from digilent.orchestration import OrchestrationService
from digilent.utils import compute_scope_metrics, compute_logic_metrics, downsample_minmax


# ---------------------------------------------------------------------------
# Utility: default config and manager
# ---------------------------------------------------------------------------

def _config(**kwargs) -> DigilentConfig:
    cfg = DigilentConfig()
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _manager() -> DeviceManager:
    m = DeviceManager()
    m.open()
    return m


# ---------------------------------------------------------------------------
# Tests: metric computation
# ---------------------------------------------------------------------------

class TestScopeMetrics(unittest.TestCase):
    def _square_wave(self, n=1000, freq_hz=100.0, sample_rate=10000.0, amp=3.3):
        """Generate a synthetic square wave."""
        samples = []
        period_samples = int(sample_rate / freq_hz)
        for i in range(n):
            samples.append(amp if (i % period_samples) < period_samples // 2 else 0.0)
        return samples

    def test_vmin_vmax_vpp(self):
        samples = [0.0, 1.0, 2.0, 3.0]
        m = compute_scope_metrics(samples, 1000.0)
        self.assertAlmostEqual(m["vmin"], 0.0)
        self.assertAlmostEqual(m["vmax"], 3.0)
        self.assertAlmostEqual(m["vpp"], 3.0)

    def test_vavg(self):
        samples = [0.0, 2.0]
        m = compute_scope_metrics(samples, 1000.0)
        self.assertAlmostEqual(m["vavg"], 1.0)

    def test_vrms_dc(self):
        samples = [2.0] * 100
        m = compute_scope_metrics(samples, 1000.0)
        self.assertAlmostEqual(m["vrms"], 2.0, places=3)

    def test_freq_detection(self):
        samples = self._square_wave(n=2000, freq_hz=100.0, sample_rate=10000.0, amp=3.3)
        m = compute_scope_metrics(samples, 10000.0)
        self.assertIsNotNone(m["freq_est_hz"])
        self.assertAlmostEqual(m["freq_est_hz"], 100.0, delta=2.0)

    def test_duty_cycle(self):
        samples = self._square_wave(n=2000, freq_hz=100.0, sample_rate=10000.0, amp=3.3)
        m = compute_scope_metrics(samples, 10000.0)
        self.assertIsNotNone(m["duty_cycle_percent"])
        self.assertAlmostEqual(m["duty_cycle_percent"], 50.0, delta=3.0)

    def test_empty_samples(self):
        m = compute_scope_metrics([], 1000.0)
        self.assertEqual(m, {})


class TestLogicMetrics(unittest.TestCase):
    def test_high_low_ratio(self):
        samples = [1, 1, 0, 0]
        m = compute_logic_metrics(samples, 1000.0)
        self.assertAlmostEqual(m["high_ratio"], 0.5)
        self.assertAlmostEqual(m["low_ratio"], 0.5)

    def test_edge_count(self):
        samples = [0, 1, 0, 1, 0]
        m = compute_logic_metrics(samples, 1000.0)
        self.assertEqual(m["edge_count"], 4)

    def test_freq_estimation(self):
        # 1000 Hz at 100000 samples/s → 100 samples/period
        samples = ([0] * 50 + [1] * 50) * 10
        m = compute_logic_metrics(samples, 100000.0)
        self.assertIsNotNone(m["freq_est_hz"])
        self.assertAlmostEqual(m["freq_est_hz"], 1000.0, delta=50.0)


class TestDownsampling(unittest.TestCase):
    def test_passthrough_if_small(self):
        samples = [float(i) for i in range(100)]
        out = downsample_minmax(samples, 200)
        self.assertEqual(out, samples)

    def test_reduces_length(self):
        samples = [float(i) for i in range(10000)]
        out = downsample_minmax(samples, 200)
        self.assertLessEqual(len(out), 200)

    def test_preserves_extremes(self):
        samples = [0.0] * 500 + [5.0] * 500
        out = downsample_minmax(samples, 100)
        self.assertAlmostEqual(min(out), 0.0)
        self.assertAlmostEqual(max(out), 5.0)


# ---------------------------------------------------------------------------
# Tests: request validation
# ---------------------------------------------------------------------------

class TestScopeValidation(unittest.TestCase):
    def setUp(self):
        self.svc = ScopeService(_manager(), _config())

    def test_invalid_channel(self):
        req = ScopeCaptureRequest(channels=[3], range_v=5.0, sample_rate_hz=1000, duration_ms=10)
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)

    def test_negative_range(self):
        req = ScopeCaptureRequest(channels=[1], range_v=-1.0, sample_rate_hz=1000, duration_ms=10)
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)

    def test_sample_rate_too_high(self):
        cfg = _config()
        cfg.safe_limits.max_scope_sample_rate_hz = 1000
        svc = ScopeService(_manager(), cfg)
        req = ScopeCaptureRequest(channels=[1], range_v=5.0, sample_rate_hz=2000, duration_ms=10)
        with self.assertRaises(DigilentRangeViolationError):
            svc._validate(req)

    def test_trigger_channel_not_in_capture(self):
        req = ScopeCaptureRequest(
            channels=[1],
            range_v=5.0,
            sample_rate_hz=1000,
            duration_ms=10,
            trigger=TriggerConfig(enabled=True, source="ch2"),
        )
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)

    def test_valid_request_passes(self):
        req = ScopeCaptureRequest(channels=[1, 2], range_v=5.0, sample_rate_hz=1000, duration_ms=10)
        self.svc._validate(req)  # must not raise


class TestLogicValidation(unittest.TestCase):
    def setUp(self):
        self.svc = LogicService(_manager(), _config())

    def test_channel_out_of_range(self):
        req = LogicCaptureRequest(channels=[16], sample_rate_hz=1000, samples=100)
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)

    def test_duplicate_channels(self):
        req = LogicCaptureRequest(channels=[0, 0], sample_rate_hz=1000, samples=100)
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)

    def test_trigger_channel_not_in_list(self):
        req = LogicCaptureRequest(
            channels=[0],
            sample_rate_hz=1000,
            samples=100,
            trigger=TriggerConfig(enabled=True, channel=3),
        )
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)

    def test_samples_exceed_limit(self):
        cfg = _config()
        cfg.max_logic_points = 100
        svc = LogicService(_manager(), cfg)
        req = LogicCaptureRequest(channels=[0], sample_rate_hz=1000, samples=200)
        with self.assertRaises(DigilentRangeViolationError):
            svc._validate(req)


class TestWavegenValidation(unittest.TestCase):
    def setUp(self):
        self.svc = WavegenService(_manager(), _config())

    def test_invalid_waveform(self):
        req = WavegenRequest(channel=1, waveform="sawtooth", frequency_hz=1000, amplitude_v=1.0, offset_v=0.0, enable=True)
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)

    def test_amplitude_too_high(self):
        cfg = _config()
        cfg.safe_limits.max_wavegen_amplitude_v = 3.0
        svc = WavegenService(_manager(), cfg)
        req = WavegenRequest(channel=1, waveform="sine", frequency_hz=1000, amplitude_v=4.0, offset_v=0.0, enable=True)
        with self.assertRaises(DigilentRangeViolationError):
            svc._validate(req)

    def test_invalid_channel(self):
        req = WavegenRequest(channel=3, waveform="sine", frequency_hz=1000, amplitude_v=1.0, offset_v=0.0, enable=True)
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)


class TestSuppliesValidation(unittest.TestCase):
    def test_disabled_by_default(self):
        svc = SuppliesService(_manager(), _config())
        req = SuppliesRequest(vplus_v=3.3, enable_vplus=True, confirm_unsafe=True)
        with self.assertRaises(DigilentNotEnabledError):
            svc._validate(req)

    def test_requires_confirm_unsafe(self):
        cfg = _config()
        cfg.allow_supplies = True
        svc = SuppliesService(_manager(), cfg)
        req = SuppliesRequest(vplus_v=3.3, enable_vplus=True, confirm_unsafe=False)
        with self.assertRaises(DigilentConfigInvalidError):
            svc._validate(req)

    def test_vplus_too_high(self):
        cfg = _config()
        cfg.allow_supplies = True
        cfg.safe_limits.max_supply_plus_v = 5.0
        svc = SuppliesService(_manager(), cfg)
        req = SuppliesRequest(vplus_v=6.0, enable_vplus=True, confirm_unsafe=True)
        with self.assertRaises(DigilentRangeViolationError):
            svc._validate(req)


class TestStaticIoValidation(unittest.TestCase):
    def setUp(self):
        self.svc = StaticIoService(_manager(), _config())

    def test_pin_out_of_range(self):
        req = StaticIoRequest(pins=[StaticIoPin(index=16, mode="output", value=1)])
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)

    def test_invalid_mode(self):
        req = StaticIoRequest(pins=[StaticIoPin(index=0, mode="tristate", value=0)])
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)

    def test_empty_pins(self):
        req = StaticIoRequest(pins=[])
        with self.assertRaises(DigilentConfigInvalidError):
            self.svc._validate(req)


# ---------------------------------------------------------------------------
# Tests: DeviceManager state machine
# ---------------------------------------------------------------------------

class TestDeviceManager(unittest.TestCase):
    def test_open_sets_idle(self):
        m = DeviceManager()
        m.open()
        self.assertEqual(m.state, "idle")
        self.assertTrue(m.is_open)

    def test_close_sets_absent(self):
        m = DeviceManager()
        m.open()
        m.close()
        self.assertFalse(m.is_open)

    def test_busy_during_session(self):
        m = DeviceManager()
        m.open()
        with m.session():
            self.assertEqual(m.state, "busy")
            with self.assertRaises(DigilentBusyError):
                with m.session():
                    pass

    def test_idle_after_session(self):
        m = DeviceManager()
        m.open()
        with m.session():
            pass
        self.assertEqual(m.state, "idle")

    def test_auto_open_in_session(self):
        m = DeviceManager()
        # Not explicitly opened — session should auto-open
        with m.session() as hdwf:
            self.assertIsNotNone(hdwf)
        self.assertEqual(m.state, "idle")


# ---------------------------------------------------------------------------
# Tests: models / from_dict
# ---------------------------------------------------------------------------

class TestModels(unittest.TestCase):
    def test_scope_request_from_dict(self):
        d = {
            "channels": [1, 2],
            "range_v": 10.0,
            "sample_rate_hz": 5000000,
            "duration_ms": 20,
            "trigger": {"enabled": True, "source": "ch1", "edge": "falling", "level_v": 2.5},
        }
        req = ScopeCaptureRequest.from_dict(d)
        self.assertEqual(req.channels, [1, 2])
        self.assertAlmostEqual(req.range_v, 10.0)
        self.assertTrue(req.trigger.enabled)
        self.assertEqual(req.trigger.edge, "falling")

    def test_logic_request_from_dict(self):
        d = {"channels": [0, 1, 2], "sample_rate_hz": 10000000, "samples": 50000}
        req = LogicCaptureRequest.from_dict(d)
        self.assertEqual(req.channels, [0, 1, 2])

    def test_wavegen_request_from_dict(self):
        d = {"channel": 2, "waveform": "square", "frequency_hz": 500, "amplitude_v": 1.65, "offset_v": 1.65, "enable": True}
        req = WavegenRequest.from_dict(d)
        self.assertEqual(req.channel, 2)
        self.assertEqual(req.waveform, "square")


# ---------------------------------------------------------------------------
# Tests: config loading
# ---------------------------------------------------------------------------

class TestConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = DigilentConfig()
        self.assertTrue(cfg.enabled)
        self.assertFalse(cfg.allow_supplies)
        self.assertEqual(cfg.max_scope_points, 20_000)

    def test_load_nonexistent_returns_defaults(self):
        from digilent.config import load_config
        cfg = load_config("/nonexistent/path/digilent.json")
        self.assertIsInstance(cfg, DigilentConfig)


if __name__ == "__main__":
    unittest.main()
