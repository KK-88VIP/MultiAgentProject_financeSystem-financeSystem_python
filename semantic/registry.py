"""
语义指标注册中心 (Semantic Metric Registry)

本模块实现了一个基于 YAML 配置文件的语义指标注册中心，用于统一管理
业务指标 (metrics)、维度 (dimensions) 和模型 (models) 的元数据。

核心功能：
- 从 YAML 文件加载指标、维度、模型的定义及元信息
- 支持指标名称的别名解析（同义词映射），例如 "营收" 可映射到 "revenue"
- 提供指标类型的判断（如是否为派生指标）
- 提供指标间依赖关系的查询
- 对输入的指标名和维度名进行合法性校验

"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class MetricRegistry:
    """语义指标注册中心，从 YAML 配置文件加载并管理指标、维度和模型的元数据。"""

    def __init__(
        self,
        metrics_path: str | None = None,
        dimensions_path: str | None = None,
        models_path: str | None = None,
        security_overrides_path: str | None = None,
    ):
        """
        初始化注册中心，加载所有 YAML 配置文件。

        Args:
            metrics_path: 指标配置文件路径，为 None 时使用默认路径 (当前目录下的 metrics.yaml)
            dimensions_path: 维度配置文件路径，为 None 时使用默认路径 (当前目录下的 dimensions.yaml)
            models_path: 模型配置文件路径，为 None 时使用默认路径 (当前目录下的 models.yaml)
        """
        # 获取当前文件所在目录作为默认配置文件的基准路径
        base = Path(__file__).resolve().parent

        # 确定各 YAML 配置文件的路径：优先使用用户传入的路径，否则使用默认路径
        self._metrics_path = Path(metrics_path) if metrics_path else base / "metrics.yaml"
        self._dimensions_path = Path(dimensions_path) if dimensions_path else base / "dimensions.yaml"
        self._models_path = Path(models_path) if models_path else base / "models.yaml"
        self._security_overrides_path = (
            Path(security_overrides_path) if security_overrides_path else base / "security_overrides.yaml"
        )

        # 从 YAML 文件中加载数据，分别提取 metrics、dimensions、models 三个顶层键
        # 若键不存在则返回空字典，确保后续代码不会因 None 而报错
        self._metrics = self._load_yaml(self._metrics_path).get("metrics", {})
        self._dimensions = self._load_yaml(self._dimensions_path).get("dimensions", {})
        self._models = self._load_yaml(self._models_path).get("models", {})
        self._security_overrides = self._load_yaml(self._security_overrides_path).get("security_overrides", {})

        # 从指标配置中读取版本号，默认为 "v1"
        self._version = str(self._load_yaml(self._metrics_path).get("version", "v1"))

        # 构建指标同义词映射表，用于将别名/标签解析为标准指标 key
        self._metric_synonym_map = self._build_metric_synonym_map()

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        """
        安全加载指定路径的 YAML 文件并返回解析后的字典。

        Args:
            path: YAML 文件的路径

        Returns:
            解析后的字典；若文件内容不是字典类型或加载失败则返回空字典
        """
        # 以 UTF-8 编码打开文件，使用 safe_load 防止执行任意代码（安全加载）
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # 防御性检查：确保解析结果是字典类型，否则返回空字典
        if not isinstance(data, dict):
            return {}
        return data

    @property
    def version(self) -> str:
        """返回当前指标配置的版本号。"""
        return self._version

    @property
    def metrics(self) -> Dict[str, Dict[str, Any]]:
        """返回指标配置副本（只读视图）。"""
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in self._metrics.items():
            if isinstance(v, dict):
                out[str(k)] = dict(v)
        return out

    @property
    def dimensions(self) -> Dict[str, Dict[str, Any]]:
        """返回维度配置副本（只读视图）。"""
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in self._dimensions.items():
            if isinstance(v, dict):
                out[str(k)] = dict(v)
        return out

    @property
    def models(self) -> Dict[str, Dict[str, Any]]:
        """返回模型配置副本（只读视图）。"""
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in self._models.items():
            if isinstance(v, dict):
                out[str(k)] = dict(v)
        return out

    @property
    def security_overrides(self) -> Dict[str, Any]:
        """返回安全覆盖配置副本（只读视图）。"""
        return dict(self._security_overrides) if isinstance(self._security_overrides, dict) else {}

    def _build_metric_synonym_map(self) -> Dict[str, str]:
        """
        构建指标同义词到标准 key 的映射表。

        映射规则（按优先级从低到高）：
        1. 标准 key 自身映射到自身（如 "revenue" -> "revenue"）
        2. 指标的 label 字段映射到标准 key（如 "营收" -> "revenue"）
        3. 指标的 synonyms 列表中的每个同义词映射到标准 key

        Returns:
            一个字典，键为所有已知的指标名称/别名，值为对应的标准指标 key
        """
        mapping: Dict[str, str] = {}

        # 遍历所有已注册的指标及其元数据
        for key, meta in self._metrics.items():
            # 将标准 key 自身也加入映射，确保通过标准名也能查到
            mapping[str(key)] = str(key)

            # 如果元数据不是字典（格式异常），跳过后续的别名提取
            if not isinstance(meta, dict):
                continue

            # 将 label（显示标签，如中文名）映射到标准 key
            label = meta.get("label")
            if label:
                mapping[str(label)] = str(key)

            # 将 synonyms（同义词列表）中的每一项映射到标准 key
            for syn in meta.get("synonyms", []):
                mapping[str(syn)] = str(key)

        return mapping

    def resolve_metric(self, name: str) -> Optional[str]:
        """
        将指标名称（包括别名、标签、同义词）解析为标准指标 key。

        Args:
            name: 待解析的指标名称，可以是标准 key、label 或 synonym

        Returns:
            对应的标准指标 key；若无法解析则返回 None
        """
        if not name:
            return None
        # 直接在同义词映射表中查找，返回对应的标准 key
        return self._metric_synonym_map.get(str(name))

    def get_metric(self, key: str) -> Dict[str, Any] | None:
        """
        根据标准 key 获取指标的元数据字典。

        Args:
            key: 标准指标 key（如 "revenue"）

        Returns:
            指标元数据的字典副本；若不存在则返回 None
        """
        m = self._metrics.get(key)
        # 返回字典的副本，防止外部修改影响内部数据
        return dict(m) if isinstance(m, dict) else None

    def get_dimension(self, key: str) -> Dict[str, Any] | None:
        """
        根据 key 获取维度的元数据字典。

        Args:
            key: 维度 key（如 "company"）

        Returns:
            维度元数据的字典副本；若不存在则返回 None
        """
        d = self._dimensions.get(key)
        return dict(d) if isinstance(d, dict) else None

    def get_dimension_column(self, key: str) -> str | None:
        """
        获取维度对应的数据库列名。

        Args:
            key: 维度 key

        Returns:
            该维度对应的 column 名称字符串；若不存在则返回 None
        """
        d = self.get_dimension(key)
        if isinstance(d, dict):
            col = d.get("column")
            if col:
                return str(col)
        return None

    def get_model(self, key: str) -> Dict[str, Any] | None:
        """
        根据 key 获取模型的元数据字典。

        Args:
            key: 模型 key

        Returns:
            模型元数据的字典副本；若不存在则返回 None
        """
        m = self._models.get(key)
        return dict(m) if isinstance(m, dict) else None

    def is_derived(self, key: str) -> bool:
        """
        判断指定指标是否为派生指标（derived metric）。

        派生指标是指由其他指标通过公式计算得出的指标，
        判断依据：type 字段为 "derived"，或元数据中包含 "formula" 字段。

        Args:
            key: 标准指标 key

        Returns:
            如果是派生指标返回 True，否则返回 False
        """
        m = self.get_metric(key) or {}
        # 满足以下任一条件即视为派生指标：type 为 "derived"，或存在 formula 字段
        return str(m.get("type", "")).lower() == "derived" or "formula" in m

    def dependencies_of(self, key: str) -> List[str]:
        """
        获取指定指标的依赖指标列表。

        对于派生指标，其计算依赖于其他基础指标或派生指标，
        本方法返回 depends_on 字段中列出的所有依赖项。

        Args:
            key: 标准指标 key

        Returns:
            依赖指标 key 的列表；若无依赖则返回空列表
        """
        m = self.get_metric(key) or {}
        deps = m.get("depends_on", [])

        # 确保 depends_on 是列表类型，并过滤掉空值
        if isinstance(deps, list):
            return [str(x) for x in deps if x]
        return []

    def validate_metrics(self, metrics: List[str]) -> None:
        """
        校验给定的指标名称列表是否全部合法。

        会先尝试将每个名称解析为标准 key，再检查是否存在于注册表中。
        若存在不合法的指标，抛出 ValueError。

        Args:
            metrics: 待校验的指标名称列表（可以是别名）

        Raises:
            ValueError: 当列表中存在无法识别的指标名称时
        """
        for m in metrics:
            # 先尝试通过同义词解析，若解析失败则使用原始名称
            resolved = self.resolve_metric(m) or m
            # 解析后的 key 必须在已注册的指标中存在，否则报错
            if resolved not in self._metrics:
                raise ValueError(f"Invalid metric: {m}")

    def validate_dimensions(self, dims: List[str]) -> None:
        """
        校验给定的维度名称列表是否全部合法。

        若存在不合法的维度，抛出 ValueError。

        Args:
            dims: 待校验的维度名称列表

        Raises:
            ValueError: 当列表中存在未注册的维度名称时
        """
        for d in dims:
            # 直接在已注册的维度字典中查找
            if d not in self._dimensions:
                raise ValueError(f"Invalid dimension: {d}")
