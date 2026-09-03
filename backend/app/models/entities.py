
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from ..core.database import Base

def gen_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"

class Merchant(Base):
    __tablename__="merchants"
    id=Column(String, primary_key=True, default=lambda: gen_id("m"))
    name=Column(String, nullable=False)
    email=Column(String)
    api_key=Column(String, unique=True, default=lambda: f"sk_{uuid.uuid4().hex[:16]}")  # for merchant auth P0-16
    created_at=Column(DateTime, default=datetime.utcnow)

class Customer(Base):
    __tablename__="customers"
    id=Column(String, primary_key=True, default=lambda: gen_id("cust"))
    merchant_id=Column(String, ForeignKey("merchants.id"))
    name=Column(String)
    email=Column(String)
    phone=Column(String)
    meta=Column(JSON, default=dict)

class Product(Base):
    __tablename__="products"
    id=Column(String, primary_key=True, default=lambda: gen_id("prod"))
    merchant_id=Column(String, ForeignKey("merchants.id"))
    name=Column(String, nullable=False)
    description=Column(Text)
    price=Column(Integer, nullable=False)  # paise
    category=Column(String)
    image_url=Column(String, default="")
    stock=Column(Integer, default=100)
    created_at=Column(DateTime, default=datetime.utcnow)

class Cart(Base):
    __tablename__="carts"
    id=Column(String, primary_key=True, default=lambda: gen_id("cart"))
    merchant_id=Column(String, ForeignKey("merchants.id"))
    customer_id=Column(String, ForeignKey("customers.id"), nullable=True)
    status=Column(String, default="active")  # active, checked_out, abandoned
    total=Column(Integer, default=0)
    created_at=Column(DateTime, default=datetime.utcnow)
    updated_at=Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    items=relationship("CartItem", backref="cart", cascade="all, delete-orphan")

class CartItem(Base):
    __tablename__="cart_items"
    id=Column(String, primary_key=True, default=lambda: gen_id("ci"))
    cart_id=Column(String, ForeignKey("carts.id"))
    product_id=Column(String, ForeignKey("products.id"))
    quantity=Column(Integer, default=1)
    unit_price=Column(Integer)
    line_total=Column(Integer)

# Checkout state machine: created -> validated -> payment_pending -> captured/failed ; blocked -> validated via approval ; any -> cancelled
CHECKOUT_TRANSITIONS = {
    "created": ["validated","blocked","cancelled"],
    "validated": ["payment_pending","cancelled"],
    "blocked": ["validated","cancelled"],
    "payment_pending": ["captured","failed","cancelled"],
    "captured": [],
    "failed": ["validated"],  # allow retry
    "cancelled": []
}

class Checkout(Base):
    __tablename__="checkouts"
    id=Column(String, primary_key=True, default=lambda: gen_id("chk"))
    cart_id=Column(String, ForeignKey("carts.id"), unique=True)
    merchant_id=Column(String, ForeignKey("merchants.id"))
    customer_id=Column(String, ForeignKey("customers.id"), nullable=True)
    status=Column(String, default="created")
    total=Column(Integer)
    idempotency_key=Column(String, unique=True, nullable=True)
    policy_version=Column(Integer, default=1)  # snapshot version at creation P0-11
    created_at=Column(DateTime, default=datetime.utcnow)

    def can_transition(self, to: str) -> bool:
        return to in CHECKOUT_TRANSITIONS.get(self.status, [])

class Order(Base):
    __tablename__="orders"
    id=Column(String, primary_key=True, default=lambda: gen_id("ord"))
    checkout_id=Column(String, ForeignKey("checkouts.id"), unique=True)
    merchant_id=Column(String, ForeignKey("merchants.id"))
    customer_id=Column(String, ForeignKey("customers.id"), nullable=True)
    status=Column(String, default="pending")  # pending, paid, failed, cancelled
    total=Column(Integer)
    payment_id=Column(String, ForeignKey("payments.id"), nullable=True)
    created_at=Column(DateTime, default=datetime.utcnow)

class Payment(Base):
    __tablename__="payments"
    id=Column(String, primary_key=True, default=lambda: gen_id("pay"))
    order_id=Column(String, ForeignKey("orders.id"), nullable=True)
    merchant_id=Column(String)
    amount=Column(Integer)
    status=Column(String, default="created")  # created, pending, captured, failed
    razorpay_order_id=Column(String, nullable=True, unique=True)  # 1:1 with payment for correlation P0-3
    razorpay_payment_id=Column(String, nullable=True)
    idempotency_key=Column(String, unique=True, nullable=True)
    created_at=Column(DateTime, default=datetime.utcnow)

class Policy(Base):
    __tablename__="policies"
    id=Column(String, primary_key=True, default=lambda: gen_id("pol"))
    merchant_id=Column(String, ForeignKey("merchants.id"), unique=True)
    max_transaction=Column(Integer, default=500000)
    max_discount=Column(Integer, default=15)
    auto_approve=Column(Boolean, default=True)
    allowed_actions=Column(JSON, default=lambda: ["create_cart","add_item","create_payment","recommend_product"])
    allowed_categories=Column(JSON, default=list)
    version=Column(Integer, default=1)  # P0-11
    updated_at=Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Approval(Base):
    __tablename__="approvals"
    id=Column(String, primary_key=True, default=lambda: gen_id("appr"))
    merchant_id=Column(String, ForeignKey("merchants.id"))
    checkout_id=Column(String, ForeignKey("checkouts.id"))
    action=Column(String)  # create_payment
    amount=Column(Integer)  # exact binding P0-12
    status=Column(String, default="pending")  # pending, approved, rejected
    requested_by=Column(String)  # agent/session
    approved_by=Column(String, nullable=True)  # authenticated approver P0-10
    policy_version=Column(Integer)
    reason=Column(Text, default="")
    created_at=Column(DateTime, default=datetime.utcnow)
    decided_at=Column(DateTime, nullable=True)

