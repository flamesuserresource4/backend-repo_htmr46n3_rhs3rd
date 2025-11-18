import os
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext

from database import db, create_document, get_documents
from schemas import (
    Product, Order, PaymentInit, ProductPriceUpdate, ProductAdminUpdate,
    BulkPriceUpdate, OrderStatusUpdate, UserCreate, UserOut
)

# ------------------ Auth Config ------------------
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

# Use a scheme that doesn't require external C extensions
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ------------------ App Init ------------------
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


# ------------------ Auth Helpers ------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        if user_id is None:
            raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception
    # fetch user
    user = db["user"].find_one({"_id": ObjectId(user_id)}) if db else None
    if not user:
        raise credentials_exception
    user["id"] = str(user["_id"])
    user.pop("_id", None)
    return user


async def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ------------------ Utility ------------------
class ProductOut(Product):
    id: Optional[str] = None


class OrderOut(BaseModel):
    id: str
    data: dict


def serialize_doc(doc):
    if not doc:
        return doc
    doc["id"] = str(doc.get("_id"))
    doc.pop("_id", None)
    return doc


# ------------------ Auth Routes ------------------
@app.post("/api/auth/register", response_model=UserOut)
async def register(user: UserCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    # unique email
    if db["user"].find_one({"email": user.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = user.model_dump()
    doc["password"] = get_password_hash(doc.pop("password"))
    inserted_id = db["user"].insert_one({
        **doc,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }).inserted_id
    created = db["user"].find_one({"_id": inserted_id})
    return serialize_doc(created)


@app.post("/api/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    user = db["user"].find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("password", "")):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    access_token = create_access_token({"sub": str(user["_id"]), "role": user.get("role", "user")})
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/api/auth/seed-admin", response_model=dict)
async def seed_admin():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    email = os.getenv("SEED_ADMIN_EMAIL", "admin@example.com")
    password = os.getenv("SEED_ADMIN_PASSWORD", "Admin@123")
    if db["user"].find_one({"email": email}):
        return {"status": "exists", "email": email}
    doc = {
        "email": email,
        "password": get_password_hash(password),
        "role": "admin",
        "full_name": "Admin",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    db["user"].insert_one(doc)
    return {"status": "created", "email": email, "password": password}


# ------------------ Public Product Routes ------------------
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


# ------------------ Admin: Product Management ------------------
@app.patch("/api/admin/products/{product_id}/price", response_model=dict, dependencies=[Depends(require_admin)])
async def update_product_price(product_id: str, payload: ProductPriceUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        res = db["product"].update_one({"_id": ObjectId(product_id)}, {"$set": {"price": payload.price, "updated_at": datetime.utcnow()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Product not found")
        return {"id": product_id, "price": payload.price}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/admin/products/{product_id}", response_model=dict, dependencies=[Depends(require_admin)])
async def admin_update_product(product_id: str, payload: ProductAdminUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        updates["updated_at"] = datetime.utcnow()
        res = db["product"].update_one({"_id": ObjectId(product_id)}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Product not found")
        doc = db["product"].find_one({"_id": ObjectId(product_id)})
        return serialize_doc(doc)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/products/bulk-price", response_model=dict, dependencies=[Depends(require_admin)])
async def bulk_update_prices(payload: BulkPriceUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        updated = 0
        for item in payload.items:
            res = db["product"].update_one({"_id": ObjectId(item.product_id)}, {"$set": {"price": item.price, "updated_at": datetime.utcnow()}})
            if res.matched_count:
                updated += 1
        return {"updated": updated, "total": len(payload.items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------ Orders ------------------
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


@app.get("/api/admin/orders", response_model=List[dict], dependencies=[Depends(require_admin)])
async def admin_list_orders(status: Optional[str] = None, limit: int = 100):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        query = {}
        if status:
            query["status"] = status
        docs = get_documents("order", query, limit=limit)
        return [serialize_doc(d) for d in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/orders/{order_id}", response_model=dict, dependencies=[Depends(require_admin)])
async def admin_get_order(order_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        doc = db["order"].find_one({"_id": ObjectId(order_id)})
        if not doc:
            raise HTTPException(status_code=404, detail="Order not found")
        return serialize_doc(doc)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/admin/orders/{order_id}", response_model=dict, dependencies=[Depends(require_admin)])
async def admin_update_order(order_id: str, payload: OrderStatusUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        updates = {"status": payload.status}
        if payload.notes is not None:
            updates["notes"] = payload.notes
        updates["updated_at"] = datetime.utcnow()
        res = db["order"].update_one({"_id": ObjectId(order_id)}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Order not found")
        doc = db["order"].find_one({"_id": ObjectId(order_id)})
        return serialize_doc(doc)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------ Payments ------------------
@app.post("/api/payments/init", response_model=dict)
async def init_payment(payload: PaymentInit):
    if payload.method == "mobile_money" and not payload.phone:
        raise HTTPException(status_code=400, detail="Phone is required for mobile money")

    reference = f"PMT-{ObjectId()}"
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
    return {"reference": reference, "status": "pending"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
