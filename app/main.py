"""ASGI application entry point."""

from __future__ import annotations

import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import router
from app.config import (
    parser_cors_origins,
    parser_latency_prewarm_requested,
    parser_public_resource_limits,
)
from app.errors import register_exception_handlers
from app.request_limits import ParserRequestLimitsMiddleware
from app.ui import register_public_routes


def create_app() -> FastAPI:
    from app.services.artifact_manifest import (
        release_artifact_verification_requested,
        verify_configured_startup_manifest,
    )

    artifact_verification = None
    settings_dependency = None
    if release_artifact_verification_requested():
        # The release gate is explicitly selected by a manifest path plus its
        # externally pinned digest.  Default startup keeps the predecessor's
        # lazy configuration behavior and does not enumerate artifacts.
        from app.config import Settings, get_settings

        settings_dependency = get_settings
        artifact_verification = verify_configured_startup_manifest(
            Settings.from_env()
        )
    application_options = {
        "title": "Document Parse API",
        "description": (
            "Extract PDF, PNG, JPEG, TIFF, WebP, and explicitly enabled "
            "DOCX, PPTX, or XLSX content into structured JSON, Markdown, "
            "or plain text. Office adapters are disabled by default."
        ),
        "version": __version__,
    }
    prewarm_requested = parser_latency_prewarm_requested()
    broker_module = sys.modules.get("app.services.tesseract_broker_client")
    active_client = None
    if broker_module is not None:
        resolver = getattr(broker_module, "active_tesseract_broker_client", None)
        if callable(resolver):
            active_client = resolver()
    if prewarm_requested:
        from app.services.parser_worker import parser_worker_lifespan

        application_options["lifespan"] = parser_worker_lifespan
    else:
        # Do not import broker code on the public rollback path.  A private
        # instrumented predecessor exists only when the pre-import supervisor
        # has already installed and validated its singleton capability.
        if active_client is not None:
            from app.services.parser_worker import instrumented_lazy_parser_lifespan

            application_options["lifespan"] = instrumented_lazy_parser_lifespan
    application = FastAPI(
        **application_options,
    )
    register_exception_handlers(application)
    application.include_router(router)
    register_public_routes(application)
    max_body_bytes, max_concurrent, upload_timeout = parser_public_resource_limits()
    application.add_middleware(
        ParserRequestLimitsMiddleware,
        max_request_body_bytes=max_body_bytes,
        max_concurrent_parse_requests=max_concurrent,
        upload_timeout_seconds=upload_timeout,
    )
    # Keep CORS outside request limits so admitted origins can read 413/429.
    cors_origins = parser_cors_origins()
    if cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["POST"],
            allow_headers=["Accept", "Content-Type"],
            allow_credentials=False,
            max_age=600,
        )
    if artifact_verification is not None and settings_dependency is not None:
        effective_settings = artifact_verification.effective_settings
        application.dependency_overrides[settings_dependency] = (
            lambda: effective_settings
        )
        application.state.release_artifact_verification = (
            artifact_verification.verification
        )
        application.state.release_artifact_profile_id = (
            artifact_verification.profile_id
        )
    if prewarm_requested or active_client is not None:
        from app.services.parser_worker import BrokerRequestBoundaryMiddleware

        application.add_middleware(BrokerRequestBoundaryMiddleware)
    return application


app = create_app()
