from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CategoryCreate(BaseModel):
    name: str
    icon: str = "🛒"
    color: str = "#6C5CE7"


class CategoryOut(BaseModel):
    id: int
    name: str
    icon: str
    color: str

    class Config:
        from_attributes = True


class PurchaseCreate(BaseModel):
    amount: float
    category_id: Optional[int] = None
    description: Optional[str] = None
    date: Optional[datetime] = None


class PurchaseOut(BaseModel):
    id: int
    amount: float
    description: Optional[str]
    date: datetime
    category: Optional[CategoryOut]

    class Config:
        from_attributes = True


class BudgetCreate(BaseModel):
    limit_amount: float
    category_id: Optional[int] = None
    period: str = "month"


class BudgetOut(BaseModel):
    id: int
    limit_amount: float
    period: str
    category: Optional[CategoryOut]

    class Config:
        from_attributes = True


class BudgetStatus(BaseModel):
    budget: BudgetOut
    spent: float
    remaining: float
    percent_used: float


class SummaryByCategory(BaseModel):
    category_id: Optional[int]
    category_name: str
    icon: str
    color: str
    total: float


class SummaryByMonth(BaseModel):
    month: str  # "2026-09"
    total: float


class StatsSummary(BaseModel):
    by_category: list[SummaryByCategory]
    by_month: list[SummaryByMonth]
    total_all_time: float
    total_current_month: float
