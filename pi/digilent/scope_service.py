"""Oscilloscope capture service."""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from . import dwf_adapter as dwf
from .config import DigilentConfig
from .device_manager import DeviceManager
from .errors import DigilentConfigInvalidError, DigilentRangeViolationError
from .models import ScopeCaptureRequest
from .utils import compute_scope_metrics, downsample_minmax


class ScopeService:
    def __init__(self, manager: DeviceManager, config: DigilentConfig) -> None:
        self._manager = manager
        self._cfg = config

    def capture(self, req: ScopeCaptureRequest) -> dict:
        """Perform a scope capture and return structured result."""
        self._validate(req)

        n_samples = min(
            int(req.sample_rate_hz * req.duration_ms / 1000),
            self._cfg.max_scope_points,
        )
        n_samples = max(n_samples, 16)

        trigger_enabled = req.trigger.enabled
        trigger_source = "ch1" if trigger_enabled else "none"
        trigger_edge = req.trigger.edge
        try:
            trigger_channel = int(req.trigger.source.replace("ch", ""))
        except (ValueError, AttributeError):
            trigger_channel = 1
        trigger_level_v = req.trigger.level_v
        trigger_timeout_s = req.trigger.timeout_ms / 1000.0 if trigger_enabled else (
            self._cfg.default_timeout_ms / 1000.0
        )

        t_start = time.monotonic()
        with self._manager.session() as hdwf:
            raw = dwf.scope_capture_raw(
                hdwf=hdwf,
                channels=req.channels,
                range_v=req.range_v,
                offset_v=req.offset_v,
                sample_rate_hz=float(req.sample_rate_hz),
                n_samples=n_samples,
                trigger_source=trigger_source,
                trigger_edge=trigger_edge,
                trigger_channel=trigger_channel,
                trigger_level_v=trigger_level_v,
                trigger_timeout_s=trigger_timeout_s,
            )
        duration_ms = round((time.monotonic() - t_start) * 1000, 1)

        # Compute metrics per channel
        metrics: dict[str, dict] = {}
        for ch, samples in raw.items():
            metrics[f"ch{ch}"] = compute_scope_metrics(samples, float(req.sample_rate_hz))

        response: dict = {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "device": self._manager.device_info.name,
            "metrics": metrics,
            "duration_ms": duration_ms,
        }

        if req.return_waveform and self._cfg.allow_raw_waveforms:
            dt_s = 1.0 / req.sample_rate_hz
            channels_data = []
            for ch, samples in raw.items():
                downsampled = downsample_minmax(samples, req.max_points)
                channels_data.append({"channel": ch, "y": [round(v, 6) for v in downsampled]})
            response["waveform"] = {
                "t_start_s": 0.0,
                "dt_s": round(dt_s * len(raw[req.channels[0]]) / len(channels_data[0]["y"]), 9),
                "unit_x": "s",
                "unit_y": "V",
                "channels": channels_data,
            }
        elif req.return_waveform:
            response.setdefault("warnings", []).append("raw waveforms disabled by server configuration")

        return response

    def measure(self, req: ScopeCaptureRequest) -> dict:
        """Like capture() but always suppresses waveform data."""
        req.return_waveform = False
        return self.capture(req)

    def _validate(self, req: ScopeCaptureRequest) -> None:
        limits = self._cfg.safe_limits

        if not req.channels:
            raise DigilentConfigInvalidError("channels must not be empty")
        for ch in req.channels:
            if ch not in (1, 2):
                raise DigilentConfigInvalidError(f"Invalid scope channel: {ch}. Must be 1 or 2")
        if req.range_v <= 0:
            raise DigilentConfigInvalidError("range_v must be positive")
        if req.sample_rate_hz > limits.max_scope_sample_rate_hz:
            raise DigilentRangeViolationError(
                f"sample_rate_hz {req.sample_rate_hz} exceeds safe limit "
                f"{limits.max_scope_sample_rate_hz}"
            )
        if req.duration_ms <= 0:
            raise DigilentConfigInvalidError("duration_ms must be positive")
        if req.max_points > self._cfg.max_scope_points:
            raise DigilentRangeViolationError(
                f"max_points {req.max_points} exceeds server limit {self._cfg.max_scope_points}"
            )
        if req.trigger.enabled:
            src = req.trigger.source
            try:
                tch = int(src.replace("ch", ""))
            except (ValueError, AttributeError):
                raise DigilentConfigInvalidError(f"Invalid trigger source: {src}")
            if tch not in req.channels:
                raise DigilentConfigInvalidError(
                    f"Trigger channel {src} is not in the active channels list"
                )
            if req.trigger.edge not in ("rising", "falling", "either"):
                raise DigilentConfigInvalidError(f"Invalid trigger edge: {req.trigger.edge}")
