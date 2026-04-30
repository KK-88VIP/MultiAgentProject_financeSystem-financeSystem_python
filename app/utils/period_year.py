# -*- coding: utf-8 -*-
"""从存储层 period_id（varchar 等）解析为公历四位年份，供筛选器 API 使用。"""


def parse_period_to_calendar_year(period_id: object) -> int | None:
    """
    仅输出四位公历年份；无法解析或越界的值返回 None（调用方应过滤并打日志）。

    规则：取规范化字符串的前 4 位，若均为数字且在 [1900, 2100] 内则视为年份。
    例如 period_id 为 \"202512\" 时取 2025；非数字前缀则丢弃。
    """
    if period_id is None:
        return None
    s = str(period_id).strip()
    if len(s) < 4 or not s[:4].isdigit():
        return None
    y = int(s[:4])
    if 1900 <= y <= 2100:
        return y
    return None
