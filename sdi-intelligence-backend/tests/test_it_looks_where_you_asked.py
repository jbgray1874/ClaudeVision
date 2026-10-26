""""Any emails from Charlotte this morning?" - and the answer says where it looked.

James Gray, 26 October 2026. The first release read a fixed seven days, every
message, no narrowing: 484 of them. Asking a question of that meant sending all
484 somewhere and hoping.

The thing that matters most here is not the filtering. It is that "nothing from
Charlotte this morning" is a sentence that can be WRONG in a way that looks
exactly like being right. So:

  * "this morning" is resolved against a real clock in Europe/London, here, and
    never by a model that has to guess the date and the zone;
  * a phrase that is not understood falls back to seven days and SAYS it did,
    rather than quietly searching a different week;
  * every answer carries the span it searched and what it narrowed by, whether
    or not anything matched.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from private_email import Denied, GraphMailbox, UK, window  # noqa: E402

OWNER = "5acf6b37-147f-4468-bdb1-ecc3da1f1076"


def at(text):
    """A UK wall-clock time, as the instant it really is."""
    return datetime.fromisoformat(text).replace(tzinfo=UK).astimezone(timezone.utc)


class WindowTests(unittest.TestCase):
    # 26 October 2026 is a Monday; British Summer Time ended the day before.
    MON = at("2026-10-26 15:38")

    def span(self, phrase, now=None):
        start, end, said = window(phrase, now or self.MON)
        return start.astimezone(UK), end.astimezone(UK), said

    def test_this_morning_is_midnight_to_now_while_it_is_still_morning(self):
        start, end, said = self.span("this morning", at("2026-10-26 09:12"))
        self.assertEqual((start.hour, start.minute), (0, 0))
        self.assertEqual(start.date(), end.date())
        self.assertEqual((end.hour, end.minute), (9, 12))
        self.assertIn("morning", said)

    def test_this_morning_ends_at_noon_once_the_morning_has(self):
        start, end, _ = self.span("this morning")          # asked at 15:38
        self.assertEqual((start.hour, end.hour), (0, 12))

    def test_today_runs_to_now_not_to_midnight_tonight(self):
        start, end, _ = self.span("today")
        self.assertEqual(start.hour, 0)
        self.assertEqual((end.hour, end.minute), (15, 38))

    def test_yesterday_is_a_whole_day_and_stops_at_todays_midnight(self):
        start, end, _ = self.span("yesterday")
        self.assertEqual(start.date().isoformat(), "2026-10-25")
        self.assertEqual(end.date().isoformat(), "2026-10-26")
        self.assertEqual((start.hour, end.hour), (0, 0))

    def test_this_week_starts_on_monday(self):
        for day, expected in (("2026-10-26 15:38", "2026-10-26"),   # Monday
                              ("2026-10-29 09:00", "2026-10-26"),   # Thursday
                              ("2026-11-01 23:00", "2026-10-26")):  # Sunday
            with self.subTest(day=day):
                start, _, _ = self.span("this week", at(day))
                self.assertEqual(start.date().isoformat(), expected)
                self.assertEqual(start.hour, 0)

    def test_last_week_is_the_whole_previous_monday_to_monday(self):
        start, end, _ = self.span("last week")
        self.assertEqual(start.date().isoformat(), "2026-10-19")
        self.assertEqual(end.date().isoformat(), "2026-10-26")

    def test_british_summer_time_is_not_utc(self):
        """In July, UK midnight is 23:00 the previous day in UTC. Resolving
        "today" in UTC would start the day an hour late and miss an email."""
        july = at("2026-07-14 10:00")
        start, _, _ = window("today", july)
        self.assertEqual(start.astimezone(timezone.utc).hour, 23)
        self.assertEqual(start.astimezone(UK).hour, 0)

    def test_an_unknown_phrase_falls_back_to_seven_days_and_says_so(self):
        start, end, said = self.span("whenever Charlotte last wrote")
        self.assertAlmostEqual((end - start).days, 7, delta=1)
        self.assertIn("not understood", said)
        self.assertIn("seven days", said)

    def test_nothing_asked_for_is_the_last_seven_days(self):
        for quiet in ("", None, "   "):
            with self.subTest(quiet=quiet):
                start, end, said = self.span(quiet)
                self.assertAlmostEqual((end - start).days, 7, delta=1)
                self.assertNotIn("not understood", said)

    def test_an_afternoon_asked_for_in_the_morning_is_empty_not_backwards(self):
        """09:12 is not yet the afternoon. An end before its start would be a
        span that matches everything or nothing, depending on the comparison."""
        start, end, _ = self.span("this afternoon", at("2026-10-26 09:12"))
        self.assertEqual(start, end)
        self.assertLessEqual(start, end)


class SearchTests(unittest.TestCase):
    NOW = at("2026-10-26 15:38")

    def mailbox(self, messages):
        asked = []

        def request(method, url, **kwargs):
            asked.append((url, kwargs.get("params")))
            if url.endswith("/me"):
                return {"id": OWNER}
            return {"value": messages}

        box = GraphMailbox(request, OWNER)
        box.asked = asked
        return box

    def message(self, name, address, when, **over):
        row = {"id": name + when, "subject": "x", "bodyPreview": "y",
               "receivedDateTime": at(when).isoformat().replace("+00:00", "Z"),
               "from": {"emailAddress": {"name": name, "address": address}}}
        row.update(over)
        return row

    def test_a_name_narrows_the_answer_without_a_second_trip_to_microsoft(self):
        box = self.mailbox([
            self.message("Charlotte Blackwell", "charlotte.blackwell@wearesdi.com",
                         "2026-10-26 08:40"),
            self.message("Marc Davies", "marc.davies@wearesdi.com", "2026-10-26 09:01"),
        ])
        out = box.review(now=self.NOW, when="this morning", sender="charlotte")
        self.assertEqual([m["from"]["emailAddress"]["name"] for m in out["messages"]],
                         ["Charlotte Blackwell"])
        self.assertEqual(len([u for u, _ in box.asked if "/messages" in u]), 1)

    def test_an_address_is_matched_by_microsoft_not_by_us(self):
        box = self.mailbox([])
        box.review(now=self.NOW, sender="Charlotte.Blackwell@WeAreSDI.com")
        query = [p for u, p in box.asked if "/messages" in u][0]["$filter"]
        self.assertIn("from/emailAddress/address eq 'charlotte.blackwell@wearesdi.com'",
                      query)

    def test_a_quote_in_an_address_cannot_end_the_literal(self):
        box = self.mailbox([])
        box.review(now=self.NOW, sender="o'brien@example.test")
        query = [p for u, p in box.asked if "/messages" in u][0]["$filter"]
        self.assertIn("'o''brien@example.test'", query)

    def test_unread_and_attachments_are_asked_of_microsoft(self):
        box = self.mailbox([])
        box.review(now=self.NOW, unread_only=True, with_attachments=True)
        query = [p for u, p in box.asked if "/messages" in u][0]["$filter"]
        self.assertIn("isRead eq false", query)
        self.assertIn("hasAttachments eq true", query)

    def test_a_message_outside_the_span_is_dropped_even_if_microsoft_returns_it(self):
        """The filter is asked for; it is not relied upon."""
        box = self.mailbox([
            self.message("Charlotte", "c@wearesdi.com", "2026-10-26 08:40"),
            self.message("Charlotte", "c@wearesdi.com", "2026-10-20 08:40"),
        ])
        out = box.review(now=self.NOW, when="this morning", sender="charlotte")
        self.assertEqual(len(out["messages"]), 1)

    def test_the_answer_says_where_it_looked_even_when_empty(self):
        out = self.mailbox([]).review(now=self.NOW, when="this morning",
                                      sender="charlotte", unread_only=True)
        self.assertEqual(out["messages"], [])
        self.assertIn("this morning", out["looked_in"])
        self.assertIn("charlotte", out["looked_in"])
        self.assertIn("unread only", out["looked_in"])
        self.assertTrue(out["complete"])

    def test_an_unknown_phrase_is_admitted_in_the_answer(self):
        out = self.mailbox([]).review(now=self.NOW, when="since the Morrisons meeting")
        self.assertIn("not understood", out["looked_in"])

    def test_the_default_is_still_seven_days_of_everything(self):
        box = self.mailbox([self.message("Anyone", "a@b.test", "2026-10-24 10:00")])
        out = box.review(now=self.NOW)
        self.assertEqual(len(out["messages"]), 1)
        self.assertEqual(out["narrowed"], [])
        self.assertIn("seven days", out["looked_in"])

    def test_the_owner_is_checked_before_anything_is_searched(self):
        box = GraphMailbox(lambda *a, **k: {"id": "someone-else"}, OWNER)
        with self.assertRaises(Denied):
            box.review(now=self.NOW, sender="charlotte")


if __name__ == "__main__":
    unittest.main()
