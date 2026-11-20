"""Additional tests for the Campus Supply Desk service."""

from pathlib import Path
import tempfile
import unittest

from supplydesk.service import OrderService


class ServiceTestBase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.service = OrderService(self.path)

    def stock(self, product_id):
        for product in self.service.catalog():
            if product["product_id"] == product_id:
                return product["stock"]


class NormalBehaviourTests(ServiceTestBase):
    def test_regular_delivery_over_100_dollars_is_free(self):
        quote = self.service.quote(
            "regular", [{"product_id": "hoodie", "quantity": 3}], "delivery")
        self.assertEqual(quote["subtotal_cents"], 12000)
        self.assertEqual(quote["delivery_cents"], 0)
        self.assertEqual(quote["total_cents"], 12000)

    def test_quote_matches_placed_order_pricing(self):
        items = [{"product_id": "hoodie", "quantity": 2}]
        quote = self.service.quote("student", items, "delivery")
        order = self.service.place_order("student", items, "delivery")
        for key in ("items", "subtotal_cents", "discount_cents",
                    "delivery_cents", "total_cents"):
            self.assertEqual(quote[key], order[key])

    def test_quote_does_not_create_save_file(self):
        self.service.quote("regular", [{"product_id": "mug", "quantity": 1}])
        self.assertFalse(self.path.exists())


class BoundaryTests(ServiceTestBase):
    def test_student_discount_at_exactly_50_dollars(self):
        quote = self.service.quote("student", [
            {"product_id": "hoodie", "quantity": 1},
            {"product_id": "notebook", "quantity": 2}])
        self.assertEqual(quote["subtotal_cents"], 5000)
        self.assertEqual(quote["discount_cents"], 500)

    def test_student_no_discount_just_below_50_dollars(self):
        quote = self.service.quote("student", [
            {"product_id": "hoodie", "quantity": 1},
            {"product_id": "notebook", "quantity": 1}])
        self.assertEqual(quote["subtotal_cents"], 4500)
        self.assertEqual(quote["discount_cents"], 0)

    def test_regular_never_gets_discount(self):
        quote = self.service.quote("regular", [{"product_id": "hoodie", "quantity": 3}])
        self.assertEqual(quote["discount_cents"], 0)

    def test_free_delivery_at_exactly_100_dollars(self):
        quote = self.service.quote("regular", [
            {"product_id": "hoodie", "quantity": 2},
            {"product_id": "notebook", "quantity": 4}], "delivery")
        self.assertEqual(quote["subtotal_cents"], 10000)
        self.assertEqual(quote["delivery_cents"], 0)

    def test_delivery_charged_just_below_100_dollars(self):
        quote = self.service.quote("regular", [
            {"product_id": "hoodie", "quantity": 2},
            {"product_id": "notebook", "quantity": 3}], "delivery")
        self.assertEqual(quote["subtotal_cents"], 9500)
        self.assertEqual(quote["delivery_cents"], 600)

    def test_quantity_one_is_accepted(self):
        quote = self.service.quote("regular", [{"product_id": "mug", "quantity": 1}])
        self.assertEqual(quote["total_cents"], 1500)

    def test_ordering_exactly_all_stock_is_accepted(self):
        order = self.service.place_order(
            "regular", [{"product_id": "notebook", "quantity": 20}])
        self.assertEqual(order["status"], "placed")
        self.assertEqual(self.stock("notebook"), 0)

    def test_ordering_one_more_than_stock_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.place_order(
                "regular", [{"product_id": "notebook", "quantity": 21}])


