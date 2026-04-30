# -*- coding: utf-8 -*-
"""
@file: test_query.py
@version: 0.2.0
@purpose: 健康检查与问数接口基础测试。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy
"""

import pytest


@pytest.mark.asyncio
async def test_health_check(ac):
    """测试系统是否存活"""
    response = await ac.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body.get("code") == 200
    assert body.get("data", {}).get("status") == "ok"


@pytest.mark.asyncio
async def test_ask_endpoint_streams(ac):
    """问数接口返回 SSE 流（200 + text/event-stream）。"""
    response = await ac.post(
        "/api/query/ask",
        json={"question": "测试问题", "clarification": {}},
    )
    assert response.status_code == 200
    assert "text/event-stream" in (response.headers.get("content-type") or "")
