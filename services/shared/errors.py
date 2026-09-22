"""Error types that cross service boundaries.

An upstream failure must not surface to the user as a bare 500 — each service
translates these into a status code that says whose fault it was.
"""

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

log = structlog.get_logger(__name__)


class ServiceError(Exception):
    """Base for anything a service raises deliberately."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UpstreamError(ServiceError):
    """A dependency (another service, or a model provider) failed."""

    status_code = status.HTTP_502_BAD_GATEWAY


class ProviderNotConfigured(ServiceError):
    """An API key is missing. A 503 with a clear message beats a confusing 500."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class NotFoundError(ServiceError):
    status_code = status.HTTP_404_NOT_FOUND


class ValidationError(ServiceError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class RateLimited(ServiceError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


def install_error_handlers(app: FastAPI, service_name: str) -> None:
    @app.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", service=service_name, path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )
