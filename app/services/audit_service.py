# -*- coding: utf-8 -*-
"""
@file: audit_service.py
@version: 0.2.0
@purpose: 审计日志服务，占位用于记录问数全链路审计信息。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Dict, Optional

audit_logger = logging.getLogger("audit")


class AuditService:
    @staticmethod
    async def log_query(
        user_id: str,
        query: str,
        sql: str,
        status: str,
        *,
        intent: Optional[Dict[str, Any]] = None,
        latency_ms: Optional[int] = None,
    ) -> None:
        """
        异步记录审计日志。

        生产环境可改为写入 MySQL `audit_log` 表或日志平台。
        """
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "user_id": user_id,
            "query": query,
            "sql": sql,
            "status": status,
            "intent": intent or {},
            "latency_ms": latency_ms,
        }
        audit_logger.info(f"AUDIT_LOG: {json.dumps(log_entry, ensure_ascii=False)}")
