"""
洞察构建器 (Insight Builder)

本模块负责将分析引擎产出的结构化分析结果转换为简洁、可读的文本洞察。

核心职责：
- 将 AnalysisEngine 生成的统计分析数据（排名、同比、异常值等）
  转换为人类可读的中文结论语句
- 每条洞察为一句简短的陈述，便于前端直接展示或嵌入报告
- 保持确定性：相同的分析数据始终生成相同的洞察文本

设计原则：
- "机器可读"意味着返回结构化的字典，而非纯文本；前端可直接解析 insights 列表
- 洞察语句简洁精炼，每条聚焦一个发现，避免冗长的综合描述
- 当数据不足以生成有意义的洞察时，给出兜底提示而非返回空结果

数据流向：
    AnalysisEngine.analyze() 输出 -> InsightBuilder.build() -> 洞察文本列表
"""

from __future__ import annotations

from typing import Any, Dict, List


class InsightBuilder:
    """
    洞察构建器，将确定性的分析数据转换为简洁的机器可读洞察文本。

    洞察生成策略（按优先级依次检查）：
    1. 空数据集 -> 提示无有效数据
    2. 数据行数 -> 基于多少条记录
    3. 实体排名 -> 谁在核心指标上排名第一
    4. 同比变化 -> 最新周期的同比百分比
    5. 异常值 -> 提示存在离群点需复核
    6. 兜底 -> 数据平稳，无显著异常
    """

    def build(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        将分析结果转换为洞察文本列表。

        依次从分析数据中提取各类发现，转换为简短的中文陈述句。
        各类发现之间相互独立，按顺序追加到 insights 列表中。

        Args:
            analysis: AnalysisEngine.analyze() 的输出字典，可能包含：
                - type: 分析类型（"empty" / "basic" / "composite"）
                - row_count: 数据行数
                - ranking: 实体排名数据（含 top3、metric 等字段）
                - yoy: 同比变化数据列表
                - outlier: 异常值记录列表

        Returns:
            洞察结果字典，包含：
            - insights: 洞察文本列表，每条为一句中文陈述
            - analysis: 原始分析数据的透传，便于前端做更丰富的可视化展示
        """
        # ========== 场景一：空数据集 ==========
        # 查询未返回任何有效数据，直接给出提示并透传原始分析数据
        if analysis.get("type") == "empty":
            return {"insights": ["未查询到有效数据，无法生成分析结论。"], "analysis": analysis}

        insights: List[str] = []

        # ========== 场景二：数据概况 ==========
        # 展示本次分析覆盖的数据量，为后续洞察提供上下文
        row_count = analysis.get("row_count")
        if row_count is not None:
            insights.append(f"本次分析基于 {row_count} 条记录。")

        # ========== 场景三：实体排名洞察 ==========
        # 从排名数据中提取第一名的信息，生成"谁在什么维度排名第一"的结论
        ranking = analysis.get("ranking")
        if isinstance(ranking, dict):
            # 取 Top3 中的第一名；若 Top3 为空则用空字典兜底，避免索引越界
            top = (ranking.get("top3") or [{}])[0]
            metric = ranking.get("metric", "核心指标")

            # 遍历第一名记录的字段，找到实体名称（即非指标列的字段）
            # 例如 {"company_cn_name": "公司A", "revenue": 1000} 中取 "公司A"
            for k, v in top.items():
                if k != metric and v is not None:
                    insights.append(f"{v} 在 {metric} 维度排名第一。")
                    break  # 只取第一个实体名称字段，避免重复输出

        # ========== 场景四：同比变化洞察 ==========
        # 从同比数据中提取最新一个时间周期的变化率
        yoy = analysis.get("yoy")
        if isinstance(yoy, list) and yoy:
            # 取列表最后一个元素，即最新时间周期的同比数据
            latest = yoy[-1]
            val = latest.get("yoy")

            if isinstance(val, (float, int)):
                # 动态识别时间字段名（可能是 period_id、year 等）
                # 方法：取除 "yoy" 之外的第一个键作为时间字段
                label = [k for k in latest.keys() if k != "yoy"]
                period_val = latest.get(label[0]) if label else "最新期"

                # 使用 Python 格式化语法 .2% 将小数转为百分比字符串（如 0.2 -> "20.00%"）
                insights.append(f"{period_val} 的同比变化为 {val:.2%}。")

        # ========== 场景五：异常值洞察 ==========
        # 若检测到离群点，提示用户关注并结合业务背景复核
        outlier = analysis.get("outlier")
        if isinstance(outlier, list) and outlier:
            insights.append("检测到异常值，建议结合业务背景进一步复核。")

        # ========== 场景六：兜底结论 ==========
        # 若以上所有场景均未产生洞察（如只有基础统计，无排名/同比/异常），
        # 给出一个中性的兜底结论，避免返回空列表
        if not insights:
            insights.append("数据波动整体平稳，未发现显著异常。")

        # 透传原始分析数据，便于前端在文本洞察之外做表格、图表等丰富展示
        return {"insights": insights, "analysis": analysis}
