import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import fixtures as F  # noqa: E402
import normalize as N  # noqa: E402
import fetch_travel_data as T  # noqa: E402


class Normalizers(unittest.TestCase):
    def test_deals_drop_incomplete_and_never_invent(self):
        deals = N.normalize_deals(F.DEALS)
        self.assertEqual([d["destination"] for d in deals], ["Cancun", "Aruba"])
        aruba = deals[1]
        self.assertIsNone(aruba["start_date"])      # malformed date is not kept
        self.assertIsNone(aruba["stops"])           # non-int stops is not kept
        self.assertIsNone(aruba["airline"])

    def test_deals_limit_sorted_by_price(self):
        self.assertEqual(len(N.normalize_deals(F.DEALS, limit=1)), 1)
        self.assertEqual(N.normalize_deals(F.DEALS, limit=1)[0]["price"], 289)

    def test_explore_merge_unions_interests_and_keeps_lowest_price(self):
        cfg = [{"planned": True, "country": "Vietnam", "airport": "HAN"}]
        merged = N.merge_explore([
            N.normalize_explore(F.EXPLORE_BEACH, "beaches"),
            N.normalize_explore(F.EXPLORE_POPULAR, "popular"),
        ], cfg)
        by = {m["name"]: m for m in merged}
        self.assertEqual(by["Cancun"]["interests"], ["beaches", "popular"])
        self.assertEqual(by["Cancun"]["price"], 280)
        self.assertEqual(by["Cancun"]["stops"], 1)         # fields move with the lowest price
        self.assertIsNone(by["Hanoi"]["price"])            # missing price stays None
        self.assertTrue(by["Hanoi"]["planned"])
        self.assertFalse(by["Reykjavik"]["planned"])
        self.assertEqual(merged[-1]["name"], "Hanoi")      # unpriced sorts last

    def test_calendar(self):
        cal = N.normalize_calendar(F.CALENDAR)
        self.assertEqual(len(cal), 2)
        self.assertTrue(cal[1]["low"])
        self.assertFalse(cal[0]["low"])

    def test_hotel_details(self):
        d = N.normalize_hotel_details(F.HOTEL_DETAILS)
        self.assertEqual(d["nightly_rate"], 120)
        self.assertEqual(d["rating"], 4.4)
        none = N.normalize_hotel_details(F.HOTEL_DETAILS_NO_PRICE)
        self.assertIsNone(none["nightly_rate"])
        self.assertIsNone(none["review_count"])

    def test_hotel_calendar(self):
        cal = N.normalize_hotel_calendar(F.HOTEL_CALENDAR)
        self.assertEqual([c["price"] for c in cal], [132, 140])

    def test_photos(self):
        photos = N.normalize_photos(F.PHOTOS)
        self.assertEqual(len(photos), 2)
        self.assertEqual(photos[1]["url"], "https://example.test/b_t.jpg")  # falls back to thumbnail
        self.assertEqual(len(N.normalize_photos(F.PHOTOS, limit=1)), 1)

    def test_reviews_short_attributed_and_skip_translated(self):
        revs = N.normalize_reviews(F.REVIEWS, limit=5, max_chars=100)
        self.assertEqual([r["author"] for r in revs], ["Ricy", "Sam"])
        self.assertLessEqual(len(revs[0]["text"]), 101)
        self.assertTrue(revs[0]["text"].endswith("\u2026"))
        self.assertEqual(revs[0]["source"], "Google")

    def test_pick_airport(self):
        self.assertEqual(N.pick_airport(F.FLIGHT_AUTOCOMPLETE), "CUN")
        self.assertIsNone(N.pick_airport({"suggestions": []}))

    def test_pick_property_requires_accommodation_and_name_match(self):
        self.assertEqual(N.pick_property(F.HOTEL_AUTOCOMPLETE, "Hotel Grand Saigon"), "TOKEN_GRAND")
        self.assertIsNone(N.pick_property(F.HOTEL_AUTOCOMPLETE, "Anatole Hotel Hanoi"))


