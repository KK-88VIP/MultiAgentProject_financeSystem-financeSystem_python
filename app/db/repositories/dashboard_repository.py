from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DashboardRepository:
    async def create(self, db: AsyncSession, dashboard_id: str, title: str, dsl: Dict[str, Any], created_by: str) -> None:
        sql = text(
            """
            INSERT INTO dashboard (id, title, dsl_json, created_by, updated_by, is_deleted)
            VALUES (:id, :title, :dsl_json, :created_by, :updated_by, 0)
            """
        )
        await db.execute(
            sql,
            {
                "id": dashboard_id,
                "title": title,
                "dsl_json": json.dumps(dsl, ensure_ascii=False),
                "created_by": created_by,
                "updated_by": created_by,
            },
        )
        await db.commit()

    async def get(self, db: AsyncSession, dashboard_id: str) -> Optional[Dict[str, Any]]:
        sql = text(
            """
            SELECT id, title, dsl_json, created_by, updated_by, is_deleted, created_at, updated_at
            FROM dashboard
            WHERE id = :id AND is_deleted = 0
            """
        )
        result = await db.execute(sql, {"id": dashboard_id})
        row = result.first()
        if not row:
            return None
        data = dict(row._mapping)
        raw_dsl = data.get("dsl_json")
        data["dsl_json"] = json.loads(raw_dsl) if isinstance(raw_dsl, str) else raw_dsl
        return data

    async def list_all(self, db: AsyncSession) -> List[Dict[str, Any]]:
        sql = text(
            """
            SELECT id, title, created_by, updated_by, created_at, updated_at
            FROM dashboard
            WHERE is_deleted = 0
            ORDER BY updated_at DESC
            """
        )
        result = await db.execute(sql)
        return [dict(r._mapping) for r in result.fetchall()]

    async def update(self, db: AsyncSession, dashboard_id: str, dsl: Dict[str, Any], updated_by: str) -> bool:
        sql = text(
            """
            UPDATE dashboard
            SET title = :title, dsl_json = :dsl_json, updated_by = :updated_by
            WHERE id = :id AND is_deleted = 0
            """
        )
        title = str(dsl.get("title") or "")
        result = await db.execute(
            sql,
            {
                "id": dashboard_id,
                "title": title,
                "dsl_json": json.dumps(dsl, ensure_ascii=False),
                "updated_by": updated_by,
            },
        )
        await db.commit()
        return result.rowcount > 0

    async def soft_delete(self, db: AsyncSession, dashboard_id: str, updated_by: str) -> bool:
        sql = text(
            """
            UPDATE dashboard
            SET is_deleted = 1, updated_by = :updated_by
            WHERE id = :id AND is_deleted = 0
            """
        )
        result = await db.execute(sql, {"id": dashboard_id, "updated_by": updated_by})
        await db.commit()
        return result.rowcount > 0

