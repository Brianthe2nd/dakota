import unittest

from mt5_funcs import calculate_calculator_result


class CalculatorTests(unittest.TestCase):
    def test_default_calculator_formula(self):
        self.assertAlmostEqual(calculate_calculator_result(10), 4.95)

    def test_custom_values(self):
        self.assertAlmostEqual(calculate_calculator_result(5, numerator=300, denominator=0.5), 30.0)


if __name__ == "__main__":
    unittest.main()
