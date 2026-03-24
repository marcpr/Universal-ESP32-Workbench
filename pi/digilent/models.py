"""Request and response data models for the Digilent HTTP API."""

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Trigger config
# ---------------------------------------------------------------------------

@dataclass
class TriggerConfig:
    enabled: bool = False
    source: str = "ch1"        # "ch1", "ch2", "ext"
    edge: str = "rising"       # "rising", "falling", "either"
    channel: int = 0           # for logic trigger
    level_v: float = 1.0
    timeout_ms: int = 1000

    @classmethod
    def from_dict(cls, d: dict) -> "TriggerConfig":
        t = cls()
        for k, v in d.items():
            if hasattr(t, k):
                setattr(t, k, v)
        return t


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

@dataclass
class ScopeCaptureRequest:
    channels: list[int] = field(default_factory=lambda: [1])
    range_v: float = 5.0
    offset_v: float = 0.0
    sample_rate_hz: int = 1_000_000
    duration_ms: int = 10
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    return_waveform: bool = False
    max_points: int = 5000

    @classmethod
    def from_dict(cls, d: dict) -> "ScopeCaptureRequest":
        r = cls()
        trig_raw = d.pop("trigger", None)
        for k, v in d.items():
            if hasattr(r, k):
                setattr(r, k, v)
        if trig_raw:
            r.trigger = TriggerConfig.from_dict(trig_raw)
        return r


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

@dataclass
class LogicCaptureRequest:
    channels: list[int] = field(default_factory=lambda: [0])
    sample_rate_hz: int = 10_000_000
    samples: int = 20_000
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    return_samples: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "LogicCaptureRequest":
        r = cls()
        trig_raw = d.pop("trigger", None)
        for k, v in d.items():
            if hasattr(r, k):
                setattr(r, k, v)
        if trig_raw:
            r.trigger = TriggerConfig.from_dict(trig_raw)
        return r


# ---------------------------------------------------------------------------
# Wavegen
# ---------------------------------------------------------------------------

@dataclass
class WavegenRequest:
    channel: int = 1
    waveform: str = "sine"      # sine, square, triangle, dc
    frequency_hz: float = 1000.0
    amplitude_v: float = 1.0
    offset_v: float = 0.0
    symmetry_percent: float = 50.0
    enable: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "WavegenRequest":
        r = cls()
        for k, v in d.items():
            if hasattr(r, k):
                setattr(r, k, v)
        return r


# ---------------------------------------------------------------------------
# Supplies
# ---------------------------------------------------------------------------

@dataclass
class SuppliesRequest:
    vplus_v: float = 3.3
    vminus_v: float = 0.0
    enable_vplus: bool = False
    enable_vminus: bool = False
    confirm_unsafe: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "SuppliesRequest":
        r = cls()
        for k, v in d.items():
            if hasattr(r, k):
                setattr(r, k, v)
        return r


# ---------------------------------------------------------------------------
# Static I/O
# ---------------------------------------------------------------------------

@dataclass
class StaticIoPin:
    index: int = 0
    mode: str = "input"     # "input", "output"
    value: int = 0          # 0 or 1

    @classmethod
    def from_dict(cls, d: dict) -> "StaticIoPin":
        return cls(
            index=d.get("index", 0),
            mode=d.get("mode", "input"),
            value=d.get("value", 0),
        )


@dataclass
class StaticIoRequest:
    pins: list[StaticIoPin] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "StaticIoRequest":
        pins = [StaticIoPin.from_dict(p) for p in d.get("pins", [])]
        return cls(pins=pins)


# ---------------------------------------------------------------------------
# Basic measure (orchestration)
# ---------------------------------------------------------------------------

@dataclass
class BasicMeasureRequest:
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "BasicMeasureRequest":
        return cls(
            action=d.get("action", ""),
            params=d.get("params", {}),
        )
