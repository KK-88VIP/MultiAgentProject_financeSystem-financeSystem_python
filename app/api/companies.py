# -*- coding: utf-8 -*-
"""
@file: companies.py
@version: 0.2.0
@purpose: 公司列表接口，供前端筛选器加载公司维表数据。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.company_repository import CompanyRepository
from app.db.session import get_db
from app.models.common import ApiResponse
from app.models.company import CompanyItem

router = APIRouter()


@router.get("", response_model=ApiResponse[list[CompanyItem]])
async def list_companies(db: AsyncSession = Depends(get_db)) -> ApiResponse[list[CompanyItem]]:
    repo = CompanyRepository(db)
    data = await repo.list_company_items()
    return ApiResponse.success(data=data)
