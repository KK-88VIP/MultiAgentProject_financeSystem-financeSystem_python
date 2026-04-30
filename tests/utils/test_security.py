# 这是最重要的一环，确保`PermissionInjector`真的把公司权限塞进去了。


import pytest
from app.security.permission_injector import PermissionInjector


def test_permission_injector():
    injector = PermissionInjector()

    # 测试 1: 无 WHERE 条件的场景
    sql = "SELECT * FROM com_kk_sub_bs_t"
    result = injector.inject_company_filter(sql, ["华为"])
    assert "WHERE" in result
    assert "company_cn_name IN ('华为')" in result

    # 测试 2: 已有 WHERE 条件的场景 (确保 AND 拼接)
    sql = "SELECT * FROM com_kk_sub_bs_t WHERE period_id = '2025'"
    result = injector.inject_company_filter(sql, ["腾讯"])
    assert "AND" in result
    assert "company_cn_name IN ('腾讯')" in result