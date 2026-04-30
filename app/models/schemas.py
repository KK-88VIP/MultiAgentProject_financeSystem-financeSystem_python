# 为了方便前端调用，我们将通用的 API 响应结构和请求参数统一收口。


from pydantic import BaseModel, Field
from typing import Any, Optional, List

class APIResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None

class QueryRequest(BaseModel):
    question: str = Field(..., description="用户自然语言提问")
    conversation_id: str = Field(..., description="会话ID")

class ChartDataRequest(BaseModel):
    metric: str
    company_codes: List[str]
    period_ids: List[str]
    chart_type: Optional[str] = None