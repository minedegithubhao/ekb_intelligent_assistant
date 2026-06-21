"""Project-specific exceptions mapped to unified API error responses."""

from __future__ import annotations


class AppException(Exception):
    """Base exception rendered by the global FastAPI exception handler."""

    def __init__(self, message: str, code: int = 40000, status_code: int = 400) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class BadRequestException(AppException):
    def __init__(self, message: str = "bad request", code: int = 40000) -> None:
        super().__init__(message=message, code=code, status_code=400)


class AuthException(AppException):
    def __init__(self, message: str = "unauthorized", code: int = 40100) -> None:
        super().__init__(message=message, code=code, status_code=401)


class PermissionDeniedException(AppException):
    def __init__(self, message: str = "permission denied", code: int = 40300) -> None:
        super().__init__(message=message, code=code, status_code=403)


class NotFoundException(AppException):
    def __init__(self, message: str = "not found", code: int = 40400) -> None:
        super().__init__(message=message, code=code, status_code=404)


class ConfigException(AppException):
    def __init__(self, message: str = "invalid config", code: int = 50010) -> None:
        super().__init__(message=message, code=code, status_code=500)


class ServiceUnavailableException(AppException):
    def __init__(self, message: str = "service unavailable", code: int = 50300) -> None:
        super().__init__(message=message, code=code, status_code=503)
