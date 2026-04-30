# -*- coding: utf-8 -*-
"""
@file: auth.py
@version: 0.1.0
@purpose: 权限相关接口，返回当前用户角色与授权公司范围。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from fastapi import APIRouter, Query

from app.models.auth import PermissionResponse
from app.models.common import ApiResponse
from app.services.permission_service import PermissionService

router = APIRouter()
service = PermissionService()


@router.get("/permissions", response_model=ApiResponse[PermissionResponse])
async def get_permissions(user_id: str = Query(..., description="用户 ID")) -> ApiResponse[PermissionResponse]:
    data = service.get_user_permissions(user_id)
    return ApiResponse.success(data=data)
