"""Waveform generator service."""

from __future__ import annotations

from datetime import datetime, timezone

from . import dwf_adapter as dwf
from .config import DigilentConfig
from .device_manager import DeviceManager
from .errors import DigilentConfigInvalidError, DigilentRangeViolationError
from .models import WavegenRequest

_VALID_WAVEFORMS = {"sine", "square", "triangle", "dc"}


class WavegenService:
    def __init__(self, manager: DeviceManager, config: DigilentConfig) -> None:
        self._manager = manager
        self._cfg = config

    def set(self, req: WavegenRequest) -> dict:
        """Configure and optionally start the waveform generator."""
        self._validate(req)

        warnings = []
        if req.enable:
            warnings.append(
                "Wavegen active — ensure amplitude and offset are safe for connected DUT"
            )

        with self._manager.session() as hdwf:
            dwf.wavegen_apply(
                hdwf=hdwf,
                channel=req.channel,
                waveform=req.waveform,
                frequency_hz=req.frequency_hz,
                amplitude_v=req.amplitude_v,
                offset_v=req.offset_v,
                symmetry_percent=req.symmetry_percent,
                enable=req.enable,
            )

        response: dict = {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": f"Wavegen CH{req.channel} {'started' if req.enable else 'stopped'}",
        }
        if warnings:
            response["warnings"] = warnings
        return response

    def stop(self, channel: int = 1) -> dict:
        """Stop the waveform generator on the specified channel."""
        if channel not in (1, 2):
            raise DigilentConfigInvalidError(f"Invalid wavegen channel: {channel}")

        with self._manager.session() as hdwf:
            dwf.wavegen_stop(hdwf=hdwf, channel=channel)

        return {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": f"Wavegen CH{channel} stopped",
        }

    def _validate(self, req: WavegenRequest) -> None:
        limits = self._cfg.safe_limits

        if req.channel not in (1, 2):
            raise DigilentConfigInvalidError(f"Invalid wavegen channel: {req.channel}")
        if req.waveform not in _VALID_WAVEFORMS:
            raise DigilentConfigInvalidError(
                f"Invalid waveform '{req.waveform}'. Must be one of {sorted(_VALID_WAVEFORMS)}"
            )
        if req.frequency_hz < 0:
            raise DigilentConfigInvalidError("frequency_hz must be >= 0")
        if abs(req.amplitude_v) > limits.max_wavegen_amplitude_v:
            raise DigilentRangeViolationError(
                f"amplitude_v {req.amplitude_v} exceeds safe limit {limits.max_wavegen_amplitude_v}"
            )
        # Peak = amplitude + offset; check both extremes
        peak_pos = req.amplitude_v + abs(req.offset_v)
        peak_neg = -req.amplitude_v - abs(req.offset_v)
        if peak_pos > limits.max_wavegen_amplitude_v or peak_neg < -limits.max_wavegen_amplitude_v:
            raise DigilentRangeViolationError(
                f"Wavegen peak voltage ({peak_pos:.2f}V / {peak_neg:.2f}V) "
                f"exceeds safe limits ±{limits.max_wavegen_amplitude_v}V"
            )
        if not (0 <= req.symmetry_percent <= 100):
            raise DigilentConfigInvalidError("symmetry_percent must be in 0..100")
