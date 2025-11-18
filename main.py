import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Product, Order, PaymentInit

app = FastAPI(title="Kakineha Coffee Beverages API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Kakineha Coffee Beverages Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


# Utility to convert ObjectId to string in API responses
class ProductOut(Product):
    id: Optional[str] = None


def serialize_doc(doc):
    if not doc:
        return doc
    doc["id"] = str(doc.get("_id"))
    doc.pop("_id", None)
    return doc


@app.post("/api/products", response_model=dict)
async def create_product(product: Product):
    try:
        inserted_id = create_document("product", product)
        return {"id": inserted_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/products", response_model=List[dict])
async def list_products(brand: Optional[str] = None, category: Optional[str] = None):
    try:
        query = {}
        if brand:
            query["brand"] = brand
        if category:
            query["category"] = category
        docs = get_documents("product", query)
        return [serialize_doc(d) for d in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/orders", response_model=dict)
async def create_order(order: Order):
    try:
        # basic subtotal validation
        calc_subtotal = sum(item.total for item in order.items)
        if abs(calc_subtotal - order.subtotal) > 0.01:
            raise HTTPException(status_code=400, detail="Subtotal mismatch")
        inserted_id = create_document("order", order)
        return {"order_id": inserted_id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/payments/init", response_model=dict)
async def init_payment(payload: PaymentInit):
    # NOTE: In production, integrate with a real provider (MTN/Airtel Mobile Money, Stripe, etc.)
    # Here we simulate a payment intent and return a mock reference for demo.
    if payload.method == "mobile_money" and not payload.phone:
        raise HTTPException(status_code=400, detail="Phone is required for mobile money")

    reference = f"PMT-{ObjectId()}"
    # Persist a payment record
    data = {
        "order_id": payload.order_id,
        "method": payload.method,
        "amount": payload.amount,
        "phone": payload.phone,
        "status": "initiated",
        "reference": reference,
    }
    try:
        create_document("payment", data)
        return {"reference": reference, "status": "initiated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/payments/status/{reference}", response_model=dict)
async def payment_status(reference: str):
    # Mock status for demo purposes
    return {"reference": reference, "status": "pending"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
