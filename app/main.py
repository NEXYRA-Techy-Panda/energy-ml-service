"""FastAPI application (contract 1.0.1): GET /health, GET /v1/model/info,
POST /v1/analyze and POST /v1/forecast.

No model is trained or loaded, so the service reports model_available=false
and model_version=null. POST /v1/analyze is a deterministic rule (method
"rule") and POST /v1/forecast a statistical profile baseline (method
"statistical_baseline", baseline_version reported); neither needs a trained
model, so neither returns MODEL_UNAVAILABLE merely because none exists.
"""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .analysis.service import analyze
from .anomalies.service import run_anomalies
from .config import CONTRACT_VERSION
from .forecast.constants import BASELINE_VERSION
from .forecast.service import run_forecast
from .errors import ApiError

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


@app.exception_handler(ApiError)
async def api_error(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.body())


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
            # Statistical forecasting baseline (not a trained model); see /v1/forecast.
            "baseline_version": BASELINE_VERSION,
            "contract_version": CONTRACT_VERSION,
        },
    )


@app.post("/v1/analyze")
async def analyze_route(request: Request) -> dict:
    # Inline bounded data only (API.md Example A): no database, files or callbacks.
    return envelope(request, analyze(await request.body()))


@app.post("/v1/forecast")
async def forecast_route(request: Request) -> dict:
    # Inline hourly history + calendar (API.md Example B); statistical baseline, no model.
    return envelope(request, run_forecast(await request.body()))


@app.post("/v1/anomalies")
async def anomalies_route(request: Request) -> dict:
    # Additive P022 extension: excess-consumption deviation vs earlier comparable reference (statistical; no model).
    return envelope(request, run_anomalies(await request.body()))
