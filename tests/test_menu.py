"""Tests that lock in the interactive menu behaviour."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from supplydesk.menu import run_menu
from supplydesk.service import OrderService


class MenuBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = OrderService(Path(self.directory.name) / "state.json")

    def run_menu_with(self, inputs):
        output = io.StringIO()
        with patch("builtins.input", side_effect=inputs), redirect_stdout(output):
            code = run_menu(self.service)
        return code, output.getvalue()

    def test_exit_returns_zero(self):
        code, text = self.run_menu_with(["0"])
        self.assertEqual(code, 0)
        self.assertIn("Goodbye.", text)

    def test_quote_shows_total_and_creates_no_order(self):
        _, text = self.run_menu_with(["2", "regular", "notebook", "2", "", "", "0"])
        self.assertIn("$10.00", text)
        self.assertIn("Quote only", text)
        self.assertEqual(self.service.list_orders(), [])

    def test_place_order_with_confirmation(self):
        self.run_menu_with(["3", "regular", "mug", "1", "", "", "y", "0"])
        orders = self.service.list_orders()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "placed")

    def test_declining_placement_changes_nothing(self):
        _, text = self.run_menu_with(["3", "regular", "mug", "1", "", "", "n", "0"])
        self.assertIn("Order not placed.", text)
        self.assertEqual(self.service.list_orders(), [])

    def test_declining_cancellation_changes_nothing(self):
        self.service.place_order("regular", [{"product_id": "mug", "quantity": 1}])
        _, text = self.run_menu_with(["6", "ORD-0001", "n", "0"])
        self.assertIn("Cancellation abandoned.", text)
        self.assertEqual(self.service.get_order("ORD-0001")["status"], "placed")

    def test_invalid_option_message(self):
        _, text = self.run_menu_with(["9", "0"])
        self.assertIn("Choose a number from 0 to 6.", text)

    def test_unknown_order_reports_error_and_menu_continues(self):
        _, text = self.run_menu_with(["5", "ORD-9999", "0"])
        self.assertIn("Error:", text)
        self.assertIn("Goodbye.", text)

    def test_end_of_input_exits_cleanly(self):
        code, text = self.run_menu_with([EOFError()])
        self.assertEqual(code, 0)
        self.assertIn("Goodbye.", text)

    def test_non_numeric_quantity_asks_to_reenter(self):
        _, text = self.run_menu_with(["2", "regular", "notebook", "abc", "", "", "0"])
        self.assertIn("Please enter a whole number", text)


if __name__ == "__main__":
    unittest.main()
    