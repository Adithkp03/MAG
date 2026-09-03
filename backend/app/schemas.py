
from pydantic import BaseModel, Field
from typing import Optional, List, Any

class ErrorResponse(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None

class ProductCreate(BaseModel):
    id: Optional[str] = None
    merchant_id: str
    name: str
    description: Optional[str] = ""
    price: int = Field(..., description="paise, 100 paise = 1 INR")
    category: Optional[str] = ""
    stock: int = 100

class ProductOut(BaseModel):
    id: str; merchant_id: str; name: str; description: str; price: int; category: str; stock: int
    class Config: from_attributes = True

class CartCreate(BaseModel):
    merchant_id: str
    customer_id: Optional[str] = None

class AddItemReq(BaseModel):
    product_id: str
    quantity: int = 1

class CheckoutCreate(BaseModel):
    cart_id: str

class CheckoutApproveReq(BaseModel):
    reason: str = "human approval"
    approved_by: str = Field(..., description="authenticated approver P0-10")  # require identity

class CheckoutOut(BaseModel):
    id: str; cart_id: str; merchant_id: str; status: str; total: int; policy_version: Optional[int]=1
    class Config: from_attributes = True

class PaymentCreate(BaseModel):
    order_id: Optional[str] = None
    merchant_id: Optional[str] = None
    amount: Optional[int] = None

class PaymentOut(BaseModel):
    id: str; order_id: Optional[str]; merchant_id: str; amount: int; status: str; razorpay_order_id: Optional[str]; razorpay_payment_id: Optional[str]
    class Config: from_attributes = True

class PolicyUpdate(BaseModel):
    max_transaction: Optional[int] = None
    max_discount: Optional[int] = None
    auto_approve: Optional[bool] = None
    allowed_actions: Optional[List[str]] = None
    allowed_categories: Optional[List[str]] = None

class AgentChatReq(BaseModel):
    merchant_id: str
    customer_id: Optional[str] = None
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None
