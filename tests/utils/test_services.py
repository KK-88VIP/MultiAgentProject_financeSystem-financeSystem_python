# 测试财务计算的核心“熔断”逻辑。

from app.services.metric_service import MetricCalculator


def test_safe_divide():
    service = MetricCalculator()

    # 正常除法
    assert service.safe_divide(100, 2) == 50

    # 分母为 0
    assert service.safe_divide(100, 0) is None

    # 分母为负数：当前实现允许负数分母，仅对 0 / None 熔断
    assert service.safe_divide(100, -5) == -20.0

    # 分子为 None
    assert service.safe_divide(None, 5) is None