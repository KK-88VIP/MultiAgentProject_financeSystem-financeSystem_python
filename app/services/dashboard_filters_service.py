# -*- coding: utf-8 -*-
"""看板筛选器统一接口：公司列表 + 可选年份（按权限过滤）。"""

from __future__ import annotations

from typing import List

from app.db.repositories.company_repository import CompanyRepository
from app.models.company import CompanyItem
from app.services.permission_service import PermissionService
from app.utils.period_year import parse_period_to_calendar_year
from app.core.logger import get_logger

logger = get_logger(__name__)


class DashboardFiltersService:
    def __init__(self):
        self._permission = PermissionService()

    async def get_filters(self, db, user_id: str | None) -> dict:
        """
        返回 { companies: CompanyItem[], years: int[] }。
        years 为去重后的四位公历年份，按降序排列。
        无公司权限时 companies 为空；years 仍返回库中可见年份（降序），由产品决定是否再收紧。
        """
        uid = (user_id or "anonymous").strip() or "anonymous"
        perm = self._permission.get_user_permissions(uid)

        repo = CompanyRepository(db)
        all_items: List[CompanyItem] = await repo.list_company_items()

        if perm.role == "admin" or "*" in (perm.authorized_companies or []):
            companies = all_items
        else:
            allowed = {str(c) for c in (perm.authorized_companies or []) if c and c != "*"}
            if not allowed:
                companies = []
            else:
                companies = [c for c in all_items if str(c.company_code) in allowed]

        # 与前端约定：无可用公司时不返回年份，避免 companies=[] 但 years 有值导致状态机歧义
        if not companies:
            return {"companies": [], "years": []}

        years = await self._load_distinct_years(repo)
        return {"companies": [c.model_dump() for c in companies], "years": years}

    async def _load_distinct_years(self, repo: CompanyRepository) -> list[int]:
        sql = """
            SELECT DISTINCT period_id FROM (
                SELECT period_id FROM com_kk_sub_pl_risk_ident_t
                UNION
                SELECT period_id FROM com_kk_sub_bs_risk_ident_t
                UNION
                SELECT period_id FROM com_kk_sub_cf_risk_ident_t
            ) u
            WHERE period_id IS NOT NULL AND CAST(period_id AS CHAR) <> ''
        """
        try:
            rows = await repo.execute_query(sql)
        except Exception as e:
            logger.warning("[DashboardFilters] distinct years query failed: %s", e)
            return []

        seen: set[int] = set()
        for row in rows:
            raw = row.get("period_id")
            y = parse_period_to_calendar_year(raw)
            if y is not None:
                seen.add(y)
            else:
                logger.debug("[DashboardFilters] skip unparseable period_id=%r", raw)

        return sorted(seen, reverse=True)
