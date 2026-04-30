# -*- coding: utf-8 -*-
"""
@file: chart_service.py
@version: 0.1.0
@purpose: 图表推荐与图表数据结构处理服务。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

# 根据指标和数据规模，自动决定前端渲染何种图表（柱状图、折线图、环形图）。

from typing import List, Dict, Any


class ChartService:
    @staticmethod
    def recommend_chart(metric: str, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        根据数据规模和指标特性推荐图表类型
        """
        data_len = len(data)

        # 简单逻辑：超过 12 个点用折线，少于 12 个用柱状，单个指标用环形/KPI卡
        if data_len == 1:
            return {"type": "kpi_card", "config": {}}
        elif data_len <= 12:
            return {"type": "bar", "config": {"xAxis": "period_id", "yAxis": metric}}
        else:
            return {"type": "line", "config": {"xAxis": "period_id", "yAxis": metric}}