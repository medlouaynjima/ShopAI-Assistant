"""
Returns Service — SQLite-backed returns / refund engine.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.services.database import get_connection


@dataclass
class ReturnRequest:
    order_id: str
    reason: str
    status: str = "pending"  # pending, approved, rejected, completed
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    refund_amount: float = 0.0
    rma_number: str = ""


RETURN_REASONS = {
    "defective": "Product is defective / malfunctioning",
    "wrong_item": "Wrong item was shipped",
    "not_as_described": "Product doesn't match description",
    "changed_mind": "Changed my mind",
    "damaged": "Package arrived damaged",
    "too_late": "Delivery was too late",
}

RETURN_POLICY = """
📋 **Return Policy Summary:**
- You have **14 days** from delivery to initiate a return.
- Items must be in original packaging and unused.
- Return shipping: **Free for defective/wrong items**, buyer pays for other reasons.
- Refunds are processed within **3-5 business days** after we receive the item.
- Non-returnable items: Clearance/outlet items, hygiene products (earbud tips, etc.)
"""


class ReturnsService:
    """SQLite-backed returns engine."""

    def get_policy(self) -> str:
        return RETURN_POLICY

    def create_return(self, order_id: str, reason: str, order_total: float) -> ReturnRequest:
        normalized_reason = (reason or "").strip().lower()
        if normalized_reason not in RETURN_REASONS:
            valid = ", ".join(sorted(RETURN_REASONS))
            raise ValueError(f"Invalid return reason '{reason}'. Valid reasons: {valid}")

        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            order_id = order_id.strip().upper()
            existing = conn.execute(
                """SELECT * FROM returns
                   WHERE order_id = ? AND status IN
                       ('pending_customer_confirmation', 'pending_approval', 'approved')
                   ORDER BY created_at DESC LIMIT 1""",
                (order_id,),
            ).fetchone()
            if existing:
                return ReturnRequest(
                    order_id=existing["order_id"],
                    reason=existing["reason"],
                    status=existing["status"],
                    created_at=existing["created_at"],
                    refund_amount=existing["refund_amount"],
                    rma_number=existing["rma_number"],
                )

            last = conn.execute(
                "SELECT rma_number FROM returns ORDER BY rma_number DESC LIMIT 1"
            ).fetchone()
            if last:
                num = int(last["rma_number"].split("-")[1]) + 1
            else:
                num = 1000
            rma = f"RMA-{num}"

            ret = ReturnRequest(
                order_id=order_id,
                reason=normalized_reason,
                refund_amount=order_total,
                rma_number=rma,
                status="pending_customer_confirmation",
            )

            conn.execute(
                """INSERT INTO returns (rma_number, order_id, reason, status, refund_amount, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (rma, order_id, normalized_reason, ret.status, order_total, ret.created_at),
            )
            conn.commit()
            return ret
        finally:
            conn.close()

    def get_return(self, order_id: str) -> Optional[ReturnRequest]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM returns WHERE order_id = ? ORDER BY created_at DESC LIMIT 1",
                (order_id,),
            ).fetchone()
            if not row:
                return None
            return ReturnRequest(
                order_id=row["order_id"],
                reason=row["reason"],
                status=row["status"],
                created_at=row["created_at"],
                refund_amount=row["refund_amount"],
                rma_number=row["rma_number"],
            )
        finally:
            conn.close()

    def get_all_returns(self) -> list[ReturnRequest]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM returns ORDER BY created_at DESC"
            ).fetchall()
            return [
                ReturnRequest(
                    order_id=r["order_id"],
                    reason=r["reason"],
                    status=r["status"],
                    created_at=r["created_at"],
                    refund_amount=r["refund_amount"],
                    rma_number=r["rma_number"],
                )
                for r in rows
            ]
        finally:
            conn.close()
