"""Power supplies and static I/O service."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import dwf_adapter as dwf
from .config import DigilentConfig
from .device_manager import DeviceManager
from .errors import DigilentConfigInvalidError, DigilentNotEnabledError, DigilentRangeViolationError
from .models import StaticIoRequest, SuppliesRequest

_log = logging.getLogger("digilent.supplies")


class SuppliesService:
    def __init__(self, manager: DeviceManager, config: DigilentConfig) -> None:
        self._manager = manager
        self._cfg = config

    def set(self, req: SuppliesRequest) -> dict:
        """Configure and optionally enable the power supplies."""
        self._validate(req)

        warnings = ["Power supply activated — verify wiring before enabling output"]

        with self._manager.session() as hdwf:
            dwf.supplies_apply(
                hdwf=hdwf,
                vplus_v=req.vplus_v,
                vminus_v=req.vminus_v,
                enable_vplus=req.enable_vplus,
                enable_vminus=req.enable_vminus,
            )

        active = req.enable_vplus or req.enable_vminus
        if active:
            _log.warning(
                "Supplies activated: V+=%.2fV (en=%s) V-=%.2fV (en=%s)",
                req.vplus_v,
                req.enable_vplus,
                req.vminus_v,
                req.enable_vminus,
            )

        response: dict = {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": "Supplies configured",
            "vplus_active": req.enable_vplus,
            "vminus_active": req.enable_vminus,
        }
        if active:
            response["warnings"] = warnings
        return response

    def _validate(self, req: SuppliesRequest) -> None:
        if not self._cfg.allow_supplies:
            raise DigilentNotEnabledError(
                "Power supply control is disabled. Set allow_supplies=true in digilent.json to enable."
            )

        limits = self._cfg.safe_limits

        if req.enable_vplus and not req.confirm_unsafe:
            raise DigilentConfigInvalidError(
                "Supply activation requires confirm_unsafe=true in the request"
            )
        if req.enable_vminus and not req.confirm_unsafe:
            raise DigilentConfigInvalidError(
                "Supply activation requires confirm_unsafe=true in the request"
            )
        if req.vplus_v > limits.max_supply_plus_v:
            raise DigilentRangeViolationError(
                f"vplus_v {req.vplus_v} exceeds safe limit {limits.max_supply_plus_v}"
            )
        if req.vminus_v < limits.min_supply_minus_v:
            raise DigilentRangeViolationError(
                f"vminus_v {req.vminus_v} below safe limit {limits.min_supply_minus_v}"
            )
        if req.vplus_v < 0:
            raise DigilentConfigInvalidError("vplus_v must be >= 0")
        if req.vminus_v > 0:
            raise DigilentConfigInvalidError("vminus_v must be <= 0")


class StaticIoService:
    def __init__(self, manager: DeviceManager, config: DigilentConfig) -> None:
        self._manager = manager
        self._cfg = config

    def set(self, req: StaticIoRequest) -> dict:
        """Configure static I/O pins."""
        self._validate(req)

        pin_tuples = [(p.index, p.mode, p.value) for p in req.pins]

        with self._manager.session() as hdwf:
            input_states = dwf.static_io_apply(hdwf=hdwf, pins=pin_tuples)

        return {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "input_states": input_states,
        }

    def _validate(self, req: StaticIoRequest) -> None:
        if not req.pins:
            raise DigilentConfigInvalidError("pins list must not be empty")
        for pin in req.pins:
            if not (0 <= pin.index <= 15):
                raise DigilentConfigInvalidError(f"Pin index {pin.index} out of range 0-15")
            if pin.mode not in ("input", "output"):
                raise DigilentConfigInvalidError(f"Invalid mode '{pin.mode}' for pin {pin.index}")
            if pin.mode == "output" and pin.value not in (0, 1):
                raise DigilentConfigInvalidError(f"Pin {pin.index} value must be 0 or 1")
