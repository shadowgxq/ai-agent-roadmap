"""Small, in-memory policy evidence used by the W14 response subgraph."""

from support_agent.models import EvidenceRef, TicketCategory


POLICY_CORPUS: dict[TicketCategory, tuple[EvidenceRef, ...]] = {
    "billing": (
        EvidenceRef(
            source_id="billing_refund_001",
            title="账单与退款处理政策",
            snippet="退款申请需要核对订单号、支付记录和退款原因。",
        ),
        EvidenceRef(
            source_id="billing_charge_001",
            title="重复扣款核查政策",
            snippet="重复扣款需要核对订单和支付记录，确认后再进入人工处理。",
        ),
    ),
    "account": (
        EvidenceRef(
            source_id="account_security_001",
            title="账户安全与身份核验政策",
            snippet="涉及账户资料变更时，需要先完成账户身份核验。",
        ),
        EvidenceRef(
            source_id="account_email_001",
            title="登录邮箱变更政策",
            snippet="登录邮箱变更需要验证当前邮箱和目标邮箱的归属。",
        ),
    ),
    "product": (
        EvidenceRef(
            source_id="product_export_001",
            title="项目数据导出说明",
            snippet="项目数据可以从项目页面的数据导出入口导出为 CSV。",
        ),
    ),
    "technical": (
        EvidenceRef(
            source_id="technical_incident_001",
            title="接口故障排查政策",
            snippet="技术故障需要记录接口、错误信息、复现步骤和请求 ID。",
        ),
        EvidenceRef(
            source_id="technical_escalation_001",
            title="服务异常升级条件",
            snippet="服务完全不可用、数据丢失或安全风险需要升级处理。",
        ),
    ),
    "other": (
        EvidenceRef(
            source_id="general_support_001",
            title="一般咨询处理说明",
            snippet="一般咨询应基于已确认的公开信息回答，无法确认时明确说明。",
        ),
    ),
}
