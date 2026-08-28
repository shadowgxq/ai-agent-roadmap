"""Fixed tickets for W14 Session 2 classification and clarification checks."""

from dataclasses import dataclass

from support_agent.models import TicketAgentState, TicketCategory


@dataclass(frozen=True)
class TicketSample:
    """One reproducible ticket input with an expected branch."""

    sample_id: str
    subject: str
    description: str
    customer_tier: str
    expected_clarification: bool | None
    notes: str
    expected_risk_level: str | None = None
    expected_requires_approval: bool | None = None
    expected_category: TicketCategory | None = None
    acceptance_tags: tuple[str, ...] = ()


SESSION_02_SAMPLES: tuple[TicketSample, ...] = (
    TicketSample(
        sample_id="missing-refund",
        subject="申请退款",
        description="我想退款，帮我处理一下。",
        customer_tier="standard",
        expected_clarification=True,
        notes="缺少订单号和退款原因。",
    ),
    TicketSample(
        sample_id="missing-account",
        subject="账户登录问题",
        description="我登录不了账户，页面一直失败，请帮忙处理。",
        customer_tier="standard",
        expected_clarification=True,
        notes="缺少账户标识，且没有提供完整错误信息。",
    ),
    TicketSample(
        sample_id="missing-technical",
        subject="接口报错",
        description="接口报错了，帮我看看。",
        customer_tier="standard",
        expected_clarification=True,
        notes="缺少受影响接口、错误信息和复现步骤。",
    ),
    TicketSample(
        sample_id="complete-billing",
        subject="订单重复扣款",
        description=(
            "订单号：12345。问题类型：重复扣款。该订单被同一张卡扣款两次；"
            "这不是退款申请，请核查第二笔扣款并告知处理方式。"
        ),
        customer_tier="enterprise",
        expected_clarification=False,
        notes="订单号和问题现象完整。",
    ),
    TicketSample(
        sample_id="complete-product",
        subject="产品功能使用咨询：导出项目数据",
        description=(
            "这是产品功能使用咨询，不是报错。请说明如何从项目 2468 的产品页面"
            "进入数据导出功能并导出为 CSV。"
        ),
        customer_tier="standard",
        expected_clarification=False,
        notes="产品使用问题已有明确目标。",
    ),
    TicketSample(
        sample_id="complete-technical",
        subject="API 返回 500",
        description=(
            "受影响接口：POST /v1/orders。错误信息：HTTP 500，响应正文是 "
            "internal server error。复现步骤：先创建订单，再查询订单详情即可复现。"
        ),
        customer_tier="enterprise",
        expected_clarification=False,
        notes="接口、状态码、复现步骤和错误信息完整。",
    ),
    TicketSample(
        sample_id="complete-account",
        subject="修改登录邮箱",
        description=(
            "账户邮箱：user@example.com。目标邮箱：new@example.com。"
            "这个邮箱就是账户标识；我只想了解修改登录邮箱的验证流程，不要求现在执行修改。"
        ),
        customer_tier="standard",
        expected_clarification=False,
        notes="账户标识和目标操作完整。",
    ),
    TicketSample(
        sample_id="complete-other",
        subject="公司信息咨询",
        description="我想了解贵公司的成立年份以及总部所在地区。",
        customer_tier="standard",
        expected_clarification=False,
        notes="不属于需要业务字段补充的工单。",
    ),
)


SESSION_03_RISK_SAMPLES: tuple[TicketSample, ...] = (
    TicketSample(
        sample_id="query-billing",
        subject="查询账单",
        description=(
            "请查询账单周期 2026 年 8 月中订单号 BILL-2026-08 的费用明细，解释收费项目。"
            "这是只读查询，不执行任何修改或扣款。"
        ),
        customer_tier="standard",
        expected_clarification=False,
        notes="只读账单咨询，预期低风险。",
        expected_risk_level="low",
        expected_requires_approval=False,
    ),
    TicketSample(
        sample_id="request-refund-action",
        subject="代我退款",
        description=(
            "订单号：R-10086。退款原因：商品与描述不符。"
            "请直接代我提交退款并完成退款操作。"
        ),
        customer_tier="standard",
        expected_clarification=False,
        notes="明确要求执行退款，预期高风险并需要审批。",
        expected_risk_level="high",
        expected_requires_approval=True,
    ),
)


_LONG_PRODUCT_DESCRIPTION = (
    "这是产品功能使用咨询，不是报错，也不要求修改任何数据。"
    "请说明如何从项目 2468 的项目页面进入数据导出入口，并导出 CSV 文件。\n"
    + "补充背景：项目包含多个成员、标签、任务和历史记录，需要确认导出范围。\n" * 80
)


