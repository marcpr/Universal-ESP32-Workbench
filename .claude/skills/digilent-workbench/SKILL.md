# Digilent Workbench Skill

Use this skill when the user wants to use the Digilent/WaveForms measurement extension of the Universal ESP32 Workbench. Trigger on: "scope", "oscilloscope", "logic analyzer", "wavegen", "waveform generator", "analog measurement", "PWM messen", "Spannung messen", "digitale Aktivität", "digilent", "Analog Discovery".

## Purpose

This skill controls the Digilent WaveForms instrument (Analog Discovery 2/3 or compatible) attached to the Raspberry Pi workbench via USB. All instrument access goes through the workbench HTTP API — never through native libraries directly.

## Before You Begin

Always check device status first:

```
GET /api/digilent/status
```

Expected response:
```json
{
  "ok": true,
  "device_present": true,
  "device_open": false,
  "state": "idle",
  "device_name": "Analog Discovery 2",
  "temperature_c": 38.5,
  "capabilities": {"scope": true, "logic": true, "wavegen": true, "supplies": true, "static_io": true}
}
```

If `device_present` is false → the device is not connected. Stop and inform the user.
If `device_open` is false → open it first: `POST /api/digilent/device/open`
If `state` is `error` → reset: `POST /api/digilent/session/reset`

## Typical Workflows

### Measure PWM output from ESP32

```
POST /api/digilent/measure/basic
{
  "action": "measure_esp32_pwm",
  "params": {
    "channel": 1,
    "expected_freq_hz": 1000,
    "tolerance_percent": 5,
    "sample_rate_hz": 2000000,
    "duration_ms": 20
  }
}
```

### Measure voltage level

```
POST /api/digilent/measure/basic
{
  "action": "measure_voltage_level",
  "params": {
    "channel": 1,
    "expected_v": 3.3,
    "tolerance_v": 0.1,
    "range_v": 5.0,
    "duration_ms": 10
  }
}
```

### Detect digital activity on UART line

```
POST /api/digilent/measure/basic
{
  "action": "detect_logic_activity",
  "params": {
    "channels": [0, 1],
    "sample_rate_hz": 1000000,
    "duration_samples": 10000,
    "min_edges": 2
  }
}
```

### Full scope capture with metrics

```
POST /api/digilent/scope/capture
{
  "channels": [1],
  "range_v": 5.0,
  "offset_v": 0.0,
  "sample_rate_hz": 1000000,
  "duration_ms": 10,
  "trigger": {
    "enabled": true,
    "source": "ch1",
    "edge": "rising",
    "level_v": 1.6,
    "timeout_ms": 1000
  },
  "return_waveform": false
}
```

Response includes metrics per channel: `vmin`, `vmax`, `vpp`, `vavg`, `vrms`, `freq_est_hz`, `duty_cycle_percent`, `rise_time_s`, `fall_time_s`.

### Logic analyzer capture

```
POST /api/digilent/logic/capture
{
  "channels": [0, 1, 2],
  "sample_rate_hz": 10000000,
  "samples": 20000,
  "trigger": {
    "enabled": true,
    "channel": 0,
    "edge": "rising",
    "timeout_ms": 1000
  },
  "return_samples": false
}
```

### Waveform generator

```
POST /api/digilent/wavegen/set
{
  "channel": 1,
  "waveform": "square",
  "frequency_hz": 1000,
  "amplitude_v": 1.65,
  "offset_v": 1.65,
  "symmetry_percent": 50,
  "enable": true
}
```

Stop: `POST /api/digilent/wavegen/stop {"channel": 1}`

## Error Handling

| HTTP | Error code | Meaning |
|------|-----------|---------|
| 400 | DIGILENT_CONFIG_INVALID | Bad parameters (channel, range, etc.) |
| 400 | DIGILENT_RANGE_VIOLATION | Parameter exceeds safe limits |
| 403 | DIGILENT_NOT_ENABLED | Feature disabled in config (e.g. supplies) |
| 409 | DIGILENT_BUSY | Device is being used by another operation |
| 503 | DIGILENT_NOT_FOUND | No device connected |
| 504 | DIGILENT_CAPTURE_TIMEOUT | Capture did not complete in time |

On error, always read `error.code` and `error.message` from the response body and report them clearly to the user.

## Safety Rules

1. **Never activate power supplies** without explicit user confirmation and hardware verification. Supplies are disabled by default.
2. **Wavegen**: always warn the user when activating. Keep amplitudes within ESP32 GPIO tolerances (3.3V logic, max ±3.6V).
3. **Scope/Logic**: read-only — safe to use freely.
4. Request raw waveform data (`return_waveform: true`) only when the user explicitly needs it.
5. Always verify `within_tolerance` in `measure/basic` responses and report pass/fail clearly.

## Wiring Notes

For passive measurements (read-only):
- Connect Digilent GND ↔ DUT GND
- Scope CH1 → signal to measure
- No other connections required

For UART logic analysis:
- DIO0 → UART TX line
- DIO1 → UART RX line
- Common GND

Boot/reset sequencing: continue to use Pi GPIO (GPIO17=EN, GPIO18=BOOT) for resets. Use Digilent Scope CH1 to observe the reset signal.

## Useful Combinations with Other Workbench Features

- Use `POST /api/gpio/set` to trigger an ESP32 reset, then immediately start a scope capture with trigger to observe the boot waveform
- Use `/api/serial/monitor` to stream UART output while capturing digital activity on the same lines via logic analyzer
- Use UDP log receiver (`/api/udplog`) to correlate firmware log messages with measurement timestamps
