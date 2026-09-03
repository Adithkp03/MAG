
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

class Checkout(Base):
    __tablename__="checkouts"
    id=Column(String, primary_key=True, default=lambda: gen_id("chk"))
    cart_id=Column(String, ForeignKey("carts.id"), unique=True)
    merchant_id=Column(String, ForeignKey("merchants.id"))
    customer_id=Column(String, ForeignKey("customers.id"), nullable=True)
    status=Column(String, default="created")  # created, validated, authorized, payment_pending, captured, failed, cancelled
    total=Column(Integer)
    idempotency_key=Column(String, unique=True, nullable=True)
    created_at=Column(DateTime, default=datetime.utcnow)

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
    razorpay_order_id=Column(String, nullable=True)
    razorpay_payment_id=Column(String, nullable=True)
    idempotency_key=Column(String, unique=True, nullable=True)
    created_at=Column(DateTime, default=datetime.utcnow)

class Policy(Base):
    __tablename__="policies"
    id=Column(String, primary_key=True, default=lambda: gen_id("pol"))
    merchant_id=Column(String, ForeignKey("merchants.id"), unique=True)
    max_transaction=Column(Integer, default=500000)  # paise 5000 INR
    max_discount=Column(Integer, default=15)
    auto_approve=Column(Boolean, default=True)
    allowed_actions=Column(JSON, default=lambda: ["create_cart","add_item","create_payment","recommend_product"])
    allowed_categories=Column(JSON, default=list)

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
