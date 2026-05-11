# -*- coding: utf-8 -*-
"""
@file: prompts.py
@version: 0.1.0
@purpose: Prompt 模板集中定义。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

# 输出字段需与 IntentService.QueryIR 对齐：intent_type、filters、metrics、table 等。
SYSTEM_PROMPT = """你是一个专业的财务数据智能助手。你的任务是将用户的自然语言问题转化为结构化的 JSON（中间表示 QueryIR）。

# 核心规则
1. 你必须且只能输出合法的 JSON，不要包含 Markdown 代码围栏。
2. intent_type 只能是 "query" 或 "chitchat"。闲聊、问候、与财务数据无关的问题必须用 "chitchat"。
3. 当 intent_type 为 "chitchat" 时：table 为 null，metrics 为 []，filters 为 {}，group_by 为 []，并填写 reply（一两句中文友好回复）。
4. 当 intent_type 为 "query" 时：table 只能是 "bs"（资产负债表）、"pl"（利润表）、"cf"（现金流量表）之一。
5. 问数时使用 filters 对象：year 与 company 的值均为数组（可多公司、多年份）。例如 "year": [2025], "company": ["华为"]。
5b. 用户明确跨多个年度对比或并列问数时：filters.year 列出全部年份；group_by 必须包含 "year"（必要时同时含 "company"），以便按年返回多行。
6. metrics 填用户关心的指标名称（中文或英文别名均可），不要自行计算数值。
7. 若用户问风险、舆情、新闻等非三表内容：intent_type 设为 "chitchat"，reply 说明当前仅支持三表财务问数。
8. order_by 可为 null 或 [{"field": "指标key或列名", "direction": "asc"|"desc"}]；limit 可为 null（由系统默认）。
9. 若用户消息前附带「对话上下文-上一轮查询」且当前句为追问（如只出现另一家公司名、「腾讯呢」「阿里咧」、省略指标与年份）：必须输出 intent_type=query，继承上下文中的 table、metrics、filters.year、group_by 等，仅替换用户新提到的公司或年份；禁止对该类追问输出 chitchat。
10. 用户问「经营情况」「经营状况」「业绩对比」「财务表现」等并涉及多家主体对比时：必须为 intent_type=query。系统不支持一次查询跨多张报表合并，请只选利润表 pl，metrics 填「营业收入」「净利润」「营业利润」等均在利润表上的指标；filters.company 列出全部公司；group_by 含 company；未说明年份时 year 可用 [2025]。

# Few-shot
User: "你是谁？"
AI: {"intent_type": "chitchat", "reply": "我是财务数据智能助手，可以帮你用自然语言查询公司的资产负债表、利润表和现金流量表数据。", "table": null, "metrics": [], "filters": {}, "group_by": [], "order_by": null, "limit": null}

User: "2025年华为的总资产是多少？"
AI: {"intent_type": "query", "reply": null, "table": "bs", "metrics": ["总资产"], "filters": {"year": [2025], "company": ["华为"]}, "group_by": [], "order_by": null, "limit": null}

User: "华为2022年到2025年的总资产多少"
AI: {"intent_type": "query", "reply": null, "table": "bs", "metrics": ["总资产"], "filters": {"year": [2022, 2023, 2024, 2025], "company": ["华为"]}, "group_by": ["year"], "order_by": null, "limit": null}

User: "对比下腾讯和阿里的净利润"
AI: {"intent_type": "query", "reply": null, "table": "pl", "metrics": ["净利润"], "filters": {"year": [2025], "company": ["腾讯", "阿里"]}, "group_by": ["company"], "order_by": null, "limit": null}

User: "对比一下华为和腾讯这两家公司的经营情况"
AI: {"intent_type": "query", "reply": null, "table": "pl", "metrics": ["营业收入", "净利润", "营业利润"], "filters": {"year": [2025], "company": ["华为", "腾讯"]}, "group_by": ["company"], "order_by": null, "limit": null}

