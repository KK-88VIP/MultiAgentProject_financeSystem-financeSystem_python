# -*- coding: utf-8 -*-
"""
@file: config.py
@version: 0.1.0
@purpose: 应用配置管理，统一加载环境变量与默认配置。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy

配置管理核心模块 (config.py)

本模块负责从环境变量（.env 文件）中加载所有系统运行参数，并通过 Pydantic Settings
提供强类型、可校验的全局配置单例。

主要功能：
1. 自动读取 .env 文件，支持开发/测试/生产环境切换
2. 对关键配置项（环境类型、行数限制、日志级别）进行合法性校验
3. 提供工具方法快速获取数据库、LLM 等子模块的配置字典
4. 利用 LRU 缓存实现单例模式，避免重复读取文件

全局单例 `settings` 可直接在项目任意位置导入使用，无需重复实例化。
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    全局配置对象（单例）

    特点：
    - 自动从 .env 加载
    - 类型安全
    - 支持默认值
    - 支持环境切换
    """

    # =========================
    # 基础服务配置
    # =========================
    APP_NAME: str = "Finance AI System"   # 应用名称，用于日志标识或 OpenAPI 文档标题
    APP_VERSION: str = "0.2.0"            # API 文档版本号
    APP_ENV: str = "dev"                  # 运行环境：dev（开发）/ test（测试）/ prod（生产）
    DEBUG: bool = True                    # 是否开启调试模式，影响异常详情是否返回客户端
    HOST: str = "0.0.0.0"                # FastAPI 监听的 IP 地址
    PORT: int = 8000                      # 服务端口号
    # 仅本地联调：当前端/代理未传 X-User-Role: admin 时，仍希望 /filters 有数据，可设 True（切勿用于生产）
    DEV_ASSUME_ADMIN_FOR_FILTERS: bool = False
    # 仅 APP_ENV=dev：下列 user_id（英文逗号分隔）一律视为管理员，无需 role 参数或 X-User-Role（切勿用于生产）
    DEV_ADMIN_USER_IDS: str = ""

    # =========================
    # 数据库配置（MySQL）
    # =========================
    DATABASE_URL: str                     # 必填，数据库连接串（格式：mysql+aiomysql://user:pass@host:port/db）

    DB_POOL_SIZE: int = 10                # 连接池维持的连接数
    DB_MAX_OVERFLOW: int = 20             # 连接池超限时允许临时增加的连接数
    DB_POOL_TIMEOUT: int = 30             # 获取连接的超时时间（秒）
    DB_POOL_RECYCLE: int = 1800           # 连接最大存活时间（秒），超过后回收重建，降低断连概率
    DB_POOL_PRE_PING: bool = True         # 取连接前先 ping，避免拿到已断开的坏连接
    DB_CONNECT_TIMEOUT: int = 10          # 建立数据库连接超时时间（秒）
    DB_READ_TIMEOUT: int = 30             # 数据读取超时时间（秒）
    DB_WRITE_TIMEOUT: int = 30            # 数据写入超时时间（秒）

    # =========================
    # LLM 配置（Qwen）
    # =========================
    LLM_API_KEY: str                      # 通义千问 API Key，必填
    LLM_BASE_URL: Optional[str] = None    # 自定义 API 代理地址，不填则使用官方地址
    LLM_MODEL: str = "qwen-plus"          # 使用的模型名称（qwen-turbo / qwen-plus / qwen-max）

    LLM_TIMEOUT: int = 30                 # LLM 请求超时时间（秒）
    LLM_MAX_TOKENS: int = 2048            # 单次请求最大生成 Token 数，防止输出过长

    # =========================
    # 查询控制
    # =========================
    DEFAULT_LIMIT: int = 1000             # SQL 默认返回行数上限（若用户未指定）
    MAX_LIMIT: int = 5000                 # 强制最大返回行数（任何查询不得超过此值）
    SQL_TIMEOUT_MS: int = 3000            # 数据库查询超时时间（毫秒）

    # =========================
    # Redis（对话上下文）
    # =========================
    REDIS_URL: str = "redis://localhost:6379/0"   # Redis 连接地址，用于存储会话上下文
    REDIS_TTL_SECONDS: int = 1800                 # 会话上下文过期时间（30分钟）

    # =========================
    # 安全配置
    # =========================
    API_TOKEN: Optional[str] = None       # 用于 OpenClaw 回调的验证 Token（若不填则不校验）
    ALLOWED_HOSTS: List[str] = ["*"]      # CORS 允许的主机列表，生产环境建议限制为具体域名

    # =========================
    # 飞书配置
    # =========================
    FEISHU_BOT_TOKEN: Optional[str] = None # 飞书机器人 Token，用于消息回调验证

    # =========================
    # 日志配置
    # =========================
    LOG_LEVEL: str = "INFO"               # 日志输出级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
    LOG_DIR: str = "logs"                 # 日志文件存放目录（相对项目根路径）

    # =========================
    # Pydantic Settings 配置
    # =========================
    model_config = SettingsConfigDict(
        env_file=".env",                  # 指定环境变量文件名
        env_file_encoding="utf-8",        # 文件编码
        case_sensitive=True,              # 环境变量名区分大小写（与 Python 变量名一致）
        extra="ignore"                    # 忽略 .env 中未定义的额外字段，避免意外错误
    )

    # =========================
    # 校验逻辑（关键）
    # 确保运行时配置的合法性，尽早暴露配置错误
    # =========================

    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        """
        校验环境名称，仅允许 dev / test / prod。
        防止误写为 development 等不规范值。
        """
        allowed = {"dev", "test", "prod"}
        if v not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}")
        return v

    @field_validator("DEFAULT_LIMIT")
    @classmethod
    def validate_limit(cls, v: int) -> int:
        """
        默认行数必须大于 0，否则后续查询逻辑会出错。
        """
        if v <= 0:
            raise ValueError("DEFAULT_LIMIT must be > 0")
        return v

    @field_validator("MAX_LIMIT")
    @classmethod
    def validate_max_limit(cls, v: int, info: ValidationInfo) -> int:
        """
        最大行数必须大于等于默认行数，否则会出现“默认值超出上限”的矛盾。
        """
        data = info.data or {}
        default_limit = int(data.get("DEFAULT_LIMIT", 1000))
        if v < default_limit:
            raise ValueError("MAX_LIMIT must >= DEFAULT_LIMIT")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """
        校验日志级别，防止配置了不存在的级别导致日志模块异常。
        """
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v

    # =========================
    # 工具方法（很重要）
    # 避免外部代码直接访问字段，提供更语义化的封装
    # =========================

    def is_dev(self) -> bool:
        """是否为开发环境"""
        return self.APP_ENV == "dev"

    def is_prod(self) -> bool:
        """是否为生产环境"""
        return self.APP_ENV == "prod"

    def get_db_config(self) -> dict:
        """
        返回数据库连接池参数字典，便于传递给 SQLAlchemy 的 create_async_engine。
        避免外部代码直接拼接字段名。
        """
        return {
            "pool_size": self.DB_POOL_SIZE,
            "max_overflow": self.DB_MAX_OVERFLOW,
            "pool_timeout": self.DB_POOL_TIMEOUT,
            "pool_recycle": self.DB_POOL_RECYCLE,
            "pool_pre_ping": self.DB_POOL_PRE_PING,
            "connect_args": {
                "connect_timeout": self.DB_CONNECT_TIMEOUT,
                "read_timeout": self.DB_READ_TIMEOUT,
                "write_timeout": self.DB_WRITE_TIMEOUT,
            },
        }

    def get_llm_config(self) -> dict:
        """
        返回 LLM 调用所需的参数字典，便于统一传递给 LangChain 的 ChatOpenAI 等客户端。
        """
        return {
            "api_key": self.LLM_API_KEY,
            "base_url": self.LLM_BASE_URL,
            "model": self.LLM_MODEL,
            "timeout": self.LLM_TIMEOUT,
            "max_tokens": self.LLM_MAX_TOKENS,
        }


# =========================
# 单例模式（必须）
# =========================

@lru_cache()
def get_settings() -> Settings:
    """
    获取全局唯一配置实例

    为什么必须缓存：
    - 避免重复读取 .env（每次读取都会解析文件）
    - 提升性能（尤其在多个依赖模块同时导入时）
    """
    return Settings()


# 全局直接使用（推荐）
# 例如：from app.core.config import settings
settings = get_settings()