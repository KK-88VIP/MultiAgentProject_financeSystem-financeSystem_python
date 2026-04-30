from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

from app.db.query_executor import QueryExecutor
from app.security.sql_guard import SQLGuard
from cache.query_cache import QueryCache
from planner.query_planner import QueryPlanner
from planner.sql_generator import SQLGenerator


class DatasetService:
    def __init__(self):
        self.planner = QueryPlanner()
        self.generator = SQLGenerator()
        self.sql_guard = SQLGuard()
        self.executor = QueryExecutor()
        self.cache = QueryCache()

    async def query(self, dataset: Dict[str, Any], db, scope: Dict[str, Any]) -> Dict[str, Any]:
        ir = SimpleNamespace(
            metrics=dataset.get("metrics") or [],
            group_by=(dataset.get("dimensions") or dataset.get("group_by") or []),
            dimensions=(dataset.get("dimensions") or dataset.get("group_by") or []),
            filters=dataset.get("filters") or {},
            order_by=dataset.get("order_by") or [],
            limit=dataset.get("limit") or 100,
        )

        plan = self.planner.plan(ir).model_dump()
        cached = self.cache.get(plan, scope)
        if cached is not None:
            return {"rows": cached, "cache": True, "plan": plan}

        sql = self.generator.generate(plan)
        safe_sql = self.sql_guard.validate(sql)
        rows = await self.executor.execute(db, safe_sql)
        self.cache.set(plan, rows, scope, ttl=300)
        return {"rows": rows, "cache": False, "plan": plan}

