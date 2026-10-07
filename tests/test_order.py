"""An order the supplier is told of, and the invoice it writes for one."""
import copy
import datetime
import unittest
from decimal import Decimal

from mockeinvoice import validate, write
from mockeinvoice.buyer import Buyer
from mockeinvoice.order import WHO, NotTaken, described, invoice, read_order
from mockeinvoice.supplier import NotBilled, Supplier

from . import unbuilt

NOON = datetime.datetime(2026, 10, 7, 12, 0, 30)
DAY = NOON.date()
ORDER = {
    "number": "4500000017",
    "buyer": {"name": "ACME Corporation", "endpoint": "0088:4098765000003",
              "vat": "DE987654321", "street": "Hauptstrasse 5", "city": "Berlin",
              "postal_code": "10115", "country": "DE"},
    "lines": [
        {"line": "10", "name": "Widget", "seller_item": "W-100", "quantity": 40,
         "unit": "C62", "price": "20.00"},
        {"line": "20", "name": "Installation", "quantity": "2.5", "unit": "HUR",
         "price": "33.333"},
    ],
}


def order(**changes):
    return dict(copy.deepcopy(ORDER), **changes)


def without(*names):
    return {name: value for name, value in ORDER.items() if name not in names}


def buyer(**changes):
    return order(buyer={name: value for name, value in dict(ORDER["buyer"], **changes).items()
                        if value is not None})


def lines(*changed):
    return order(lines=[{name: value for name, value in dict(ORDER["lines"][0], **one).items()
                         if value is not None} for one in changed])


def amounts(document, *terms):
    return tuple(document.text(term) for term in terms)


class ReadingAnOrder(unittest.TestCase):
    def test_what_it_says_is_held(self):
        read = read_order(order(reference="04011000-12345-06", currency="CHF"))
        self.assertEqual((read.number, read.reference, read.currency, read.status),
                         ("4500000017", "04011000-12345-06", "CHF", "open"))
        self.assertEqual(read.buyer, ORDER["buyer"])
        self.assertEqual([(one.line, one.name, one.seller_item, one.buyer_item, one.quantity,
                           one.unit, one.price, one.billed, one.open) for one in read.lines],
                         [("10", "Widget", "W-100", "", Decimal(40), "C62", Decimal("20.00"),
                           0, Decimal(40)),
                          ("20", "Installation", "", "", Decimal("2.5"), "HUR",
                           Decimal("33.333"), 0, Decimal("2.5"))])

    def test_a_line_with_no_number_has_its_place_for_one(self):
        read = read_order(lines({"line": None}, {"line": None}, {"line": "7"}))
        self.assertEqual([one.line for one in read.lines], ["1", "2", "7"])

    def test_a_number_is_never_a_float(self):
        self.assertEqual(read_order(lines({"price": Decimal("0.10")})).lines[0].price,
                         Decimal("0.10"))
        for name in ("quantity", "price"):
            with self.assertRaises(NotTaken) as raised:
                read_order(lines({name: 0.1}))
            self.assertIn("line 1's %s" % name, str(raised.exception))

    def test_what_is_not_taken(self):
        for said, why in (
                ([], "the order is a JSON object, not list"),
                (order(delivery="tomorrow"), "the order has delivery, and what is taken is"),
                (without("number"), "the order has no number"),
                (order(number=" "), "the order has no number"),
                (order(number=4500000017), "the order's number is text, not 4500000017"),
                (order(reference=7), "the order's reference is text, not 7"),
                (without("buyer"), "the buyer is a JSON object, not NoneType"),
                (buyer(name=None), "the buyer has no name"),
                (buyer(endpoint=None, country=" "), "the buyer has no endpoint and no country"),
                (buyer(telephone="1"), "the buyer has telephone"),
                (buyer(vat=19), "the buyer's vat is text, not 19"),
                (buyer(endpoint="4098765000003"), "the buyer's endpoint is written "
                                                  "scheme:identifier"),
                (without("lines"), "the order has no lines"),
                (order(lines=[]), "the order has no lines"),
                (order(lines=["Widget"]), "line 1 is a JSON object, not str"),
                (lines({"colour": "grey"}), "line 1 has colour"),
                (lines({}, {"name": " "}), "line 2 has no name"),
                (lines({"unit": None}), "line 1 has no unit"),
                (lines({"quantity": None}), "line 1 has no quantity"),
                (lines({"price": None}), "line 1 has no price"),
                (lines({"quantity": "forty"}), "line 1's quantity is a number, not 'forty'"),
                (lines({"quantity": True}), "line 1's quantity is a number written as text"),
                (lines({"quantity": 0}), "line 1 orders 0"),
                (lines({"quantity": "-1"}), "line 1 orders -1"),
                (lines({"price": "-0.01"}), "line 1's price is -0.01"),
                (lines({}, {}), "two lines are numbered 10"),
                (lines({"line": "2"}, {"line": None}), "two lines are numbered 2")):
            with self.assertRaises(NotTaken, msg=why) as raised:
                read_order(said)
            self.assertIn(why, str(raised.exception))

    def test_a_price_of_nothing_is_a_price(self):
        self.assertEqual(read_order(lines({"price": 0})).lines[0].price, 0)


