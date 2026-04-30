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

