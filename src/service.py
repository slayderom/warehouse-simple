from psycopg.errors import UniqueViolation
from src.repository import WarehouseRepository, get_conn


class AppError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


class WarehouseService:
    def __init__(self):
        self.repo = WarehouseRepository()

    def create_product(self, sku: str, name: str, price, stock: int):
        try:
            with get_conn() as conn:
                res = self.repo.create_product(conn.cursor(), sku.strip(), name.strip(), price, stock)
                conn.commit()
                return res
        except UniqueViolation:
            raise AppError(409, f"SKU '{sku}' уже существует")

    def list_products(self, search, limit: int, offset: int):
        with get_conn() as conn:
            items, total = self.repo.list_products(conn.cursor(), search, limit, offset)
            return {"items": items, "total": total, "limit": limit, "offset": offset}

    def get_product(self, product_id: int):
        with get_conn() as conn:
            prod = self.repo.get_product(conn.cursor(), product_id)
            if not prod:
                raise AppError(404, "Товар не найден")
            return prod

    def update_stock(self, product_id: int, delta=None, stock=None):
        if (delta is None) == (stock is None):
            raise AppError(422, "Передайте только delta или только stock")
        with get_conn() as conn:
            cur = conn.cursor()
            if not self.repo.get_product(cur, product_id):
                raise AppError(404, "Товар не найден")
            updated = (
                self.repo.set_stock(cur, product_id, stock)
                if stock is not None
                else self.repo.add_stock(cur, product_id, delta)
            )
            if not updated:
                raise AppError(422, "Остаток не может быть меньше нуля")
            conn.commit()
            return updated

    def create_order(self, items: list):
        skus = [i.sku.strip() for i in items]
        if len(skus) != len(set(skus)):
            raise AppError(422, "Повтор SKU в заказе запрещён")

        # Сортируем позиции по SKU перед транзакцией, чтобы исключить deadlock при конкурентных заказах
        ordered_items = sorted(items, key=lambda x: x.sku.strip())

        with get_conn() as conn:
            cur = conn.cursor()
            order = self.repo.create_order(cur)
            for item in ordered_items:
                prod = self.repo.get_product_by_sku(cur, item.sku.strip())
                if not prod:
                    conn.rollback()
                    raise AppError(404, f"SKU '{item.sku}' не найден")

                reserved = self.repo.atomic_reserve(cur, prod["id"], item.quantity)
                if not reserved:
                    conn.rollback()
                    raise AppError(422, f"Недостаточно товара '{item.sku}'")

                self.repo.add_order_item(cur, order["id"], prod["id"], item.quantity, prod["price"])

            result_items = self.repo.get_order_items(cur, order["id"])
            conn.commit()
            return {**order, "items": result_items}

    def get_order(self, order_id: int):
        with get_conn() as conn:
            cur = conn.cursor()
            order = self.repo.get_order(cur, order_id)
            if not order:
                raise AppError(404, "Заказ не найден")
            return {**order, "items": self.repo.get_order_items(cur, order_id)}

    def cancel_order(self, order_id: int):
        with get_conn() as conn:
            cur = conn.cursor()
            order = self.repo.get_order(cur, order_id)
            if not order:
                raise AppError(404, "Заказ не найден")

            cancelled = self.repo.mark_order_cancelled(cur, order_id)
            if not cancelled:
                raise AppError(409, "Заказ уже отменён")

            items = self.repo.get_order_items(cur, order_id)
            for item in sorted(items, key=lambda x: x["sku"]):
                self.repo.add_stock(cur, item["product_id"], item["quantity"])

            conn.commit()
            return {**cancelled, "items": items}
