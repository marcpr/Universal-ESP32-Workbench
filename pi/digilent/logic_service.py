"""Logic analyzer capture service."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from . import dwf_adapter as dwf
from .config import DigilentConfig
from .device_manager import DeviceManager
from .errors import DigilentConfigInvalidError, DigilentRangeViolationError
from .models import LogicCaptureRequest
from .utils import compute_logic_metrics


class LogicService:
    def __init__(self, manager: DeviceManager, config: DigilentConfig) -> None:
        self._manager = manager
        self._cfg = config

    def capture(self, req: LogicCaptureRequest) -> dict:
        """Perform a logic capture and return structured result."""
        self._validate(req)

        n_samples = min(req.samples, self._cfg.max_logic_points)

        trigger_enabled = req.trigger.enabled
        trigger_channel = req.trigger.channel if trigger_enabled else 0
        trigger_edge = req.trigger.edge
        trigger_timeout_s = req.trigger.timeout_ms / 1000.0 if trigger_enabled else (
            self._cfg.default_timeout_ms / 1000.0
        )

        t_start = time.monotonic()
        with self._manager.session() as hdwf:
            raw = dwf.logic_capture_raw(
                hdwf=hdwf,
                channels=req.channels,
                sample_rate_hz=float(req.sample_rate_hz),
                n_samples=n_samples,
                trigger_enabled=trigger_enabled,
                trigger_channel=trigger_channel,
                trigger_edge=trigger_edge,
                trigger_timeout_s=trigger_timeout_s,
            )
        duration_ms = round((time.monotonic() - t_start) * 1000, 1)

        metrics: dict[str, dict] = {}
        for ch, samples in raw.items():
            metrics[str(ch)] = compute_logic_metrics(samples, float(req.sample_rate_hz))

        response: dict = {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "device": self._manager.device_info.name,
            "metrics": metrics,
            "duration_ms": duration_ms,
        }

        if req.return_samples:
            response["logic_samples"] = {
                "sample_rate_hz": req.sample_rate_hz,
                "channels": req.channels,
                "packed": False,
                "samples": {str(ch): s for ch, s in raw.items()},
            }

        return response

    def _validate(self, req: LogicCaptureRequest) -> None:
        limits = self._cfg.safe_limits

        if not req.channels:
            raise DigilentConfigInvalidError("channels must not be empty")
        if len(req.channels) != len(set(req.channels)):
            raise DigilentConfigInvalidError("Duplicate channels are not allowed")
        for ch in req.channels:
            if not (0 <= ch <= 15):
                raise DigilentConfigInvalidError(f"Channel {ch} out of range 0-15")
        if req.sample_rate_hz > limits.max_logic_sample_rate_hz:
            raise DigilentRangeViolationError(
                f"sample_rate_hz {req.sample_rate_hz} exceeds safe limit "
                f"{limits.max_logic_sample_rate_hz}"
            )
        if req.samples > self._cfg.max_logic_points:
            raise DigilentRangeViolationError(
                f"samples {req.samples} exceeds server limit {self._cfg.max_logic_points}"
            )
        if req.trigger.enabled and req.trigger.channel not in req.channels:
            raise DigilentConfigInvalidError(
                f"Trigger channel {req.trigger.channel} not in requested channels {req.channels}"
            )
        if req.trigger.enabled and req.trigger.edge not in ("rising", "falling", "either"):
            raise DigilentConfigInvalidError(f"Invalid trigger edge: {req.trigger.edge}")
