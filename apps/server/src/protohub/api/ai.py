"""Authenticated real-model generation; no Kubernetes or executable-code interface."""

from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from protohub.ai.gemini import GeminiGenerator, GeneratedPlan
from protohub.domain.http_contract import route
from protohub.domain.models import (
    AiApplicationList,
    AiConfirmRequest,
    AiCreateRequest,
    AiReviseRequest,
    LogoutResult,
)
from protohub.domain.settings import Settings
from protohub.persistence.ai import (
    AiGenerationFailed,
    AiQuotaExceeded,
    AiRepository,
    Reservation,
)


def failure(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": str(getattr(request.state, "request_id", uuid4())),
            }
        },
    )


def install_ai_routes(
    application: FastAPI,
    config: Settings,
    factory: sessionmaker[Session],
) -> None:
    repository = AiRepository(factory, config)
    application.state.ai_repository = repository
    application.state.ai_generator = GeminiGenerator(config)

    def enabled(request: Request) -> JSONResponse | None:
        if not config.ai_ready:
            return failure(request, 503, "ai_unavailable", "Gemini is not configured")
        return None

    def generate(request: Request, reservation: Reservation):
        if reservation.cached is not None:
            return reservation.cached
        try:
            generated = application.state.ai_generator.generate(
                reservation.brief,
                reservation.config,
                reservation.instruction,
            )
            generated = GeneratedPlan.model_validate(generated)
            if generated.config.template != reservation.config.template:
                raise ValueError("Provider changed the selected template")
        except Exception:
            repository.fail(reservation)
            return failure(
                request,
                503,
                "ai_generation_failed",
                "Gemini could not create a screen plan. Your saved plan has not changed.",
            )
        return repository.complete(reservation, generated)

    @route(application, "ai_list")
    def list_apps(request: Request):
        return enabled(request) or AiApplicationList(
            items=repository.list(request.state.principal.email)
        )

    @route(application, "ai_get")
    def get_app(application_id: UUID, request: Request):
        return enabled(request) or repository.get(application_id, request.state.principal.email)

    @route(application, "ai_create")
    def create_app(payload: AiCreateRequest, request: Request):
        if response := enabled(request):
            return response
        try:
            reservation = repository.reserve(request.state.principal.email, payload)
        except AiQuotaExceeded:
            return failure(request, 429, "ai_quota_exceeded", "Gemini request limit reached")
        except AiGenerationFailed:
            return failure(
                request,
                503,
                "ai_generation_failed",
                "This generation failed. Review the input and start a new request.",
            )
        return generate(request, reservation)

    @route(application, "ai_revise")
    def revise_app(application_id: UUID, payload: AiReviseRequest, request: Request):
        if response := enabled(request):
            return response
        try:
            reservation = repository.reserve(
                request.state.principal.email,
                payload,
                application_id,
            )
        except AiQuotaExceeded:
            return failure(request, 429, "ai_quota_exceeded", "Gemini request limit reached")
        except AiGenerationFailed:
            return failure(
                request,
                503,
                "ai_generation_failed",
                "This generation failed. Review the input and start a new request.",
            )
        return generate(request, reservation)

    @route(application, "ai_confirm")
    def confirm_app(application_id: UUID, payload: AiConfirmRequest, request: Request):
        return enabled(request) or repository.confirm(
            application_id,
            request.state.principal.email,
            payload.expected_revision,
        )

    @route(application, "ai_delete")
    def delete_app(application_id: UUID, request: Request):
        if response := enabled(request):
            return response
        repository.delete(application_id, request.state.principal.email)
        return LogoutResult()