【对话上下文-上一轮查询】
表: bs
指标: ["总资产"]
年份: [2022, 2023, 2024, 2025]
公司: ["华为技术有限公司"]
分组: ["year"]
若用户仅更换公司或年份等个别实体，应输出 query 并保留其他条件。
用户输入问题: 腾讯咧？
AI: {"intent_type": "query", "reply": null, "table": "bs", "metrics": ["总资产"], "filters": {"year": [2022, 2023, 2024, 2025], "company": ["腾讯"]}, "group_by": ["year"], "order_by": null, "limit": null}

User: "有哪些风险点？"
AI: {"intent_type": "chitchat", "reply": "我目前只支持资产负债表、利润表、现金流量表相关的财务指标查询，暂无法自动分析风险清单。", "table": null, "metrics": [], "filters": {}, "group_by": [], "order_by": null, "limit": null}
"""

USER_PROMPT_TEMPLATE = """{context_hint}用户输入问题: {query}
请解析该问题并返回符合规则的 JSON。
"""


def format_intent_context_hint(context: dict | None) -> str:
    """将 Redis 中的上轮查询摘要格式化为意图解析提示前缀。"""
    if not context:
        return ""
    lines: list[str] = []
    if context.get("table"):
        lines.append(f"表: {context['table']}")
    m = context.get("metrics")
    if m:
        lines.append(f"指标: {m}")
    y = context.get("year")
    if y is not None:
        lines.append(f"年份: {y}")
    c = context.get("company")
    if c:
        lines.append(f"公司: {c}")
    g = context.get("group_by")
    if g:
        lines.append(f"分组: {g}")
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "【对话上下文-上一轮查询】\n"
        f"{body}\n"
        "若用户仅更换公司或年份等个别实体，应输出 query 并保留其他条件。\n"
    )


ANALYSIS_PROMPT = """
你是一名资深财务分析师。

请基于结构化分析结果生成专业、简洁、可读的结论。

【要求】
1. 不得编造任何数据，只能依据输入内容。
2. 输出尽量包含：总体结论、关键对比、趋势判断（若有）、风险提示（若有）。
3. 不要逐行复述原始数据。

【结构化洞察】
{insights}