class TheSupplierItself(unittest.TestCase):
    def test_a_change_is_made_and_the_rest_is_left(self):
        now = described(WHO, {"name": "Initech AG", "payment_days": 14, "vat_rate": 7})
        self.assertEqual((now["name"], now["payment_days"], now["vat_rate"], now["iban"]),
                         ("Initech AG", 14, "7", WHO["iban"]))
        self.assertEqual(WHO["name"], "Globex GmbH")
        self.assertEqual(described(WHO, {"vat_rate": Decimal("8.1")})["vat_rate"], "8.1")
        self.assertEqual(described(WHO, {"payment_days": 0})["payment_days"], 0)

    def test_what_is_not_taken(self):
        for changes, why in (
                ("Initech", "the supplier is a JSON object, not str"),
                ({"fax": "1"}, "the supplier has fax, and what is taken is name, endpoint"),
                ({"name": 7}, "the supplier's name is text, not 7"),
                ({"endpoint": "4012345000009"}, "the supplier's endpoint is written"),
                ({"payment_days": "30"}, "payment_days is a whole number of days, not '30'"),
                ({"payment_days": -1}, "payment_days is a whole number of days, not -1"),
                ({"payment_days": True}, "payment_days is a whole number of days, not True"),
                ({"vat_rate": "nineteen"}, "vat_rate is a number, not 'nineteen'"),
                ({"vat_rate": 0}, "vat_rate is 0, and every line is VAT category S"),
                ({"vat_rate": "-19"}, "vat_rate is -19")):
            with self.assertRaises(NotTaken, msg=why) as raised:
                described(WHO, changes)
            self.assertIn(why, str(raised.exception))


