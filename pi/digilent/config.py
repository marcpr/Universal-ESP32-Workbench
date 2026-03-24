"""Digilent extension configuration loading and validation."""

import json
import os
from dataclasses import dataclass, field

DEFAULT_CONFIG_PATH = "/etc/rfc2217/digilent.json"


@dataclass
class SafeLimits:
    max_scope_sample_rate_hz: int = 50_000_000
    max_logic_sample_rate_hz: int = 100_000_000
    max_wavegen_amplitude_v: float = 5.0
    max_supply_plus_v: float = 5.0
    min_supply_minus_v: float = -5.0


@dataclass
class DigilentConfig:
    enabled: bool = True
    auto_open: bool = False
    preferred_device: str = "auto"
    max_scope_points: int = 20_000
    max_logic_points: int = 100_000
    default_timeout_ms: int = 3000
    allow_raw_waveforms: bool = True
    allow_supplies: bool = False
    safe_limits: SafeLimits = field(default_factory=SafeLimits)
    labels: dict[str, str] = field(default_factory=dict)


def load_config(path: str = DEFAULT_CONFIG_PATH) -> DigilentConfig:
    """Load config from JSON file, fall back to defaults if missing."""
    if not os.path.exists(path):
        return DigilentConfig()

    with open(path) as f:
        raw = json.load(f)

    limits_raw = raw.pop("safe_limits", {})
    limits = SafeLimits(**{k: v for k, v in limits_raw.items() if hasattr(SafeLimits, k)})

    cfg = DigilentConfig(safe_limits=limits)
    for key, val in raw.items():
        if hasattr(cfg, key) and key != "safe_limits":
            setattr(cfg, key, val)

    return cfg
