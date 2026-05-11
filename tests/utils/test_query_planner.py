from planner.query_planner import QueryPlanner


class _IR:
    def __init__(self):
        self.metrics = ["revenue"]
        self.filters = {"year": [2024], "company": ["腾讯"]}
        self.group_by = ["company"]
        self.order_by = [{"field": "revenue", "direction": "desc"}]
        self.limit = 100


def test_query_planner_builds_plan():
    plan = QueryPlanner().plan(_IR())
    dumped = plan.model_dump()
    assert dumped["table"] == "pl"
    assert dumped["metric_keys"] == ["revenue"]
    assert dumped["filters"]["year"] == [2024]


class _IRMultiYearNoGroup:
    """多年份、未声明 group_by 时应自动按年分组，避免 SQL 聚成单行。"""

    def __init__(self):
        self.metrics = ["total_assets"]
        self.filters = {"year": [2022, 2023, 2024], "company": ["华为"]}
        self.group_by = []
        self.order_by = []
        self.limit = 100


def test_query_planner_auto_groups_by_year_when_multi_year():
    plan = QueryPlanner().plan(_IRMultiYearNoGroup())
    dumped = plan.model_dump()
    assert dumped["table"] == "bs"
    assert "year" in dumped["group_by"]

