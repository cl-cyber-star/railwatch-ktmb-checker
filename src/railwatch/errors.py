"""Application-specific exceptions."""


class RailwatchError(Exception):
    """Base exception for expected Railwatch failures."""


class ApiError(RailwatchError):
    """The Railwatch backend returned an invalid or unsuccessful response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SessionError(RailwatchError):
    """The saved KTMB browser session is invalid."""


class SessionRejectedError(SessionError):
    """KTMB rejected the supplied browser session."""


class CheckerFailure(RailwatchError):
    """One or more monitor checks failed."""
