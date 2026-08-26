"""LangChain agent factory for ticket support tasks."""

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel

from support_agent.models import TicketClassification
from support_agent.tools import lookup_ticket_policy


SYSTEM_PROMPT = """你是客服工单分类 Agent。

你的任务是识别工单类别和优先级，并返回 TicketClassification。
涉及退款、账单、技术或账户政策时，先调用 lookup_ticket_policy 查询只读政策。
如果缺少政策要求的关键信息，将 needs_clarification 设为 true，并在 reason 中说明缺少什么。
不要承诺退款、修改账户或伪造用户未提供的信息。
"""


def create_support_agent(model: BaseChatModel):
    """Create the framework-managed model-tool-model loop."""

    return create_agent(
        model=model,
        tools=[lookup_ticket_policy],
        system_prompt=SYSTEM_PROMPT,
        response_format=ToolStrategy(TicketClassification),
        name="support_agent",
    )
