from __future__ import annotations

from fastapi import HTTPException

from app.db.repositories.dashboard_repository import DashboardRepository
from app.dsl.validator import DSLValidator
from app.models.dashboard_dsl import DashboardDSL
from app.services.chart_service import ChartService
from app.services.dataset_service import DatasetService


class DashboardDSLService:
    def __init__(self):
        self.validator = DSLValidator()
        self.repo = DashboardRepository()
        self.dataset_service = DatasetService()
        self.chart_service = ChartService()

    async def create(self, db, dsl: DashboardDSL, created_by: str):
        self._validate_or_raise(dsl)
        await self.repo.create(db, dsl.id, dsl.title, dsl.model_dump(), created_by)

    async def get(self, db, dashboard_id: str):
        row = await self.repo.get(db, dashboard_id)
        if not row:
            raise HTTPException(status_code=404, detail="dashboard not found")
        return row

    async def list_all(self, db):
        return await self.repo.list_all(db)

    async def update(self, db, dashboard_id: str, dsl: DashboardDSL, updated_by: str):
        self._validate_or_raise(dsl)
        ok = await self.repo.update(db, dashboard_id, dsl.model_dump(), updated_by)
        if not ok:
            raise HTTPException(status_code=404, detail="dashboard not found")

    async def delete(self, db, dashboard_id: str, updated_by: str):
        ok = await self.repo.soft_delete(db, dashboard_id, updated_by)
        if not ok:
            raise HTTPException(status_code=404, detail="dashboard not found")

    async def render(self, db, dsl: DashboardDSL, scope: dict):
        self._validate_or_raise(dsl)
        global_filters = {f.name: f.default for f in dsl.filters if f.default is not None}
        widgets = []
        for widget in dsl.widgets:
            dataset = widget.dataset.model_dump()
            merged_filters = dict(global_filters)
            merged_filters.update(dataset.get("filters") or {})
            dataset["filters"] = merged_filters
            result = await self.dataset_service.query(dataset, db, scope)
            chart = self._to_chart(result["rows"], widget.chart.type, widget.chart.x, widget.chart.y)
            widgets.append({"widget_id": widget.id, "chart": chart, "cache": result["cache"]})
        return {"dashboard_id": dsl.id, "widgets": widgets}

    @staticmethod
    def _to_chart(rows, chart_type: str, x_field: str, y_field: str):
        if not rows:
            return {"chart_type": chart_type, "x_axis": [], "y_axis": [], "x_field": x_field, "y_field": y_field}
        return {
            "chart_type": chart_type,
            "x_field": x_field,
            "y_field": y_field,
            "x_axis": [r.get(x_field) for r in rows],
            "y_axis": [r.get(y_field) for r in rows],
        }

    def _validate_or_raise(self, dsl: DashboardDSL) -> None:
        try:
            self.validator.validate(dsl)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"DSL_INVALID: {e}")

