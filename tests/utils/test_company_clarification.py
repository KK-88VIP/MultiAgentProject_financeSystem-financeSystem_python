import pytest

from app.services.intent_service import IntentService, QueryIR


class _RepoHuaweiTencent:
    async def list_all(self):
        return [
            "华为技术有限公司",
            "深圳市腾讯计算机系统有限公司",
        ]


class _RepoTwoHuawei:
    async def list_all(self):
        return [
            "华为技术有限公司",
            "华为投资控股有限公司",
        ]


@pytest.mark.asyncio
async def test_multi_company_comparison_not_clarification():
    svc = IntentService(llm_client=None, company_repo=_RepoHuaweiTencent())
    ir = QueryIR(
        intent_type="query",
        filters={"company": ["华为", "腾讯"]},
        group_by=["company"],
    )
    out = await svc.normalize_companies(ir)
    assert len(out.filters["company"]) == 2
    assert out.company_resolution_ambiguous is False
    assert svc.detect_ambiguity(out) is None


@pytest.mark.asyncio
async def test_single_slot_multiple_matches_is_clarification():
    svc = IntentService(llm_client=None, company_repo=_RepoTwoHuawei())
    ir = QueryIR(
        intent_type="query",
        filters={"company": ["华为"]},
        group_by=["company"],
    )
    out = await svc.normalize_companies(ir)
    assert out.company_resolution_ambiguous is True
    opts = svc.detect_ambiguity(out)
    assert opts is not None
    assert len(opts) >= 2
