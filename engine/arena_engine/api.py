"""The implemented v1 first-match API, shared by dashboard and Switch client."""

from contextlib import asynccontextmanager
import json
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

from .contract import load_contract
from .errors import ArenaError
from .models import Action, CreateMatch, Submit, ChallengeRequest, ChallengeDecision, ReviewComplete, Selection
from .runtime import Settings
from .service import Engine
from .workspaces import WorkspaceError


def create_app(settings=None, runner=None, start_worker=True) -> FastAPI:
    settings = settings or Settings.from_env()
    contract = load_contract()
    try:
        engine = Engine(settings, runner, exclusive=start_worker)
    except WorkspaceError:
        engine = None

    @asynccontextmanager
    async def lifespan(_app):
        if engine and start_worker:
            engine.start()
        try:
            yield
        finally:
            if engine:
                engine.stop()

    app = FastAPI(title="Coding Arena", version=contract["contract_version"], lifespan=lifespan)
    app.state.engine = engine

    if settings.ui_origin:
        app.add_middleware(CORSMiddleware, allow_origins=[settings.ui_origin],
                           allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
                           expose_headers=["X-Arena-Mode", "Content-Disposition"])

    @app.middleware("http")
    async def response_mode(request: Request, call_next):
        class DuplicateField(ValueError):
            pass

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise DuplicateField()
                result[key] = value
            return result

        try:
            if request.method == "POST" and "application/json" in request.headers.get("content-type", ""):
                try:
                    json.loads(await request.body(), object_pairs_hook=unique_object)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass  # The framework returns the normal malformed-input envelope.
            response = await call_next(request)
        except DuplicateField:
            response = JSONResponse(status_code=422, content={"error": {"code": "INVALID_INPUT",
                "message": "Duplicate JSON object fields are not allowed", "details": {}}})
        except Exception:
            response = JSONResponse(status_code=503, content={"error": {"code": "INVALID_STATE",
                "message": "Engine operation failed; retry the same request ID after recovery", "details": {}}})
        if settings.ui_origin and request.headers.get("origin") == settings.ui_origin:
            response.headers["Access-Control-Allow-Origin"] = settings.ui_origin
            response.headers["Access-Control-Expose-Headers"] = "X-Arena-Mode, Content-Disposition"
        if request.url.path == "/api/v1" or request.url.path.startswith("/api/v1/"):
            response.headers["X-Arena-Mode"] = "live"
        return response

    @app.exception_handler(ArenaError)
    async def arena_error(_request: Request, exc: ArenaError):
        return JSONResponse(status_code=exc.status, content=exc.payload())

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        code = "NOT_FOUND" if exc.status_code == 404 else "INVALID_INPUT"
        return JSONResponse(status_code=exc.status_code, content={
            "error": {"code": code, "message": str(exc.detail), "details": {}},
        })

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        status = 400 if any(error["type"] == "json_invalid" for error in exc.errors()) else 422
        return JSONResponse(status_code=status, content={"error": {"code": "INVALID_INPUT",
            "message": "Request does not match the v1 interface", "details": {
                "fields": [".".join(str(part) for part in error["loc"]) for error in exc.errors()]}}})

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, _exc: Exception):
        return JSONResponse(status_code=503, content={"error": {"code": "INVALID_STATE",
            "message": "Engine operation failed; retry the same request ID after recovery", "details": {}}})

    def actor(authorization: Annotated[str | None, Header()] = None):
        if engine is None:
            raise ArenaError("INVALID_STATE", "Initialize the engine state directory before using match endpoints", 503)
        return engine.authenticate(authorization)

    Actor = Annotated[str, Depends(actor)]

    @app.get("/api/v1/health")
    def health():
        return {"api_version": contract["contract_version"], "mode": "live", "runner_available": bool(
            engine and not engine.worker_failed and engine.runner.available()), "status": "ok"}

    @app.post("/api/v1/matches")
    def create(body: CreateMatch, who: Actor):
        result, status = engine.create(who, body.model_dump(mode="json"))
        return JSONResponse(result, status_code=status)

    @app.get("/api/v1/matches/{match_id}")
    def match(match_id: str, who: Actor):
        return engine.get_match(who, match_id)

    @app.get("/api/v1/matches/{match_id}/assignments/{slot}")
    def assignment(match_id: str, slot: str, who: Actor):
        return engine.assignment(who, match_id, slot)

    @app.post("/api/v1/matches/{match_id}/submissions")
    def submit(match_id: str, body: Submit, who: Actor):
        result, status = engine.submit(who, match_id, body.model_dump(mode="json"))
        return JSONResponse(result, status_code=status)

    @app.post("/api/v1/matches/{match_id}/practice")
    def practice(match_id: str, body: Submit, who: Actor):
        result, status = engine.submit(who, match_id, body.model_dump(mode="json"), practice=True)
        return JSONResponse(result, status_code=status)

    @app.get("/api/v1/matches/{match_id}/events")
    def events(match_id: str, who: Actor, after: Annotated[int, Query(ge=0)] = 0):
        return engine.events(who, match_id, after)

    @app.post("/api/v1/matches/{match_id}/actions")
    def action(match_id: str, body: Action, who: Actor):
        result, status = engine.action(who, match_id, body.model_dump(mode="json"))
        return JSONResponse(result, status_code=status)

    @app.get("/api/v1/jobs/{job_id}")
    def job(job_id: str, who: Actor):
        return engine.get_job(who, job_id)

    @app.post("/api/v1/matches/{match_id}/challenges")
    def challenge(match_id: str, body: ChallengeRequest, who: Actor):
        result, status = engine.challenge(who, match_id, body.model_dump(mode="json"))
        return JSONResponse(result, status_code=status)

    @app.post("/api/v1/matches/{match_id}/reviews/{slot}/complete")
    def review_complete(match_id: str, slot: str, body: ReviewComplete, who: Actor):
        result, status = engine.review_complete(who, match_id, slot, body.model_dump(mode="json"))
        return JSONResponse(result, status_code=status)

    @app.post("/api/v1/matches/{match_id}/challenges/{challenge_id}/decision")
    def decision(match_id: str, challenge_id: str, body: ChallengeDecision, who: Actor):
        result, status = engine.adjudicate(who, match_id, challenge_id, body.model_dump(mode="json"))
        return JSONResponse(result, status_code=status)

    @app.post("/api/v1/matches/{match_id}/selection")
    def selection(match_id: str, body: Selection, who: Actor):
        result, status = engine.select(who, match_id, body.model_dump(mode="json"))
        return JSONResponse(result, status_code=status)

    @app.get("/api/v1/artifacts/{artifact_id}")
    def artifact(artifact_id: str, who: Actor):
        contents, filename, content_type = engine.artifact(who, artifact_id)
        return Response(contents, media_type=content_type, headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff"})

    return app
