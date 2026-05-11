import pytest

from app.llm.prompts import format_intent_context_hint
from app.services.intent_service import IntentService, QueryIR


def test_format_intent_context_hint_empty():
    assert format_intent_context_hint({}) == ""
    assert format_intent_context_hint(None) == ""


def test_format_intent_context_hint_nonempty():
    h = format_intent_context_hint(
        {"table": "bs", "metrics": ["total_assets"], "year": [2022, 2023]}
    )
    assert "表: bs" in h
    assert "total_assets" in h
    assert "2022" in h


class _FakeCompanyRepo:
    async def list_all(self):
        return [
            "华为技术有限公司",
            "深圳市腾讯计算机系统有限公司",
        ]


@pytest.mark.asyncio
async def test_rescue_chitchat_tencent_with_prior_context():
    svc = IntentService(llm_client=None, company_repo=_FakeCompanyRepo())
    chat = QueryIR(
        intent_type="chitchat",
        reply="请问你想了解什么",
        table=None,
        metrics=[],
        filters={},
        group_by=[],
    )
    ctx = {
        "table": "bs",
        "metrics": ["total_assets"],
        "year": [2022, 2023, 2024],
        "group_by": ["year"],
    }
    out = await svc._rescue_chitchat_to_query_if_followup("腾讯咧？", chat, ctx)
    assert out.intent_type == "query"
    assert out.table == "bs"
    assert out.metrics == ["total_assets"]
    assert out.filters.get("year") == [2022, 2023, 2024]
    assert any("腾讯" in c for c in out.filters["company"])


@pytest.mark.asyncio
async def test_rescue_keeps_chitchat_without_context_metrics():
    svc = IntentService(llm_client=None, company_repo=_FakeCompanyRepo())
    chat = QueryIR(
        intent_type="chitchat",
        reply="hi",
        table=None,
        metrics=[],
        filters={},
        group_by=[],
    )
    out = await svc._rescue_chitchat_to_query_if_followup("腾讯咧？", chat, {})
    assert out.intent_type == "chitchat"
