# -*- coding: utf-8 -*-
"""
@file: request_context.py
@purpose: 请求级上下文，保存 request_id / trace_id。
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


def set_request_context(request_id: str, trace_id: str | None = None) -> tuple[Token, Token]:
    trace_val = trace_id or request_id
    return _request_id_var.set(request_id), _trace_id_var.set(trace_val)


def reset_request_context(tokens: tuple[Token, Token]) -> None:
    request_token, trace_token = tokens
    _request_id_var.reset(request_token)
    _trace_id_var.reset(trace_token)


def get_request_id() -> str | None:
    return _request_id_var.get()


def get_trace_id() -> str | None:
    return _trace_id_var.get()
