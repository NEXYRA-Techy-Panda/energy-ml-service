"""FastAPI application: GET /health and GET /v1/model/info only (contract 1.0.1).

No model is trained or loaded at F2, so the service reports itself healthy
with model_available=false and never fabricates a model version or a
prediction. /v1/analyze and /v1/forecast are deliberately not implemented.
"""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import CONTRACT_VERSION

# Private service called only by auditor-backend: interactive docs and the
# OpenAPI route are disabled so only the contract routes exist.
app = FastAPI(title="energy-ml-service", docs_url=None, redoc_url=None, openapi_url=None)

# No model is loaded at the scaffold stage.
MODEL_AVAILABLE = False


def envelope(request: Request, data: object) -> dict:
    """Contract success envelope: { data, meta: { request_id } }."""
    return {"data": data, "meta": {"request_id": request.state.request_id}}


def error_response(status: int, code: str, message: str) -> JSONResponse:
    """Contract error envelope: { error: { code, message } }."""
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(404, "NOT_FOUND", f"No route for {request.method} {request.url.path}")
    if exc.status_code == 413:
        return error_response(413, "REQUEST_TOO_LARGE", "Request body exceeds the allowed size")
    if 400 <= exc.status_code < 500:
        return error_response(exc.status_code, "VALIDATION_ERROR", str(exc.detail))
    return error_response(exc.status_code, "INTERNAL_ERROR", "Internal server error")


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return error_response(400, "VALIDATION_ERROR", "Request failed validation")


@app.exception_handler(Exception)
async def unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
    return error_response(500, "INTERNAL_ERROR", "Internal server error")


@app.get("/health")
async def health(request: Request) -> dict:
    return envelope(request, {"status": "ok", "model_available": MODEL_AVAILABLE})


@app.get("/v1/model/info")
async def model_info(request: Request) -> dict:
    # Uninitialised shape (contract leaves it unspecified): versions are null
    # rather than invented, and model_available makes the state explicit.
    return envelope(
        request,
        {
            "model_available": MODEL_AVAILABLE,
            "model_version": None,
            "baseline_version": None,
            "contract_version": CONTRACT_VERSION,
        },
    )
