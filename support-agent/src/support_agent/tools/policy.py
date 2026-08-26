"""Read-only support policy lookup tool."""

from typing import Literal, TypedDict

from langchain.tools import tool
from pydantic import BaseModel, Field


PolicyCategory = Literal["refund", "billing", "technical", "account"]


class TicketPolicyQuery(BaseModel):
    """Typed input accepted by the policy lookup tool."""

    category: PolicyCategory = Field(description="需要查询的工单政策类别")


class TicketPolicyResult(TypedDict):
    """Structured policy data returned to the model."""

    category: PolicyCategory
    summary: str
    required_information: list[str]
    escalation_conditions: list[str]


POLICIES: dict[PolicyCategory, TicketPolicyResult] = {
    "refund": {
        "category": "refund",
        "summary": "退款申请需要核对订单、支付记录和退款原因。",
        "required_information": ["order_id", "refund_reason"],
        "escalation_conditions": ["重复扣款", "支付争议", "高金额订单"],
    },
    "billing": {
        "category": "billing",
        "summary": "账单问题需要核对账单周期、金额和相关订单。",
        "required_information": ["billing_period", "order_id"],
        "escalation_conditions": ["重复扣款", "金额异常", "用户否认交易"],
    },
    "technical": {
        "category": "technical",
        "summary": "技术问题需要记录复现步骤、错误信息和运行环境。",
        "required_information": ["reproduction_steps", "error_message"],
        "escalation_conditions": ["服务完全不可用", "数据丢失", "安全风险"],
    },
    "account": {
        "category": "account",
        "summary": "账户问题需要先确认用户身份和受影响的账户功能。",
        "required_information": ["account_id", "affected_feature"],
        "escalation_conditions": ["账户被盗", "无法完成身份验证", "权限异常"],
    },
}


@tool(args_schema=TicketPolicyQuery)
def lookup_ticket_policy(category: PolicyCategory) -> TicketPolicyResult:
    """查询指定类别的客服处理政策；该工具只读，不修改工单或账户。"""

    return POLICIES[category]
