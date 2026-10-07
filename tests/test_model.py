"""The model: what a value is, and that the standard's numbering is all there."""
import datetime
import unittest
from decimal import Decimal

from mockeinvoice.model import ATTRIBUTE_TERMS, GROUPS, TERMS, Document, Group, Value


class ANumber(unittest.TestCase):
    def test_it_is_a_decimal_made_from_the_text(self):
        number = Value("1190.00").number
        self.assertIsInstance(number, Decimal)
        self.assertEqual(number, Decimal("1190.00"))

    def test_the_digits_after_the_point_are_kept_as_sent(self):
        self.assertEqual(str(Value("10.50").number), "10.50")
        self.assertEqual(str(Value("10.5").number), "10.5")
        self.assertEqual(Value("10.500").number.as_tuple().exponent, -3)

    def test_a_tenth_and_two_tenths_are_three_tenths(self):
        # The sum a float gets wrong, and the reason there is no float here.
        self.assertEqual(Value("0.1").number + Value("0.2").number, Value("0.3").number)

    def test_what_xml_schema_calls_a_decimal_is_one(self):
        for text in ("0", "-12.5", "+3", ".5", "5.", " 7.25 ", "007"):
            self.assertIsNotNone(Value(text).number, text)

    def test_what_python_would_take_and_xml_schema_would_not_is_none(self):
        for text in ("1e3", "1E-2", "NaN", "Infinity", "-inf", "1,5", "1 000", "", "EUR 5",
                     "0x10", "1_000", "١٢"):
            self.assertIsNone(Value(text).number, text)

    def test_a_float_is_refused_when_a_value_is_made_by_hand(self):
        with self.assertRaises(TypeError):
            Value.of(0.1)
        self.assertEqual(Value.of(Decimal("0.10"), currencyID="EUR"),
                         Value("0.10", {"currencyID": "EUR"}))


class ADate(unittest.TestCase):
    def test_it_is_read_as_written_year_month_day(self):
        self.assertEqual(Value("2026-10-02").date, datetime.date(2026, 10, 2))

    def test_anything_else_is_none(self):
        for text in ("20261002", "2026-13-01", "2026-02-30", "02.10.2026", "2026-10-02Z", ""):
            self.assertIsNone(Value(text).date, text)


class TheStandardsNumbering(unittest.TestCase):
    def test_every_business_term_from_1_to_165_is_named_but_the_one_it_skips(self):
        expected = {"BT-%d" % n for n in range(1, 166)} - {"BT-4"}
        self.assertEqual(set(TERMS), expected)

    def test_every_group_from_1_to_32_is_named(self):
        self.assertEqual(set(GROUPS), {"BG-%d" % n for n in range(1, 33)})

    def test_every_term_is_in_a_group_the_standard_has_or_in_the_document(self):
        for term, (_name, group, kind) in TERMS.items():
            self.assertTrue(group == "" or group in GROUPS, term)
            self.assertIn(kind, ("identifier", "date", "code", "text", "amount", "price",
                                 "quantity", "percentage", "binary"), term)

    def test_no_two_terms_share_a_name(self):
        names = [name for name, _group, _kind in TERMS.values()]
        self.assertEqual(len(names), len(set(names)))


class AGroup(unittest.TestCase):
    def test_a_term_is_its_first_value_and_values_is_all_of_them(self):
        group = Group()
        group.add("BT-29", Value("A", {"schemeID": "0088"}))
        group.add("BT-29", "B")
        self.assertEqual(group.term("BT-29").text, "A")
        self.assertEqual([v.text for v in group.values("BT-29")], ["A", "B"])
        self.assertIsNone(group.term("BT-30"))
        self.assertEqual(group.text("BT-30"), "")

    def test_a_term_the_syntax_writes_as_an_attribute_is_found_by_its_own_number(self):
        line = Group("BG-25")
        line.add("BT-129", Value("40", {"unitCode": "C62"}))
        self.assertEqual(line.text("BT-130"), "C62")
        self.assertEqual(line.values("BT-150"), [])
        for term, (holder, _attribute) in ATTRIBUTE_TERMS.items():
            self.assertIn(holder, TERMS, term)

    def test_groups_are_kept_in_order_and_an_untouched_one_is_empty(self):
        document = Document(kind="CreditNote")
        self.assertTrue(document.empty())
        first, second = document.new("BG-25"), document.new("BG-25")
        self.assertEqual(document.all("BG-25"), [first, second])
        self.assertFalse(document.empty())          # it has two lines
        self.assertTrue(first.empty())
        first.add("BT-126", "1")
        self.assertFalse(first.empty())


if __name__ == "__main__":
    unittest.main()
