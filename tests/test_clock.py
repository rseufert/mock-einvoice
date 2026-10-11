"""The clock: pinned or real, moved forward, and said in UTC."""
import datetime
import unittest

from mockeinvoice import read_response
from mockeinvoice.buyer import Buyer
from mockeinvoice.clock import MOST, UTC, Clock, Invalid, moment, stamp, utc
from mockeinvoice.supplier import Supplier

from .test_buyer import INVOICE

NINE = datetime.datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
CEST = datetime.timezone(datetime.timedelta(hours=2))


class AMoment(unittest.TestCase):
    def test_how_one_is_written(self):
        for text, at in (("2026-10-07T09:00", NINE), ("2026-10-07T09:00:00", NINE),
                         ("2026-10-07T09:00Z", NINE), ("2026-10-07T09:00:00Z", NINE),
                         ("2026-10-07T11:00+02:00", NINE), ("2026-10-07T04:00:00-05:00", NINE),
                         ("2026-10-07", NINE.replace(hour=0)),
                         ("2026-10-07T09:00:30", NINE.replace(second=30))):
            self.assertEqual(moment(text), at, text)
            self.assertEqual(moment(text).utcoffset(), datetime.timedelta(0), text)

    def test_how_one_is_not(self):
        for text in ("", "tomorrow", "2026-10-07 09:00", "2026-10-07T09", "2026-10-07T09:00:00.5",
                     "2026-10-07Z", "2026-10-07T09:00 Z", "2026-10-07T09:00+0200",
                     "07.10.2026", "2026-13-01", "2026-02-30T09:00", "2026-10-07T24:00",
                     " 2026-10-07", 20261007, None):
            with self.assertRaises(Invalid, msg=text):
                moment(text)

    def test_a_time_with_no_zone_is_utc_and_one_with_a_zone_is_that_moment(self):
        self.assertEqual(utc(datetime.datetime(2026, 10, 7, 9, 0)), NINE)
        self.assertEqual(utc(datetime.datetime(2026, 10, 7, 11, 0, tzinfo=CEST)), NINE)
        self.assertEqual(utc(datetime.datetime(2026, 10, 7, 11, 0, tzinfo=CEST)).tzinfo, UTC)

    def test_a_stamp_is_to_the_second_in_utc_with_a_z(self):
        self.assertEqual(stamp(datetime.datetime(2026, 10, 7, 9, 0, 30, 999999)),
                         "2026-10-07T09:00:30Z")
        self.assertEqual(stamp(datetime.datetime(2026, 10, 8, 1, 30, tzinfo=CEST)),
                         "2026-10-07T23:30:00Z")


class Pinned(unittest.TestCase):
    def test_it_stands_still(self):
        clock = Clock("2026-10-07T09:00")
        self.assertEqual((clock.now(), clock(), clock.now(), clock.stamp()),
                         (NINE, NINE, NINE, "2026-10-07T09:00:00Z"))
        self.assertEqual(Clock(datetime.datetime(2026, 10, 7, 11, 0, tzinfo=CEST)).now(), NINE)
        self.assertEqual(Clock(datetime.datetime(2026, 10, 7, 9, 0)).now(), NINE)
        with self.assertRaises(Invalid):
            Clock("nine")

    def test_seconds_move_it_and_it_stays_moved(self):
        clock = Clock(NINE)
        self.assertEqual(clock.advance(seconds=90), {
            "from": "2026-10-07T09:00:00Z", "to": "2026-10-07T09:01:30Z", "seconds": 90,
            "pinned": True})
        self.assertEqual(clock.advance(seconds="30")["to"], "2026-10-07T09:02:00Z")
        self.assertEqual((clock.now(), clock.now()), (NINE.replace(minute=2),) * 2)
        self.assertEqual(clock.advance(seconds=0)["seconds"], 0)

    def test_a_time_moves_it_there(self):
        clock = Clock(NINE)
        self.assertEqual(clock.advance(to="2026-10-08T12:00+02:00"), {
            "from": "2026-10-07T09:00:00Z", "to": "2026-10-08T10:00:00Z", "seconds": 90000,
            "pinned": True})
        self.assertEqual(clock.advance(to=datetime.datetime(2026, 10, 9))["to"],
                         "2026-10-09T00:00:00Z")
        self.assertEqual(clock.advance(to="2026-10-09")["seconds"], 0)

    def test_it_does_not_go_backwards_or_too_far_and_stays_where_it_was(self):
        clock = Clock(NINE)
        for how in ({}, {"seconds": 1, "to": "2026-10-08"}, {"seconds": -1},
                    {"seconds": 1.0}, {"seconds": True}, {"seconds": "1.5"}, {"seconds": "٣"},
                    {"seconds": MOST + 1}, {"to": "2026-10-07T08:59:59"}, {"to": "2026-10-06"},
                    {"to": "2036-10-06"}, {"to": "soon"}, {"to": 5}):
            with self.assertRaises(Invalid, msg=how):
                clock.advance(**how)
        self.assertEqual(clock.now(), NINE)
        self.assertEqual(clock.advance(seconds=MOST)["seconds"], MOST)


