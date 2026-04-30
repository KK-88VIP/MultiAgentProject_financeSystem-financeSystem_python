from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class FilterItem(BaseModel):
    name: str
    type: Literal["select", "multi_select"] = "select"
    default: Optional[int | str] = None


class Dataset(BaseModel):
    metrics: List[str]
    dimensions: List[str] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)
    filters: Dict = Field(default_factory=dict)
    order_by: Optional[List[Dict]] = None
    limit: Optional[int] = 100


class ChartConfig(BaseModel):
    type: str
    x: str
    y: str


class Position(BaseModel):
    x: int
    y: int
    w: int
    h: int


class Widget(BaseModel):
    id: str
    type: str = "chart"
    dataset: Dataset
    chart: ChartConfig
    position: Position


class DashboardDSL(BaseModel):
    id: str
    title: str
    version: str = "v1"
    filters: List[FilterItem] = Field(default_factory=list)
    widgets: List[Widget]

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if v != "v1":
            raise ValueError("DSL version must be v1")
        return v


class DashboardRenderRequest(BaseModel):
    dsl: Optional[DashboardDSL] = None
    dashboard_id: Optional[str] = None
    runtime_filters: Dict = Field(default_factory=dict)

