from __future__ import annotations

from typing import Any, Dict, List


class InsightBuilder:
    """Convert deterministic analysis payload into concise machine-readable insights."""

    def build(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        if analysis.get("type") == "empty":
            return {"insights": ["未查询到有效数据，无法生成分析结论。"], "analysis": analysis}

        insights: List[str] = []
        row_count = analysis.get("row_count")
        if row_count is not None:
            insights.append(f"本次分析基于 {row_count} 条记录。")

        ranking = analysis.get("ranking")
        if isinstance(ranking, dict):
            top = (ranking.get("top3") or [{}])[0]
            metric = ranking.get("metric", "核心指标")
            for k, v in top.items():
                if k != metric and v is not None:
                    insights.append(f"{v} 在 {metric} 维度排名第一。")
                    break

        yoy = analysis.get("yoy")
        if isinstance(yoy, list) and yoy:
            latest = yoy[-1]
            val = latest.get("yoy")
            if isinstance(val, (float, int)):
                label = [k for k in latest.keys() if k != "yoy"]
                period_val = latest.get(label[0]) if label else "最新期"
                insights.append(f"{period_val} 的同比变化为 {val:.2%}。")

        outlier = analysis.get("outlier")
        if isinstance(outlier, list) and outlier:
            insights.append("检测到异常值，建议结合业务背景进一步复核。")

        if not insights:
            insights.append("数据波动整体平稳，未发现显著异常。")

        return {"insights": insights, "analysis": analysis}