class WebhookEvent(Base):
    __tablename__="webhook_events"
    id=Column(String, primary_key=True, default=lambda: gen_id("wevt"))
    event_id=Column(String, unique=True)  # Razorpay event id durable dedup P0-2
    type=Column(String)
    payload=Column(JSON)
    processed=Column(Boolean, default=False)
    created_at=Column(DateTime, default=datetime.utcnow)

class AuditEvent(Base):
    __tablename__="audit_events"
    id=Column(String, primary_key=True, default=lambda: gen_id("audit"))
    event_id=Column(String, unique=True, default=lambda: f"evt_{uuid.uuid4().hex[:8]}")
    merchant_id=Column(String)
    agent_id=Column(String, default="commerce-agent")
    action=Column(String)
    reason=Column(Text, default="")
    amount=Column(Integer, nullable=True)
    policy_result=Column(String, default="")
    risk_score=Column(Float, default=0.0)
    authorization=Column(String, default="")
    result=Column(String, default="")
    timestamp=Column(DateTime, default=datetime.utcnow)
    payload=Column(JSON, default=dict)

class AgentSession(Base):
    __tablename__="agent_sessions"
    id=Column(String, primary_key=True, default=lambda: gen_id("sess"))
    merchant_id=Column(String)
    customer_id=Column(String, nullable=True)
    status=Column(String, default="active")
    created_at=Column(DateTime, default=datetime.utcnow)

class AgentRun(Base):
    __tablename__="agent_runs"
    id=Column(String, primary_key=True, default=lambda: gen_id("run"))
    session_id=Column(String, ForeignKey("agent_sessions.id"))
    merchant_id=Column(String)
    customer_id=Column(String, nullable=True)
    user_message=Column(Text)
    status=Column(String, default="running")  # running, completed, failed, blocked
    created_at=Column(DateTime, default=datetime.utcnow)
    completed_at=Column(DateTime, nullable=True)
    final_reply=Column(Text, nullable=True)

class AgentMessage(Base):
    __tablename__="agent_messages"
    id=Column(String, primary_key=True, default=lambda: gen_id("msg"))
    run_id=Column(String, ForeignKey("agent_runs.id"))
    session_id=Column(String, ForeignKey("agent_sessions.id"))
    role=Column(String)  # user, assistant, tool
    content=Column(Text)
    tool_call_id=Column(String, nullable=True)
    created_at=Column(DateTime, default=datetime.utcnow)

class AgentToolCall(Base):
    __tablename__="agent_tool_calls"
    id=Column(String, primary_key=True, default=lambda: gen_id("tc"))
    run_id=Column(String, ForeignKey("agent_runs.id"))
    session_id=Column(String, ForeignKey("agent_sessions.id"))
    tool=Column(String)
    input=Column(JSON)
    output=Column(JSON)
    policy_result=Column(String, nullable=True)
    risk_score=Column(Float, nullable=True)
    created_at=Column(DateTime, default=datetime.utcnow)

class Campaign(Base):
    __tablename__="campaigns"
    id=Column(String, primary_key=True, default=lambda: gen_id("camp"))
    merchant_id=Column(String, index=True)
    name=Column(String)
    target_category=Column(String)
    discount=Column(Integer)  # percent
    trigger_product_id=Column(String, nullable=True)
    recommend_product_id=Column(String, nullable=True)
    proposal_reason=Column(Text)
    expected_incremental_paise=Column(Integer, default=0)
    status=Column(String, default="proposed")  # proposed, approved, active, completed, rejected
    proposed_by=Column(String, default="growth-agent")
    approved_by=Column(String, nullable=True)
    created_at=Column(DateTime, default=datetime.utcnow)
    approved_at=Column(DateTime, nullable=True)

class CampaignAudience(Base):
    __tablename__="campaign_audiences"
    id=Column(String, primary_key=True, default=lambda: gen_id("caud"))
    campaign_id=Column(String, ForeignKey("campaigns.id"))
    segment=Column(String)  # e.g. keyboard_buyers
    customer_count=Column(Integer, default=0)
    created_at=Column(DateTime, default=datetime.utcnow)

class CampaignAction(Base):
    __tablename__="campaign_actions"
    id=Column(String, primary_key=True, default=lambda: gen_id("cact"))
    campaign_id=Column(String, ForeignKey("campaigns.id"))
    action_type=Column(String)  # discount, cross_sell, email
    payload=Column(JSON, default=dict)
    created_at=Column(DateTime, default=datetime.utcnow)

class CampaignRun(Base):
    __tablename__="campaign_runs"
    id=Column(String, primary_key=True, default=lambda: gen_id("crun"))
    campaign_id=Column(String, ForeignKey("campaigns.id"))
    status=Column(String, default="running")
    started_at=Column(DateTime, default=datetime.utcnow)
    ended_at=Column(DateTime, nullable=True)

class CampaignMetric(Base):
    __tablename__="campaign_metrics"
    id=Column(String, primary_key=True, default=lambda: gen_id("cmet"))
    campaign_id=Column(String, ForeignKey("campaigns.id"))
    run_id=Column(String, nullable=True)
    impressions=Column(Integer, default=0)
    conversions=Column(Integer, default=0)
    revenue_paise=Column(Integer, default=0)
    uplift_paise=Column(Integer, default=0)
    recorded_at=Column(DateTime, default=datetime.utcnow)

