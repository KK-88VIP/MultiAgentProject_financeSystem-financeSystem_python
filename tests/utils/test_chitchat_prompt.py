from app.llm.prompts import (
    CHITCHAT_PROMPT,
    format_chitchat_context_block,
    format_company_catalog_for_chitchat,
    question_asks_company_catalog,
    scoped_company_names,
)


def test_format_chitchat_context_block_empty():
    assert format_chitchat_context_block({}) == ""
    assert format_chitchat_context_block(None) == ""


def test_format_chitchat_context_block_nonempty():
    s = format_chitchat_context_block(
        {"table": "pl", "metrics": ["revenue"], "year": [2025]}
    )
    assert "pl" in s
    assert "revenue" in s


def test_scoped_company_names_star():
    s = scoped_company_names(["A公司", "B公司"], ["*"])
    assert s == ["A公司", "B公司"]


def test_scoped_company_names_user_filter():
    s = scoped_company_names(
        ["华为技术有限公司", "深圳市腾讯计算机系统有限公司"],
        ["华为技术有限公司"],
    )
    assert s == ["华为技术有限公司"]


def test_question_asks_company_catalog():
    assert question_asks_company_catalog("我现在能查哪些公司的数据？")
    assert question_asks_company_catalog("支持哪些公司？")
    assert not question_asks_company_catalog("华为2025年营收多少")


def test_format_company_catalog_admin_scope():
    text = format_company_catalog_for_chitchat(
        ["华为技术有限公司", "深圳市腾讯计算机系统有限公司"],
        ["*"],
    )
    assert "华为技术有限公司" in text
    assert "共 2 家" in text


def test_format_company_catalog_user_scope():
    text = format_company_catalog_for_chitchat(
        ["华为技术有限公司", "深圳市腾讯计算机系统有限公司"],
        ["华为技术有限公司"],
    )
    assert "华为技术有限公司" in text
    assert "腾讯" not in text


def test_chitchat_prompt_format():
    text = CHITCHAT_PROMPT.format(
        boundary_text="仅支持三表指标问数。",
        context_block="（无）",
        question="你好呀",
    )
    assert "你好呀" in text
    assert "财务数据智能助手" in text
    assert "仅支持三表指标问数" in text
