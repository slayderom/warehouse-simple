from contextlib import asynccontextmanager
from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.repository import init_db
from src.service import AppError, WarehouseService


class ProductIn(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    price: Decimal = Field(..., gt=0)
    stock: int = Field(..., ge=0)


class StockIn(BaseModel):
    delta: Optional[int] = None
    stock: Optional[int] = Field(None, ge=0)


class OrderItemIn(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., gt=0)


class OrderIn(BaseModel):
    items: List[OrderItemIn] = Field(..., min_length=1)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Warehouse API", lifespan=lifespan)
service = WarehouseService()


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.post("/api/products", status_code=201)
def create_product(data: ProductIn):
    return service.create_product(data.sku, data.name, data.price, data.stock)


@app.get("/api/products")
def list_products(search: Optional[str] = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return service.list_products(search, limit, offset)


@app.get("/api/products/{product_id}")
def get_product(product_id: int):
    return service.get_product(product_id)


@app.patch("/api/products/{product_id}/stock")
def update_stock(product_id: int, data: StockIn):
    return service.update_stock(product_id, data.delta, data.stock)


@app.post("/api/orders", status_code=201)
def create_order(data: OrderIn):
    return service.create_order(data.items)


@app.get("/api/orders/{order_id}")
def get_order(order_id: int):
    return service.get_order(order_id)


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: int):
    return service.cancel_order(order_id)
