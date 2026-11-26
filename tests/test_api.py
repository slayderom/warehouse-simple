import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "postgresql://santyev-v-v:1234@localhost:5432/warehouse_test_db"

from src.main import app
from src.repository import get_conn


@pytest.fixture()
def client():
    with TestClient(app) as c:
        with get_conn() as conn:
            conn.execute("TRUNCATE TABLE order_items, orders, products RESTART IDENTITY CASCADE;")
            conn.commit()
        yield c


def test_products_flow(client: TestClient):
    r = client.post("/api/products", json={"sku": "NB-1", "name": "Laptop", "price": "1000.00", "stock": 5})
    assert r.status_code == 201
    pid = r.json()["id"]

    assert client.post("/api/products", json={"sku": "NB-1", "name": "Dup", "price": "10", "stock": 1}).status_code == 409
    assert client.post("/api/products", json={"sku": "BAD", "name": "Bad", "price": "-5", "stock": 1}).status_code == 422
    assert client.get(f"/api/products/{pid}").status_code == 200
    assert client.get("/api/products/999").status_code == 404

    lst = client.get("/api/products?search=Lap&limit=10&offset=0").json()
    assert lst["total"] == 1

    assert client.patch(f"/api/products/{pid}/stock", json={"delta": -2}).json()["stock"] == 3
    assert client.patch(f"/api/products/{pid}/stock", json={"delta": -10}).status_code == 422
    assert client.patch(f"/api/products/{pid}/stock", json={"stock": 8}).json()["stock"] == 8
    assert client.patch(f"/api/products/{pid}/stock", json={}).status_code == 422
    assert client.patch("/api/products/999/stock", json={"delta": 1}).status_code == 404


def test_orders_atomic_cancel_and_price_lock(client: TestClient):
    p1 = client.post("/api/products", json={"sku": "A", "name": "Item A", "price": "100.00", "stock": 5}).json()
    p2 = client.post("/api/products", json={"sku": "B", "name": "Item B", "price": "200.00", "stock": 1}).json()

    # Повтор SKU и неизвестный SKU
    assert client.post("/api/orders", json={"items": [{"sku": "A", "quantity": 1}, {"sku": "A", "quantity": 1}]}).status_code == 422
    assert client.post("/api/orders", json={"items": [{"sku": "NO_SKU", "quantity": 1}]}).status_code == 404

    # Нехватка второй позиции -> откат всей транзакции (остаток A остаётся 5)
    fail = client.post("/api/orders", json={"items": [{"sku": "A", "quantity": 2}, {"sku": "B", "quantity": 5}]})
    assert fail.status_code == 422
    assert client.get(f"/api/products/{p1['id']}").json()["stock"] == 5

    # Успешный заказ
    ok = client.post("/api/orders", json={"items": [{"sku": "A", "quantity": 2}]})
    assert ok.status_code == 201
    oid = ok.json()["id"]

    # Меняем цену товара в БД -> в заказе остаётся старая цена 100.00
    with get_conn() as conn:
        conn.execute("UPDATE products SET price = 555.00 WHERE id = %s", (p1["id"],))
        conn.commit()
    assert Decimal(client.get(f"/api/orders/{oid}").json()["items"][0]["unit_price"]) == Decimal("100.00")
    assert client.get("/api/orders/999").status_code == 404

    # Отмена и повторная отмена
    assert client.post(f"/api/orders/{oid}/cancel").status_code == 200
    assert client.get(f"/api/products/{p1['id']}").json()["stock"] == 5
    assert client.post(f"/api/orders/{oid}/cancel").status_code == 409
    assert client.post("/api/orders/999/cancel").status_code == 404


def test_concurrent_last_item(client: TestClient):
    p = client.post("/api/products", json={"sku": "LAST", "name": "Last", "price": "50.00", "stock": 1}).json()

    def buy():
        return client.post("/api/orders", json={"items": [{"sku": "LAST", "quantity": 1}]}).status_code

    with ThreadPoolExecutor(max_workers=10) as ex:
        codes = [f.result() for f in [ex.submit(buy) for _ in range(10)]]

    assert codes.count(201) == 1
    assert codes.count(422) == 9
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 0
