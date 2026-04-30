# -*- coding: utf-8 -*-
"""
@file: exceptions.py
@version: 0.1.0
@purpose: 自定义异常与全局异常处理注册。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger("app")

def setup_exception_handlers(app):
    def _ctx(request: Request) -> dict:
        request_id = getattr(request.state, "request_id", None)
        trace_id = getattr(request.state, "trace_id", request_id)
        return {"request_id": request_id, "trace_id": trace_id}

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        ctx = _ctx(request)
        if isinstance(exc.detail, dict):
            payload = {**ctx, **exc.detail}
            payload.setdefault("code", exc.status_code)
            payload.setdefault("message", "请求失败")
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                payload["message"] = "未登录或鉴权失败"
            elif exc.status_code == status.HTTP_403_FORBIDDEN:
                payload.setdefault("message", "无权限访问该资源")
                payload.setdefault("error_code", "PERMISSION_DENIED")
            return JSONResponse(status_code=exc.status_code, content=payload)

        payload = {
            "code": exc.status_code,
            "message": exc.detail if isinstance(exc.detail, str) else "请求失败",
            **ctx,
        }
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            payload["message"] = "未登录或鉴权失败"
        elif exc.status_code == status.HTTP_403_FORBIDDEN:
            payload["message"] = "无权限访问该资源"
            payload["error_code"] = "PERMISSION_DENIED"
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # 记录详细日志到 error.log
        logger.error(f"Global Error: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"code": 500, "message": "系统内部错误，请联系IT负责人KK", **_ctx(request)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": 422,
                "message": "请求参数校验失败",
                "details": exc.errors(),
                **_ctx(request),
            },
        )
