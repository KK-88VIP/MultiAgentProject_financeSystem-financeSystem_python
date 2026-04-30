from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List

from semantic.registry import MetricRegistry


@dataclass
class QueryPlan:
    semantic_version: str
    model: str
    table: str
    metrics: List[Dict[str, Any]]
    metric_keys: List[str]
    filters: Dict[str, Any]
    group_by: List[str]
    order_by: List[Dict[str, Any]]
    limit: int | None
    post_compute: List[str]

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


class QueryPlanner:
    """Build deterministic query plans from QueryIR."""

    def __init__(self, registry: MetricRegistry | None = None):
        self.registry = registry or MetricRegistry()

    def plan(self, ir) -> QueryPlan:
        metric_keys = list(ir.metrics or [])
        if not metric_keys:
            raise ValueError("No metrics found in intent")

        expanded: List[str] = []
        post_compute: List[str] = []
        for key in metric_keys:
            resolved = self.registry.resolve_metric(key) or key
            m = self.registry.get_metric(resolved)
            if not m:
                raise ValueError(f"Unknown metric: {key}")
            expanded.append(resolved)
            if self.registry.is_derived(resolved):
                post_compute.append(resolved)
                expanded.extend(self.registry.dependencies_of(resolved))

        # keep order, deduplicate
        seen = set()
        metric_keys_expanded: List[str] = []
        for k in expanded:
            if k not in seen:
                seen.add(k)
                metric_keys_expanded.append(k)

        metrics: List[Dict[str, Any]] = []
        tables = set()
        for key in metric_keys_expanded:
            meta = self.registry.get_metric(key)
            if not meta:
                continue
            metric_meta = dict(meta)
            metric_meta["key"] = key
            metrics.append(metric_meta)
            table = meta.get("table")
            if table:
                tables.add(str(table))

        if not tables:
            raise ValueError("No valid table found for metrics")
        if len(tables) > 1:
            raise ValueError("Cross-table query is not supported in current version")

        dimensions = list(getattr(ir, "dimensions", []) or [])
        group_by = list(ir.group_by or [])
        group_dims = dimensions or group_by

        order_by = list(ir.order_by or [])
        valid_order_fields = set(metric_keys_expanded) | set(group_dims)
        for ob in order_by:
            field = ob.get("field")
            if field and field not in valid_order_fields:
                raise ValueError(f"order_by.field not matched: {field}")

        limit = ir.limit if getattr(ir, "limit", None) else 100
        try:
            limit = int(limit)
        except Exception:
            limit = 100
        limit = min(max(limit, 1), 1000)

        table_key = tables.pop()
        return QueryPlan(
            semantic_version=self.registry.version,
            model=table_key,
            table=table_key,
            metrics=metrics,
            metric_keys=metric_keys_expanded,
            filters=dict(ir.filters or {}),
            group_by=group_dims,
            order_by=order_by,
            limit=limit,
            post_compute=post_compute,
        )