class TheInvoice(unittest.TestCase):
    def written(self, said=ORDER, who=WHO, quantities=None):
        return validate(write(invoice(read_order(said), who, "GLX-0001", DAY, quantities)))

    def test_it_is_valid_with_nothing_to_say(self):
        document, report = self.written()
        self.assertEqual((report.specification, report.verdict, report.findings),
                         ("peppol", "valid", []))
        self.assertEqual(document.kind, "Invoice")

    def test_it_refers_to_the_order_and_its_lines(self):
        document, _report = self.written()
        self.assertEqual(amounts(document, "BT-13", "BT-10"), ("4500000017", "4500000017"))
        self.assertEqual([(line.text("BT-126"), line.text("BT-132"), line.text("BT-153"),
                           line.text("BT-155"), line.text("BT-129"), line.text("BT-130"),
                           line.text("BT-146"), line.text("BT-131"))
                          for line in document.all("BG-25")],
                         [("1", "10", "Widget", "W-100", "40", "C62", "20.00", "800.00"),
                          ("2", "20", "Installation", "", "2.5", "HUR", "33.333", "83.33")])

    def test_the_buyers_own_reference_is_used_where_it_gave_one(self):
        document, report = self.written(order(reference="04011000-12345-06"))
        self.assertEqual(amounts(document, "BT-13", "BT-10") + (report.verdict,),
                         ("4500000017", "04011000-12345-06", "valid"))

    def test_the_parties_are_the_orders_buyer_and_the_supplier(self):
        document, _report = self.written(buyer(legal_id="HRB 1"))
        self.assertEqual(amounts(document, "BT-44", "BT-49", "BT-49-1", "BT-48", "BT-47",
                                 "BT-50", "BT-52", "BT-53", "BT-55"),
                         ("ACME Corporation", "4098765000003", "0088", "DE987654321", "HRB 1",
                          "Hauptstrasse 5", "Berlin", "10115", "DE"))
        self.assertEqual(amounts(document, "BT-27", "BT-34", "BT-34-1", "BT-31", "BT-30",
                                 "BT-35", "BT-37", "BT-38", "BT-40", "BT-41", "BT-42", "BT-43"),
                         ("Globex GmbH", "4012345000009", "0088", "DE123456789", "",
                          "Industriestrasse 1", "Hamburg", "20095", "DE",
                          "Accounts receivable", "+49 40 000000", "ar@globex.example"))

    def test_how_it_is_to_be_paid_and_when(self):
        document, _report = self.written(who=described(WHO, {"payment_days": 14}))
        self.assertEqual(amounts(document, "BT-1", "BT-2", "BT-9", "BT-3", "BT-5"),
                         ("GLX-0001", "2026-10-07", "2026-10-21", "380", "EUR"))
        (payment,) = document.all("BG-16")
        self.assertEqual(amounts(payment, "BT-81", "BT-83", "BT-84", "BT-85", "BT-86"),
                         ("30", "GLX-0001", "DE02120300000000202051", "Globex GmbH",
                          "BYLADEM1001"))

    def test_the_sums(self):
        document, _report = self.written()
        self.assertEqual(amounts(document, "BT-106", "BT-109", "BT-110", "BT-112", "BT-115"),
                         ("883.33", "883.33", "167.83", "1051.16", "1051.16"))
        (breakdown,) = document.all("BG-23")
        self.assertEqual(amounts(breakdown, "BT-116", "BT-117", "BT-118", "BT-119"),
                         ("883.33", "167.83", "S", "19"))
        self.assertEqual({(line.text("BT-151"), line.text("BT-152"))
                          for line in document.all("BG-25")}, {("S", "19")})

    def test_half_a_cent_goes_up_on_a_line_and_on_the_vat(self):
        # 3 at 0.335 is 1.005; 19% of 0.50 is 0.095.
        for line, sums in (({"quantity": 3, "price": "0.335"}, ("1.01", "0.19", "1.20")),
                           ({"quantity": 1, "price": "0.50"}, ("0.50", "0.10", "0.60"))):
            document, report = self.written(lines(line))
            self.assertEqual(amounts(document, "BT-106", "BT-110", "BT-115") + (report.verdict,),
                             sums + ("valid",))

    def test_the_vat_is_reckoned_once_on_the_sum_and_not_line_by_line(self):
        # Three lines of 0.02: 19% is 0.0038 on each, which is nothing a
        # line, and 0.0114 on their sum, which is a cent.
        document, report = self.written(lines(*({"line": str(n), "quantity": 1, "price": "0.02"}
                                                for n in range(3))))
        self.assertEqual(amounts(document, "BT-106", "BT-110") + (report.verdict,),
                         ("0.06", "0.01", "valid"))

    def test_another_rate_another_currency_another_country(self):
        who = described(WHO, {"vat_rate": "8.1", "currency": "CHF"})
        document, report = self.written(buyer(country="FR", city=None, postal_code=None,
                                              street=None, vat=None), who)
        self.assertEqual(amounts(document, "BT-5", "BT-110", "BT-55") + (report.verdict,),
                         ("CHF", "71.55", "FR", "valid"))
        self.assertEqual(document.term("BT-115").attributes, {"currencyID": "CHF"})
        document, _report = self.written(order(currency="SEK"), who)
        self.assertEqual(document.text("BT-5"), "SEK")

    def test_some_of_it(self):
        document, report = self.written(quantities={"20": Decimal("1.5")})
        self.assertEqual([(line.text("BT-126"), line.text("BT-132"), line.text("BT-129"),
                           line.text("BT-131")) for line in document.all("BG-25")],
                         [("1", "20", "1.5", "50.00")])
        self.assertEqual(amounts(document, "BT-106", "BT-110", "BT-115") + (report.verdict,),
                         ("50.00", "9.50", "59.50", "valid"))

    def test_an_order_that_makes_an_invoice_that_is_not_valid(self):
        # Germany's rules want a German buyer's city and post code; a GLN
        # has a check digit; a unit is one of Recommendation 20's.
        for said, rule in ((buyer(postal_code=None), "DE-R-009"),
                           (buyer(endpoint="0088:1"), "PEPPOL-COMMON-R040"),
                           (lines({"unit": "each"}), "BR-CL-23")):
            _document, report = self.written(said)
            self.assertEqual(report.verdict, "invalid")
            self.assertIn(rule, [found.code for found in report.failures])


