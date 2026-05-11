from app.services.intent_service import (
    IntentService,
    QueryIR,
    _guess_company_short_names,
    _is_vague_operating_comparison_question,
)


def test_vague_operating_comparison_detection():
    assert _is_vague_operating_comparison_question(
        "对比一下华为和腾讯这两家公司的经营情况"
    )
    assert not _is_vague_operating_comparison_question("2025年华为总资产多少")
    assert not _is_vague_operating_comparison_question("对比下腾讯和阿里的净利润")


def test_guess_company_short_names_huawei_tencent():
    names = _guess_company_short_names("对比一下华为和腾讯这两家公司的经营情况")
    assert "华为" in names
    assert "腾讯" in names


def test_apply_operating_bundle_from_chitchat():
    svc = IntentService(llm_client=None, company_repo=None)
    ir = QueryIR(
        intent_type="chitchat",
        reply="请问您想了解什么",
        table=None,
        metrics=[],
        filters={},
        group_by=[],
    )
    out = svc._apply_operating_situation_comparison_bundle(
        "对比一下华为和腾讯这两家公司的经营情况", ir
    )
    assert out.intent_type == "query"
    assert out.reply is None
    assert out.table == "pl"
    assert "营业收入" in out.metrics
    assert "company" in out.group_by
    assert out.filters.get("year") == [2025]
    assert "华为" in out.filters["company"]


def test_metrics_span_multiple_tables():
    svc = IntentService(llm_client=None, company_repo=None)
    assert svc._metrics_span_multiple_tables(["revenue", "total_assets"])
    assert not svc._metrics_span_multiple_tables(["revenue", "net_profit"])
