# -*- coding: utf-8 -*-
"""Dashboard render 的 runtime_filters 校验（与前端联调契约一致）。"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException


def validate_runtime_filters(filters: Any) -> None:
    """
    runtime_filters 仅允许平铺 dict，value 仅允许 int/float（非 bool）/str。
    数组、对象、None、bool 一律视为非法，由路由层转为 HTTP 422。
    """

    if filters is None or filters == {}:
        return
    if not isinstance(filters, dict):
        raise HTTPException(
            status_code=422,
            detail=_invalid_detail("runtime_filters", "object", type(filters).__name__),
        )
    for key, val in filters.items():
        field = f"runtime_filters.{key}"
        if val is None:
            raise HTTPException(
                status_code=422,
                detail=_invalid_detail(field, "number|string", "null"),
            )
        if isinstance(val, bool):
            raise HTTPException(
                status_code=422,
                detail=_invalid_detail(field, "number|string", "bool"),
            )
        if isinstance(val, (list, dict)):
            raise HTTPException(
                status_code=422,
                detail=_invalid_detail(field, "number|string", type(val).__name__),
            )
        if isinstance(val, int):
            continue
        if isinstance(val, float):
            if not val == val:  # NaN
                raise HTTPException(
                    status_code=422,
                    detail=_invalid_detail(field, "number|string", "float(nan)"),
                )
            continue
        if isinstance(val, str):
            continue
        raise HTTPException(
            status_code=422,
            detail=_invalid_detail(field, "number|string", type(val).__name__),
        )


def _invalid_detail(field: str, expected: str, actual: str) -> Dict[str, Any]:
    return {
        "code": 422,
        "message": f"DSL_INVALID: {field} must be {expected}",
        "details": [{"field": field, "expected": expected, "actual": actual}],
    }
