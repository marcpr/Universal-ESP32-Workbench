"""Metric calculation utilities for scope and logic data."""

import math
from typing import Sequence


# ---------------------------------------------------------------------------
# Scope metrics
# ---------------------------------------------------------------------------

def compute_scope_metrics(
    samples: Sequence[float],
    sample_rate_hz: float,
) -> dict:
    """Compute standard scope metrics from a voltage sample array."""
    if not samples:
        return {}

    n = len(samples)
    vmin = min(samples)
    vmax = max(samples)
    vpp = vmax - vmin
    vavg = sum(samples) / n
    vrms = math.sqrt(sum(v * v for v in samples) / n)

    threshold = (vmax + vmin) / 2.0

    freq_hz, period_s, duty_pct = _estimate_freq_duty(samples, sample_rate_hz, threshold)
    rise_s, fall_s = _estimate_rise_fall(samples, sample_rate_hz, vmin, vmax)

    return {
        "vmin": round(vmin, 6),
        "vmax": round(vmax, 6),
        "vpp": round(vpp, 6),
        "vavg": round(vavg, 6),
        "vrms": round(vrms, 6),
        "freq_est_hz": round(freq_hz, 3) if freq_hz is not None else None,
        "period_est_s": round(period_s, 9) if period_s is not None else None,
        "duty_cycle_percent": round(duty_pct, 2) if duty_pct is not None else None,
        "rise_time_s": round(rise_s, 9) if rise_s is not None else None,
        "fall_time_s": round(fall_s, 9) if fall_s is not None else None,
    }


def _estimate_freq_duty(
    samples: Sequence[float],
    sample_rate_hz: float,
    threshold: float,
) -> tuple[float | None, float | None, float | None]:
    """Estimate frequency, period, and duty cycle via threshold crossings."""
    if sample_rate_hz <= 0 or len(samples) < 4:
        return None, None, None

    dt = 1.0 / sample_rate_hz
    rising: list[float] = []
    high_count = 0

    for i, v in enumerate(samples):
        if v >= threshold:
            high_count += 1

    # Detect rising edges (threshold crossings low->high)
    prev_high = samples[0] >= threshold
    for i in range(1, len(samples)):
        cur_high = samples[i] >= threshold
        if cur_high and not prev_high:
            rising.append(i * dt)
        prev_high = cur_high

    duty_pct = (high_count / len(samples)) * 100.0

    if len(rising) < 2:
        return None, None, duty_pct

    # Average period from consecutive rising edges
    periods = [rising[i + 1] - rising[i] for i in range(len(rising) - 1)]
    avg_period = sum(periods) / len(periods)
    if avg_period <= 0:
        return None, None, duty_pct

    freq_hz = 1.0 / avg_period
    return freq_hz, avg_period, duty_pct


def _estimate_rise_fall(
    samples: Sequence[float],
    sample_rate_hz: float,
    vmin: float,
    vmax: float,
) -> tuple[float | None, float | None]:
    """Estimate 10%-90% rise time and 90%-10% fall time."""
    if sample_rate_hz <= 0 or len(samples) < 4:
        return None, None

    vpp = vmax - vmin
    if vpp < 0.01:  # too small to measure
        return None, None

    dt = 1.0 / sample_rate_hz
    low_10 = vmin + 0.10 * vpp
    high_90 = vmin + 0.90 * vpp

    rise_s = _measure_transition(samples, dt, low_10, high_90, rising=True)
    fall_s = _measure_transition(samples, dt, high_90, low_10, rising=False)
    return rise_s, fall_s


def _measure_transition(
    samples: Sequence[float],
    dt: float,
    level_start: float,
    level_end: float,
    rising: bool,
) -> float | None:
    """Find first transition from level_start to level_end."""
    cross_start: float | None = None

    for i in range(1, len(samples)):
        prev, cur = samples[i - 1], samples[i]
        if rising:
            if cross_start is None and prev < level_start <= cur:
                cross_start = i * dt
            elif cross_start is not None and prev < level_end <= cur:
                return (i * dt) - cross_start
        else:
            if cross_start is None and prev > level_start >= cur:
                cross_start = i * dt
            elif cross_start is not None and prev > level_end >= cur:
                return (i * dt) - cross_start

    return None


# ---------------------------------------------------------------------------
# Logic metrics
# ---------------------------------------------------------------------------

def compute_logic_metrics(
    samples: Sequence[int],
    sample_rate_hz: float,
) -> dict:
    """Compute standard logic metrics from a binary sample array (0/1)."""
    if not samples:
        return {}

    n = len(samples)
    high_count = sum(1 for s in samples if s)
    low_count = n - high_count

    edge_count = sum(
        1 for i in range(1, n) if samples[i] != samples[i - 1]
    )

    freq_hz, period_s, duty_pct = _estimate_logic_freq_duty(
        samples, sample_rate_hz
    )

    return {
        "high_ratio": round(high_count / n, 6),
        "low_ratio": round(low_count / n, 6),
        "edge_count": edge_count,
        "freq_est_hz": round(freq_hz, 3) if freq_hz is not None else None,
        "period_est_s": round(period_s, 9) if period_s is not None else None,
        "duty_cycle_percent": round(duty_pct, 2) if duty_pct is not None else None,
    }


def _estimate_logic_freq_duty(
    samples: Sequence[int],
    sample_rate_hz: float,
) -> tuple[float | None, float | None, float | None]:
    if sample_rate_hz <= 0 or len(samples) < 4:
        return None, None, None

    dt = 1.0 / sample_rate_hz
    rising: list[float] = []
    high_count = 0

    prev = samples[0]
    for i, s in enumerate(samples):
        if s:
            high_count += 1
        if i > 0 and s == 1 and prev == 0:
            rising.append(i * dt)
        prev = s

    duty_pct = (high_count / len(samples)) * 100.0

    if len(rising) < 2:
        return None, None, duty_pct

    periods = [rising[i + 1] - rising[i] for i in range(len(rising) - 1)]
    avg_period = sum(periods) / len(periods)
    if avg_period <= 0:
        return None, None, duty_pct

    return 1.0 / avg_period, avg_period, duty_pct


# ---------------------------------------------------------------------------
# Downsampling
# ---------------------------------------------------------------------------

def downsample_minmax(samples: list[float], max_points: int) -> list[float]:
    """Min/max bucket downsampling to preserve envelope of waveform."""
    n = len(samples)
    if n <= max_points:
        return list(samples)

    # Each output bucket covers n/max_points input samples.
    # We alternate min and max to preserve the waveform shape.
    bucket_size = n / (max_points / 2)
    result: list[float] = []

    i = 0
    bucket = 0
    while len(result) < max_points and i < n:
        start = int(bucket * bucket_size)
        end = min(int((bucket + 1) * bucket_size), n)
        if start >= n:
            break
        chunk = samples[start:end]
        result.append(min(chunk))
        if len(result) < max_points:
            result.append(max(chunk))
        bucket += 1
        i = end

    return result
