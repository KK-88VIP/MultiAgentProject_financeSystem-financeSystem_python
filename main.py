# -*- coding: utf-8 -*-
"""
@file: main.py
@version: 0.1.0
@purpose: FastAPI 应用入口，负责应用初始化、路由注册与基础健康检查。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, claw_callback, companies, dashboard, dashboard_v2, feishu_callback, query
from app.core.config import settings
from app.core.exceptions import setup_exception_handlers
from app.core.request_context import reset_request_context, set_request_context
from app.models.common import ApiResponse


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_HOSTS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["X-User-Id", "X-User-Role", "Content-Type", "Authorization"],
        expose_headers=["X-Request-Id", "X-Trace-Id"],
    )

    @app.middleware("http")
    async def inject_request_context(request: Request, call_next):
        request_id = str(uuid.uuid4())
        trace_id = request_id
        tokens = set_request_context(request_id=request_id, trace_id=trace_id)
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            reset_request_context(tokens)

    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
    app.include_router(dashboard_v2.router, prefix="/api/dashboard", tags=["DashboardV2"])
    app.include_router(query.router, prefix="/api/query", tags=["Query"])
    app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
    app.include_router(companies.router, prefix="/api/companies", tags=["Companies"])
    app.include_router(feishu_callback.router, prefix="/api/feishu", tags=["Feishu"])
    app.include_router(claw_callback.router, prefix="/api/claw", tags=["Claw"])

    setup_exception_handlers(app)

    @app.get("/health", response_model=ApiResponse[dict])
    async def health_check() -> ApiResponse[dict]:
        return ApiResponse.success(data={"status": "ok"})

    return app


app = create_app()
