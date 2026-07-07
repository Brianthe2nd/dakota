import unittest

from mt5_funcs import calculate_calculator_result, calculate_sl_points_from_price_levels


class CalculatorTests(unittest.TestCase):
    def test_default_calculator_formula(self):
        self.assertAlmostEqual(calculate_calculator_result(10), 4.95)

    def test_custom_values(self):
        self.assertAlmostEqual(calculate_calculator_result(5, numerator=300, denominator=0.5), 30.0)

    def test_price_levels_to_sl_points(self):
        self.assertAlmostEqual(calculate_sl_points_from_price_levels(100.0, 120.0, point_value=0.5), 40.0)


if __name__ == "__main__":
    unittest.main()
