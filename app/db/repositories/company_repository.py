# -*- coding: utf-8 -*-
"""
@file: company_repository.py
@version: 0.1.0
@purpose: 公司维表数据访问层。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""
from app.db.repositories.base import BaseRepository
from app.models.company import CompanyItem


class CompanyRepository(BaseRepository):
    async def get_all_names(self):
        # 获取所有公司名称，用于模糊匹配初始化
        sql = "SELECT DISTINCT company_cn_name FROM com_kk_sub_company_d"
        rows = await self.execute_query(sql)
        return [row["company_cn_name"] for row in rows]

    async def list_all(self) -> list[str]:
        """IntentService 兼容入口，与 `get_all_names` 等价。"""
        return await self.get_all_names()

    async def list_company_items(self) -> list[CompanyItem]:
        """公司下拉列表：优先使用公司维表中的公司编码。"""
        sql = """
            SELECT company_code, company_cn_name, company_en_name
            FROM com_kk_sub_company_d
            ORDER BY company_code
        """
        rows = await self.execute_query(sql)
        return [
            CompanyItem(
                company_code=int(row["company_code"]),
                company_cn_name=row["company_cn_name"],
                company_en_name=row.get("company_en_name"),
            )
            for row in rows
        ]