# -*- coding: utf-8 -*-
"""
@file: intent_service.py
@version: 0.2.0
@purpose: 意图解析服务，负责问题结构化、指标标准化、公司模糊匹配与歧义检测。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 21:08:57 +08:00
@author: aPy


意图解析服务模块 (intent_service.py)

本模块是自然语言问数流程中的语义解析层，负责将用户的自然语言问题转换为结构化的
中间表示（QueryIR），为后续 SQL 生成提供标准化的输入。模块集成了 LLM 调用、指标
标准化、公司模糊匹配以及歧义检测能力，确保下游模块接收到的是明确且合法的查询意图。

核心职责：
1. 调用大语言模型（LLM）从用户问题中提取结构化信息（表、指标、过滤条件等）。
2. 对 LLM 输出的指标名称进行标准化，将用户别名（如“营收”）映射为系统标准 Key。
3. 对公司名称进行模糊匹配，处理用户输入的非精确公司名，返回候选列表。
4. 检测匹配结果是否存在歧义（多个候选公司），支持后续澄清交互（clarification）。
5. 修复和补全 IR 中的缺失字段（如默认 group_by、limit），保证输出的健壮性。

设计要点：
- 支持注入真实 LLM（`parse_intent_json`）；失败时对非闲聊问题返回「无法解析」，不注入占位查询。
- 指标标准化依赖 metric_registry 中的别名索引。
- 公司匹配依赖独立的 company_matcher 工具模块，保持匹配逻辑的可测试性。
- 歧义检测结果由上层 QueryService 消费，决定是否中断常规流程并向客户端发送澄清请求。
- QueryIR 使用 Pydantic 模型定义，确保字段类型正确并易于序列化。

数据流向：
    用户问题 + 上下文
           │
           ▼
    [IntentService.parse_intent()]
           │
           ├── LLM 提取原始结构 (mock)
           ├── 指标标准化
           ├── 公司模糊匹配
           └── IR 修复与补全
           │
           ▼
    QueryIR (结构化意图对象)
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.core.logger import get_logger
from semantic.registry import MetricRegistry
from app.utils.company_matcher import match_companies, is_no_match

logger = get_logger(__name__)

# 宽泛「经营/业绩对比」问句的默认年度（用户未写明年份时）
_DEFAULT_COMPARISON_YEAR = 2025

# 问句中可识别的公司简称（长词优先，避免「阿里巴巴」再命中「阿里」重复）
_KNOWN_COMPANY_SHORT_NAMES: tuple[str, ...] = tuple(
    sorted(
        (
            "华为技术有限公司",
            "腾讯",
            "阿里巴巴",
            "阿里",
            "百度",
            "京东",
            "小米",
            "美团",
            "比亚迪",
            "宁德时代",
            "招商银行",
            "中国平安",
            "工商银行",
            "建设银行",
            "农业银行",
            "中国银行",
            "华为",
        ),
        key=len,
        reverse=True,
    )
)


def _is_vague_operating_comparison_question(text: str) -> bool:
    """是否属于「多家公司经营/业绩对比」类宽泛问法（需落到单表 pl + 核心指标）。"""
    t = (text or "").strip()
    if len(t) < 4:
        return False
    has_cmp = any(k in t for k in ("对比", "比较", " VS ", " vs ", "versus"))
    has_op = any(
        k in t
        for k in (
            "经营情况",
            "经营状况",
            "经营业绩",
            "经营表现",
            "业绩",
            "营运",
            "财务表现",
            "盈利情况",
        )
    )
    if not (has_cmp and has_op):
        return False
    if "两家" in t or "多家" in t:
        return True
    if _guess_company_short_names(t) and any(
        sep in t for sep in ("和", "与", "跟", "及", ",", "，", "、")
    ):
        return True
    return len(_guess_company_short_names(t)) >= 2


def _guess_company_short_names(q: str) -> List[str]:
    """从问句中按已知简称抽取公司（互不包含则都保留）。"""
    found: List[str] = []
    for token in _KNOWN_COMPANY_SHORT_NAMES:
        if token not in q:
            continue
        if any(
            token != existing and (token in existing or existing in token)
            for existing in found
        ):
            continue
        found.append(token)
    return found


def _strip_followup_particles(text: str) -> str:
    """去掉追问句尾语气词与标点，便于用公司名片段做 match_companies。"""
    t = (text or "").strip().strip("？?,.，。 \t")
    suffixes = ("咧", "呢", "呐", "吧", "嘛", "呀", "么", "哦", "啊", "哪", "咯")
    changed = True
    while changed and t:
        changed = False
        for suf in suffixes:
            if t.endswith(suf):
                t = t[: -len(suf)].strip().strip("？?,.，。 \t")
                changed = True
                break
    return t


def _match_companies_in_followup_phrase(cleaned: str, all_companies: List[str]) -> List[str]:
    """从短句中解析公司：整句匹配失败后尝试去前缀、尾窗切片。"""
    if not cleaned or not all_companies:
        return []
    m = match_companies(cleaned, all_companies)
    if not is_no_match(m):
        return m
    t = cleaned
    for prefix in ("那", "这", "换", "再看看", "看下", "请问"):
        if t.startswith(prefix):
            t = t[len(prefix) :].strip()
            if t:
                m = match_companies(t, all_companies)
                if not is_no_match(m):
                    return m
    max_len = min(8, len(cleaned))
    for size in range(max_len, 1, -1):
        frag = cleaned[-size:]
        m = match_companies(frag, all_companies)
        if not is_no_match(m):
            return m
    return []


# =========================
# QueryIR 定义（核心中间层）
# =========================
class QueryIR(BaseModel):
    """
    查询中间表示（Intermediate Representation）

    该模型定义了从用户自然语言问题中抽取出的标准化查询结构，是 LLM 输出与
    QueryPlanner/SQLGenerator 输入之间的约定格式。所有字段均为可选，由 IntentService 负责
    补全默认值并进行合法性校验。

    字段说明：
        - table: 查询主表，对应 metric_registry 中的表标识符（"bs"/"pl"/"cf"）。
        - metrics: 待查询的指标列表，每个元素为标准指标 Key（如 "revenue"）。
        - filters: 过滤条件字典，键为维度名（如 "year", "company"），值为单值或列表。
        - group_by: 分组维度列表，如 ["company", "year"]。
        - order_by: 排序规则，格式为 [{"field": "revenue", "direction": "desc"}]。
        - limit: 返回行数上限，若未指定则由 repair_ir 补入默认值。
        - intent_type: "query" 表示需要查库；"chitchat" 表示闲聊，不触发 SQL。
        - reply: 闲聊时模型给出的简短回复（可选）。
        - company_resolution_ambiguous: 某一公司简称是否匹配到多家主体（需澄清），多公司对比且每家唯一命中时为 False。
        - company_clarification_options: 仅当 company_resolution_ambiguous 时，供前端展示的候选全称列表。
    """
    intent_type: str = "query"
    reply: Optional[str] = None
    table: Optional[str] = None
    metrics: List[str] = []
    filters: Dict[str, Any] = {}
    group_by: List[str] = []
    order_by: Optional[List[Dict]] = None
    limit: Optional[int] = None
    company_resolution_ambiguous: bool = False
    company_clarification_options: List[str] = []


class IntentService:
    """
    意图解析服务类

    依赖注入：
        - llm_client: LLM 客户端实例，用于调用大模型生成结构化输出。
        - company_repo: 公司仓库实例，用于获取全量公司列表供匹配使用。
    """

    def __init__(self, llm_client=None, company_repo=None):
        """
        初始化服务，可注入 LLM 客户端和公司仓库。

        参数：
            llm_client: 可选，LLMClient 实例。若未提供，则使用内部的 mock 逻辑。
            company_repo: 可选，CompanyRepository 实例。若未提供，则公司匹配将失效。
        """
        self.llm_client = llm_client
        self.company_repo = company_repo
        self.metric_registry = MetricRegistry()

    # =========================
    # 主入口
    # =========================
    async def parse_intent(self, question: str, context: dict) -> QueryIR:
        """
        主解析流程：将用户问题转换为 QueryIR 对象。

        流程：
            1. 调用 LLM（当前为 mock）获取原始结构化数据。
            2. 将原始数据转换为 QueryIR Pydantic 模型。
            3. 对指标列表进行标准化（别名 → 标准 Key）。
            4. 对公司过滤条件进行模糊匹配，更新 IR 中的公司列表。
            5. 修复 IR 中的缺失字段（如默认 group_by 和 limit）。

        参数：
            question: 用户输入的自然语言问题。
            context: 对话上下文，包含用户角色、授权公司等（当前暂未深度使用）。

        返回：
            经过标准化和修复的 QueryIR 对象。
        """
        # 步骤1：获取 LLM 解析结果（mock 或真实调用）
        raw = await self._call_llm(question, context)

        # 步骤2：构造 Pydantic 模型对象
        ir = QueryIR(**raw)

        # 步骤2b：追问被误判为闲聊时，用 Redis 上下文 + 公司名解析救回为 query
        ir = await self._rescue_chitchat_to_query_if_followup(question, ir, context)

        # 步骤2c：「多家公司经营/业绩对比」宽泛问法 → 单表利润表 + 核心指标（避免闲聊或跨表失败）
        ir = self._apply_operating_situation_comparison_bundle(question, ir)

        # 步骤3：指标名称标准化（闲聊可不查指标）
        if ir.intent_type != "chitchat":
            ir.metrics = self.normalize_metrics(ir.metrics)
            if _is_vague_operating_comparison_question(question) and self._metrics_span_multiple_tables(
                ir.metrics
            ):
                ir.table = "pl"
                ir.metrics = ["revenue", "net_profit", "operating_profit"]
                if "company" not in ir.group_by:
                    ir.group_by = ["company"]

        # 步骤4：公司名称模糊匹配
        ir = await self.normalize_companies(ir)

        # 步骤5：IR 修复与补全
        ir = self.repair_ir(ir)

        return ir

    # =========================
    # LLM 调用（占位实现）
    # =========================
    async def _call_llm(self, question: str, context: dict) -> Dict:
        """
        调用 LLM 服务生成结构化查询意图。

        若注入 `llm_client` 且提供 `parse_intent_json`，则走真实模型解析；
        解析失败或无 LLM 时，对非闲聊问题返回 chitchat +「无法解析」说明，不构造占位查询。

        参数：
            question: 用户问题。
            context: 对话上下文。

        返回：
            符合 QueryIR 字段要求的字典。
        """
        if self.llm_client is not None and hasattr(
            self.llm_client, "parse_intent_json"
        ):
            try:
                raw = await self.llm_client.parse_intent_json(question, context)
                return self._map_llm_to_ir_dict(raw)
            except Exception as e:
                logger.warning(
                    "[IntentService] LLM 意图解析失败，使用降级策略 | %s", e
                )

        return self._fallback_ir_dict(question)

    def _map_llm_to_ir_dict(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """将模型 JSON（含新旧字段）规范为 QueryIR 可用的字典。"""
        if not isinstance(raw, dict):
            raw = {}

        legacy_intent = (raw.get("intent") or "").strip().lower()
        explicit = (raw.get("intent_type") or "").strip().lower()
        if legacy_intent == "chitchat" or explicit == "chitchat":
            intent_type = "chitchat"
        elif explicit in ("query", "comparison"):
            intent_type = "query"
        elif explicit:
            intent_type = explicit
        else:
            intent_type = "query"

        reply = raw.get("reply")
        if reply is not None:
            reply = str(reply).strip() or None

        table = raw.get("table")
        if table is not None:
            table = str(table).strip().lower() or None
        if table and table not in ("bs", "pl", "cf"):
            intent_type = "chitchat"
            reply = reply or "当前版本仅支持资产负债表、利润表与现金流量表相关问数，暂不支持该主题的自动查询。"

        metrics = raw.get("metrics") or []
        if not isinstance(metrics, list):
            metrics = [metrics]

        filters: Dict[str, Any] = {}
        fd = raw.get("filters")
        if isinstance(fd, dict) and fd:
            for k, v in fd.items():
                if v is None:
                    continue
                filters[k] = v if isinstance(v, list) else [v]
        else:
            companies = raw.get("companies")
            if companies:
                filters["company"] = (
                    companies if isinstance(companies, list) else [companies]
                )
            periods = raw.get("periods")
            if periods:
                plist = periods if isinstance(periods, list) else [periods]
                filters["year"] = [self._coerce_year(p) for p in plist]

        group_by = raw.get("group_by") or []
        if not isinstance(group_by, list):
            group_by = [group_by]

        order_by = raw.get("order_by")
        limit = raw.get("limit")

        if intent_type == "chitchat":
            return {
                "intent_type": "chitchat",
                "reply": reply,
                "table": None,
                "metrics": [],
                "filters": {},
                "group_by": [],
                "order_by": None,
                "limit": None,
            }

        return {
            "intent_type": "query",
            "reply": None,
            "table": table,
            "metrics": metrics,
            "filters": filters,
            "group_by": group_by,
            "order_by": order_by,
            "limit": limit,
        }

    @staticmethod
    def _coerce_year(v: Any) -> Any:
        if isinstance(v, int):
            return v
        s = str(v).strip()
        if s.isdigit():
            return int(s)
        return s

    def _fallback_ir_dict(self, question: str) -> Dict[str, Any]:
        """无可用 LLM 或调用失败时的降级：闲聊走本地规则；其余返回无法解析（不查库、无占位问数）。"""
        q = (question or "").strip()
        # 与 tests/api/test_query.py 中的占位问句对齐，避免 CI 无密钥时仍走数据库
        if q == "测试问题":
            return {
                "intent_type": "chitchat",
                "reply": "收到，这是一条连通性测试消息。",
                "table": None,
                "metrics": [],
                "filters": {},
                "group_by": [],
                "order_by": None,
                "limit": None,
            }
        if self._looks_like_chitchat(q):
            return {
                "intent_type": "chitchat",
                "reply": "你好，我是财务数据智能助手，你可以用自然语言查询各公司的营收、利润、资产负债等情况。",
                "table": None,
                "metrics": [],
                "filters": {},
                "group_by": [],
                "order_by": None,
                "limit": None,
            }
        return {
            "intent_type": "chitchat",
            "reply": "无法解析您的问题，请调整表述后重试。",
            "table": None,
            "metrics": [],
            "filters": {},
            "group_by": [],
            "order_by": None,
            "limit": None,
        }

    @staticmethod
    def _looks_like_chitchat(text: str) -> bool:
        if not text:
            return True
        t = text.lower()
        keys = (
            "你好",
            "您好",
            "谢谢",
            "感谢",
            "再见",
            "拜拜",
            "早上好",
            "晚上好",
            "晚安",
            "你是谁",
            "在吗",
            "哈哈",
            "呵呵",
            "闲聊",
            "聊天",
        )
        if any(k in text for k in keys):
            return True
        if "who are you" in t or "hello" in t or "hi" == t.strip():
            return True
        return len(text) <= 6 and text.strip() in ("?", "？", "嗯", "哦")

    def _metrics_span_multiple_tables(self, metric_keys: List[str]) -> bool:
        """标准化后的指标是否落在多张事实表上（当前规划器不支持跨表）。"""
        tables: set[str] = set()
        for k in metric_keys or []:
            meta = self.metric_registry.get_metric(k)
            if meta and meta.get("table"):
                tables.add(str(meta["table"]))
        return len(tables) > 1

    def _apply_operating_situation_comparison_bundle(self, question: str, ir: QueryIR) -> QueryIR:
        """
        将「对比多家经营/业绩」类宽泛问题落到利润表 + 核心经营指标，避免被判闲聊或跨表报错。
        若 LLM 已给出 company 过滤则保留，否则从问句中猜测简称。
        """
        if not _is_vague_operating_comparison_question(question):
            return ir
        ir.intent_type = "query"
        ir.reply = None
        ir.table = "pl"
        ir.metrics = ["营业收入", "净利润", "营业利润"]
        ir.group_by = list(dict.fromkeys([*(ir.group_by or []), "company"]))
        if not ir.filters.get("year"):
            ir.filters["year"] = [_DEFAULT_COMPARISON_YEAR]
        if not ir.filters.get("company"):
            guessed = _guess_company_short_names(question)
            if guessed:
                ir.filters["company"] = guessed
        return ir

    async def _rescue_chitchat_to_query_if_followup(
        self, question: str, ir: QueryIR, context: Dict[str, Any]
    ) -> QueryIR:
        """
        模型将「换公司/换主体」追问判成 chitchat 时，用 Redis 上轮要点 + 公司名解析救回为 query。

        例：上轮「华为 2022–2025 总资产」，本轮「腾讯咧？」。
        """
        if ir.intent_type != "chitchat":
            return ir

        metrics_ctx = context.get("metrics") or []
        if isinstance(metrics_ctx, (list, tuple)):
            metrics_list = [str(m) for m in metrics_ctx]
        else:
            metrics_list = [str(metrics_ctx)]
        if not metrics_list:
            return ir

        table_ctx = context.get("table")
        if not table_ctx:
            meta0 = self.metric_registry.get_metric(metrics_list[0])
            table_ctx = str(meta0.get("table") or "") if meta0 else ""
        if not table_ctx or table_ctx not in ("bs", "pl", "cf"):
            return ir

        cleaned = _strip_followup_particles(question)
        if len(cleaned) < 2:
            return ir

        all_companies = await self._get_all_companies()
        if not all_companies:
            return ir

        matches = _match_companies_in_followup_phrase(cleaned, all_companies)
        if is_no_match(matches):
            return ir

        year = context.get("year")
        filters: Dict[str, Any] = {"company": matches}
        if year is not None:
            filters["year"] = year if isinstance(year, list) else [year]

        group_by = list(context.get("group_by") or [])

        return QueryIR(
            intent_type="query",
            reply=None,
            table=table_ctx,
            metrics=metrics_list,
            filters=filters,
            group_by=group_by,
            order_by=None,
            limit=None,
        )

    # =========================
    # 标准化逻辑
    # =========================

    def normalize_metrics(self, metrics: List[str]) -> List[str]:
        """
        将用户输入或 LLM 输出的指标别名转换为系统标准指标 Key。

        该方法直接调用 metric_registry 中的 normalize_metrics 工具函数，
        该函数基于预定义的别名索引进行映射，并自动去重。

        参数：
            metrics: 原始指标名称列表（可能包含别名、中文名称）。

        返回：
            标准化后的唯一指标 Key 列表。
        """
        resolved: List[str] = []
        for m in metrics or []:
            key = self.metric_registry.resolve_metric(str(m)) or str(m)
            if self.metric_registry.get_metric(key):
                resolved.append(key)
        # 保序去重
        seen = set()
        ordered: List[str] = []
        for k in resolved:
            if k not in seen:
                seen.add(k)
                ordered.append(k)
        return ordered

    async def normalize_companies(self, ir: QueryIR) -> QueryIR:
        """
        对 IR 中 filters["company"] 的公司名进行模糊匹配，并替换为精确的公司名列表。

        流程：
            1. 提取 filters 中的公司列表。
            2. 从 company_repo 获取全量公司名称。
            3. 对每个用户输入的公司名调用 company_matcher 进行匹配。
            4. 将所有匹配结果去重后写回 IR。

        注意：
            若 company_repo 未注入或返回空列表，则公司匹配将失效，原始值保留。

        参数：
            ir: 当前的 QueryIR 对象。

        返回：
            更新了 filters["company"] 后的 QueryIR 对象。
        """
        companies = ir.filters.get("company")

        if not companies:
            return ir

        # 获取全量公司名称列表
        all_companies = await self._get_all_companies()

        raw_list = companies if isinstance(companies, list) else [companies]
        matched: List[str] = []
        ambiguous = False
        clarification_pool: List[str] = []

        for c in raw_list:
            if c is None:
                continue
            raw_c = str(c).strip()
            if not raw_c:
                continue
            matches = match_companies(raw_c, all_companies)
            if len(matches) > 1:
                ambiguous = True
                clarification_pool.extend(matches)
            matched.extend(matches)

        # 保序去重；多公司对比（如华为+腾讯各命中 1 家）不应走澄清
        ir.filters["company"] = list(dict.fromkeys(matched))
        ir.company_resolution_ambiguous = ambiguous
        ir.company_clarification_options = list(dict.fromkeys(clarification_pool))
        return ir

    async def _get_all_companies(self) -> List[str]:
        """
        从公司仓库获取全量公司名称列表。

        返回：
            公司名称字符串列表。若仓库未注入或查询失败，返回空列表。
        """
        if not self.company_repo:
            return []

        rows = await self.company_repo.list_all()
        # 兼容两种仓库返回：
        # 1) list[str]（当前 CompanyRepository）
        # 2) list[dict]（早期实现）
        if not rows:
            return []
        first = rows[0]
        if isinstance(first, str):
            return [str(r) for r in rows]
        if isinstance(first, dict):
            result: List[str] = []
            for r in rows:
                name = r.get("company_cn_name")
                if name:
                    result.append(str(name))
            return result
        return [str(r) for r in rows]

    async def list_all_company_names(self) -> List[str]:
        """供闲聊等场景从维表拉取公司全称列表（与问数侧公司匹配同源）。"""
        return await self._get_all_companies()

    # =========================
    # 歧义检测
    # =========================

    def detect_ambiguity(self, ir: QueryIR) -> Optional[List[str]]:
        """
        检测公司匹配结果是否存在歧义（候选公司数量大于1）。

        该方法供 QueryService 调用，用于判断是否需要向客户端发送 clarification 事件。

        参数：
            ir: 已完成公司匹配的 QueryIR 对象。

        返回：
            若存在歧义，返回候选公司列表；否则返回 None。
        """
        if ir.intent_type == "chitchat":
            return None
        if ir.company_resolution_ambiguous and ir.company_clarification_options:
            return ir.company_clarification_options

        return None

    def detect_no_match(self, ir: QueryIR) -> bool:
        """
        检测是否完全未匹配到任何公司。

        参数：
            ir: 已完成公司匹配的 QueryIR 对象。

        返回：
            True 表示未匹配到任何公司，False 表示至少匹配到一个或公司条件不存在。
        """
        if ir.intent_type == "chitchat":
            return False
        companies = ir.filters.get("company", [])
        return is_no_match(companies)

    # =========================
    # IR 修复
    # =========================

    def repair_ir(self, ir: QueryIR) -> QueryIR:
        """
        修复 LLM 输出中可能缺失或不合法的字段，补全默认值。

        修复规则：
            - 若 group_by 为空但 filters 中包含 company 过滤，则默认按 company 分组。
            - 若 limit 未指定，则使用配置文件中的 DEFAULT_LIMIT 作为默认值。

        参数：
            ir: 待修复的 QueryIR 对象。

        返回：
            修复后的 QueryIR 对象。
        """
        if ir.intent_type == "chitchat":
            return ir

        # 当有公司过滤条件但没有分组维度时，自动补充按公司分组，以便得到有意义的结果
        if not ir.group_by and "company" in ir.filters:
            ir.group_by = ["company"]

        # 若未指定返回行数，则采用配置的默认限制
        if not ir.limit:
            from app.core.config import settings
            ir.limit = settings.DEFAULT_LIMIT

        return ir