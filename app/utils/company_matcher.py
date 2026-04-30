# -*- coding: utf-8 -*-
"""
@file: company_matcher.py
@version: 0.1.0
@purpose: 公司名称模糊匹配工具，用于识别候选公司并支持 clarification 流程。
@created: 2026-04-17 21:08:57 +08:00
@updated: 2026-04-17 21:08:57 +08:00
@author: aPy

公司名称模糊匹配工具

本模块提供轻量级的公司名称匹配功能，用于处理用户自然语言问数中公司名称的模糊输入。
其核心设计原则是“在 Python 层做匹配，在业务层做澄清”，避免在数据库 SQL 中引入复杂的模糊查询，
保证查询性能与安全性。

设计原则：
1. 不在 SQL 层做模糊匹配（避免误匹配与性能损耗）
2. 在 Python 层基于预加载的公司列表进行匹配，返回候选集
3. 由上层服务（QueryService）根据候选数量决定是否进入 clarification 流程，
   以交互方式引导用户明确选择目标公司

当前实现：
- 基于简单子串匹配与基础归一化（去空格、小写化）
- 公司候选列表由 company_repository 提供，通过外部注入

后续可扩展方向：
- 拼音匹配（处理用户输入拼音首字母）
- 向量相似度（基于词嵌入的语义匹配）
"""

from typing import List


def _normalize(text: str) -> str:
    """
    基础归一化函数，对输入字符串进行轻量清洗。

    操作：
    - 移除所有空格（用户可能输入"华 为 技 术"）
    - 转换为小写（忽略大小写差异，如"Tencent"与"tencent"）

    目的：
    - 提高匹配的鲁棒性，避免因空格或大小写导致漏匹配

    注意：
    - 此归一化仅用于匹配逻辑，返回值仍为原始公司名称，以保证展示准确性
    """
    return text.replace(" ", "").lower()


def match_companies(
    query: str,
    candidates: List[str],
    top_k: int = 5,
) -> List[str]:
    """
    对公司名候选列表进行模糊匹配，返回可能的目标公司名称列表。

    Args:
        query: 用户输入的公司名片段（如 "腾讯"）
        candidates: 全量公司名称列表（通常来自 company_repository.list_all()）
        top_k: 最大返回候选数量（用于控制澄清选项数量，避免过多选项干扰用户）

    Returns:
        匹配结果列表，按完全匹配优先排序，后跟子串匹配结果。
        - 若完全匹配存在，返回前 top_k 个完全匹配项
        - 若无完全匹配，返回前 top_k 个子串匹配项
        - 若均无匹配，返回空列表

    匹配规则（按优先级）：
        1. 归一化后字符串完全相等（exact match）
        2. 查询字符串是归一化后公司名的子串（partial match）

    设计考量：
        - 优先返回完全匹配是为了应对用户输入完整正确名称的情况，减少澄清步骤
        - 对子串匹配结果进行 top_k 截断，防止候选过多造成用户体验下降
    """
    # 边界处理：空查询或空候选集直接返回空列表
    if not query or not candidates:
        return []

    q = _normalize(query)

    exact_matches = []
    partial_matches = []

    for name in candidates:
        norm_name = _normalize(name)

        # 规则1：完全匹配
        if q == norm_name:
            exact_matches.append(name)
            continue

        # 规则2：子串匹配（查询字符串出现在公司名中）
        if q in norm_name:
            partial_matches.append(name)

    # 完全匹配优先返回
    if exact_matches:
        return exact_matches[:top_k]

    # 否则返回子串匹配结果（同样截断）
    return partial_matches[:top_k]


def has_ambiguity(matches: List[str]) -> bool:
    """
    判断匹配结果是否存在歧义，即是否需要进行澄清交互。

    歧义条件：
        - 匹配结果数量大于 1（用户输入可能对应多家公司）

    用途：
        - 在 IntentService 中调用，决定是否中断常规流程，向客户端发送 clarification 事件
    """
    return len(matches) > 1


def is_no_match(matches: List[str]) -> bool:
    """
    判断是否完全没有匹配到任何公司。

    用途：
        - 当无匹配时，系统可返回友好提示（如"未找到相关公司，请检查名称"）
        - 避免在无匹配时继续进行 SQL 生成，减少无效操作
    """
    return len(matches) == 0
