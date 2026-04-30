# 定义异步 FastAPI 客户端，用于模拟 HTTP 请求。

import os

# 保证导入 `main` 前 pydantic-settings 能通过必填项校验（本地若无 .env 亦可跑测试）
os.environ.setdefault("DATABASE_URL", "mysql+aiomysql://user:pass@127.0.0.1:3306/test_db")
os.environ.setdefault("LLM_API_KEY", "test-dummy-key")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def ac():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
