# -*- coding: utf-8 -*-
"""
@file: client.py
@version: 0.1.0
@purpose: 大模型客户端封装，占位用于统一对接 LLM 服务商。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

# 使用LangChain接入阿里千问（兼容OpenAI接口规范）。包含两个动作：一是结构化解析意图，二是流式生成财务总结。
import json
from typing import AsyncGenerator
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.core.config import settings
from app.llm.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


class LLMClient:
    def __init__(self):
        base_url = settings.LLM_BASE_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        # 阿里千问完全兼容 OpenAI SDK，只需替换 base_url
        self.llm = ChatOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=base_url,
            model=settings.LLM_MODEL,  # 预期为 qwen-plus
            temperature=0.0,  # 意图解析要求高度确定性，降至 0
            model_kwargs={"response_format": {"type": "json_object"}}  # 强制 JSON 输出
        )

        self.stream_llm = ChatOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=base_url,
            model=settings.LLM_MODEL,
            temperature=0.3,  # 总结环节可以稍微自然一点
            streaming=True
        )

    def _strip_json_fence(self, content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl != -1:
                text = text[first_nl + 1 :]
            if text.endswith("```"):
                text = text[: text.rfind("```")].strip()
        return text.strip()

    async def parse_intent_json(self, query: str) -> dict:
        """调用大模型进行意图抽取，返回原始 JSON 字典（由 IntentService 映射为 QueryIR）。"""
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=USER_PROMPT_TEMPLATE.format(query=query)),
        ]
        response = await self.llm.ainvoke(messages)
        try:
            content = self._strip_json_fence(response.content or "")
            return json.loads(content)
        except Exception as e:
            raise ValueError(f"大模型解析意图失败或格式错误: {str(e)}") from e

    async def generate_summary_stream(self, data_result: list, question: str) -> AsyncGenerator[str, None]:
        """流式生成业务总结给前端 (SSE)"""
        prompt = f"你是一个财务分析师。用户的问题是：{question}。\n查询到的数据结果是：{data_result}。\n请用简明扼要的专业话术对数据进行总结，不要解释 SQL 操作。"

        # 模拟设置流式超时的处理（由上层调用方的 try-except 捕获）
        async for chunk in self.stream_llm.astream([HumanMessage(content=prompt)]):
            if chunk.content:
                yield chunk.content

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """通用流式补全（供 QueryService 等按自定义 prompt 调用）。"""
        async for chunk in self.stream_llm.astream([HumanMessage(content=prompt)]):
            if chunk.content:
                yield chunk.content