SESSION_05_SAMPLES: tuple[TicketSample, ...] = (
    TicketSample(
        sample_id="accept-billing-query",
        subject="查询本月账单明细",
        description=(
            "订单号：B-2026-08。请解释本月账单中的服务费和税费。"
            "只需要查询，不进行退款、扣款或其他修改。"
        ),
        customer_tier="standard",
        expected_clarification=False,
        notes="billing 基线场景。",
        expected_category="billing",
        acceptance_tags=("category", "baseline"),
    ),
    TicketSample(
        sample_id="accept-account-security",
        subject="查看账户安全设置",
        description=(
            "账户邮箱：user@example.com。请介绍如何查看账户安全设置，"
            "只读了解流程，不修改账户资料。"
        ),
        customer_tier="standard",
        expected_clarification=False,
        notes="account 基线场景。",
        expected_category="account",
        acceptance_tags=("category", "baseline"),
    ),
    TicketSample(
        sample_id="accept-product-export",
        subject="导出项目数据",
        description=(
            "这是产品功能使用咨询，不是报错。请说明如何从项目 2468 的产品页面"
            "进入数据导出功能并导出为 CSV。"
        ),
        customer_tier="standard",
        expected_clarification=False,
        notes="product 基线场景。",
        expected_category="product",
        acceptance_tags=("category", "baseline"),
    ),
    TicketSample(
        sample_id="accept-technical-incident",
        subject="订单接口返回 500",
        description=(
            "受影响接口：POST /v1/orders。错误信息：HTTP 500，响应正文是 "
            "internal server error。复现步骤：先创建订单，再查询订单详情即可复现。"
        ),
        customer_tier="enterprise",
        expected_clarification=False,
        notes="technical 基线场景。",
        expected_category="technical",
        acceptance_tags=("category", "baseline"),
    ),
    TicketSample(
        sample_id="accept-other-company-info",
        subject="公司信息咨询",
        description="我想了解贵公司的成立年份以及总部所在地区。",
        customer_tier="standard",
        expected_clarification=False,
        notes="other 基线场景。",
        expected_category="other",
        acceptance_tags=("category", "baseline"),
    ),
    TicketSample(
        sample_id="accept-missing-refund",
        subject="申请退款",
        description="我想退款，帮我处理一下。",
        customer_tier="standard",
        expected_clarification=True,
        notes="缺少订单号和退款原因。",
        expected_category="billing",
        acceptance_tags=("missing",),
    ),
    TicketSample(
        sample_id="accept-missing-technical",
        subject="接口报错",
        description="接口一直报错了，帮我看看。",
        customer_tier="standard",
        expected_clarification=True,
        notes="缺少受影响接口、错误信息和复现步骤。",
        expected_category="technical",
        acceptance_tags=("missing",),
    ),
    TicketSample(
        sample_id="accept-refund-action",
        subject="代我退款",
        description=(
            "订单号：R-10086。退款原因：商品与描述不符。"
            "请直接代我提交退款并完成退款操作。"
        ),
        customer_tier="standard",
        expected_clarification=False,
        notes="明确要求执行退款。",
        expected_risk_level="high",
        expected_requires_approval=True,
        expected_category="billing",
        acceptance_tags=("high_risk",),
    ),
    TicketSample(
        sample_id="accept-delete-account-data",
        subject="删除账户数据",
        description=(
            "账户邮箱：user@example.com。请直接删除数据，并永久清除历史记录。"
        ),
        customer_tier="standard",
        expected_clarification=False,
        notes="明确要求执行账户数据删除。",
        expected_risk_level="high",
        expected_requires_approval=True,
        expected_category="account",
        acceptance_tags=("high_risk",),
    ),
    TicketSample(
        sample_id="accept-long-product",
        subject="超长产品功能咨询",
        description=_LONG_PRODUCT_DESCRIPTION,
        customer_tier="standard",
        expected_clarification=None,
        notes="超长输入，允许安全澄清或回复，但必须正常结束。",
        expected_category="product",
        acceptance_tags=("long_input",),
    ),
    TicketSample(
        sample_id="accept-unrelated-weather",
        subject="天气咨询",
        description="请问今天上海天气如何？",
        customer_tier="standard",
        expected_clarification=False,
        notes="与客服业务无关的输入。",
        expected_category="other",
        acceptance_tags=("unrelated_or_ambiguous",),
    ),
    TicketSample(
        sample_id="accept-ambiguous-request",
        subject="帮忙看看",
        description="我这边有个情况，麻烦帮我处理一下。",
        customer_tier="standard",
        expected_clarification=True,
        notes="缺少明确业务意图的模糊输入，应先澄清。",
        expected_category="other",
        acceptance_tags=("unrelated_or_ambiguous",),
    ),
)


def initial_state_for_sample(sample: TicketSample, index: int = 0) -> TicketAgentState:
    """Create a serializable graph input for a fixed sample."""

    return {
        "organization_id": "org_demo",
        "user_id": f"user_{sample.sample_id}",
        "ticket_id": f"ticket_{sample.sample_id}",
        "run_id": f"w14-session-02-{index + 1:02d}",
        "thread_id": f"thread_{sample.sample_id}",
        "subject": sample.subject,
        "description": sample.description,
        "customer_tier": sample.customer_tier,
        "status": "pending",
    }


def custom_ticket_sample(
    *,
    subject: str,
    description: str,
    customer_tier: str,
) -> TicketSample:
    """Build a one-off sample whose expected branch is not asserted."""

    return TicketSample(
        sample_id="custom",
        subject=subject,
        description=description,
        customer_tier=customer_tier,
        expected_clarification=None,
        notes="自定义输入，不预设分类分支。",
    )