class Billing(unittest.TestCase):
    def setUp(self):
        self.delivered = []
        self.supplier = Supplier(now=lambda: NOON, deliver=lambda xml: (
            self.delivered.append(xml) or {"status": 201}))

    def test_an_order_is_taken_and_nothing_is_billed(self):
        taken = self.supplier.take(ORDER)
        self.assertEqual((taken.id, taken.received, taken.status, taken.invoices),
                         ("1", "2026-10-07T12:00:30", "open", []))
        self.assertIs(self.supplier.orders["1"], taken)
        self.assertEqual(self.supplier.take(order(number="4500000018")).id, "2")
        # A number it already holds is no reason not to take a second.
        self.assertEqual(self.supplier.take(ORDER).id, "3")
        self.assertEqual((self.delivered, self.supplier.sent), ([], {}))

    def test_one_that_could_not_be_billed_is_not_taken(self):
        with self.assertRaises(NotTaken) as raised:
            self.supplier.take(buyer(postal_code=None))
        self.assertEqual(raised.exception.reason, "the invoice for this order would be "
                         "invalid, and an order that cannot be billed is not taken")
        self.assertIn("DE-R-009", [found.code for found in raised.exception.report.failures])
        with self.assertRaises(NotTaken) as raised:
            self.supplier.take(without("lines"))
        self.assertIsNone(raised.exception.report)
        self.assertEqual(self.supplier.orders, {})

    def test_nor_one_whose_invoice_could_not_be_judged(self):
        with unbuilt("peppol", "DE-R-"), self.assertRaises(NotTaken) as raised:
            self.supplier.take(ORDER)
        self.assertIn("would be not judged", raised.exception.reason)

    def test_billed_it_is_sent_like_any_other(self):
        self.supplier.take(ORDER)
        issued = self.supplier.bill("1")
        self.assertEqual((issued.id, issued.number, issued.order, issued.forced,
                          issued.report.verdict, issued.delivery),
                         ("1", "GLX-0001", "1", False, "valid", {"status": 201}))
        self.assertEqual(self.delivered, [issued.xml])
        self.assertEqual(issued.document.text("BT-13"), "4500000017")
        taken = self.supplier.orders["1"]
        self.assertEqual((taken.status, taken.invoices, [line.open for line in taken.lines]),
                         ("billed", ["1"], [0, 0]))

    def test_a_buyer_takes_it_and_its_answer_is_about_it(self):
        receiving = Buyer(now=lambda: NOON, answers="always")
        self.supplier.deliver = lambda xml: {"held": receiving.receive(xml).id}
        receiving.deliver = lambda xml: {"ignored": self.supplier.hear(xml).ignored}
        self.supplier.take(ORDER)
        issued = self.supplier.bill("1")
        self.assertEqual((issued.delivery, issued.status, receiving.invoices["1"].number),
                         ({"held": "1"}, "AB", "GLX-0001"))

    def test_billed_twice_it_is_refused(self):
        self.supplier.take(ORDER)
        self.supplier.bill("1")
        with self.assertRaises(NotBilled) as raised:
            self.supplier.bill("1")
        self.assertEqual((raised.exception.code, raised.exception.reason),
                         ("BILLED", "order 4500000017 is billed in full, by GLX-0001"))
        self.assertEqual(len(self.supplier.sent), 1)

    def test_in_parts(self):
        self.supplier.take(ORDER)
        first = self.supplier.bill("1", {"10": 15})
        taken = self.supplier.orders["1"]
        self.assertEqual((taken.status, [(line.billed, line.open) for line in taken.lines]),
                         ("billed in part", [(15, 25), (0, Decimal("2.5"))]))
        second = self.supplier.bill("1", {"10": "5", "20": Decimal("2.5")})
        rest = self.supplier.bill("1")
        self.assertEqual([(one.number, [(line.text("BT-132"), line.text("BT-129"))
                                        for line in one.document.all("BG-25")])
                          for one in (first, second, rest)],
                         [("GLX-0001", [("10", "15")]),
                          ("GLX-0002", [("10", "5"), ("20", "2.5")]),
                          ("GLX-0003", [("10", "20")])])
        self.assertEqual((taken.status, taken.invoices), ("billed", ["1", "2", "3"]))
        with self.assertRaises(NotBilled) as raised:
            self.supplier.bill("1", {"10": 1})
        self.assertEqual(raised.exception.reason, "order 4500000017 is billed in full, by "
                         "GLX-0001 and GLX-0002 and GLX-0003")

    def test_what_is_not_billed(self):
        self.supplier.take(ORDER)
        self.supplier.bill("1", {"10": 30})
        for identifier, quantities, code, why in (
                ("2", None, "NO-SUCH-ORDER", "no order 2 was taken"),
                ("1", {"30": 1}, "NO-SUCH-LINE", "order 4500000017 has no line 30: its lines "
                                                 "are 10, 20"),
                ("1", {"10": 11}, "OVER-BILLED", "line 10 is to be billed for 11, and 10 of "
                                                 "the 40 ordered is not yet billed"),
                ("1", {"10": 0}, "REQUEST", "line 10 is to be billed for 0"),
                ("1", {"10": "-1"}, "REQUEST", "line 10 is to be billed for -1"),
                ("1", {"10": 0.5}, "REQUEST", "line 10's quantity is a number written as text"),
                ("1", {"10": "some"}, "REQUEST", "line 10's quantity is a number, not 'some'"),
                ("1", {}, "REQUEST", "no line was named to be billed")):
            with self.assertRaises(NotBilled, msg=why) as raised:
                self.supplier.bill(identifier, quantities)
            self.assertEqual(raised.exception.code, code)
            self.assertIn(why, raised.exception.reason)
        taken = self.supplier.orders["1"]
        self.assertEqual(([line.billed for line in taken.lines], len(self.supplier.sent),
                          self.supplier.written), ([30, 0], 1, 1))

    def test_a_refusal_in_a_request_for_two_lines_bills_neither(self):
        self.supplier.take(ORDER)
        with self.assertRaises(NotBilled):
            self.supplier.bill("1", {"10": 1, "20": 3})
        self.assertEqual(self.supplier.orders["1"].status, "open")

    def test_an_invoice_that_is_not_valid_is_not_sent_and_nothing_is_billed(self):
        # The supplier changed after the order was taken: it has no name now.
        self.supplier.take(ORDER)
        self.supplier.describe({"name": ""})
        with self.assertRaises(NotBilled) as raised:
            self.supplier.bill("1")
        self.assertEqual((raised.exception.code, raised.exception.reason),
                         ("NOT-VALID", "the invoice written for order 4500000017 is invalid "
                                       "and was not sent"))
        self.assertIn("BR-06", [found.code for found in raised.exception.report.failures])
        taken = self.supplier.orders["1"]
        self.assertEqual((taken.status, taken.invoices, self.delivered, self.supplier.sent,
                          self.supplier.written), ("open", [], [], {}, 0))
        self.supplier.describe({"name": "Initech AG", "number_prefix": "INI-"})
        self.assertEqual(self.supplier.bill("1").number, "INI-0001")

    def test_its_numbers_are_its_own_count_and_not_the_count_of_what_was_sent(self):
        from .test_buyer import INVOICE
        self.supplier.send(INVOICE)
        self.supplier.take(ORDER)
        issued = self.supplier.bill("1")
        self.assertEqual((issued.id, issued.number, self.supplier.sent["1"].order),
                         ("2", "GLX-0001", ""))

    def test_reset_forgets_the_orders_and_the_count_and_not_who_it_is(self):
        self.supplier.describe({"name": "Initech AG"})
        self.supplier.take(ORDER)
        self.supplier.bill("1")
        self.supplier.reset()
        self.assertEqual((self.supplier.orders, self.supplier.written,
                          self.supplier.who["name"]), ({}, 0, "Initech AG"))
        self.supplier.take(ORDER)
        self.assertEqual(self.supplier.bill("1").number, "GLX-0001")

    def test_a_supplier_can_be_someone_else_from_the_start(self):
        supplier = Supplier(who={"name": "Initech AG"})
        self.assertEqual((supplier.who["name"], supplier.who["vat"]),
                         ("Initech AG", WHO["vat"]))
        with self.assertRaises(NotTaken):
            Supplier(who={"fax": "1"})

    def test_one_change_to_who_it_is_does_not_undo_another(self):
        self.supplier.describe({"name": "Initech AG"})
        now = self.supplier.describe({"city": "Kiel"})
        self.assertEqual((now["name"], now["city"], self.supplier.who), ("Initech AG", "Kiel", now))
        with self.assertRaises(NotTaken):
            self.supplier.describe({"vat_rate": 0})
        self.assertEqual(self.supplier.who, now)

    def test_with_no_buyer_there_it_is_billed_all_the_same(self):
        self.supplier.deliver = lambda xml: {"to": "nowhere", "error": "refused"}
        self.supplier.take(ORDER)
        issued = self.supplier.bill("1")
        self.assertEqual((issued.delivery["error"], self.supplier.orders["1"].status),
                         ("refused", "billed"))


if __name__ == "__main__":
    unittest.main()
