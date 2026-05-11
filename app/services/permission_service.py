# -*- coding: utf-8 -*-
"""
@file: permission_service.py
@version: 0.1.0
@purpose: 权限服务，负责用户角色、授权公司与公司列表提供。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

# 这个服务负责解析用户角色，并输出该用户合法的查询范围。

from typing import List, Optional, Set

from app.core.config import settings
from app.models.auth import PermissionResponse


def _dev_admin_uid_set() -> Set[str]:
    raw = (settings.DEV_ADMIN_USER_IDS or "").strip()
    if not raw:
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}


class PermissionService:
    def __init__(self):
        # 未来如果有了权限映射表，可以在这里注入数据库依赖
        pass

    def get_allowed_companies(self, user_role: str, provided_companies: List[str]) -> List[str]:
        """
        根据用户角色和前端传入的公司列表，计算最终合法的公司查询范围
        """
        # 如果是管理员，返回特殊标记 ["*"]，表示查询时不应用公司过滤 (全量)
        if user_role == "admin":
            return ["*"]

        # 如果是普通用户，返回前端传入的公司列表 (前端应校验传入的公司是否在用户所属范围内)
        # 暂时没有权限映射表，信任前端传入列表
        return provided_companies if provided_companies else []

    def check_access(self, target_company: str, allowed_companies: List[str]) -> bool:
        """
        检查特定公司是否在访问权限内
        """
        if "*" in allowed_companies:
            return True
        return target_company in allowed_companies

    def get_user_permissions(
        self, user_id: str, header_role: Optional[str] = None
    ) -> PermissionResponse:
        """
        返回用户权限摘要（MVP：基于 user_id + 请求头角色占位，后续可接 IAM/权限表）。

        管理员判定（与联调约定 X-User-Role: admin|user 对齐）：
        - 请求头 / 参数角色为 admin；或
        - user_id 为历史占位 admin / system_admin；或
        - APP_ENV=dev 且 user_id 在 DEV_ADMIN_USER_IDS（.env 逗号分隔）中。
        """
        role_norm = (header_role or "").strip().lower()
        uid = (user_id or "anonymous").strip() or "anonymous"

        if role_norm == "admin" or uid in {"admin", "system_admin"}:
            return PermissionResponse(
                user_id=uid,
                role="admin",
                authorized_companies=["*"],
                allowed=True,
            )
        if settings.APP_ENV == "dev" and uid in _dev_admin_uid_set():
            return PermissionResponse(
                user_id=uid,
                role="admin",
                authorized_companies=["*"],
                allowed=True,
            )
        return PermissionResponse(
            user_id=uid,
            role="user",
            authorized_companies=[],
            allowed=True,
        )
