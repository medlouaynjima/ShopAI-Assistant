"""
FastAPI Routes — the Agent Gateway.
"""
import hmac
import re
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from src.agent.graph import agent_graph
from src.agent.entities import extract_order_id
from src.agent.state import AgentState
from src.api.schemas import (
    CancellationResponse,
    AdminDashboardResponse,
    AdminAuditResponse,
    AdminTicketResponse,
    AdminTicketUpdate,
    AdminTicketTriageUpdate,
    AdminTicketAssignRequest,
    AdminTicketNoteRequest,
    AuthMessageResponse,
    AuthTokenResponse,
    ChatRequest,
    ChatResponse,
    CheckoutRequest,
    CheckoutResponse,
    ConversationClearResponse,
    ConversationHistoryResponse,
    CustomerOrderActionRequest,
    CustomerOrderResponse,
    CustomerProfileResponse,
    GuestChatRequest,
    HealthResponse,
    ReadinessResponse,
    LoginRequest,
    ProductCategoriesResponse,
    ProductResponse,
    RegisterRequest,
    ReturnRequestBody,
    ReturnWorkflowResponse,
    SupportTicketRequest,
    SupportTicketResponse,
    CustomerSupportTicketResponse,
    VerifyEmailRequest,
    ChatFeedbackRequest,
    QualityReviewRequest,
)
from src.config import settings
from src.observability.langfuse_setup import trace_workflow
from src.services.auth_service import AuthService, EmailDeliveryError
from src.services.checkout_service import CheckoutService
from src.services.admin_service import AdminService
from src.services.conversation_service import ConversationService
from src.services.operations_service import OperationsService
from src.services.order_service import OrderService
from src.services.product_service import ProductService
from src.services.returns_service import ReturnsService
from src.services.database import get_connection
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)
auth_service = AuthService()
operations_service = OperationsService()
order_service = OrderService()
product_service = ProductService()
returns_service = ReturnsService()
admin_service = AdminService()
conversation_service = ConversationService()
checkout_service = CheckoutService()