class InvalidInputTests(ServiceTestBase):
    def test_invalid_requests_raise_and_change_nothing(self):
        bad_requests = {
            "bad customer": ("vip", [{"product_id": "mug", "quantity": 1}], "pickup"),
            "bad fulfillment": ("regular", [{"product_id": "mug", "quantity": 1}], "mail"),
            "empty items": ("regular", [], "pickup"),
            "unknown product": ("regular", [{"product_id": "car", "quantity": 1}], "pickup"),
            "zero quantity": ("regular", [{"product_id": "mug", "quantity": 0}], "pickup"),
            "negative quantity": ("regular", [{"product_id": "mug", "quantity": -1}], "pickup"),
            "quantity 100": ("regular", [{"product_id": "mug", "quantity": 100}], "pickup"),
            "boolean quantity": ("regular", [{"product_id": "mug", "quantity": True}], "pickup"),
            "float quantity": ("regular", [{"product_id": "mug", "quantity": 1.5}], "pickup"),
            "string quantity": ("regular", [{"product_id": "mug", "quantity": "2"}], "pickup"),
            "item not a dict": ("regular", ["mug"], "pickup"),
        }
        for name, (customer, items, fulfillment) in bad_requests.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    self.service.place_order(customer, items, fulfillment)
        self.assertEqual(self.service.list_orders(), [])
        self.assertEqual(self.stock("mug"), 8)
        self.assertFalse(self.path.exists())

    def test_unknown_order_id_raises(self):
        with self.assertRaises(ValueError):
            self.service.get_order("ORD-9999")
        with self.assertRaises(ValueError):
            self.service.cancel_order("ORD-9999")

    def test_duplicate_lines_cannot_exceed_combined_stock(self):
        items = [{"product_id": "hoodie", "quantity": 3},
                 {"product_id": "hoodie", "quantity": 3}]
        with self.assertRaises(ValueError):
            self.service.place_order("regular", items)
        self.assertEqual(self.stock("hoodie"), 5)


class PreserveBehaviourTests(ServiceTestBase):
    def test_order_ids_increase_and_are_not_reused(self):
        first = self.service.place_order("regular", [{"product_id": "mug", "quantity": 1}])
        self.service.cancel_order(first["order_id"])
        second = self.service.place_order("regular", [{"product_id": "mug", "quantity": 1}])
        self.assertEqual(first["order_id"], "ORD-0001")
        self.assertEqual(second["order_id"], "ORD-0002")

    def test_history_keeps_cancelled_orders_in_order(self):
        a = self.service.place_order("regular", [{"product_id": "mug", "quantity": 1}])
        b = self.service.place_order("regular", [{"product_id": "bag", "quantity": 1}])
        self.service.cancel_order(a["order_id"])
        ids = [o["order_id"] for o in self.service.list_orders()]
        statuses = [o["status"] for o in self.service.list_orders()]
        self.assertEqual(ids, [a["order_id"], b["order_id"]])
        self.assertEqual(statuses, ["cancelled", "placed"])

    def test_placing_order_deducts_stock(self):
        self.service.place_order("regular", [{"product_id": "bag", "quantity": 3}])
        self.assertEqual(self.stock("bag"), 1)

    def test_cancelled_order_keeps_original_totals(self):
        order = self.service.place_order("student", [{"product_id": "hoodie", "quantity": 2}])
        cancelled = self.service.cancel_order(order["order_id"])
        self.assertEqual(cancelled["total_cents"], order["total_cents"])
        self.assertEqual(cancelled["items"], order["items"])

    def test_state_survives_reopening(self):
        self.service.place_order("regular", [{"product_id": "pen-pack", "quantity": 4}])
        reopened = OrderService(self.path)
        self.assertEqual(len(reopened.list_orders()), 1)
        self.assertEqual(reopened.catalog()[1]["stock"], 6)

    def test_cancelling_twice_does_not_restore_stock_twice(self):
        order = self.service.place_order("regular", [{"product_id": "mug", "quantity": 2}])
        self.service.cancel_order(order["order_id"])
        again = self.service.cancel_order(order["order_id"])
        self.assertEqual(again["status"], "cancelled")
        self.assertEqual(self.stock("mug"), 8)


if __name__ == "__main__":
    unittest.main()