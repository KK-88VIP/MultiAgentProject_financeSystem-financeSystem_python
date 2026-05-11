# -*- coding: utf-8 -*-
"""
@file: metric_service.py
@version: 0.2.0
@purpose: 衍生指标计算服务，封装安全除法与基于 pandas 的派生指标计算入口。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 21:08:57 +08:00
@author: aPy


指标计算服务模块 (metric_service.py)

本模块负责在 Python 层对已从数据库查询出的原始财务数据进行二次加工，计算派生指标
（如毛利率、资产负债率等）。遵循"SQL 只做基础聚合，Python 做复杂计算"的设计原则，
将业务逻辑与数据获取解耦，提升系统的可维护性和扩展性。

核心职责：
1. 接收 QueryExecutor 返回的原始数据（List[Dict] 格式）。
2. 将数据转换为 pandas DataFrame 以便高效进行列级运算。
3. 根据 metric_registry 中定义的派生指标公式，动态计算派生字段。
4. 处理计算过程中可能出现的除零、无穷大、空值等异常情况，确保输出数据干净可用。
5. 返回包含原始字段和派生字段的完整数据，供上层（QueryService）进行图表渲染和文本总结。

设计原则：
- 单一职责：仅负责派生指标的计算，不关心数据如何获取。
- 依赖注入：计算公式和依赖关系均来自 metric_registry，无需硬编码。
- 防御性编程：对公式执行失败进行捕获和日志记录，避免单点故障影响整体响应。
- 数据清理：统一处理 NaN 和 Inf，保证 JSON 序列化兼容性。

注意：
- 派生指标的计算公式使用 pandas.DataFrame.eval() 执行，其表达式语法受限且环境受控，
  避免了任意代码执行风险。
- 计算失败时，该指标列将被跳过，其余数据照常返回，不中断服务。
"""

from typing import List, Dict

import pandas as pd

from app.core.logger import get_logger
from semantic.registry import MetricRegistry

logger = get_logger(__name__)


class MetricService:
    """
    派生指标计算器类

    使用方法：
        calc = MetricService()
        enriched_data = calc.calc_derived_metrics(raw_data)
    """

    def __init__(self):
        self.registry = MetricRegistry()

    def safe_divide(self, numerator, denominator):
        """安全除法：分母为0或分子为None时返回None，避免崩溃。"""
        if denominator is None or denominator == 0 or numerator is None:
            return None
        return numerator / denominator

    def calc_derived_metrics(self, data: List[Dict]) -> List[Dict]:
        """
        主入口：对输入数据计算所有已定义的派生指标。

        参数：
            data：SQL 查询返回的原始数据，每行为一个字典，键为字段名。

        返回：
            包含原始字段和成功计算的派生字段的数据列表。若输入为空，原样返回。

        执行流程：
            1. 将输入转换为 DataFrame。
            2. 遍历 metric_registry 中所有 type="derived" 的指标。
            3. 检查依赖字段是否均存在于 DataFrame 中。
            4. 若依赖满足，尝试执行计算公式，失败则记录警告并跳过。
            5. 清理 DataFrame 中的 Inf 和 NaN 值。
            6. 转换回字典列表并返回。
        """
        if not data:
            return data

        try:
            df = pd.DataFrame(data)

            # 遍历所有派生指标定义
            for metric, meta in self._iter_derived_metrics():
                deps = self.registry.dependencies_of(metric)

                # 依赖字段缺失时跳过计算（例如查询未包含成本字段，无法计算毛利率）
                if not all(col in df.columns for col in deps):
                    continue

                try:
                    # 执行公式计算
                    df[metric] = self._apply_formula(df, metric, meta)
                except Exception as e:
                    # 计算失败（如除零）不应阻断整个请求，仅记录警告
                    logger.warning(f"[MetricService] failed to calc {metric}: {e}")

            # 清理异常值，确保 JSON 可序列化
            df = self._clean_df(df)

            return df.to_dict(orient="records")

        except Exception as e:
            # 若整个流程出现意外错误（如 DataFrame 转换失败），降级返回原始数据
            logger.error(f"[MetricService] error: {e}")
            return data

    # =========================
    # 内部辅助方法
    # =========================

    def _iter_derived_metrics(self):
        """
        生成器：遍历 METRIC_REGISTRY 中所有 type="derived" 的指标。

        返回：
            (metric_key, metric_meta) 的元组。
        """
        for metric, meta in (self.registry._metrics or {}).items():  # noqa: SLF001
            key = str(metric)
            if self.registry.is_derived(key):
                yield key, (meta or {})

    def _apply_formula(self, df: pd.DataFrame, metric: str, meta: Dict):
        """
        应用派生指标的计算公式。

        参数：
            df：包含依赖字段的 DataFrame。
            metric：标准指标 Key（用于日志）。
            meta：指标元数据字典，需包含 "formula" 字段。

        返回：
            计算结果的 pandas Series。

        安全性说明：
            - 公式字符串来自开发者维护的 metric_registry，非用户输入。
            - pandas.eval() 仅支持有限的数学和列引用表达式，无法执行任意 Python 代码。
            - 列名由白名单控制，不存在注入风险。
        """
        formula = meta.get("formula")
        # 使用 pandas eval 在 DataFrame 上下文中执行表达式
        return df.eval(formula)

    def _clean_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        清理 DataFrame 中的非法浮点值，确保 JSON 序列化兼容。

        操作：
            - 正负无穷大（inf/-inf）替换为 pd.NA。
            - NaN 替换为 Python None。
        """
        # 将 inf 和 -inf 转换为 NaN
        df = df.replace([float("inf"), float("-inf")], pd.NA)

        # 将所有 NaN 统一转换为 Python None（JSON 序列化友好）
        df = df.where(pd.notnull(df), None)

        return df