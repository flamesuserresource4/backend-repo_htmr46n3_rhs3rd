"""
Database Schemas for Kakineha Coffee Beverages

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase class name.
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class Product(BaseModel):
    name: str = Field(..., description="Product name")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Unit price in UGX")
    category: str = Field(..., description="Category e.g., beans, ground, beverage")
    brand: str = Field(..., description="Brand e.g., Kakineha, Nucafe, Omukaga")
    type: Optional[str] = Field(None, description="Subtype e.g., Arabica, Wuga Arabica, Robusta, Hot Coffee, Tea")
    unit: str = Field("kg", description="Selling unit e.g., kg, bag, cup")
    in_stock: bool = Field(True, description="Availability flag")
    image_url: Optional[str] = Field(None, description="Image URL for product")


class OrderItem(BaseModel):
    product_id: str = Field(..., description="Product ObjectId as string")
    name: str = Field(..., description="Product name at time of order")
    quantity: float = Field(..., gt=0, description="Quantity ordered (supports decimals for kg)")
    unit_price: float = Field(..., ge=0, description="Price per unit at time of order")
    total: float = Field(..., ge=0, description="Computed line total")


class Customer(BaseModel):
    full_name: str
    phone: str
    email: Optional[str] = None
    address: Optional[str] = None


class Order(BaseModel):
    customer: Customer
    items: List[OrderItem]
    subtotal: float = Field(..., ge=0)
    payment_method: str = Field(..., description="mobile_money | card | cash_on_pickup")
    status: str = Field("pending", description="pending | paid | failed | cancelled")
    notes: Optional[str] = None


class PaymentInit(BaseModel):
    order_id: str
    method: str = Field(..., description="mobile_money | card")
    amount: float = Field(..., ge=0)
    phone: Optional[str] = Field(None, description="Required for mobile money")

