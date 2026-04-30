# 定义基础接口，减少重复的 session 管理代码。
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

class BaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute_query(self, sql: str, params: dict = None):
        result = await self.session.execute(text(sql), params or {})
        columns = result.keys()
        return [dict(zip(columns, row)) for row in result.fetchall()]
