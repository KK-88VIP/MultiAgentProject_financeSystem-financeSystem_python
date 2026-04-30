from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd


class AnalysisEngine:
    """Deterministic analytics engine for summary generation."""

    ENTITY_CANDIDATES = ("company_cn_name", "company_name")
    TIME_CANDIDATES = ("period_id", "year")

    def analyze(self, rows: List[Dict], metric_keys: List[str] | None = None) -> Dict[str, Any]:
        df = pd.DataFrame(rows)
        if df.empty:
            return {"type": "empty", "insights": {}}

        entity_col = self._pick_col(df, self.ENTITY_CANDIDATES)
        time_col = self._pick_col(df, self.TIME_CANDIDATES)
        numeric_cols = self._numeric_columns(df, metric_keys)
        if not numeric_cols:
            return {
                "type": "basic",
                "insights": {
                    "row_count": int(len(df)),
                    "sample": df.head(5).to_dict("records"),
                },
            }

        main_metric = numeric_cols[0]
        analysis: Dict[str, Any] = {
            "type": "composite",
            "main_metric": main_metric,
            "row_count": int(len(df)),
            "entity_field": entity_col,
            "time_field": time_col,
            "stats": self._stats(df, numeric_cols),
        }

        if entity_col:
            analysis["ranking"] = self._ranking(df, entity_col, main_metric)
        if time_col:
            analysis["trend"] = self._trend(df, time_col, main_metric)
            yoy = self._yoy(df, time_col, main_metric)
            if yoy:
                analysis["yoy"] = yoy
        outliers = self._outlier(df, main_metric)
        if outliers:
            analysis["outlier"] = outliers
        if len(numeric_cols) > 1:
            analysis["correlation"] = (
                df[numeric_cols].corr(numeric_only=True).fillna(0.0).to_dict()
            )
        return analysis

    @staticmethod
    def _pick_col(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    @staticmethod
    def _numeric_columns(df: pd.DataFrame, metric_keys: List[str] | None) -> List[str]:
        preferred = [m for m in (metric_keys or []) if m in df.columns]
        for col in preferred:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        auto = []
        for col in df.columns:
            converted = pd.to_numeric(df[col], errors="coerce")
            if converted.notna().any():
                df[col] = converted
            if pd.api.types.is_numeric_dtype(df[col]) and df[col].notna().any():
                auto.append(col)
        # keep metric order first
        ordered = []
        for col in preferred + auto:
            if col not in ordered:
                ordered.append(col)
        return ordered

    @staticmethod
    def _stats(df: pd.DataFrame, numeric_cols: List[str]) -> Dict[str, Dict[str, float]]:
        result: Dict[str, Dict[str, float]] = {}
        for col in numeric_cols:
            s = pd.to_numeric(df[col], errors="coerce")
            result[col] = {
                "max": float(s.max()) if s.notna().any() else 0.0,
                "min": float(s.min()) if s.notna().any() else 0.0,
                "mean": float(s.mean()) if s.notna().any() else 0.0,
            }
        return result

    @staticmethod
    def _ranking(df: pd.DataFrame, entity_col: str, metric_col: str) -> Dict[str, Any]:
        ranked = (
            df[[entity_col, metric_col]]
            .groupby(entity_col, as_index=False)[metric_col]
            .sum()
            .sort_values(metric_col, ascending=False)
        )
        return {
            "metric": metric_col,
            "top3": ranked.head(3).to_dict("records"),
            "bottom3": ranked.tail(3).to_dict("records"),
        }

    @staticmethod
    def _trend(df: pd.DataFrame, time_col: str, metric_col: str) -> List[Dict[str, Any]]:
        trend = (
            df[[time_col, metric_col]]
            .groupby(time_col, as_index=False)[metric_col]
            .sum()
            .sort_values(time_col)
        )
        return trend.to_dict("records")

    @staticmethod
    def _yoy(df: pd.DataFrame, time_col: str, metric_col: str) -> List[Dict[str, Any]]:
        grouped = (
            df[[time_col, metric_col]]
            .groupby(time_col, as_index=False)[metric_col]
            .sum()
            .sort_values(time_col)
        )
        if len(grouped) < 2:
            return []
        grouped["prev"] = grouped[metric_col].shift(1)
        grouped["yoy"] = grouped.apply(
            lambda r: (r[metric_col] - r["prev"]) / r["prev"]
            if pd.notna(r["prev"]) and float(r["prev"]) != 0.0
            else None,
            axis=1,
        )
        rows = []
        for _, r in grouped.iterrows():
            if pd.isna(r["yoy"]):
                continue
            rows.append({str(time_col): r[time_col], "yoy": float(r["yoy"])})
        return rows

    @staticmethod
    def _outlier(df: pd.DataFrame, metric_col: str) -> List[Dict[str, Any]]:
        series = pd.to_numeric(df[metric_col], errors="coerce")
        if series.notna().sum() < 10:
            return []
        mean = float(series.mean())
        std = float(series.std())
        if std == 0:
            return []
        mask = (series > mean + 2 * std) | (series < mean - 2 * std)
        return df[mask].head(10).to_dict("records")

