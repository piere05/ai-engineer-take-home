import unittest
from extract import parse_results


class ParseResultsTests(unittest.TestCase):
    def test_numeric_table_row_and_printed_range(self):
        rows = parse_results("""Test                                              Result                   Unit             Reference Range
Haemoglobin                                       13.5                     g/dL             13.0 - 17.0
""")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"test_name": "Haemoglobin", "value": 13.5, "unit": "g/dL", "reference_range": "13.0 - 17.0"})

    def test_does_not_invent_missing_reference_range(self):
        rows = parse_results("T3       179       ng/dL")
        self.assertTrue(all(row.get("reference_range") is None for row in rows))

    def test_digital_row_without_range_keeps_value_and_unit(self):
        rows = parse_results("     T3                                                179 ng/dL")
        self.assertEqual(rows, [{"test_name": "T3", "value": 179, "unit": "ng/dL", "reference_range": None}])

    def test_rejects_address_and_metadata(self):
        rows = parse_results("""14, 2nd Main Road, Jayanagar, Bengaluru 560011
Patient Name : Meera Gowda Sample ID : 45693617
Haemoglobin 13.5 g/dL 13.0 - 17.0
""")
        self.assertEqual([r["test_name"] for r in rows], ["Haemoglobin"])

    def test_qualitative_result_is_not_forced_to_number(self):
        rows = parse_results("Colour | Dark Yellow | Pale Yellow")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["value"], "Dark Yellow")

    def test_prescription_dose_is_not_a_lab_result(self):
        rows = parse_results("Rx\n1. Tab. Metformin 500 mg 1-0-1 afterfood x 30 days")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
