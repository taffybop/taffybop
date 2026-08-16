"""ASGI application entry point."""

from __future__ import annotations

import sys

from fastapi import FastAPI

from app import __version__
from app.api import router
from app.config import parser_latency_prewarm_requested
from app.errors import register_exception_handlers


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
