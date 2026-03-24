"""
High-level orchestration actions for agent-friendly measurements.

Actions are composites that use the lower-level services and return
structured pass/fail results with tolerances.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import DigilentConfig
from .device_manager import DeviceManager
from .errors import DigilentConfigInvalidError
from .models import LogicCaptureRequest, ScopeCaptureRequest, TriggerConfig
from .scope_service import ScopeService
from .logic_service import LogicService


class OrchestrationService:
    def __init__(self, manager: DeviceManager, config: DigilentConfig) -> None:
        self._manager = manager
        self._cfg = config
        self._scope = ScopeService(manager, config)
        self._logic = LogicService(manager, config)

    def measure_basic(self, action: str, params: dict) -> dict:
        """Dispatch a named high-level measurement action."""
        dispatch = {
            "measure_esp32_pwm": self._measure_esp32_pwm,
            "measure_voltage_level": self._measure_voltage_level,
            "detect_logic_activity": self._detect_logic_activity,
        }
        handler = dispatch.get(action)
        if handler is None:
            raise DigilentConfigInvalidError(
                f"Unknown action '{action}'. "
                f"Available actions: {sorted(dispatch.keys())}"
            )
        return handler(params)

    # -----------------------------------------------------------------------
    # Action: measure_esp32_pwm
    # -----------------------------------------------------------------------

    def _measure_esp32_pwm(self, params: dict) -> dict:
        """
        Measure PWM output from an ESP32 GPIO.

        params:
            channel (int): Scope channel (default: 1)
            expected_freq_hz (float): Expected PWM frequency
            tolerance_percent (float): Acceptable deviation in percent (default: 5)
            sample_rate_hz (int): Scope sample rate (default: 2×expected)
            duration_ms (int): Capture window (default: 20)
        """
        ch = int(params.get("channel", 1))
        expected_hz = float(params.get("expected_freq_hz", 1000.0))
        tolerance = float(params.get("tolerance_percent", 5.0))
        sample_rate = int(params.get("sample_rate_hz", max(int(expected_hz * 20), 100_000)))
        duration_ms = int(params.get("duration_ms", 20))
        range_v = float(params.get("range_v", 5.0))

        req = ScopeCaptureRequest(
            channels=[ch],
            range_v=range_v,
            offset_v=0.0,
            sample_rate_hz=sample_rate,
            duration_ms=duration_ms,
            trigger=TriggerConfig(enabled=True, source=f"ch{ch}", edge="rising", level_v=range_v / 2),
        )
        capture = self._scope.capture(req)
        ch_metrics = capture["metrics"].get(f"ch{ch}", {})

        measured_hz = ch_metrics.get("freq_est_hz")
        duty = ch_metrics.get("duty_cycle_percent")
        vpp = ch_metrics.get("vpp")

        within = None
        if measured_hz is not None and expected_hz > 0:
            deviation_pct = abs(measured_hz - expected_hz) / expected_hz * 100.0
            within = deviation_pct <= tolerance

        return {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": "measure_esp32_pwm",
            "within_tolerance": within,
            "result": {
                "measured_freq_hz": measured_hz,
                "expected_freq_hz": expected_hz,
                "tolerance_percent": tolerance,
                "duty_cycle_percent": duty,
                "vpp": vpp,
                "vmin": ch_metrics.get("vmin"),
                "vmax": ch_metrics.get("vmax"),
            },
        }

    # -----------------------------------------------------------------------
    # Action: measure_voltage_level
    # -----------------------------------------------------------------------

    def _measure_voltage_level(self, params: dict) -> dict:
        """
        Measure DC or slowly-varying voltage on a scope channel.

        params:
            channel (int): Scope channel (default: 1)
            expected_v (float): Expected voltage (for tolerance check)
            tolerance_v (float): Acceptable deviation in volts (default: 0.1)
            range_v (float): Scope range in volts (default: 5.0)
            duration_ms (int): Capture window (default: 10)
        """
        ch = int(params.get("channel", 1))
        expected_v = params.get("expected_v")
        tolerance_v = float(params.get("tolerance_v", 0.1))
        range_v = float(params.get("range_v", 5.0))
        duration_ms = int(params.get("duration_ms", 10))

        req = ScopeCaptureRequest(
            channels=[ch],
            range_v=range_v,
            offset_v=0.0,
            sample_rate_hz=10_000,
            duration_ms=duration_ms,
            trigger=TriggerConfig(enabled=False),
        )
        capture = self._scope.capture(req)
        ch_metrics = capture["metrics"].get(f"ch{ch}", {})
        vavg = ch_metrics.get("vavg")

        within = None
        if vavg is not None and expected_v is not None:
            within = abs(vavg - expected_v) <= tolerance_v

        return {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": "measure_voltage_level",
            "within_tolerance": within,
            "result": {
                "measured_v": vavg,
                "expected_v": expected_v,
                "tolerance_v": tolerance_v,
                "vmin": ch_metrics.get("vmin"),
                "vmax": ch_metrics.get("vmax"),
                "vrms": ch_metrics.get("vrms"),
            },
        }

    # -----------------------------------------------------------------------
    # Action: detect_logic_activity
    # -----------------------------------------------------------------------

    def _detect_logic_activity(self, params: dict) -> dict:
        """
        Detect digital activity (transitions) on one or more logic channels.

        params:
            channels (list[int]): Logic channels to observe (default: [0])
            sample_rate_hz (int): Sample rate (default: 1_000_000)
            duration_samples (int): Number of samples (default: 10_000)
            min_edges (int): Minimum edge count to consider "active" (default: 2)
        """
        channels = list(params.get("channels", [0]))
        sample_rate = int(params.get("sample_rate_hz", 1_000_000))
        n_samples = int(params.get("duration_samples", 10_000))
        min_edges = int(params.get("min_edges", 2))

        req = LogicCaptureRequest(
            channels=channels,
            sample_rate_hz=sample_rate,
            samples=n_samples,
            trigger=TriggerConfig(enabled=False),
        )
        capture = self._logic.capture(req)

        active_channels: list[int] = []
        channel_results: dict[str, dict] = {}
        for ch in channels:
            metrics = capture["metrics"].get(str(ch), {})
            edges = metrics.get("edge_count", 0)
            active = edges >= min_edges
            if active:
                active_channels.append(ch)
            channel_results[str(ch)] = {
                "edge_count": edges,
                "active": active,
                "freq_est_hz": metrics.get("freq_est_hz"),
                "duty_cycle_percent": metrics.get("duty_cycle_percent"),
            }

        return {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": "detect_logic_activity",
            "within_tolerance": len(active_channels) > 0,
            "result": {
                "active_channels": active_channels,
                "min_edges_threshold": min_edges,
                "channels": channel_results,
            },
        }
