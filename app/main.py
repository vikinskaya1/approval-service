import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routers import approval_requests, health

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("approval-service")

app = FastAPI(title="approval-service", version="1.0.0")

app.include_router(health.router)
app.include_router(approval_requests.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.__class__.__name__, "message": str(exc.detail)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Pydantic error details never contain secrets for this service's schemas
    # (ids, titles, enums, comments/reasons only), so it's safe to surface them.
    return JSONResponse(
        status_code=422,
        content={"error": "ValidationError", "message": "invalid request body", "details": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak internals (stack traces, DB URLs, exception args that might
    # embed connection strings, etc.) into the response or logs beyond a
    # generic message + exception type.
    logger.exception("unhandled error handling request")
    return JSONResponse(
        status_code=500,
        content={"error": "InternalServerError", "message": "an unexpected error occurred"},
    )
