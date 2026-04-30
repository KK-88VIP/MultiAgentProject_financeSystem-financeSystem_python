from app.services.analysis_engine import AnalysisEngine


def test_analysis_engine_detects_ranking_and_trend():
    rows = [
        {"company_cn_name": "腾讯", "period_id": "2023", "revenue": 100.0},
        {"company_cn_name": "阿里", "period_id": "2023", "revenue": 80.0},
        {"company_cn_name": "腾讯", "period_id": "2024", "revenue": 120.0},
        {"company_cn_name": "阿里", "period_id": "2024", "revenue": 90.0},
    ]
    out = AnalysisEngine().analyze(rows, ["revenue"])
    assert out["main_metric"] == "revenue"
    assert "ranking" in out
    assert "trend" in out
    assert out["ranking"]["top3"][0]["company_cn_name"] == "腾讯"

