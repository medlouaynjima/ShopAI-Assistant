"""
Pydantic schemas for the FastAPI gateway.
"""
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class GuestChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class GuestChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[GuestChatMessage] = Field(default_factory=list, max_length=12)


class ChatResponse(BaseModel):
    response: str
    intent: str = "general"
    order_id: str = ""
    tracking_number: str = ""
    customer_email: str = ""
    tool_results: dict = Field(default_factory=dict)
    pending_cancellation_id: str = ""
    pending_cancellation_order_id: str = ""
    turn_id: str = ""


class ConversationMessageResponse(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    pending_cancellation_id: str = ""
    pending_cancellation_order_id: str = ""
    turn_id: str = ""
    feedback: str = ""


class ConversationHistoryResponse(BaseModel):
    session_id: str
    messages: list[ConversationMessageResponse]


class ConversationClearResponse(BaseModel):
    deleted_messages: int


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


class ReadinessResponse(BaseModel):
    status: str
    components: dict[str, str]


class CustomerOrderActionRequest(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=32)


class CheckoutItemRequest(BaseModel):
    sku: str = Field(..., min_length=1, max_length=32)
    quantity: int = Field(..., ge=1, le=99)


class CheckoutRequest(BaseModel):
    items: list[CheckoutItemRequest] = Field(..., min_length=1, max_length=30)
    shipping_address: str = Field(..., min_length=8, max_length=500)


class ReturnRequestBody(CustomerOrderActionRequest):
    reason: Literal[
        "defective",
        "wrong_item",
        "not_as_described",
        "changed_mind",
        "damaged",
        "too_late",
    ]


class SupportTicketRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=5000)
    order_id: str = Field(default="", max_length=32)


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    full_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=10, max_length=128)


class VerifyEmailRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class AuthMessageResponse(BaseModel):
    message: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    full_name: str


class CustomerProfileResponse(BaseModel):
    email: str
    full_name: str


class ProductResponse(BaseModel):
    sku: str
    name: str
    category: str
    description: str
    price: float
    inventory: int


class ProductCategoriesResponse(BaseModel):
    categories: list[str]


class OrderItemResponse(BaseModel):
    product_name: str
    sku: str
    quantity: int
    price: float


class CheckoutResponse(BaseModel):
    order_id: str
    status: str
    total: float
    created_at: str
    tracking_number: str | None = None
    items: list[OrderItemResponse]


class CustomerOrderResponse(BaseModel):
    order_id: str
    status: str
    total: float
    created_at: str
    tracking_number: str | None
    items: list[OrderItemResponse]


class CancellationResponse(BaseModel):
    cancellation_id: str
    order_id: str
    status: str
    message: str


class ReturnWorkflowResponse(BaseModel):
    rma_number: str
    order_id: str
    status: str
    refund_amount: float
    message: str


class SupportTicketResponse(BaseModel):
    ticket_id: str
    order_id: str | None
    status: str
    message: str


class AdminTicketResponse(BaseModel):
    ticket_id: str
    customer_email: str
    order_id: str | None
    description: str
    status: str
    created_at: str
    category: str
    priority: str
    ai_category: str
    ai_priority: str
    triage_summary: str
    suggested_team: str
    triage_reason: str
    triage_confidence: float
    triage_source: str
    subcategory: str
    suggested_next_action: str
    assigned_team: str
    first_staff_activity_at: str | None
    resolved_at: str | None
    reopened_count: int
    notes: list[dict] = Field(default_factory=list)


class AdminTicketUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved"]


class AdminTicketTriageUpdate(BaseModel):
    category: Literal["orders", "shipping", "returns", "payments", "products", "account", "complaint", "other"]
    priority: Literal["urgent", "high", "normal", "low"]


class AdminTicketAssignRequest(BaseModel):
    assigned_team: Literal[
        "Order management", "Logistics", "Returns", "Billing",
        "Product support", "Account security", "Customer care", "Unassigned",
    ]


class AdminTicketNoteRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=4000)


class CustomerSupportTicketResponse(BaseModel):
    ticket_id: str
    order_id: str | None
    status: str
    category: str
    priority: str
    triage_summary: str
    created_at: str


class ChatFeedbackRequest(BaseModel):
    turn_id: str = Field(..., min_length=1, max_length=64)
    feedback: Literal["helpful", "not_helpful", "unresolved"]


class QualityReviewRequest(BaseModel):
    turn_id: str = Field(..., min_length=1, max_length=64)
    label: Literal["incorrect_answer", "policy_issue", "tool_failure", "privacy", "unnecessary_escalation", "missed_escalation", "other"]
    note: str = Field(default="", max_length=2000)


class AdminDashboardResponse(BaseModel):
    total_orders: int
    total_customers: int
    open_tickets: int
    high_priority_tickets: int
    untriaged_tickets: int
    ticket_category_counts: dict[str, int]
    pending_return_approvals: int
    recent_tickets: list[AdminTicketResponse]


class AdminAuditResponse(BaseModel):
    event_id: str
    action: str
    resource_id: str
    details: dict
    created_at: str
