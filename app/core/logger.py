# -*- coding: utf-8 -*-
"""
@file: logger.py
@version: 0.1.0
@purpose: 日志初始化工具，提供统一日志格式入口。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy

日志配置模块 (logger.py)

本模块负责初始化并配置全局日志系统，提供统一的日志格式、输出目标（控制台 + 文件）
以及日志滚动策略。模块导入时自动执行一次全局配置，其他模块可通过 `get_logger(__name__)`
获取对应的 Logger 实例，无需重复配置。

主要特性：
1. 支持开发环境控制台彩色输出（便于调试）
2. 全环境日志持久化至 `logs/` 目录
3. 按日志级别分离存储：常规日志 (`app.log`) 与错误日志 (`error.log`)
4. 自动滚动归档：单个日志文件超过 10MB 时轮转，最多保留 5 个备份
5. 线程安全的文件写入（RotatingFileHandler 内部加锁）

注意：本模块在 `app.core.config` 之后导入，依赖 `settings.LOG_DIR` 和 `settings.LOG_LEVEL`。
"""



import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings


def _create_log_dir():
    """
    确保日志目录存在

    为什么放在函数内：
    - 避免模块加载时自动创建目录（可能因权限问题报错）
    - 仅在首次初始化 Handler 时调用
    """
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)  # parents=True 支持多级目录创建
    return log_dir


def _get_formatter():
    """
    统一日志格式

    字段说明：
    - %(asctime)s：日志产生时间，精确到秒
    - %(levelname)s：日志级别（INFO/WARNING/ERROR）
    - %(name)s：Logger 名称（通常为模块路径，如 app.services.query_service）
    - %(message)s：实际日志内容
    """
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _create_file_handler(filename: str, level: int):
    """
    创建文件日志处理器（带滚动）

    Args:
        filename: 日志文件名（不含路径）
        level: 该 Handler 处理的最低日志级别（低于该级别的日志不会写入此文件）

    滚动策略：
    - maxBytes = 10MB：单文件达到该大小时自动轮转
    - backupCount = 5：保留最近 5 个备份文件（如 app.log.1, app.log.2 ...）
    - encoding = "utf-8"：避免中文乱码
    """
    log_dir = _create_log_dir()
    file_path = log_dir / filename

    handler = RotatingFileHandler(
        file_path,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(_get_formatter())
    return handler


def _create_console_handler():
    """
    控制台输出（仅开发环境使用）

    为什么不在生产环境输出控制台：
    - 生产环境日志量大，控制台输出会拖慢服务
    - 生产日志通常由容器平台（如 Docker / K8s）统一收集
    """
    handler = logging.StreamHandler()
    handler.setLevel(settings.LOG_LEVEL)  # 控制台输出的级别与全局配置一致
    handler.setFormatter(_get_formatter())
    return handler


def setup_logger():
    """
    初始化全局日志配置（只执行一次）

    注意事项：
    - 必须防止重复添加 Handler，否则同一条日志会输出多次
    - 通过检查 `logger.handlers` 是否为空来判断是否已初始化
    """
    logger = logging.getLogger()  # 获取 Root Logger
    logger.setLevel(settings.LOG_LEVEL)

    # 防止重复添加 handler（多次初始化问题）
    # 例如：在测试环境中可能多次导入本模块
    if logger.handlers:
        return logger

    # 控制台日志（仅开发环境）
    if settings.is_dev():
        logger.addHandler(_create_console_handler())

    # 文件日志
    # INFO 及以上级别的日志写入 app.log（包含 WARNING、ERROR）
    logger.addHandler(_create_file_handler("app.log", logging.INFO))
    # ERROR 及以上级别单独写入 error.log，便于快速定位错误
    logger.addHandler(_create_file_handler("error.log", logging.ERROR))

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取模块级 logger

    使用方式：
        logger = get_logger(__name__)

    原理：
    - __name__ 会传入当前模块的完整路径（如 app.services.query_service）
    - logging.getLogger 会返回该名称对应的 Logger 实例
    - 若该 Logger 不存在，则自动创建并继承 Root Logger 的配置
    """
    return logging.getLogger(name)


# 初始化全局 logger（应用启动时调用一次）
# 由于该语句在模块导入时执行，因此整个应用只需导入一次本模块即可完成日志初始化
setup_logger()



"""
扩展阅读：

1. 为什么使用 RotatingFileHandler 而不是 TimedRotatingFileHandler？
   - 本系统日志量主要由用户查询次数决定，按大小轮转更可控，避免某个时段突发大量日志撑爆磁盘。

2. 如何在异步代码中安全记录日志？
   - Python logging 模块本身是线程安全的，但在异步环境中无需额外处理，直接调用 logger.info() 即可。

3. 如何接入 ELK / Loki 等集中式日志系统？
   - 后期可通过添加自定义 Handler（如 `logstash_async` 或 `python-json-logger`）输出 JSON 格式日志，
     无需修改现有业务代码。
"""