class NotPinned(unittest.TestCase):
    def test_it_is_real_time_and_then_real_time_moved(self):
        real = [datetime.datetime(2026, 10, 7, 9, 0, 0, 250000, tzinfo=UTC)]
        clock = Clock(real=lambda: real[0])
        self.assertEqual(clock.now(), real[0])
        self.assertEqual(clock.advance(seconds=3600), {
            "from": "2026-10-07T09:00:00Z", "to": "2026-10-07T10:00:00Z", "seconds": 3600,
            "pinned": False})
        real[0] += datetime.timedelta(seconds=5)
        self.assertEqual(clock.stamp(), "2026-10-07T10:00:05Z")
        # A time is moved to by the second, whatever part of one has gone.
        self.assertEqual(clock.advance(to="2026-10-07T10:00:06"), {
            "from": "2026-10-07T10:00:05Z", "to": "2026-10-07T10:00:06Z", "seconds": 1,
            "pinned": False})
        real[0] -= datetime.timedelta(seconds=1)
        # A time it is at within the second is not behind it.
        self.assertEqual(clock.advance(to="2026-10-07T10:00:05")["seconds"], 0)
        with self.assertRaises(Invalid):
            clock.advance(to="2026-10-07T10:00:04")

    def test_with_nothing_given_it_is_now(self):
        before = datetime.datetime.now(UTC)
        self.assertLessEqual(before, Clock().now())
        self.assertLess(Clock().now() - before, datetime.timedelta(seconds=5))
        self.assertEqual(Clock(real=lambda: datetime.datetime(2026, 10, 7, 9, 0)).now(), NINE)


class WhatGoesByIt(unittest.TestCase):
    def test_a_buyer_and_a_supplier_stamp_by_it_and_write_by_it(self):
        clock = Clock("2026-10-07T23:59:30")
        buyer, supplier = Buyer(now=clock, answers="always"), Supplier(now=clock)
        held = buyer.receive(INVOICE)
        first = read_response(held.responses[0].xml)[0]
        self.assertEqual((held.received, first.issue_date, first.issue_time,
                          supplier.send(INVOICE).sent),
                         ("2026-10-07T23:59:30Z", "2026-10-07", "23:59:30",
                          "2026-10-07T23:59:30Z"))
        clock.advance(seconds=45)
        said = read_response(buyer.answer(held.id, "IP", [], [], "", False).xml)[0]
        self.assertEqual((said.issue_date, said.issue_time,
                          supplier.send(INVOICE).sent),
                         ("2026-10-08", "00:00:15", "2026-10-08T00:00:15Z"))

    def test_a_time_they_are_given_in_another_zone_is_said_in_utc(self):
        late = datetime.datetime(2026, 10, 8, 1, 30, tzinfo=CEST)
        buyer = Buyer(now=lambda: late, answers="always")
        held = buyer.receive(INVOICE)
        first = read_response(held.responses[0].xml)[0]
        self.assertEqual((held.received, first.issue_date, first.issue_time),
                         ("2026-10-07T23:30:00Z", "2026-10-07", "23:30:00"))
        from .test_order import ORDER
        supplier = Supplier(now=lambda: late)
        supplier.take(ORDER)
        self.assertEqual(supplier.bill("1").document.text("BT-2"), "2026-10-07")


if __name__ == "__main__":
    unittest.main()
