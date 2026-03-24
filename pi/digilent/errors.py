"""Digilent extension error classes and codes."""


class DigilentError(Exception):
    """Base class for all Digilent errors."""

    code: str = "DIGILENT_INTERNAL_ERROR"

    def __init__(self, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class DigilentNotFoundError(DigilentError):
    code = "DIGILENT_NOT_FOUND"


class DigilentBusyError(DigilentError):
    code = "DIGILENT_BUSY"


class DigilentConfigInvalidError(DigilentError):
    code = "DIGILENT_CONFIG_INVALID"


class DigilentCaptureTimeoutError(DigilentError):
    code = "DIGILENT_CAPTURE_TIMEOUT"


class DigilentTriggerTimeoutError(DigilentError):
    code = "DIGILENT_TRIGGER_TIMEOUT"


class DigilentRangeViolationError(DigilentError):
    code = "DIGILENT_RANGE_VIOLATION"


class DigilentTransportError(DigilentError):
    code = "DIGILENT_TRANSPORT_ERROR"


class DigilentInternalError(DigilentError):
    code = "DIGILENT_INTERNAL_ERROR"


class DigilentNotEnabledError(DigilentError):
    code = "DIGILENT_NOT_ENABLED"