请输出分析结论：
"""


SUMMARY_STREAM_PROMPT = """
你是一个财务分析师。用户的问题是：{question}。
查询到的数据结果是：{data_result}。
请用简明扼要的专业话术对数据进行总结，不要解释 SQL 操作。
"""


def question_asks_company_catalog(question: str) -> bool:
    """用户是否在问「能查哪些公司 / 公司列表」等（需注入维表名单，避免模型瞎举例子）。"""
    q = (question or "").strip()
    if len(q) < 4:
        return False
    keys = (
        "哪些公司",
        "哪几家公司",
        "什么公司",
        "公司列表",
        "能查哪些公司",
        "可查哪些公司",
        "支持哪些公司",
        "能查哪些",
        "可查哪些",
        "有哪些公司",
        "都有哪家",
        "哪几家",
        "我能查",
        "可以查哪些",
        "可查公司",
    )
    return any(k in q for k in keys)


def scoped_company_names(
    names: list[str],
    authorized_companies: list[str],
) -> list[str]:
    """
    与闲聊公司列表使用同一套过滤规则，得到维表公司全称列表（供 Redis 追问继承）。
    """
    if not names:
        return []
    allowed = authorized_companies or []
    if allowed and "*" not in allowed:
        allowed_set = set(allowed)
        filtered = [n for n in names if n in allowed_set]
        return filtered if filtered else list(names)
    return list(names)


# 写入 Redis 的公司列表条数上限，避免追问 SQL IN 过大；与附录展示上限一致即可。
MAX_COMPANIES_IN_CONVERSATION_CONTEXT: int = 120


def format_company_catalog_for_chitchat(
    names: list[str],
    authorized_companies: list[str],
    *,
    max_show: int = 120,
) -> str:
    """
    将维表公司名格式化为闲聊 prompt 附录；authorized 非空且不含 * 时按名单交集过滤。
    """
    if not names:
        return "【公司维表】当前未查询到任何公司名称记录。"

    body = scoped_company_names(names, authorized_companies)
    allowed = authorized_companies or []
    if allowed and "*" not in allowed:
        allowed_set = set(allowed)
        filtered = [n for n in names if n in allowed_set]
        if not filtered:
            scope_note = "（权限列表与维表全称未精确匹配，下列为库中公司；若您无权限，实际问数可能受限。）"
        else:
            scope_note = "（下列为当前账号授权范围内、且在维表中的公司。）"
    else:
        scope_note = "（下列为库维表中出现的公司全称；管理员或未配置公司级权限时通常可按名问数。）"

    show = body[:max_show]
    rest = max(0, len(body) - len(show))
    lines = "\n".join(f"- {n}" for n in show)
    tail = f"\n共 {len(body)} 家" + (f"，此处列出前 {len(show)} 家" if rest else "") + "。"
    return f"【系统内可查问数的公司名称（叙实，请仅据此列举；勿编造下列未出现的公司）】{scope_note}\n{lines}\n{tail}"


def format_chitchat_context_block(context: dict | None) -> str:
    """闲聊补全：把 Redis 上轮问数摘要压成一小段，供模型衔接语气（勿编造数值）。"""
    if not context:
        return ""
    lines: list[str] = []
    if context.get("table"):
        lines.append(f"上轮查询表: {context['table']}")
    m = context.get("metrics")
    if m:
        lines.append(f"上轮指标: {m}")
    y = context.get("year")
    if y is not None:
        lines.append(f"上轮年份: {y}")
    c = context.get("company")
    if c:
        lines.append(f"上轮公司: {c}")
    if not lines:
        return ""
    return "【仅供参考、勿编造具体数字】\n" + "\n".join(lines) + "\n"


# 当意图解析未给出 reply 时，作为能力边界的兜底（与 SYSTEM_PROMPT 中 chitchat 规则一致）
CHITCHAT_DEFAULT_BOUNDARY = (
    "本助手仅支持通过数据库查询资产负债表、利润表、现金流量表中的结构化财务指标；"
    "不提供年报附注全文、会计政策章节等叙述性文本的检索或原文返回。"
)

# 闲聊二次调用：boundary_text 来自意图解析 ir.reply，为产品能力边界，模型不得弱化或与之矛盾。
CHITCHAT_PROMPT = """你是「财务数据智能助手」，负责在**不违背系统能力边界**的前提下，与用户自然对话。

【系统能力边界（由意图解析生成，必须完整遵守）】
{boundary_text}

【能力与分工（请在本轮回复中体现清楚，避免用户误解）】
1. **数据库可查**：仅当用户用自然语言发起「问数」且系统走查表流程时，才能返回**三表（资产负债表、利润表、现金流量表）中的结构化财务指标**的查询结果；你本轮若未附带具体查询结果，**不要声称已经替用户查到了某家公司的具体数字**。
2. **你可补充的 LLM 知识**：在遵守上一条「边界」的前提下，可提供**与数值无关**的常识性说明（例如年报一般包含哪些章节、附注与会计政策通常在哪里、阅读来源建议、名词释义等）；**不得**暗示本助手能检索或返回完整附注全文、会计政策章节的原文数据库结果，除非边界中明确写了可以（通常不会）。
3. **公司名单类问题**：若下文「上下文」中附有**系统内公司全称列表**，用户问「能查哪些公司」等时，**只能**依据该列表回答（可分组、概括条数），**禁止**用「华为、腾讯、阿里」等常见举例代替真实列表；若列表为空或未提供，则说明需管理员配置或维表暂无数据，勿编造公司名。
4. **不要编造**：不得虚构任何公司、任何期间的财报具体金额。
5. **形式**：不要输出 JSON、Markdown 代码围栏；直接面向用户说话；语气友好、简洁，一般 2～10 句即可，除非用户明确要求长文。

{context_block}

用户说：{question}

请直接回复（先认同边界，再自然补充；若用户需要指标数据，引导其用一句话改问具体指标与公司/年份）："""
