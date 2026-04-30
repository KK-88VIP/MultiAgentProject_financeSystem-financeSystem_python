from __future__ import annotations

from app.models.dashboard_dsl import DashboardDSL
from semantic.registry import MetricRegistry


class DSLValidator:
    def __init__(self):
        self.registry = MetricRegistry()

    def validate(self, dsl: DashboardDSL) -> bool:
        ids = set()
        if len(dsl.widgets) > 12:
            raise ValueError("DSL_INVALID: too many widgets (max 12)")

        for widget in dsl.widgets:
            if widget.id in ids:
                raise ValueError(f"DSL_INVALID: duplicate widget id: {widget.id}")
            ids.add(widget.id)

            dataset = widget.dataset
            self.registry.validate_metrics(dataset.metrics)

            dims = dataset.dimensions or dataset.group_by
            self.registry.validate_dimensions(dims)

            out_fields = set(dataset.metrics) | set(dims)
            if widget.chart.x not in out_fields:
                raise ValueError(f"DSL_INVALID: chart.x not found in dataset output: {widget.chart.x}")
            if widget.chart.y not in out_fields:
                raise ValueError(f"DSL_INVALID: chart.y not found in dataset output: {widget.chart.y}")

        return True

