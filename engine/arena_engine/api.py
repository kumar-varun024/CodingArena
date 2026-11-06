"""Sprint 1 HTTP foundation. Match operations arrive in Sprint 2."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .contract import load_contract


def create_app() -> FastAPI:
    contract = load_contract()
    app = FastAPI(title="Coding Arena", version=contract["contract_version"])

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        code = "NOT_FOUND" if exc.status_code == 404 else "INVALID_INPUT"
        return JSONResponse(status_code=exc.status_code, content={
            "error": {"code": code, "message": str(exc.detail), "details": {}},
        })

    @app.get("/api/v1/health")
    def health():
        # No production job executor yet. Doctor reports image readiness separately.
        return {"api_version": "1.0", "mode": "live", "runner_available": False,
                "status": "ok"}

    return app