def get_current_customer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Sign in to access this endpoint.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    customer = auth_service.get_customer_for_token(credentials.credentials)
    if not customer:
        raise HTTPException(
            status_code=401,
            detail="Session is invalid or expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    customer["access_token"] = credentials.credentials
    return customer


def _run_operation(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _require_admin_key(provided_key: str | None) -> None:
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin approval is disabled until ADMIN_API_KEY is configured.",
        )
    if not provided_key or not hmac.compare_digest(provided_key, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid admin API key is required.",
        )


@router.get("/admin/dashboard", response_model=AdminDashboardResponse)
async def get_admin_dashboard(
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        return admin_service.dashboard()


@router.get("/admin/llm-metrics")
async def get_admin_llm_metrics(
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        from src.observability.llm_metrics import metrics_snapshot

        return metrics_snapshot()


@router.get("/admin/analytics")
async def get_admin_analytics(
        date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        status_filter: str | None = Query(default=None, alias="status", max_length=20),
        category_filter: str | None = Query(default=None, alias="category", max_length=24),
        priority_filter: str | None = Query(default=None, alias="priority", max_length=12),
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        try:
            return admin_service.analytics(date_from, date_to, status_filter, category_filter, priority_filter)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Dates must be valid YYYY-MM-DD values.") from exc


@router.get("/admin/quality-queue")
async def get_admin_quality_queue(
        limit: int = Query(default=100, ge=1, le=200),
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        return admin_service.quality_queue(limit)


@router.post("/admin/quality-reviews")
async def post_admin_quality_review(
        req: QualityReviewRequest,
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        try:
            return admin_service.add_quality_review(req.turn_id, "admin", req.label, req.note)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/admin/tickets", response_model=list[AdminTicketResponse])
async def list_admin_tickets(
        status_filter: str | None = Query(default=None, alias="status", max_length=20),
        category_filter: str | None = Query(default=None, alias="category", max_length=24),
        priority_filter: str | None = Query(default=None, alias="priority", max_length=12),
        limit: int = Query(default=100, ge=1, le=200),
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        try:
            return admin_service.list_tickets(status_filter, category_filter, priority_filter, limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/admin/returns/pending")
async def list_pending_admin_returns(
        limit: int = Query(default=100, ge=1, le=200),
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        return admin_service.pending_returns(limit)


@router.get("/admin/audit", response_model=list[AdminAuditResponse])
async def list_admin_audit(
        limit: int = Query(default=100, ge=1, le=200),
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        return admin_service.recent_audit(limit)


@router.patch("/admin/tickets/{ticket_id}", response_model=AdminTicketResponse)
async def update_admin_ticket(
        ticket_id: str,
        req: AdminTicketUpdate,
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        result = _run_operation(admin_service.update_ticket, ticket_id, req.status)
        return AdminTicketResponse(**result)


@router.patch("/admin/tickets/{ticket_id}/triage", response_model=AdminTicketResponse)
async def update_admin_ticket_triage(
        ticket_id: str,
        req: AdminTicketTriageUpdate,
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        result = _run_operation(
            admin_service.update_ticket_triage, ticket_id, req.category, req.priority
        )
        return AdminTicketResponse(**result)


@router.post("/admin/tickets/{ticket_id}/triage", response_model=AdminTicketResponse)
async def rerun_admin_ticket_triage(
        ticket_id: str,
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        try:
            result = await run_in_threadpool(admin_service.rerun_ticket_triage, ticket_id)
            return AdminTicketResponse(**result)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/admin/tickets/{ticket_id}/team", response_model=AdminTicketResponse)
async def assign_admin_ticket_team(
        ticket_id: str,
        req: AdminTicketAssignRequest,
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        result = _run_operation(admin_service.assign_ticket, ticket_id, req.assigned_team)
        result["notes"] = []
        return AdminTicketResponse(**result)


@router.post("/admin/tickets/{ticket_id}/notes")
async def add_admin_ticket_note(
        ticket_id: str,
        req: AdminTicketNoteRequest,
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
        _require_admin_key(x_admin_key)
        return _run_operation(admin_service.add_ticket_note, ticket_id, req.note)


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


def _database_ready() -> bool:
    connection = get_connection()
    try:
        connection.execute("SELECT 1").fetchone()
        return True
    finally:
        connection.close()


def _redis_ready() -> bool | None:
    if not settings.redis_url:
        return None
    from redis import Redis

    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
        retry_on_timeout=False,
    )
    try:
        return bool(client.ping())
    finally:
        client.close()


@router.get("/ready", response_model=ReadinessResponse)
async def readiness():
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import JSONResponse

    import logging
    logger = logging.getLogger(__name__)
    try:
        database_ok = await run_in_threadpool(_database_ready)
    except Exception as exc:
        logger.warning("Readiness database probe failed: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "components": {"database": "unavailable"}},
        )
    components = {"database": "ok" if database_ok else "unavailable"}
    try:
        redis_ok = await run_in_threadpool(_redis_ready)
        components["cache"] = "not_configured" if redis_ok is None else "ok" if redis_ok else "degraded"
    except Exception as exc:
        logger.warning("Readiness cache probe failed: %s", type(exc).__name__)
        components["cache"] = "degraded"
    return ReadinessResponse(status="ready", components=components)


@router.post("/auth/register", response_model=AuthMessageResponse, status_code=202)
async def register_customer(req: RegisterRequest):
    try:
        auth_service.register(req.email, req.full_name, req.password)
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AuthMessageResponse(
        message="If this address can be registered, a verification code has been emailed."
    )


@router.post("/auth/verify-email", response_model=AuthMessageResponse)
async def verify_customer_email(req: VerifyEmailRequest):
    try:
        auth_service.verify_email(req.email, req.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AuthMessageResponse(message="Email verified. You can now sign in.")


@router.post("/auth/login", response_model=AuthTokenResponse)
async def login_customer(req: LoginRequest):
    try:
        token, full_name, expires_at = auth_service.login(req.email, req.password)
    except PermissionError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AuthTokenResponse(
        access_token=token,
        full_name=full_name,
        expires_at=expires_at,
    )


@router.get("/auth/me", response_model=CustomerProfileResponse)
async def get_customer_profile(customer: dict = Depends(get_current_customer)):
    return CustomerProfileResponse(email=customer["email"], full_name=customer["full_name"])


@router.post("/auth/logout", response_model=AuthMessageResponse)
async def logout_customer(
    customer: dict = Depends(get_current_customer),
):
    auth_service.logout(customer["access_token"])
    return AuthMessageResponse(message="Signed out.")


@router.get("/products/categories", response_model=ProductCategoriesResponse)
async def list_product_categories():
    """Public storefront categories; account data remains behind authentication."""
    return ProductCategoriesResponse(categories=product_service.get_categories())


@router.get("/products", response_model=list[ProductResponse])
async def list_products(
    query: str = Query(default="", max_length=100),
    category: str = Query(default="", max_length=80),
    in_stock: bool = False,
):
    """Public product catalog and availability for the storefront."""
    products = product_service.search(query, category, in_stock)
    return [
        ProductResponse(
            sku=product.sku,
            name=product.name,
            category=product.category,
            description=product.description,
            price=product.price,
            inventory=product.inventory,
        )
        for product in products
    ]


@router.get("/orders/mine", response_model=list[CustomerOrderResponse])
async def list_customer_orders(
    customer: dict = Depends(get_current_customer),
):
    orders = order_service.get_orders_by_email(customer["email"])
    return [
        CustomerOrderResponse(
            order_id=order.order_id,
            status=order.status,
            total=order.total,
            created_at=order.created_at,
            tracking_number=order.tracking_number,
            items=[
                {
                    "product_name": item.product_name,
                    "sku": item.sku,
                    "quantity": item.quantity,
                    "price": item.price,
                }
                for item in order.items
            ],
        )
        for order in orders
    ]


@router.post("/orders/checkout", response_model=CheckoutResponse)
async def create_checkout_order(
    req: CheckoutRequest,
    customer: dict = Depends(get_current_customer),
):
    """Create a demo order after validating current catalog inventory and prices."""
    result = _run_operation(
        checkout_service.create_demo_order,
        email=customer["email"],
        customer_name=customer["full_name"],
        shipping_address=req.shipping_address,
        items=[item.model_dump() for item in req.items],
    )
    return CheckoutResponse(**result)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    customer: dict = Depends(get_current_customer),
):
    """Run the agent as the authenticated customer."""

    history = conversation_service.get_messages(
        customer["email"], req.session_id
    )
    messages = [
        SystemMessage(content=(
            "You are an English-language customer support assistant for Morrow. "
            "Write all responses clearly and professionally in English. "
            "Use prior conversation only for context; account data must always "
            "come from the authenticated customer and authorized tools."
        )),
    ]
    messages.extend(
        HumanMessage(content=message["content"])
        if message["role"] == "user"
        else AIMessage(content=message["content"])
        for message in history
    )
    messages.append(HumanMessage(content=req.message))

    turn_started = time.perf_counter()
    initial_state: AgentState = {
        "messages": messages,
        "intent": "",
        "specialist": "",
        "order_id": "",
        "tracking_number": "",
        "return_reason": "",
        "customer_email": customer["email"],
        "tool_results": {},
        "tool_events": [],
        "final_response": "",
        "retry_count": 0,
        "error_message": "",
    }

    with trace_workflow() as workflow_trace:
        result = await run_in_threadpool(agent_graph.invoke, initial_state, {})
        workflow_trace.intent = result.get("intent", "unknown")
        if result.get("error_message"):
            workflow_trace.status = "error"

    response_text = result.get("final_response", "Sorry, something went wrong.")
    tool_results = dict(result.get("tool_results") or {})
    cancellation_order_id = str(result.get("order_id") or "").strip().upper()
    if result.get("intent") == "order_cancellation" and not cancellation_order_id:
        cancellation_order_id = extract_order_id(req.message)
    if result.get("intent") == "order_cancellation" and not cancellation_order_id:
        prior_request = re.search(
            r"Cancellation request\s+(CAN-[A-Z0-9-]+)\s+for order\s+#?([A-Z0-9-]+)\s+is pending_confirmation",
            str(tool_results.get("request_order_cancellation", "")),
            re.IGNORECASE,
        )
        if prior_request:
            cancellation_order_id = prior_request.group(2).upper()

    if result.get("intent") == "order_cancellation":
        if not cancellation_order_id:
            # Resolve a singular cancellation request using only the signed-in account.
            cancellable_orders = await run_in_threadpool(
                order_service.get_cancellable_orders_by_email,
                customer["email"],
            )
            if len(cancellable_orders) == 1:
                cancellation_order_id = cancellable_orders[0].order_id
            elif len(cancellable_orders) > 1:
                options = "\n".join(
                    f"• **{order.order_id}** — {order.status.replace('_', ' ')} — "
                    f"{', '.join(item.product_name for item in order.items)}"
                    for order in cancellable_orders[:10]
                )
                response_text = (
                    "I found several orders on your account that may be cancelled:\n\n"
                    f"{options}\n\nWhich one would you like me to cancel? "
                    "Nothing has been changed yet."
                )
            else:
                response_text = (
                    "I checked your account, but none of your orders are currently "
                    "eligible for cancellation."
                )

        if cancellation_order_id:
            try:
                request = await run_in_threadpool(
                    operations_service.request_cancellation,
                    cancellation_order_id,
                    customer["email"],
                )
                tool_results["request_order_cancellation"] = (
                    f"Cancellation request {request['cancellation_id']} for order "
                    f"#{request['order_id']} is {request['status']}. "
                    "The order has not been cancelled. Customer confirmation is required."
                )
            except (LookupError, PermissionError):
                response_text = (
                    f"I couldn't find order **{cancellation_order_id}** on your account. "
                    "I haven't changed anything."
                )
            except ValueError as error:
                response_text = str(error)

    return_order_id = str(result.get("order_id") or "").strip().upper()
    if result.get("intent") == "return_request":
        if return_order_id:
            order = await run_in_threadpool(
                order_service.get_order_for_customer,
                return_order_id,
                customer["email"],
            )
            if not order:
                response_text = (
                    f"I couldn't find order **{return_order_id}** on your account. "
                    "Check the order number in My orders and try again."
                )
            else:
                eligible, eligibility_message = await run_in_threadpool(
                    order_service.can_return, return_order_id
                )
                if not eligible:
                    response_text = (
                        f"Order **{return_order_id}** can't be returned: {eligibility_message} "
                        "No return request or refund was created."
                    )
                elif not result.get("return_reason"):
                    response_text = (
                        f"Order **{return_order_id}** is eligible for return. "
                        "What is the reason: changed your mind, damaged, defective, wrong item, or something else?"
                    )
        else:
            response_text = (
                "Which order would you like to return? Share its order number from My orders."
            )

    cancellation_result = str(tool_results.get("request_order_cancellation", ""))
    pending_cancellation = re.search(
        r"Cancellation request\s+(CAN-[A-Z0-9-]+)\s+for order\s+#?([A-Z0-9-]+)\s+is pending_confirmation",
        cancellation_result,
        re.IGNORECASE,
    )
    cancellation_id = pending_cancellation.group(1).upper() if pending_cancellation else ""
    cancellation_order_id = pending_cancellation.group(2).upper() if pending_cancellation else ""
    if pending_cancellation:
        response_text = (
            f"I’ve created a cancellation request for **{cancellation_order_id}**. "
            "The order is still active.\n\n"
            f"Request reference: `{cancellation_id}`. To cancel the order, use the "
            "**Confirm cancellation** button below. Nothing changes until you confirm."
        )
    events = list(result.get("tool_events") or [])
    if result.get("error_message"):
        outcome = "model_error"
    elif any(not event.get("success", False) for event in events):
        outcome = "tool_error"
    elif cancellation_id or result.get("intent") in {"order_cancellation", "return_request"}:
        outcome = "awaiting_customer_action"
    elif "create_support_ticket" in tool_results:
        outcome = "escalated"
    elif events:
        outcome = "evidence_answered"
    else:
        outcome = "unverified_answer"
    turn_id = conversation_service.record_agent_turn(
        customer["email"], req.session_id, result.get("intent", "general"), outcome,
        events, round((time.perf_counter() - turn_started) * 1000),
    )
    conversation_service.save_exchange(
        customer["email"], req.session_id, req.message, response_text, turn_id
    )
    return ChatResponse(
        response=response_text,
        intent=result.get("intent", "general"),
        order_id=result.get("order_id", "") or cancellation_order_id,
        tracking_number=result.get("tracking_number", ""),
        customer_email=result.get("customer_email", ""),
        tool_results=tool_results,
        pending_cancellation_id=cancellation_id,
        pending_cancellation_order_id=cancellation_order_id,
        turn_id=turn_id,
    )


@router.post("/chat/guest", response_model=ChatResponse)
async def guest_chat(req: GuestChatRequest):
    """Public product/policy chat. No account identity or private tools are available."""
    messages = [SystemMessage(content=(
        "You are Morrow's public shopping assistant. Help visitors choose products and "
        "answer questions using public catalog and published policy information. You do "
        "not have a customer account context. Ask visitors to sign in before looking up "
        "orders, payment records, personal shipments, or making a request on their behalf. "
        "Answer clearly and naturally in English."
    ))]
    messages.extend(
        HumanMessage(content=message.content)
        if message.role == "user"
        else AIMessage(content=message.content)
        for message in req.history[-12:]
    )
    messages.append(HumanMessage(content=req.message))
    initial_state: AgentState = {
        "messages": messages,
        "intent": "",
        "specialist": "",
        "order_id": "",
        "tracking_number": "",
        "return_reason": "",
        "customer_email": "",
        "guest_access": True,
        "tool_results": {},
        "tool_events": [],
        "final_response": "",
        "retry_count": 0,
        "error_message": "",
    }
    with trace_workflow() as workflow_trace:
        result = await run_in_threadpool(agent_graph.invoke, initial_state, {})
        workflow_trace.intent = result.get("intent", "unknown")
        if result.get("error_message"):
            workflow_trace.status = "error"
    intent = result.get("intent", "general")
    response_text = result.get("final_response", "Sorry, something went wrong.")
    if intent not in {"product_search", "return_policy", "general"}:
        response_text = (
            "I can help with products and store policies here. Please sign in to get help "
            "with your orders, payments, returns, or personal shipping details."
        )
    return ChatResponse(
        response=response_text,
        intent=intent,
        order_id="",
        tracking_number="",
        customer_email="",
        tool_results=dict(result.get("tool_results") or {}),
    )


@router.get("/chat/history", response_model=ConversationHistoryResponse)
async def get_chat_history(
    session_id: str = Query(default="default", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    customer: dict = Depends(get_current_customer),
):
    messages = conversation_service.get_messages(customer["email"], session_id, limit=50)
    for message in messages:
        content = message["content"]
        if message["role"] != "assistant" or not re.search(
            r"cancellation|cancelled", content, re.IGNORECASE
        ) or not re.search(
            r"pending[_ ]confirmation|request reference:\s*`?CAN-|not cancelled yet|has(?:n't|n’t) been cancelled yet|has not been cancelled",
            content,
            re.IGNORECASE,
        ):
            continue
        order_match = re.search(r"\b(ORD-[A-Z0-9-]+)\b", content, re.IGNORECASE)
        if not order_match:
            continue
        pending = operations_service.get_pending_cancellation(
            order_match.group(1), customer["email"]
        )
        if pending:
            message["pending_cancellation_id"] = pending["cancellation_id"]
            message["pending_cancellation_order_id"] = pending["order_id"]
    return ConversationHistoryResponse(
        session_id=session_id,
        messages=messages,
    )


@router.post("/chat/feedback")
async def post_chat_feedback(
        req: ChatFeedbackRequest,
        customer: dict = Depends(get_current_customer),
):
        try:
            conversation_service.save_feedback(req.turn_id, customer["email"], req.feedback)
            return {"saved": True, "feedback": req.feedback}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/chat/history", response_model=ConversationClearResponse)
async def clear_chat_history(
    session_id: str = Query(default="default", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    customer: dict = Depends(get_current_customer),
):
    deleted = conversation_service.clear_session(customer["email"], session_id)
    return ConversationClearResponse(deleted_messages=deleted)


@router.post("/orders/cancellation-requests", response_model=CancellationResponse)
async def request_order_cancellation(
    req: CustomerOrderActionRequest,
    customer: dict = Depends(get_current_customer),
):
    """Create a cancellation request; the order stays unchanged until confirmed."""
    request = _run_operation(
        operations_service.request_cancellation,
        req.order_id,
        customer["email"],
    )
    return CancellationResponse(
        cancellation_id=request["cancellation_id"],
        order_id=request["order_id"],
        status=request["status"],
        message="Confirm this request to cancel the order.",
    )


@router.post(
    "/cancellation-requests/{cancellation_id}/confirm",
    response_model=CancellationResponse,
)
async def confirm_order_cancellation(
    cancellation_id: str,
    session_id: str = Query(default="default", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    customer: dict = Depends(get_current_customer),
):
    result = _run_operation(
        operations_service.confirm_cancellation,
        cancellation_id,
        customer["email"],
    )
    confirmation_message = (
        f"Cancellation confirmed for order **{result['order_id']}**. "
        f"Request `{result['cancellation_id']}` is complete."
        if result["status"] == "confirmed"
        else f"Cancellation request `{result['cancellation_id']}` is {result['status']}."
    )
    conversation_service.save_exchange(
        customer["email"],
        session_id,
        f"Confirm cancellation request {result['cancellation_id']}.",
        confirmation_message,
    )
    return CancellationResponse(
        cancellation_id=result["cancellation_id"],
        order_id=result["order_id"],
        status=result["status"],
        message=confirmation_message,
    )


@router.post("/returns/requests", response_model=ReturnWorkflowResponse)
async def request_return(
    req: ReturnRequestBody,
    customer: dict = Depends(get_current_customer),
):
    """Create a return request after checking order ownership and eligibility."""
    order = order_service.get_order(req.order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {req.order_id} not found.")
    if order.email.strip().lower() != customer["email"].strip().lower():
        raise HTTPException(status_code=403, detail="The email does not match this order.")
    eligible, reason = order_service.can_return(req.order_id)
    if not eligible:
        raise HTTPException(status_code=409, detail=reason)

    ret = _run_operation(
        returns_service.create_return,
        order.order_id,
        req.reason,
        order.total,
    )
    return ReturnWorkflowResponse(
        rma_number=ret.rma_number,
        order_id=ret.order_id,
        status=ret.status,
        refund_amount=ret.refund_amount,
        message=(
            "Confirm this return request to send it for human approval. "
            "No refund has been issued."
        ) if ret.status == "pending_customer_confirmation" else (
            "This return request is already being processed. No refund has been issued."
        ),
    )


@router.post("/returns/{rma_number}/confirm", response_model=ReturnWorkflowResponse)
async def confirm_return(
    rma_number: str,
    customer: dict = Depends(get_current_customer),
):
    result = _run_operation(
        operations_service.confirm_return,
        rma_number,
        customer["email"],
    )
    return ReturnWorkflowResponse(
        rma_number=result["rma_number"],
        order_id=result["order_id"],
        status=result["status"],
        refund_amount=result["refund_amount"],
        message="Return confirmed and queued for human approval. No refund has been issued.",
    )


@router.post("/admin/returns/{rma_number}/approve", response_model=ReturnWorkflowResponse)
async def approve_return(
    rma_number: str,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
    _require_admin_key(x_admin_key)
    result = _run_operation(operations_service.approve_return, rma_number)
    return ReturnWorkflowResponse(
        rma_number=result["rma_number"],
        order_id=result["order_id"],
        status=result["status"],
        refund_amount=result["refund_amount"],
        message="Return approved. This demo records approval only; no payment was transferred.",
    )


@router.post("/support/tickets", response_model=SupportTicketResponse)
async def create_support_ticket(
    req: SupportTicketRequest,
    customer: dict = Depends(get_current_customer),
):
    ticket = _run_operation(
        operations_service.create_support_ticket,
        customer["email"],
        req.description,
        req.order_id,
    )
    return SupportTicketResponse(
        ticket_id=ticket["ticket_id"],
        order_id=ticket["order_id"],
        status=ticket["status"],
        message="Your request has been escalated to the support team.",
    )


@router.get("/support/tickets/mine", response_model=list[CustomerSupportTicketResponse])
async def list_my_support_tickets(
        customer: dict = Depends(get_current_customer),
):
        tickets = await run_in_threadpool(
            operations_service.list_customer_tickets, customer["email"]
        )
        return [CustomerSupportTicketResponse(**ticket) for ticket in tickets]
