"""
确定性分析引擎 (Analysis Engine)

本模块负责对查询结果进行确定性的统计分析，自动生成结构化的分析洞察。

核心职责：
- 基础统计：计算各数值指标的最大值、最小值、均值
- 实体排名：按实体（如公司）聚合后排序，输出 Top3/Bottom3
- 时间趋势：按时间维度聚合，输出时序趋势数据
- 同比分析：计算相邻时间周期的变化率（同比）
- 异常检测：基于 2σ 原则（均值±2倍标准差）识别离群值
- 相关性分析：计算多个数值指标之间的皮尔逊相关系数

设计原则：
- "确定性"意味着相同的输入数据始终产生相同的分析结果，不依赖随机种子或概率模型
- 所有分析方法均为纯函数式设计，不修改输入数据
- 自动识别实体列和时间列，兼容不同的数据模型

数据流向：
    查询结果 (List[Dict]) -> AnalysisEngine.analyze() -> 分析洞察 (Dict)

"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd


class AnalysisEngine:
    """
    确定性分析引擎，对查询结果进行多维度统计分析并生成结构化洞察。

    分析维度包括：基础统计、实体排名、时间趋势、同比变化、异常值检测、
    指标相关性。引擎会根据数据中实际存在的列自动选择适用的分析维度。
    """

    # 候选实体列名（按优先级排序），用于识别数据中的实体维度（如公司名称）
    # 引擎会按顺序查找，使用第一个在数据中实际存在的列
    ENTITY_CANDIDATES = ("company_cn_name",)

    # 候选时间列名（按优先级排序），用于识别数据中的时间维度
    TIME_CANDIDATES = ("period_id",)

    def analyze(self, rows: List[Dict], metric_keys: List[str] | None = None) -> Dict[str, Any]:
        """
        对查询结果执行完整的统计分析，返回结构化的分析洞察。

        分析流程：
        1. 将原始行数据转为 DataFrame，空数据直接返回
        2. 自动识别实体列、时间列和数值列
        3. 计算基础统计量（max/min/mean）
        4. 若存在实体列，计算排名（Top3/Bottom3）
        5. 若存在时间列，计算趋势和同比
        6. 检测异常值（2σ 离群）
        7. 若有多个数值列，计算相关性矩阵

        Args:
            rows: 查询结果的行数据列表，每个元素为一行的字典表示
            metric_keys: 用户请求的指标 key 列表，用于优先识别数值列并保持顺序

        Returns:
            分析结果字典，包含以下字段：
            - type: 分析类型（"empty" / "basic" / "composite"）
            - main_metric: 主分析指标名称（仅 composite 类型）
            - row_count: 数据行数
            - stats: 各数值列的统计量
            - ranking: 实体排名（若存在实体列）
            - trend: 时间趋势（若存在时间列）
            - yoy: 同比变化（若存在时间列且数据量≥2）
            - outlier: 异常值记录（若检测到离群点）
            - correlation: 指标相关性矩阵（若存在多个数值列）
        """
        # 将原始数据转为 Pandas DataFrame，便于后续的统计计算
        df = pd.DataFrame(rows)

        # 空数据集直接返回，避免后续计算报错
        if df.empty:
            return {"type": "empty", "insights": {}}

        # 自动识别数据中的关键维度列
        entity_col = self._pick_col(df, self.ENTITY_CANDIDATES)  # 实体列（如公司名）
        time_col = self._pick_col(df, self.TIME_CANDIDATES)      # 时间列（如期间ID）

        # 识别并转换数值列，metric_keys 优先（保持用户请求的指标顺序）
        numeric_cols = self._numeric_columns(df, metric_keys)

        # 若没有数值列，只能提供最基本的行数和样本数据
        if not numeric_cols:
            return {
                "type": "basic",
                "insights": {
                    "row_count": int(len(df)),
                    "sample": df.head(5).to_dict("records"),
                },
            }

        # 选择第一个数值列作为主分析指标（通常是用户最关心的核心指标）
        main_metric = numeric_cols[0]

        # 构建分析结果的骨架，包含基础信息和统计量
        analysis: Dict[str, Any] = {
            "type": "composite",
            "main_metric": main_metric,
            "row_count": int(len(df)),
            "entity_field": entity_col,
            "time_field": time_col,
            "stats": self._stats(df, numeric_cols),
        }

        # 若存在实体列，计算主指标的实体排名（Top3/Bottom3）
        if entity_col:
            analysis["ranking"] = self._ranking(df, entity_col, main_metric)

        # 若存在时间列，计算时间趋势和同比变化
        if time_col:
            analysis["trend"] = self._trend(df, time_col, main_metric)
            # 同比分析需要至少 2 个时间周期的数据
            yoy = self._yoy(df, time_col, main_metric)
            if yoy:
                analysis["yoy"] = yoy

        # 异常值检测：基于 2σ 原则（均值 ± 2 倍标准差之外的值视为离群）
        outliers = self._outlier(df, main_metric)
        if outliers:
            analysis["outlier"] = outliers

        # 若存在多个数值列，计算它们之间的皮尔逊相关系数矩阵
        if len(numeric_cols) > 1:
            analysis["correlation"] = (
                df[numeric_cols].corr(numeric_only=True).fillna(0.0).to_dict()
            )

        return analysis

    @staticmethod
    def _pick_col(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
        """
        从候选列名列表中选择第一个在 DataFrame 中实际存在的列。

        按候选列表的优先级顺序查找，返回第一个匹配项。
        这种设计允许不同数据模型使用不同的列名，引擎自动适配。

        Args:
            df: 数据 DataFrame
            candidates: 候选列名元组（按优先级排序）

        Returns:
            匹配到的列名；若无匹配则返回 None
        """
        for c in candidates:
            if c in df.columns:
                return c
        return None

    @staticmethod
    def _numeric_columns(df: pd.DataFrame, metric_keys: List[str] | None) -> List[str]:
        """
        识别 DataFrame 中的数值列，优先返回用户请求的指标列。

        处理逻辑：
        1. 优先处理 metric_keys 中指定的列（尝试转换为数值类型）
        2. 自动扫描所有列，将可转换为数值的列也加入结果
        3. 最终列表中 metric_keys 的列排在前面，保持用户意图的优先级

        Args:
            df: 数据 DataFrame（会被原地修改，数值列会被转换类型）
            metric_keys: 用户请求的指标 key 列表，用于优先排序

        Returns:
            数值列名列表，metric_keys 中的列排在前面
        """
        # 第一步：提取在 DataFrame 中存在的指标列，并强制转换为数值类型
        # errors="coerce" 表示无法转换的值变为 NaN，而非报错
        preferred = [m for m in (metric_keys or []) if m in df.columns]
        for col in preferred:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 第二步：自动扫描所有列，将可转为数值的列加入候选
        auto = []
        for col in df.columns:
            # 尝试将列转换为数值类型
            converted = pd.to_numeric(df[col], errors="coerce")
            # 若转换后至少有一个非 NaN 值，说明该列包含有效数值
            if converted.notna().any():
                df[col] = converted
            # 若该列已是数值类型且包含有效数据，加入候选列表
            if pd.api.types.is_numeric_dtype(df[col]) and df[col].notna().any():
                auto.append(col)

        # 第三步：合并两个列表，metric_keys 排在前面，去重保持顺序
        ordered = []
        for col in preferred + auto:
            if col not in ordered:
                ordered.append(col)
        return ordered

    @staticmethod
    def _stats(df: pd.DataFrame, numeric_cols: List[str]) -> Dict[str, Dict[str, float]]:
        """
        计算各数值列的基础统计量（最大值、最小值、均值）。

        对每个数值列分别计算三个统计指标，用于快速了解数据的分布概况。
        若某列全为 NaN（无有效数据），则三个统计量均为 0.0。

        Args:
            df: 数据 DataFrame
            numeric_cols: 需要计算统计量的数值列名列表

        Returns:
            嵌套字典，外层键为列名，内层包含 max/min/mean 三个统计量
            示例：{"revenue": {"max": 1000.0, "min": 100.0, "mean": 500.0}}
        """
        result: Dict[str, Dict[str, float]] = {}
        for col in numeric_cols:
            # 确保列为数值类型，非数值转为 NaN
            s = pd.to_numeric(df[col], errors="coerce")
            result[col] = {
                # 若全为 NaN（notna().any() 为 False），返回 0.0 避免 NaN 传播
                "max": float(s.max()) if s.notna().any() else 0.0,
                "min": float(s.min()) if s.notna().any() else 0.0,
                "mean": float(s.mean()) if s.notna().any() else 0.0,
            }
        return result

    @staticmethod
    def _ranking(df: pd.DataFrame, entity_col: str, metric_col: str) -> Dict[str, Any]:
        """
        按实体列分组聚合后，计算主指标的排名（Top3 和 Bottom3）。

        处理流程：
        1. 按实体列分组并对指标列求和（同一实体可能有多行数据）
        2. 按指标值降序排列
        3. 提取前 3 名和后 3 名

        Args:
            df: 数据 DataFrame
            entity_col: 实体列名（如公司名）
            metric_col: 排名依据的指标列名（如营收）

        Returns:
            排名字典，包含：
            - metric: 排名依据的指标名
            - top3: 排名前 3 的实体记录列表
            - bottom3: 排名后 3 的实体记录列表
        """
        # 按实体分组聚合，然后按指标值降序排序
        ranked = (
            df[[entity_col, metric_col]]
            .groupby(entity_col, as_index=False)[metric_col]
            .sum()
            .sort_values(metric_col, ascending=False)
        )
        return {
            "metric": metric_col,
            "top3": ranked.head(3).to_dict("records"),
            "bottom3": ranked.tail(3).to_dict("records"),
        }

    @staticmethod
    def _trend(df: pd.DataFrame, time_col: str, metric_col: str) -> List[Dict[str, Any]]:
        """
        按时间维度聚合指标值，生成时间趋势数据。

        处理流程：
        1. 按时间列分组并对指标列求和
        2. 按时间顺序排列
        3. 输出每个时间点的聚合值

        适用于生成折线图等时序可视化所需的数据。

        Args:
            df: 数据 DataFrame
            time_col: 时间列名（如 period_id）
            metric_col: 趋势分析的指标列名

        Returns:
            趋势数据列表，每个元素为一个时间点的记录字典
            示例：[{"period_id": "202401", "revenue": 1000}, {"period_id": "202402", "revenue": 1200}]
        """
        # 按时间分组聚合，按时间顺序排列
        trend = (
            df[[time_col, metric_col]]
            .groupby(time_col, as_index=False)[metric_col]
            .sum()
            .sort_values(time_col)
        )
        return trend.to_dict("records")

    @staticmethod
    def _yoy(df: pd.DataFrame, time_col: str, metric_col: str) -> List[Dict[str, Any]]:
        """
        计算指标的同比变化率（相邻时间周期的百分比变化）。

        "同比"在此上下文中指相邻时间周期的变化率，计算公式为：
            yoy = (当前值 - 上期值) / 上期值

        处理逻辑：
        1. 按时间分组聚合
        2. 使用 shift(1) 获取上一期的值
        3. 计算变化率，处理除零和 NaN 的边界情况
        4. 跳过第一期（无上期数据，yoy 为 NaN）

        Args:
            df: 数据 DataFrame
            time_col: 时间列名
            metric_col: 同比分析的指标列名

        Returns:
            同比数据列表，每个元素包含时间标识和 yoy 值
            示例：[{"period_id": "202402", "yoy": 0.2}, {"period_id": "202403", "yoy": -0.1}]
            若数据不足 2 个时间周期，返回空列表
        """
        # 按时间分组聚合并排序
        grouped = (
            df[[time_col, metric_col]]
            .groupby(time_col, as_index=False)[metric_col]
            .sum()
            .sort_values(time_col)
        )

        # 至少需要 2 个时间周期才能计算同比
        if len(grouped) < 2:
            return []

        # shift(1) 将数据下移一行，即获取上一期的值
        grouped["prev"] = grouped[metric_col].shift(1)

        # 逐行计算同比变化率，处理除零和 NaN 边界情况
        grouped["yoy"] = grouped.apply(
            lambda r: (r[metric_col] - r["prev"]) / r["prev"]
            if pd.notna(r["prev"]) and float(r["prev"]) != 0.0  # 上期值非 NaN 且非零
            else None,
            axis=1,
        )

        # 过滤掉同比为 NaN 的行（第一期无上期数据）
        rows = []
        for _, r in grouped.iterrows():
            if pd.isna(r["yoy"]):
                continue
            rows.append({str(time_col): r[time_col], "yoy": float(r["yoy"])})
        return rows

    @staticmethod
    def _outlier(df: pd.DataFrame, metric_col: str) -> List[Dict[str, Any]]:
        """
        基于 2σ 原则检测指标列中的异常值（离群点）。

        检测方法：
        - 计算指标列的均值 (μ) 和标准差 (σ)
        - 超出 [μ - 2σ, μ + 2σ] 范围的值视为异常
        - 在正态分布假设下，约 95% 的数据落在此范围内，5% 被标记为异常

        边界条件：
        - 数据量不足 10 条时跳过检测（样本太少，统计意义不足）
        - 标准差为 0 时跳过（所有值相同，无异常可言）
        - 最多返回 10 条异常记录（避免结果过大）

        Args:
            df: 数据 DataFrame
            metric_col: 异常检测的指标列名

        Returns:
            异常记录列表（原始行数据），最多 10 条
            若无异常或数据不足，返回空列表
        """
        # 确保列为数值类型
        series = pd.to_numeric(df[metric_col], errors="coerce")

        # 数据量不足 10 条时跳过检测，样本太少统计意义不足
        if series.notna().sum() < 10:
            return []

        # 计算均值和标准差
        mean = float(series.mean())
        std = float(series.std())

        # 标准差为 0 说明所有值相同，不存在异常
        if std == 0:
            return []

        # 标记超出 [μ - 2σ, μ + 2σ] 范围的值为异常
        mask = (series > mean + 2 * std) | (series < mean - 2 * std)

        # 最多返回 10 条异常记录，防止结果过大
        return df[mask].head(10).to_dict("records")
