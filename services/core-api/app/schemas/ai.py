from typing import Any, Literal

from pydantic import BaseModel, Field


class AIReplyRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2_000)
    order_id: str | None = Field(default=None, max_length=100)
    product_id: str | None = Field(default=None, max_length=100)
    inquiry_id: str | None = Field(default=None, max_length=100)
    order_context: dict[str, Any] = Field(default_factory=dict)
    policy_context: str = Field(default="", max_length=10_000)
    session_id: str | None = Field(default=None, max_length=120)
    user_id: str | None = Field(default=None, max_length=120)
    organization_id: str | None = Field(default=None, max_length=120)
    request_id: str | None = Field(default=None, max_length=120)
    channel: Literal["demo-store", "ops-console", "api"] = "api"


class AIReplyResponse(BaseModel):
    answer: str
    model: str
    prompt_source: Literal["langfuse", "fallback"]
    prompt_version: str | None = None
    requires_human: bool = False
    category: Literal["DELIVERY", "CANCEL", "REFUND", "OTHER"] = "OTHER"
    risk: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    inquiry_id: str | None = None
    conversation_id: str | None = None
    trace_id: str | None = None


class CommerceInsightResponse(BaseModel):
    period: str
    insight: str
    model: str
    prompt_source: Literal["langfuse", "fallback"]
    prompt_version: str | None = None


class MonthlyReportRequest(BaseModel):
    period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    send_discord: bool = False


class MonthlyReportResponse(BaseModel):
    period: str
    report: str
    model: str
    prompt_source: Literal["langfuse", "fallback"]
    prompt_version: str | None = None
    discord_sent: bool = False


class SellerDailyReportRequest(BaseModel):
    org_id: str = Field(min_length=1, max_length=64)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    send_discord: bool = False


class SellerDailyReportResponse(BaseModel):
    date: str
    org_id: str
    org_name: str
    report: str
    snapshot: dict[str, Any]
    model: str
    prompt_source: Literal["langfuse", "fallback"]
    prompt_version: str | None = None
    discord_sent: bool = False
