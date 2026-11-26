import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import psycopg
from psycopg.rows import dict_row


def get_db_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://santyev-v-v:1234@localhost:5432/warehouse_db")


def get_conn():
    return psycopg.connect(get_db_url(), row_factory=dict_row)


def init_db() -> None:
    sql = Path("migrations/init.sql").read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.execute(sql)
        conn.commit()


class WarehouseRepository:
    def create_product(self, cur, sku: str, name: str, price, stock: int) -> Dict[str, Any]:
        return cur.execute(
            "INSERT INTO products (sku, name, price, stock) VALUES (%s, %s, %s, %s) RETURNING *",
            (sku, name, price, stock),
        ).fetchone()

    def get_product(self, cur, product_id: int) -> Optional[Dict[str, Any]]:
        return cur.execute("SELECT * FROM products WHERE id = %s", (product_id,)).fetchone()

    def get_product_by_sku(self, cur, sku: str) -> Optional[Dict[str, Any]]:
        return cur.execute("SELECT * FROM products WHERE sku = %s", (sku,)).fetchone()

    def list_products(self, cur, search: Optional[str], limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
        if search:
            pattern = f"%{search}%"
            total = cur.execute(
                "SELECT COUNT(*) AS c FROM products WHERE sku ILIKE %s OR name ILIKE %s", (pattern, pattern)
            ).fetchone()["c"]
            items = cur.execute(
                "SELECT * FROM products WHERE sku ILIKE %s OR name ILIKE %s ORDER BY id LIMIT %s OFFSET %s",
                (pattern, pattern, limit, offset),
            ).fetchall()
        else:
            total = cur.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
            items = cur.execute("SELECT * FROM products ORDER BY id LIMIT %s OFFSET %s", (limit, offset)).fetchall()
        return items, total

    def set_stock(self, cur, product_id: int, new_stock: int) -> Optional[Dict[str, Any]]:
        return cur.execute(
            "UPDATE products SET stock = %s WHERE id = %s RETURNING *", (new_stock, product_id)
        ).fetchone()

    def atomic_reserve(self, cur, product_id: int, qty: int) -> Optional[Dict[str, Any]]:
        """Атомарное списание: сработает только если stock >= qty."""
        return cur.execute(
            "UPDATE products SET stock = stock - %s WHERE id = %s AND stock >= %s RETURNING *",
            (qty, product_id, qty),
        ).fetchone()

    def add_stock(self, cur, product_id: int, delta: int) -> Optional[Dict[str, Any]]:
        return cur.execute(
            "UPDATE products SET stock = stock + %s WHERE id = %s AND stock + %s >= 0 RETURNING *",
            (delta, product_id, delta),
        ).fetchone()

    def create_order(self, cur) -> Dict[str, Any]:
        return cur.execute("INSERT INTO orders (status) VALUES ('Reserved') RETURNING *").fetchone()

    def add_order_item(self, cur, order_id: int, product_id: int, qty: int, price) -> None:
        cur.execute(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)",
            (order_id, product_id, qty, price),
        )

    def get_order(self, cur, order_id: int) -> Optional[Dict[str, Any]]:
        return cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,)).fetchone()

    def get_order_items(self, cur, order_id: int) -> List[Dict[str, Any]]:
        return cur.execute(
            """
            SELECT oi.product_id, p.sku, p.name, oi.quantity, oi.unit_price
            FROM order_items oi JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = %s ORDER BY oi.id
            """,
            (order_id,),
        ).fetchall()

    def mark_order_cancelled(self, cur, order_id: int) -> Optional[Dict[str, Any]]:
        """Атомарная смена статуса: сработает ровно один раз только для Reserved."""
        return cur.execute(
            "UPDATE orders SET status = 'Cancelled' WHERE id = %s AND status = 'Reserved' RETURNING *",
            (order_id,),
        ).fetchone()
