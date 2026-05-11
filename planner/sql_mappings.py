from __future__ import annotations

from semantic.registry import MetricRegistry

_registry = MetricRegistry()

# 逻辑模型到物理表映射：单一事实源来自 semantic/models.yaml
TABLE_MAPPING = {
    model_key: str(model_meta["table"])
    for model_key, model_meta in _registry.models.items()
    if isinstance(model_meta, dict) and model_meta.get("table")
}

# 语义维度到物理列映射：单一事实源来自 semantic/dimensions.yaml
DIMENSION_MAPPING = {
    dim_key: str(dim_meta["column"])
    for dim_key, dim_meta in _registry.dimensions.items()
    if isinstance(dim_meta, dict) and dim_meta.get("column")
}

