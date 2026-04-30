from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class MetricRegistry:
    """Semantic metric registry loaded from YAML."""

    def __init__(
        self,
        metrics_path: str | None = None,
        dimensions_path: str | None = None,
        models_path: str | None = None,
    ):
        base = Path(__file__).resolve().parent
        self._metrics_path = Path(metrics_path) if metrics_path else base / "metrics.yaml"
        self._dimensions_path = Path(dimensions_path) if dimensions_path else base / "dimensions.yaml"
        self._models_path = Path(models_path) if models_path else base / "models.yaml"
        self._metrics = self._load_yaml(self._metrics_path).get("metrics", {})
        self._dimensions = self._load_yaml(self._dimensions_path).get("dimensions", {})
        self._models = self._load_yaml(self._models_path).get("models", {})
        self._version = str(self._load_yaml(self._metrics_path).get("version", "v1"))
        self._metric_synonym_map = self._build_metric_synonym_map()

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {}
        return data

    @property
    def version(self) -> str:
        return self._version

    def _build_metric_synonym_map(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for key, meta in self._metrics.items():
            mapping[str(key)] = str(key)
            if not isinstance(meta, dict):
                continue
            label = meta.get("label")
            if label:
                mapping[str(label)] = str(key)
            for syn in meta.get("synonyms", []):
                mapping[str(syn)] = str(key)
        return mapping

    def resolve_metric(self, name: str) -> Optional[str]:
        if not name:
            return None
        return self._metric_synonym_map.get(str(name))

    def get_metric(self, key: str) -> Dict[str, Any] | None:
        m = self._metrics.get(key)
        return dict(m) if isinstance(m, dict) else None

    def get_dimension(self, key: str) -> Dict[str, Any] | None:
        d = self._dimensions.get(key)
        return dict(d) if isinstance(d, dict) else None

    def get_dimension_column(self, key: str) -> str | None:
        d = self.get_dimension(key)
        if isinstance(d, dict):
            col = d.get("column")
            if col:
                return str(col)
        return None

    def get_model(self, key: str) -> Dict[str, Any] | None:
        m = self._models.get(key)
        return dict(m) if isinstance(m, dict) else None

    def is_derived(self, key: str) -> bool:
        m = self.get_metric(key) or {}
        return str(m.get("type", "")).lower() == "derived" or "formula" in m

    def dependencies_of(self, key: str) -> List[str]:
        m = self.get_metric(key) or {}
        deps = m.get("depends_on", [])
        if isinstance(deps, list):
            return [str(x) for x in deps if x]
        return []

    def validate_metrics(self, metrics: List[str]) -> None:
        for m in metrics:
            resolved = self.resolve_metric(m) or m
            if resolved not in self._metrics:
                raise ValueError(f"Invalid metric: {m}")

    def validate_dimensions(self, dims: List[str]) -> None:
        for d in dims:
            if d not in self._dimensions:
                raise ValueError(f"Invalid dimension: {d}")

