"""
Thin ctypes wrapper around the Digilent WaveForms SDK (libdwf.so).

All DWF library calls are confined to this module. Higher-level services
must not call libdwf functions directly.

The library is loaded lazily on first use. If it is not installed, all
functions raise DigilentTransportError.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
from ctypes import byref, c_bool, c_byte, c_char, c_double, c_int, c_ubyte, c_uint

from .errors import DigilentNotFoundError, DigilentTransportError

# ---------------------------------------------------------------------------
# Library loading
# ---------------------------------------------------------------------------

_lib: ctypes.CDLL | None = None
_lib_error: str | None = None

# DWF device handle (c_int, value -1 = invalid)
HDWF_NONE = c_int(-1)
HDWF = c_int

# Acquisition modes
_ACQMODE_SINGLE = c_int(1)

# Trigger sources
_TRIGSRC_NONE = c_int(0)
_TRIGSRC_PC = c_int(1)
_TRIGSRC_DET_ANALOG_IN = c_int(2)
_TRIGSRC_DET_DIGITAL_IN = c_int(3)

# Trigger slopes
_SLOPE_RISE = c_int(0)
_SLOPE_FALL = c_int(1)
_SLOPE_EITHER = c_int(2)

# Analog out waveform functions
_FUNC_DC = c_ubyte(0)
_FUNC_SINE = c_ubyte(1)
_FUNC_SQUARE = c_ubyte(2)
_FUNC_TRIANGLE = c_ubyte(3)
_FUNC_RAMP_UP = c_ubyte(4)

# Analog out node
_NODE_CARRIER = c_int(0)

# Enum filter (0 = all devices)
_ENUMFILTER_ALL = c_int(0)

# DWF state values
_STATE_DONE = c_ubyte(2)
_STATE_ARMED = c_ubyte(1)
_STATE_RUNNING = c_ubyte(3)

# Digital in sample format (number of bits per sample)
_DIG_FORMAT_16 = c_int(16)


def _load_lib() -> ctypes.CDLL:
    """Load libdwf.so, raising DigilentTransportError if not found."""
    global _lib, _lib_error
    if _lib is not None:
        return _lib
    if _lib_error is not None:
        raise DigilentTransportError(_lib_error)

    search_paths = [
        "/usr/lib/libdwf.so",
        "/usr/local/lib/libdwf.so",
        "/usr/lib/aarch64-linux-gnu/libdwf.so",
        "/usr/lib/arm-linux-gnueabihf/libdwf.so",
    ]

    for path in search_paths:
        if os.path.exists(path):
            try:
                _lib = ctypes.cdll.LoadLibrary(path)
                return _lib
            except OSError as exc:
                _lib_error = f"Failed to load {path}: {exc}"

    # Last attempt via system linker
    name = ctypes.util.find_library("dwf")
    if name:
        try:
            _lib = ctypes.cdll.LoadLibrary(name)
            return _lib
        except OSError as exc:
            _lib_error = f"Failed to load {name}: {exc}"

    _lib_error = (
        "libdwf.so not found. Install WaveForms from https://digilent.com/reference/software/waveforms/waveforms-3/start"
    )
    raise DigilentTransportError(_lib_error)


def _check(result: c_bool | int, op: str) -> None:
    """Raise DigilentTransportError if a DWF call returned False/0."""
    val = result if isinstance(result, int) else bool(result)
    if not val:
        lib = _load_lib()
        msg_buf = (c_char * 512)()
        lib.FDwfGetLastErrorMsg(msg_buf)
        msg = msg_buf.value.decode("utf-8", errors="replace").strip()
        raise DigilentTransportError(f"DWF call failed [{op}]: {msg}")


# ---------------------------------------------------------------------------
# Device enumeration and lifecycle
# ---------------------------------------------------------------------------

def enumerate_devices() -> int:
    """Return the number of connected WaveForms-compatible devices."""
    lib = _load_lib()
    count = c_int()
    _check(lib.FDwfEnum(_ENUMFILTER_ALL, byref(count)), "FDwfEnum")
    return count.value


def get_device_name(idx: int) -> str:
    """Return the name string of the device at index idx."""
    lib = _load_lib()
    buf = (c_char * 32)()
    _check(lib.FDwfEnumDeviceName(c_int(idx), buf), "FDwfEnumDeviceName")
    return buf.value.decode("utf-8", errors="replace").strip()


def open_device(idx: int = -1) -> c_int:
    """
    Open a WaveForms device by index. Pass idx=-1 to open the first available.
    Returns the device handle (HDWF).
    Raises DigilentNotFoundError if no device is found.
    """
    lib = _load_lib()
    hdwf = c_int()
    result = lib.FDwfDeviceOpen(c_int(idx), byref(hdwf))
    if not result or hdwf.value == HDWF_NONE.value:
        msg_buf = (c_char * 512)()
        lib.FDwfGetLastErrorMsg(msg_buf)
        msg = msg_buf.value.decode("utf-8", errors="replace").strip()
        raise DigilentNotFoundError(
            f"No WaveForms device found (idx={idx}). DWF: {msg}"
        )
    return hdwf


def close_device(hdwf: c_int) -> None:
    """Close the device handle. Safe to call even if already closed."""
    if hdwf.value == HDWF_NONE.value:
        return
    try:
        lib = _load_lib()
        lib.FDwfDeviceClose(hdwf)
    except DigilentTransportError:
        pass  # best-effort close


def read_temperature(hdwf: c_int) -> float | None:
    """
    Attempt to read the device temperature in degrees Celsius.
    Returns None if unsupported by the connected device.
    """
    try:
        lib = _load_lib()
        # AD2: temperature is at AnalogIO channel 0, node 0 on some firmware
        # versions. We try channel indices until one succeeds.
        temp = c_double()
        for ch in range(4):
            result = lib.FDwfAnalogIOChannelNodeGet(
                hdwf, c_int(ch), c_int(0), byref(temp)
            )
            if result:
                t = temp.value
                # Sanity check: plausible temperature range
                if -40.0 <= t <= 125.0:
                    return round(t, 1)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Oscilloscope (AnalogIn)
# ---------------------------------------------------------------------------

def scope_capture_raw(
    hdwf: c_int,
    channels: list[int],
    range_v: float,
    offset_v: float,
    sample_rate_hz: float,
    n_samples: int,
    trigger_source: str,
    trigger_edge: str,
    trigger_channel: int,
    trigger_level_v: float,
    trigger_timeout_s: float,
) -> dict[int, list[float]]:
    """
    Configure the AnalogIn instrument and capture one acquisition.

    Returns a dict mapping channel number (1-based) -> list of voltage samples.
    """
    lib = _load_lib()

    # Disable all channels first, then enable requested ones
    for ch in (0, 1):
        lib.FDwfAnalogInChannelEnableSet(hdwf, c_int(ch), c_bool(False))

    for ch in channels:
        idx = ch - 1  # DWF uses 0-based channel indices
        _check(
            lib.FDwfAnalogInChannelEnableSet(hdwf, c_int(idx), c_bool(True)),
            "FDwfAnalogInChannelEnableSet",
        )
        _check(
            lib.FDwfAnalogInChannelRangeSet(hdwf, c_int(idx), c_double(range_v)),
            "FDwfAnalogInChannelRangeSet",
        )
        _check(
            lib.FDwfAnalogInChannelOffsetSet(hdwf, c_int(idx), c_double(offset_v)),
            "FDwfAnalogInChannelOffsetSet",
        )

    _check(
        lib.FDwfAnalogInFrequencySet(hdwf, c_double(sample_rate_hz)),
        "FDwfAnalogInFrequencySet",
    )
    _check(
        lib.FDwfAnalogInBufferSizeSet(hdwf, c_int(n_samples)),
        "FDwfAnalogInBufferSizeSet",
    )
    _check(
        lib.FDwfAnalogInAcquisitionModeSet(hdwf, _ACQMODE_SINGLE),
        "FDwfAnalogInAcquisitionModeSet",
    )

    # Trigger configuration
    if trigger_source == "none":
        _check(
            lib.FDwfAnalogInTriggerSourceSet(hdwf, _TRIGSRC_NONE),
            "FDwfAnalogInTriggerSourceSet(none)",
        )
        _check(
            lib.FDwfAnalogInTriggerAutoTimeoutSet(hdwf, c_double(trigger_timeout_s)),
            "FDwfAnalogInTriggerAutoTimeoutSet",
        )
    else:
        _check(
            lib.FDwfAnalogInTriggerSourceSet(hdwf, _TRIGSRC_DET_ANALOG_IN),
            "FDwfAnalogInTriggerSourceSet(det)",
        )
        _check(
            lib.FDwfAnalogInTriggerAutoTimeoutSet(hdwf, c_double(trigger_timeout_s)),
            "FDwfAnalogInTriggerAutoTimeoutSet",
        )
        _check(
            lib.FDwfAnalogInTriggerChannelSet(hdwf, c_int(trigger_channel - 1)),
            "FDwfAnalogInTriggerChannelSet",
        )
        edge_val = {"rising": _SLOPE_RISE, "falling": _SLOPE_FALL, "either": _SLOPE_EITHER}.get(
            trigger_edge, _SLOPE_RISE
        )
        _check(
            lib.FDwfAnalogInTriggerConditionSet(hdwf, edge_val),
            "FDwfAnalogInTriggerConditionSet",
        )
        _check(
            lib.FDwfAnalogInTriggerLevelSet(hdwf, c_double(trigger_level_v)),
            "FDwfAnalogInTriggerLevelSet",
        )

    # Start acquisition
    _check(
        lib.FDwfAnalogInConfigure(hdwf, c_bool(False), c_bool(True)),
        "FDwfAnalogInConfigure",
    )

    # Wait for acquisition to complete
    import time
    deadline = time.monotonic() + trigger_timeout_s + 1.0
    sts = c_ubyte()
    while time.monotonic() < deadline:
        _check(lib.FDwfAnalogInStatus(hdwf, c_bool(True), byref(sts)), "FDwfAnalogInStatus")
        if sts.value == _STATE_DONE.value:
            break
        time.sleep(0.005)
    else:
        from .errors import DigilentCaptureTimeoutError
        raise DigilentCaptureTimeoutError("Scope capture timed out waiting for done state")

    # Read data for each channel
    result: dict[int, list[float]] = {}
    for ch in channels:
        idx = ch - 1
        buf = (c_double * n_samples)()
        _check(
            lib.FDwfAnalogInStatusData(hdwf, c_int(idx), buf, c_int(n_samples)),
            "FDwfAnalogInStatusData",
        )
        result[ch] = list(buf)

    return result


# ---------------------------------------------------------------------------
# Logic Analyzer (DigitalIn)
# ---------------------------------------------------------------------------

def logic_capture_raw(
    hdwf: c_int,
    channels: list[int],
    sample_rate_hz: float,
    n_samples: int,
    trigger_enabled: bool,
    trigger_channel: int,
    trigger_edge: str,
    trigger_timeout_s: float,
) -> dict[int, list[int]]:
    """
    Configure the DigitalIn instrument and capture one acquisition.

    Returns a dict mapping channel index (0-based) -> list of 0/1 samples.
    """
    lib = _load_lib()

    # Get system clock frequency for divider calculation
    hz_system = c_double()
    _check(
        lib.FDwfDigitalInInternalClockInfo(hdwf, byref(hz_system)),
        "FDwfDigitalInInternalClockInfo",
    )
    div = max(1, int(hz_system.value / sample_rate_hz))

    _check(
        lib.FDwfDigitalInDividerSet(hdwf, c_uint(div)),
        "FDwfDigitalInDividerSet",
    )
    _check(
        lib.FDwfDigitalInSampleFormatSet(hdwf, _DIG_FORMAT_16),
        "FDwfDigitalInSampleFormatSet",
    )
    _check(
        lib.FDwfDigitalInBufferSizeSet(hdwf, c_int(n_samples)),
        "FDwfDigitalInBufferSizeSet",
    )
    _check(
        lib.FDwfDigitalInAcquisitionModeSet(hdwf, _ACQMODE_SINGLE),
        "FDwfDigitalInAcquisitionModeSet",
    )

    if trigger_enabled:
        _check(
            lib.FDwfDigitalInTriggerSourceSet(hdwf, _TRIGSRC_DET_DIGITAL_IN),
            "FDwfDigitalInTriggerSourceSet",
        )
        ch_mask = c_uint(1 << trigger_channel)
        zero = c_uint(0)
        if trigger_edge == "rising":
            _check(
                lib.FDwfDigitalInTriggerSet(hdwf, zero, zero, ch_mask, zero),
                "FDwfDigitalInTriggerSet(rise)",
            )
        elif trigger_edge == "falling":
            _check(
                lib.FDwfDigitalInTriggerSet(hdwf, zero, zero, zero, ch_mask),
                "FDwfDigitalInTriggerSet(fall)",
            )
        else:  # either
            _check(
                lib.FDwfDigitalInTriggerSet(hdwf, zero, zero, ch_mask, ch_mask),
                "FDwfDigitalInTriggerSet(either)",
            )
    else:
        _check(
            lib.FDwfDigitalInTriggerSourceSet(hdwf, _TRIGSRC_PC),
            "FDwfDigitalInTriggerSourceSet(pc)",
        )

    # Start
    _check(
        lib.FDwfDigitalInConfigure(hdwf, c_bool(False), c_bool(True)),
        "FDwfDigitalInConfigure",
    )

    # Poll until done
    import time
    deadline = time.monotonic() + trigger_timeout_s + 1.0
    sts = c_ubyte()
    while time.monotonic() < deadline:
        _check(lib.FDwfDigitalInStatus(hdwf, c_bool(True), byref(sts)), "FDwfDigitalInStatus")
        if sts.value == _STATE_DONE.value:
            break
        time.sleep(0.005)
    else:
        from .errors import DigilentCaptureTimeoutError
        raise DigilentCaptureTimeoutError("Logic capture timed out waiting for done state")

    # Read 16-bit samples (each sample is a 16-bit word with all DIO values)
    raw_buf = (ctypes.c_uint16 * n_samples)()
    bytes_needed = ctypes.sizeof(raw_buf)
    _check(
        lib.FDwfDigitalInStatusData(hdwf, raw_buf, c_int(bytes_needed)),
        "FDwfDigitalInStatusData",
    )

    # Extract individual channel bits
    result: dict[int, list[int]] = {}
    for ch in channels:
        mask = 1 << ch
        result[ch] = [1 if (raw_buf[i] & mask) else 0 for i in range(n_samples)]

    return result


# ---------------------------------------------------------------------------
# Waveform Generator (AnalogOut)
# ---------------------------------------------------------------------------

_WAVEFORM_MAP: dict[str, c_ubyte] = {
    "dc": _FUNC_DC,
    "sine": _FUNC_SINE,
    "square": _FUNC_SQUARE,
    "triangle": _FUNC_TRIANGLE,
}


def wavegen_apply(
    hdwf: c_int,
    channel: int,      # 1-based
    waveform: str,
    frequency_hz: float,
    amplitude_v: float,
    offset_v: float,
    symmetry_percent: float,
    enable: bool,
) -> None:
    """Configure and start/stop the AnalogOut waveform generator."""
    lib = _load_lib()
    idx = c_int(channel - 1)  # DWF 0-based

    func = _WAVEFORM_MAP.get(waveform, _FUNC_SINE)

    _check(lib.FDwfAnalogOutNodeEnableSet(hdwf, idx, _NODE_CARRIER, c_bool(True)), "FDwfAnalogOutNodeEnableSet")
    _check(lib.FDwfAnalogOutNodeFunctionSet(hdwf, idx, _NODE_CARRIER, func), "FDwfAnalogOutNodeFunctionSet")
    _check(lib.FDwfAnalogOutNodeFrequencySet(hdwf, idx, _NODE_CARRIER, c_double(frequency_hz)), "FDwfAnalogOutNodeFrequencySet")
    _check(lib.FDwfAnalogOutNodeAmplitudeSet(hdwf, idx, _NODE_CARRIER, c_double(amplitude_v)), "FDwfAnalogOutNodeAmplitudeSet")
    _check(lib.FDwfAnalogOutNodeOffsetSet(hdwf, idx, _NODE_CARRIER, c_double(offset_v)), "FDwfAnalogOutNodeOffsetSet")
    _check(lib.FDwfAnalogOutNodeSymmetrySet(hdwf, idx, _NODE_CARRIER, c_double(symmetry_percent)), "FDwfAnalogOutNodeSymmetrySet")

    # fStart: 1 = start, 0 = stop
    _check(lib.FDwfAnalogOutConfigure(hdwf, idx, c_bool(enable)), "FDwfAnalogOutConfigure")


def wavegen_stop(hdwf: c_int, channel: int) -> None:
    """Stop the waveform generator on the given channel (1-based)."""
    lib = _load_lib()
    idx = c_int(channel - 1)
    lib.FDwfAnalogOutConfigure(hdwf, idx, c_bool(False))


# ---------------------------------------------------------------------------
# Power Supplies (AnalogIO)
# ---------------------------------------------------------------------------

def supplies_apply(
    hdwf: c_int,
    vplus_v: float,
    vminus_v: float,
    enable_vplus: bool,
    enable_vminus: bool,
) -> None:
    """
    Set the Analog Discovery positive/negative supply voltages.
    AD2: channel 0 = V+, channel 1 = V-
         node 0 = enable, node 1 = voltage
    """
    lib = _load_lib()

    # V+ supply
    _check(lib.FDwfAnalogIOChannelNodeSet(hdwf, c_int(0), c_int(0), c_double(1.0 if enable_vplus else 0.0)), "supplies V+ enable")
    _check(lib.FDwfAnalogIOChannelNodeSet(hdwf, c_int(0), c_int(1), c_double(vplus_v)), "supplies V+ voltage")

    # V- supply
    _check(lib.FDwfAnalogIOChannelNodeSet(hdwf, c_int(1), c_int(0), c_double(1.0 if enable_vminus else 0.0)), "supplies V- enable")
    _check(lib.FDwfAnalogIOChannelNodeSet(hdwf, c_int(1), c_int(1), c_double(vminus_v)), "supplies V- voltage")

    # Master enable
    master = enable_vplus or enable_vminus
    _check(lib.FDwfAnalogIOEnableSet(hdwf, c_bool(master)), "FDwfAnalogIOEnableSet")


def supplies_off(hdwf: c_int) -> None:
    """Turn off all power supplies."""
    lib = _load_lib()
    lib.FDwfAnalogIOEnableSet(hdwf, c_bool(False))


# ---------------------------------------------------------------------------
# Static I/O (DigitalIO)
# ---------------------------------------------------------------------------

def static_io_apply(
    hdwf: c_int,
    pins: list[tuple[int, str, int]],  # (index, mode, value)
) -> dict[int, int]:
    """
    Configure static digital I/O pins.
    Returns current input state for all input-mode pins.
    """
    lib = _load_lib()

    output_enable_mask = 0
    output_mask = 0

    for idx, mode, value in pins:
        if mode == "output":
            output_enable_mask |= 1 << idx
            if value:
                output_mask |= 1 << idx

    _check(lib.FDwfDigitalIOOutputEnableSet(hdwf, c_uint(output_enable_mask)), "FDwfDigitalIOOutputEnableSet")
    _check(lib.FDwfDigitalIOOutputSet(hdwf, c_uint(output_mask)), "FDwfDigitalIOOutputSet")
    _check(lib.FDwfDigitalIOStatus(hdwf), "FDwfDigitalIOStatus")

    input_word = c_uint()
    _check(lib.FDwfDigitalIOInputStatus(hdwf, byref(input_word)), "FDwfDigitalIOInputStatus")

    # Extract states for input pins
    input_states: dict[int, int] = {}
    for idx, mode, _ in pins:
        if mode == "input":
            input_states[idx] = 1 if (input_word.value & (1 << idx)) else 0

    return input_states


def is_available() -> bool:
    """Return True if the DWF library can be loaded."""
    try:
        _load_lib()
        return True
    except DigilentTransportError:
        return False
