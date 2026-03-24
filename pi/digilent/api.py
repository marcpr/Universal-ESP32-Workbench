"""
Digilent API — HTTP dispatch and module-level controller facade.

This module acts as the public interface for portal.py:

    import digilent.api as digilent_api
    digilent_api.init()
    digilent_api.handle_get(handler, path)
    digilent_api.handle_post(handler, path)
    digilent_api.shutdown()

All HTTP handler methods follow the same conventions as the portal:
- use handler._send_json() and handler._read_json()
- set appropriate HTTP status codes
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .config import DigilentConfig, load_config
from .device_manager import DeviceManager
from .errors import (
    DigilentBusyError,
    DigilentConfigInvalidError,
    DigilentError,
    DigilentNotEnabledError,
    DigilentNotFoundError,
    DigilentRangeViolationError,
)
from .logic_service import LogicService
from .models import (
    BasicMeasureRequest,
    LogicCaptureRequest,
    ScopeCaptureRequest,
    StaticIoRequest,
    SuppliesRequest,
    WavegenRequest,
)
from .orchestration import OrchestrationService
from .scope_service import ScopeService
from .supplies_service import StaticIoService, SuppliesService
from .wavegen_service import WavegenService

_log = logging.getLogger("digilent.api")

# ---------------------------------------------------------------------------
# Module-level state (initialised by init())
# ---------------------------------------------------------------------------

_config: DigilentConfig | None = None
_manager: DeviceManager | None = None
_scope: ScopeService | None = None
_logic: LogicService | None = None
_wavegen: WavegenService | None = None
_supplies: SuppliesService | None = None
_static_io: StaticIoService | None = None
_orchestration: OrchestrationService | None = None


def init(config_path: str | None = None) -> None:
    """Initialise the Digilent services. Called once at portal startup."""
    global _config, _manager, _scope, _logic, _wavegen, _supplies, _static_io, _orchestration

    from .config import DEFAULT_CONFIG_PATH
    _config = load_config(config_path or DEFAULT_CONFIG_PATH)

    if not _config.enabled:
        _log.info("Digilent extension disabled by configuration")
        return

    _manager = DeviceManager()
    _scope = ScopeService(_manager, _config)
    _logic = LogicService(_manager, _config)
    _wavegen = WavegenService(_manager, _config)
    _supplies = SuppliesService(_manager, _config)
    _static_io = StaticIoService(_manager, _config)
    _orchestration = OrchestrationService(_manager, _config)

    if _config.auto_open:
        _log.info("auto_open=true — attempting to open Digilent device")
        try:
            _manager.open()
            _log.info("Digilent device opened: %s", _manager.device_info.name)
        except DigilentError as exc:
            _log.warning("auto_open failed: %s", exc)


def shutdown() -> None:
    """Close device on portal shutdown."""
    if _manager:
        _manager.close()


# ---------------------------------------------------------------------------
# HTTP dispatch
# ---------------------------------------------------------------------------

def handle_get(handler, path: str) -> None:
    """Dispatch GET requests under /api/digilent."""
    if path == "/api/digilent/status":
        _h_status(handler)
    else:
        _not_found(handler, path)


def handle_post(handler, path: str) -> None:
    """Dispatch POST requests under /api/digilent."""
    routes = {
        "/api/digilent/device/open": _h_device_open,
        "/api/digilent/device/close": _h_device_close,
        "/api/digilent/scope/capture": _h_scope_capture,
        "/api/digilent/scope/measure": _h_scope_measure,
        "/api/digilent/logic/capture": _h_logic_capture,
        "/api/digilent/wavegen/set": _h_wavegen_set,
        "/api/digilent/wavegen/stop": _h_wavegen_stop,
        "/api/digilent/supplies/set": _h_supplies_set,
        "/api/digilent/static-io/set": _h_static_io_set,
        "/api/digilent/measure/basic": _h_measure_basic,
        "/api/digilent/session/reset": _h_session_reset,
    }
    fn = routes.get(path)
    if fn is None:
        _not_found(handler, path)
    else:
        fn(handler)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok_if_not_init(handler) -> bool:
    """Return True (and send error) if services are not initialised."""
    if _manager is None:
        handler._send_json(
            {
                "ok": False,
                "ts": _ts(),
                "request_id": _req_id(),
                "error": {
                    "code": "DIGILENT_NOT_AVAILABLE",
                    "message": "Digilent extension is disabled or not initialised",
                },
            },
            503,
        )
        return True
    return False


def _error_response(exc: DigilentError) -> tuple[dict, int]:
    """Map a DigilentError to (response_dict, http_status)."""
    status_map = {
        "DIGILENT_BUSY": 409,
        "DIGILENT_NOT_FOUND": 503,
        "DIGILENT_CONFIG_INVALID": 400,
        "DIGILENT_RANGE_VIOLATION": 400,
        "DIGILENT_NOT_ENABLED": 403,
        "DIGILENT_CAPTURE_TIMEOUT": 504,
        "DIGILENT_TRIGGER_TIMEOUT": 504,
    }
    status = status_map.get(exc.code, 500)
    return {
        "ok": False,
        "ts": _ts(),
        "request_id": _req_id(),
        "error": exc.to_dict(),
    }, status


def _run(handler, fn, *args, **kwargs) -> None:
    """Execute fn(*args), handling DigilentError and unexpected exceptions."""
    t0 = time.monotonic()
    req_id = _req_id()
    try:
        result = fn(*args, **kwargs)
        result.setdefault("request_id", req_id)
        duration_ms = round((time.monotonic() - t0) * 1000, 1)
        _log.info(
            '{"component":"digilent","op":"%s","request_id":"%s","duration_ms":%s,"status":"ok"}',
            fn.__name__, req_id, duration_ms,
        )
        handler._send_json(result, 200)
    except DigilentError as exc:
        resp, status = _error_response(exc)
        resp["request_id"] = req_id
        duration_ms = round((time.monotonic() - t0) * 1000, 1)
        _log.warning(
            '{"component":"digilent","op":"%s","request_id":"%s","duration_ms":%s,"status":"error","code":"%s"}',
            fn.__name__, req_id, duration_ms, exc.code,
        )
        handler._send_json(resp, status)
    except Exception as exc:
        resp = {
            "ok": False,
            "ts": _ts(),
            "request_id": req_id,
            "error": {
                "code": "DIGILENT_INTERNAL_ERROR",
                "message": f"Unexpected error: {exc}",
            },
        }
        _log.exception("Unexpected error in digilent handler")
        handler._send_json(resp, 500)


def _not_found(handler, path: str) -> None:
    handler._send_json(
        {"ok": False, "error": {"code": "NOT_FOUND", "message": f"No Digilent endpoint at {path}"}},
        404,
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def _h_status(handler) -> None:
    if _manager is None:
        handler._send_json(
            {
                "ok": True,
                "device_present": False,
                "device_open": False,
                "device_name": None,
                "state": "absent",
                "temperature_c": None,
                "capabilities": {},
                "extension_enabled": False,
            }
        )
        return
    _manager.refresh_temperature()
    handler._send_json(_manager.status_dict())


def _h_device_open(handler) -> None:
    if _ok_if_not_init(handler):
        return
    _run(handler, _manager.open)


def _h_device_close(handler) -> None:
    if _ok_if_not_init(handler):
        return

    def _close():
        _manager.close()
        return {"ok": True, "ts": _ts(), "message": "Device closed"}

    _run(handler, _close)


def _h_scope_capture(handler) -> None:
    if _ok_if_not_init(handler):
        return
    body = handler._read_json() or {}
    req = ScopeCaptureRequest.from_dict(body)
    _run(handler, _scope.capture, req)


def _h_scope_measure(handler) -> None:
    if _ok_if_not_init(handler):
        return
    body = handler._read_json() or {}
    req = ScopeCaptureRequest.from_dict(body)
    _run(handler, _scope.measure, req)


def _h_logic_capture(handler) -> None:
    if _ok_if_not_init(handler):
        return
    body = handler._read_json() or {}
    req = LogicCaptureRequest.from_dict(body)
    _run(handler, _logic.capture, req)


def _h_wavegen_set(handler) -> None:
    if _ok_if_not_init(handler):
        return
    body = handler._read_json() or {}
    req = WavegenRequest.from_dict(body)
    _run(handler, _wavegen.set, req)


def _h_wavegen_stop(handler) -> None:
    if _ok_if_not_init(handler):
        return
    body = handler._read_json() or {}
    channel = int(body.get("channel", 1))
    _run(handler, _wavegen.stop, channel)


def _h_supplies_set(handler) -> None:
    if _ok_if_not_init(handler):
        return
    body = handler._read_json() or {}
    req = SuppliesRequest.from_dict(body)
    _run(handler, _supplies.set, req)


def _h_static_io_set(handler) -> None:
    if _ok_if_not_init(handler):
        return
    body = handler._read_json() or {}
    req = StaticIoRequest.from_dict(body)
    _run(handler, _static_io.set, req)


def _h_measure_basic(handler) -> None:
    if _ok_if_not_init(handler):
        return
    body = handler._read_json() or {}
    req = BasicMeasureRequest.from_dict(body)
    _run(handler, _orchestration.measure_basic, req.action, req.params)


def _h_session_reset(handler) -> None:
    if _ok_if_not_init(handler):
        return

    def _reset():
        _manager.reset_session()
        return {"ok": True, "ts": _ts(), "message": "Session reset — device closed"}

    _run(handler, _reset)
