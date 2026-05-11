# -*- coding: utf-8 -*-
"""
@file: client.py
@version: 0.1.0
@purpose: 大模型客户端封装，占位用于统一对接 LLM 服务商。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy

LLM 客户端 (LLM Client)

本模块封装了与大语言模型 (LLM) 的所有交互，基于 LangChain 框架接入阿里千问 (Qwen)。
阿里千问的 DashScope 平台完全兼容 OpenAI SDK 接口规范，因此使用 ChatOpenAI 即可直连。

核心职责：
- 结构化意图解析：调用 LLM 将用户的自然语言查询解析为结构化 JSON，
  供下游 IntentService 映射为 QueryIR
- 流式财务总结：将查询结果交给 LLM 生成专业财务分析话术，
  以 SSE (Server-Sent Events) 流式推送给前端
- 通用流式补全：提供一个通用的流式文本生成接口，供其他服务按需调用

模型配置策略：
- 意图解析使用 temperature=0.0，要求最高确定性（相同输入始终产出相同 JSON）
- 流式总结使用 temperature=0.3，允许适度的表达多样性
- 意图解析强制 JSON 输出格式 (response_format=json_object)，减少格式错误


"""

import json
from typing import AsyncGenerator

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.config import settings
from app.llm.prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    SUMMARY_STREAM_PROMPT,
    format_intent_context_hint,
)


class LLMClient:
    """
    LLM 客户端，封装与阿里千问模型的交互逻辑。

    内部维护两个 ChatOpenAI 实例：
    - self.llm: 用于意图解析（低温度、强制 JSON 输出、非流式）
    - self.stream_llm: 用于文本生成（适度温度、流式输出）
    """

    def __init__(self):
        """
        初始化 LLM 客户端，创建两个专用的模型实例。

        配置来源优先级：
        1. 环境变量/配置文件中的 LLM_BASE_URL
        2. 阿里千问 DashScope 的默认兼容端点
        """
        # 阿里千问 DashScope 提供 OpenAI 兼容接口，只需替换 base_url 即可使用 ChatOpenAI
        # 默认端点：https://dashscope.aliyuncs.com/compatible-mode/v1
        base_url = settings.LLM_BASE_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1"

        # ---- 意图解析专用实例 ----
        # 特点：低温度 + 强制 JSON 输出，追求最高确定性
        self.llm = ChatOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=base_url,
            model=settings.LLM_MODEL,        # 预期为 qwen-plus 等千问系列模型
            temperature=0.0,                  # 降至 0，确保相同输入产出相同 JSON 结构
            model_kwargs={
                "response_format": {"type": "json_object"}  # 强制模型输出合法 JSON，减少格式纠错成本
            },
        )

        # ---- 流式文本生成专用实例 ----
        # 特点：适度温度 + 流式输出，允许表达多样性
        self.stream_llm = ChatOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=base_url,
            model=settings.LLM_MODEL,
            temperature=0.3,                  # 总结环节允许适度创造性，语言更自然
            streaming=True,                   # 启用流式输出，支持逐 token 推送
        )

    def _strip_json_fence(self, content: str) -> str:
        """
        去除 LLM 输出中可能包裹 JSON 的 Markdown 代码围栏。

        LLM 有时会在 JSON 外层包裹 ```json ... ``` 格式的 Markdown 代码块，
        直接 json.loads 会失败。本方法将其剥离，提取纯 JSON 字符串。

        处理逻辑：
        1. 去除首尾空白
        2. 若以 ``` 开头，找到第一个换行符，截取其后的内容
        3. 若以 ``` 结尾，找到最后一个 ```，截取其前的内容
        4. 再次去除首尾空白

        Args:
            content: LLM 原始输出文本

        Returns:
            去除代码围栏后的纯文本内容
        """
        text = content.strip()

        # 处理开头的 ```json 或 ``` 标记
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl != -1:
                # 截取第一个换行符之后的内容，跳过 ```json 这一行
                text = text[first_nl + 1 :]

            # 处理结尾的 ``` 标记
            if text.endswith("```"):
                text = text[: text.rfind("```")].strip()

        return text.strip()

    async def parse_intent_json(self, query: str, context: dict | None = None) -> dict:
        """
        调用大模型进行结构化意图抽取，将自然语言查询解析为 JSON 字典。

        流程：
        1. 将系统提示词和用户问题组装为消息列表
        2. 调用 LLM（非流式，强制 JSON 输出）
        3. 去除可能的 Markdown 代码围栏
        4. 解析为 Python 字典

        返回的 JSON 字典将由下游 IntentService 映射为 QueryIR 对象。

        Args:
            query: 用户的自然语言查询，如 "今年营收最高的三家公司是谁？"
            context: 可选，上轮对话上下文（表/指标/年份/公司等），用于追问解析。

        Returns:
            解析后的 JSON 字典，典型结构如：
            {
                "metrics": ["revenue"],
                "dimensions": ["company_cn_name"],
                "order_by": [{"field": "revenue", "direction": "desc"}],
                "limit": 3,
                "filters": {"period_id": "2024"}
            }

        Raises:
            ValueError: 当 LLM 输出无法解析为合法 JSON 时
        """
        context_hint = format_intent_context_hint(context)
        human = USER_PROMPT_TEMPLATE.format(
            context_hint=context_hint,
            query=query,
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=human),
        ]

        # 调用 LLM（非流式，等待完整响应）
        response = await self.llm.ainvoke(messages)

        try:
            # 去除可能的 Markdown 代码围栏，然后解析 JSON
            content = self._strip_json_fence(response.content or "")
            return json.loads(content)
        except Exception as e:
            # 捕获所有解析异常（JSONDecodeError 等），统一包装为 ValueError
            raise ValueError(f"大模型解析意图失败或格式错误: {str(e)}") from e

    async def generate_summary_stream(
        self, data_result: list, question: str
    ) -> AsyncGenerator[str, None]:
        """
        流式生成财务分析总结，以异步生成器的形式逐块输出文本。

        将查询结果和用户问题交给 LLM，要求其以专业财务分析师的角色
        生成简明扼要的数据总结。结果以 SSE 流的形式推送给前端，
        用户可以逐字看到总结内容，体验更流畅。

        Args:
            data_result: 查询结果数据列表（字典列表形式）
            question: 用户的原始问题

        Yields:
            总结文本的增量片段（每个 chunk 为一个字符串片段）
        """
        # 构建提示词：由 prompts.py 统一维护模板
        prompt = SUMMARY_STREAM_PROMPT.format(
            question=question,
            data_result=data_result,
        )

        # 使用 astream 进行流式调用，逐 token 获取 LLM 输出
        # 超时等异常由上层调用方的 try-except 捕获处理
        async for chunk in self.stream_llm.astream([HumanMessage(content=prompt)]):
            # 过滤空内容（流式传输中某些 chunk 可能为空）
            if chunk.content:
                yield chunk.content

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        通用流式文本补全接口，供 QueryService 等上层服务按自定义 prompt 调用。

        与 generate_summary_stream 的区别：
        - 本方法接受完整的自定义 prompt，不限定角色和格式
        - generate_summary_stream 针对财务总结场景封装了特定的 prompt 模板

        Args:
            prompt: 完整的提示词文本

        Yields:
            文本的增量片段（每个 chunk 为一个字符串片段）
        """
        async for chunk in self.stream_llm.astream([HumanMessage(content=prompt)]):
            if chunk.content:
                yield chunk.content
