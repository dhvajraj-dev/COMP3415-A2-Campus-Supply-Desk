"""Tests for CR-01: express delivery."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from supplydesk.cli import main
from supplydesk.menu import run_menu
from supplydesk.service import OrderService


class ExpressTestBase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.service = OrderService(self.path)


class ExpressPricingTests(ExpressTestBase):
    def test_regular_two_notebooks_express(self):
        quote = self.service.quote(
            "regular", [{"product_id": "notebook", "quantity": 2}], "express")
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 2200)

    def test_student_two_hoodies_express(self):
        quote = self.service.quote(
            "student", [{"product_id": "hoodie", "quantity": 2}], "express")
        self.assertEqual(quote["discount_cents"], 800)
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 8400)

    def test_express_fee_never_waived_but_standard_is(self):
        items = [{"product_id": "hoodie", "quantity": 3}]
        standard = self.service.quote("regular", items, "delivery")
        express = self.service.quote("regular", items, "express")
        self.assertEqual(standard["total_cents"], 12000)
        self.assertEqual(express["delivery_cents"], 1200)
        self.assertEqual(express["total_cents"], 13200)

    def test_express_fee_charged_on_very_large_student_order(self):
        quote = self.service.quote(
            "student", [{"product_id": "hoodie", "quantity": 5}], "express")
        self.assertEqual(quote["subtotal_cents"], 20000)
        self.assertEqual(quote["discount_cents"], 2000)
        self.assertEqual(quote["total_cents"], 19200)

    def test_student_discount_boundary_unchanged_with_express(self):
        quote = self.service.quote("student", [
            {"product_id": "hoodie", "quantity": 1},
            {"product_id": "notebook", "quantity": 2}], "express")
        self.assertEqual(quote["discount_cents"], 500)
        self.assertEqual(quote["total_cents"], 5700)

    def test_regular_never_discounted_with_express(self):
        quote = self.service.quote(
            "regular", [{"product_id": "hoodie", "quantity": 2}], "express")
        self.assertEqual(quote["discount_cents"], 0)

    def test_pickup_and_standard_delivery_unchanged(self):
        items = [{"product_id": "notebook", "quantity": 2}]
        self.assertEqual(self.service.quote("regular", items)["delivery_cents"], 0)
        self.assertEqual(
            self.service.quote("regular", items, "delivery")["delivery_cents"], 600)
        big = [{"product_id": "hoodie", "quantity": 3}]
        self.assertEqual(
            self.service.quote("regular", big, "delivery")["delivery_cents"], 0)


class ExpressOrderTests(ExpressTestBase):
    ITEMS = [{"product_id": "hoodie", "quantity": 2}]

    def test_quote_matches_placed_express_order(self):
        quote = self.service.quote("student", self.ITEMS, "express")
        order = self.service.place_order("student", self.ITEMS, "express")
        for key in ("fulfillment", "items", "subtotal_cents", "discount_cents",
                    "delivery_cents", "total_cents"):
            self.assertEqual(quote[key], order[key])

    def test_express_order_kept_after_reopen_and_cancel(self):
        order = self.service.place_order("student", self.ITEMS, "express")
        reopened = OrderService(self.path)
        self.assertEqual(reopened.get_order(order["order_id"]), order)
        cancelled = reopened.cancel_order(order["order_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["fulfillment"], "express")
        self.assertEqual(cancelled["items"], order["items"])
        self.assertEqual(cancelled["delivery_cents"], 1200)
        self.assertEqual(cancelled["total_cents"], 8400)
        stock = {p["product_id"]: p["stock"] for p in reopened.catalog()}
        self.assertEqual(stock["hoodie"], 5)

    def test_other_fulfillment_values_still_invalid(self):
        for value in ("overnight", "Express", "", "express "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.service.quote("regular", self.ITEMS, value)
        self.assertEqual(self.service.list_orders(), [])


class ExpressInterfaceTests(ExpressTestBase):
    def test_command_line_quote_express(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--data", str(self.path), "quote", "--customer", "student",
                         "--fulfillment", "express", "--item", "hoodie:2"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["total_cents"], 8400)

    def test_command_line_rejects_unknown_fulfillment(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            main(["--data", str(self.path), "quote", "--fulfillment", "overnight",
                  "--item", "hoodie:2"])
        self.assertEqual(ctx.exception.code, 2)

    def test_command_line_place_express(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--data", str(self.path), "place", "--fulfillment",
                         "express", "--item", "notebook:2"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["total_cents"], 2200)

    def test_menu_prompt_mentions_express_and_accepts_it(self):
        prompts = []
        answers = iter(["2", "student", "hoodie", "2", "", "express", "0"])

        def fake_input(prompt=""):
            prompts.append(prompt)
            return next(answers)

        out = io.StringIO()
        with patch("builtins.input", side_effect=fake_input), redirect_stdout(out):
            run_menu(self.service)
        self.assertTrue(any("express" in p for p in prompts))
        self.assertIn("$84.00", out.getvalue())

    def test_menu_default_fulfillment_still_pickup(self):
        answers = iter(["2", "", "notebook", "2", "", "", "0"])
        out = io.StringIO()
        with patch("builtins.input", side_effect=lambda prompt="": next(answers)), \
                redirect_stdout(out):
            run_menu(self.service)
        self.assertIn("$10.00", out.getvalue())


if __name__ == "__main__":
    unittest.main()