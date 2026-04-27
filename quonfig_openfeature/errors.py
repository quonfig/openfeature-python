"""Map Quonfig SDK errors to OpenFeature ``ErrorCode`` values."""

from __future__ import annotations

from openfeature.flag_evaluation import ErrorCode
from quonfig.exceptions import (
    QuonfigInitTimeoutError,
    QuonfigKeyNotFoundError,
    QuonfigNotInitializedError,
)


def to_error_code(err: BaseException) -> ErrorCode:
    """Map a native SDK error to an OpenFeature ``ErrorCode``.

    Order matters: typed ``QuonfigError`` subclasses win over message-based
    inspection so callers don't accidentally end up with ``GENERAL`` when the
    underlying SDK raised something specific.
    """
    if isinstance(err, QuonfigKeyNotFoundError):
        return ErrorCode.FLAG_NOT_FOUND
    if isinstance(err, (QuonfigInitTimeoutError, QuonfigNotInitializedError)):
        return ErrorCode.PROVIDER_NOT_READY

    msg = (str(err) or "").lower()

    if (
        "not found" in msg
        or "flag not found" in msg
        or "no value found" in msg
        or "value found for key" in msg
    ):
        return ErrorCode.FLAG_NOT_FOUND
    if "type mismatch" in msg or isinstance(err, TypeError):
        return ErrorCode.TYPE_MISMATCH
    if "not initialized" in msg or "provider not ready" in msg:
        return ErrorCode.PROVIDER_NOT_READY

    return ErrorCode.GENERAL