class Budget(unittest.TestCase):
    def cfg(self):
        return json.loads((HERE.parent / "data" / "config.json").read_text(encoding="utf-8"))

    def test_plan_counts_first_run_then_cached(self):
        cfg = self.cfg()
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        first = T.plan_calls(cfg, {"airports": {}, "hotels": {}}, None, now)
        self.assertEqual(first["hotels autocomplete"], 3)
        self.assertEqual(first["hotel photos"], 3)
        self.assertEqual(first["flights deals"], 1)
        self.assertLessEqual(sum(first.values()), cfg["max_calls_per_run"])
        lookup = {"airports": {d["id"]: "XXX" for d in cfg["destinations"]},
                  "hotels": {h["id"]: "t" for d in cfg["destinations"] for h in d.get("hotels", [])}}
        recent = {"destinations": [{"hotels": [
            {"id": h["id"], "photos_updated_at": "2026-08-30T00:00:00Z", "reviews_updated_at": "2026-08-30T00:00:00Z"}
            for d in cfg["destinations"] for h in d.get("hotels", [])]}]}
        steady = T.plan_calls(cfg, lookup, recent, now)
        self.assertEqual(steady["flights autocomplete"], 0)
        self.assertEqual(steady["hotel photos"], 0)
        self.assertEqual(steady["hotel reviews"], 0)

    def test_client_stops_at_cap(self):
        c = T.Client("k", max_calls=0)
        with self.assertRaises(T.BudgetExceeded):
            c.get("google_flights_deals")


class FakeClient:
    """Returns mocked responses by engine; one engine can be made to fail."""
    RESP = {
        "google_flights_autocomplete": F.FLIGHT_AUTOCOMPLETE,
        "google_hotels_autocomplete": F.HOTEL_AUTOCOMPLETE,
        "google_flights_deals": F.DEALS,
        "google_travel_explore": F.EXPLORE_BEACH,
        "google_flights_calendar": F.CALENDAR,
        "google_hotels": F.HOTEL_DETAILS,
        "google_hotels_price_calendar": F.HOTEL_CALENDAR,
        "google_hotels_photos": F.PHOTOS,
        "google_hotels_reviews": F.REVIEWS,
    }

    def __init__(self, fail=()):
        self.fail, self.calls = set(fail), 0

    def get(self, engine, **params):
        self.calls += 1
        if engine in self.fail:
            raise T.ApiError(engine + ": boom")
        if engine == "google_hotels_autocomplete":   # echo the queried hotel back as a match
            return {"suggestions": [{"value": params["q"], "type": "accommodation", "property_token": "TOK-" + params["q"]}]}
        return self.RESP[engine]


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((HERE.parent / "data" / "config.json").read_text(encoding="utf-8"))
        self.now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    def validate(self, out):
        try:
            from jsonschema import Draft7Validator
        except ImportError:
            self.skipTest("jsonschema not installed")
        for name, doc in out.items():
            schema = json.loads((HERE.parent / "data" / "schema" / (name + ".schema.json")).read_text(encoding="utf-8"))
            errs = list(Draft7Validator(schema).iter_errors(doc))
            self.assertEqual(errs, [], name)

    def test_full_run_matches_schemas_and_budget(self):
        client = FakeClient()
        lookup = {"airports": {}, "hotels": {}}
        planned = sum(T.plan_calls(self.cfg, lookup, None, self.now).values())
        out, warnings = T.run(self.cfg, lookup, {}, client, self.now)
        self.assertEqual(client.calls, planned)                 # plan matches reality
        self.assertEqual(set(out), {"fares", "explore", "calendar", "stays"})
        self.validate(out)
        self.assertEqual(lookup["airports"]["bali"], "CUN")     # cached from autocomplete
        self.assertEqual(len(out["stays"]["destinations"]), 3)

    def test_failure_keeps_previous_block_and_its_old_timestamp(self):
        prev = {"calendar": {"updated_at": "2026-08-20T00:00:00Z", "origin": "STL", "currency": "USD", "routes": [
            {"id": "aruba", "name": "Aruba", "arrival": "AUA", "round_trip_days": 7,
             "updated_at": "2026-08-20T00:00:00Z", "prices": []}]}}
        lookup = {"airports": {d["id"]: "AUA" for d in self.cfg["destinations"]}, "hotels": {}}
        out, warnings = T.run(self.cfg, lookup, prev, FakeClient(fail={"google_flights_calendar"}), self.now)
        aruba = [r for r in out["calendar"]["routes"] if r["id"] == "aruba"]
        self.assertEqual(aruba[0]["updated_at"], "2026-08-20T00:00:00Z")   # page greys this out after 72h
        self.assertTrue(any("calendar" in w for w in warnings))
        self.validate(out)

    def test_unmatched_hotel_is_not_guessed(self):
        class NoMatch(FakeClient):
            def get(self, engine, **p):
                return {"suggestions": []} if engine == "google_hotels_autocomplete" else super().get(engine, **p)
        out, warnings = T.run(self.cfg, {"airports": {}, "hotels": {}}, {}, NoMatch(), self.now)
        hotel = out["stays"]["destinations"][0]["hotels"][0]
        self.assertIsNone(hotel["property_token"])
        self.assertIsNone(hotel["nightly_rate"])
        self.assertEqual(hotel["photos"], [])


if __name__ == "__main__":
    unittest.main()
