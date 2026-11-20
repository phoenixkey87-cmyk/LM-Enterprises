#!/usr/bin/env python3
"""Fetch Google Flights / Hotels data through SerpApi and write static JSON to /data.

Runs in GitHub Actions (SERPAPI_API_KEY comes from a repository secret). The web
page only reads the JSON files this script writes; it never talks to SerpApi.

Usage:
  python scripts/fetch_travel_data.py            # real run
  python scripts/fetch_travel_data.py --plan     # print the call budget and exit (no key needed)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normalize as N  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ENDPOINT = "https://serpapi.com/search.json"


class BudgetExceeded(RuntimeError):
    pass


class Client:
    """Thin SerpApi client with a hard call cap. The API key is never logged."""

    def __init__(self, api_key, max_calls):
        self.api_key = api_key
        self.max_calls = max_calls
        self.calls = 0
        self.failures = 0

    def get(self, engine, **params):
        if self.calls >= self.max_calls:
            raise BudgetExceeded("MAX_CALLS_PER_RUN (%d) reached" % self.max_calls)
        self.calls += 1
        query = {"engine": engine, "api_key": self.api_key}
        query.update({k: v for k, v in params.items() if v is not None})
        url = ENDPOINT + "?" + urllib.parse.urlencode(query)
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    body = json.loads(r.read().decode("utf-8"))
                if isinstance(body, dict) and body.get("error"):
                    # e.g. "Google hasn't returned any results for this query."
                    raise ApiError("%s: %s" % (engine, body["error"]))
                return body
            except urllib.error.HTTPError as e:
                last = ApiError("%s: HTTP %s" % (engine, e.code))
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except ApiError as e:
                last = e
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last = ApiError("%s: %s" % (engine, type(e).__name__))
            time.sleep(2 * (attempt + 1))
        self.failures += 1
        raise last


class ApiError(RuntimeError):
    pass


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def day(now, offset):
    return (now + timedelta(days=offset)).strftime("%Y-%m-%d")


def flight_destinations(cfg):
    return [d for d in cfg["destinations"] if d.get("flights", True) and (d.get("airport") or d.get("flight_query"))]


def hotels_of(cfg):
    for d in cfg["destinations"]:
        if d.get("featured"):
            for h in d.get("hotels") or []:
                yield d, h


def prev_hotels(prev_stays):
    out = {}
    for d in (prev_stays or {}).get("destinations", []):
        for h in d.get("hotels", []):
            out[h["id"]] = h
    return out


def photos_reviews_due(prev_hotel, now, days, field):
    """True when photos/reviews were never fetched or are older than `days`."""
    ts = parse_iso((prev_hotel or {}).get(field + "_updated_at"))
    return ts is None or now - ts >= timedelta(days=days)


def plan_calls(cfg, lookup, prev_stays, now):
    """Return {category: count}. Mirrors exactly what run() will request."""
    days = cfg.get("photos_reviews_refresh_days", 7)
    ph = prev_hotels(prev_stays)
    c = {
        "flights autocomplete": sum(1 for d in flight_destinations(cfg)
                                    if not d.get("airport") and d["id"] not in lookup["airports"]),
        "hotels autocomplete": sum(1 for _, h in hotels_of(cfg)
                                   if not h.get("property_token") and h["id"] not in lookup["hotels"]),
        "flights deals": 1,
        "travel explore": len(cfg["explore"]["interests"]),
        "flights calendar": len(flight_destinations(cfg)),
        "hotel details": 0, "hotel price calendar": 0, "hotel photos": 0, "hotel reviews": 0,
    }
    for _, h in hotels_of(cfg):
        c["hotel details"] += 1
        c["hotel price calendar"] += 1
        if photos_reviews_due(ph.get(h["id"]), now, days, "photos"):
            c["hotel photos"] += 1
        if photos_reviews_due(ph.get(h["id"]), now, days, "reviews"):
            c["hotel reviews"] += 1
    return c


def run(cfg, lookup, prev, client, now):
    G = {"gl": cfg["gl"], "hl": cfg["hl"], "currency": cfg["currency"]}
    origin = cfg["origin"]["airport"]
    ts = iso(now)
    out = {}
    warnings = []

    def attempt(label, fn):
        try:
            return fn()
        except BudgetExceeded:
            raise
        except ApiError as e:
            warnings.append("%s failed (%s)" % (label, e))
            print("WARN:", warnings[-1])
            return None

    # --- Resolve IDs once (cached in data/lookup.json) --------------------------------
    for d in flight_destinations(cfg):
        if d.get("airport"):
            d["_resolved_airport"] = d["airport"]
            continue
        code = lookup["airports"].get(d["id"])
        if not code:
            resp = attempt("airport lookup " + d["id"], lambda: client.get(
                "google_flights_autocomplete", q=d["flight_query"], exclude_regions="true", gl=cfg["gl"], hl=cfg["hl"]))
            code = N.pick_airport(resp)
            if code:
                lookup["airports"][d["id"]] = code
            else:
                warnings.append("no airport resolved for %s; skipping its flights" % d["id"])
        d["_resolved_airport"] = code

    for d, h in hotels_of(cfg):
        token = h.get("property_token") or lookup["hotels"].get(h["id"])
        if not token:
            resp = attempt("hotel lookup " + h["id"], lambda: client.get(
                "google_hotels_autocomplete", q=h["query"], gl=cfg["gl"], hl=cfg["hl"], currency=cfg["currency"]))
            token = N.pick_property(resp, h["name"])
            if token:
                lookup["hotels"][h["id"]] = token
            else:
                warnings.append("no confident property match for '%s'; add property_token in config" % h["name"])
        h["_token"] = token

    # --- Flights Deals ------------------------------------------------------------------
    w = cfg["date_windows"]["deals"]
    resp = attempt("flights deals", lambda: client.get(
        "google_flights_deals", departure_id=origin, type=1,
        outbound_date="%s,%s" % (day(now, w["start_offset_days"]), day(now, w["end_offset_days"])),
        trip_length=cfg["trip_lengths"]["deals"], **G))
    if resp is not None:
        out["fares"] = {"updated_at": ts, "stale_hours": cfg["stale_hours"], "origin": origin, "currency": cfg["currency"],
                        "deals": N.normalize_deals(resp, cfg["deals"]["max_items"])}

    # --- Travel Explore -----------------------------------------------------------------
    batches = []
    for it in cfg["explore"]["interests"]:
        params = dict(departure_id=origin, month=0, type=1,
                      travel_duration=cfg["trip_lengths"]["explore_travel_duration"], **G)
        if it["id"] != "0":
            params["interest"] = it["id"]
        resp = attempt("explore " + it["key"], lambda: client.get("google_travel_explore", **params))
        if resp is not None:
            batches.append(N.normalize_explore(resp, it["key"]))
    if batches:
        out["explore"] = {"updated_at": ts, "stale_hours": cfg["stale_hours"], "origin": origin, "currency": cfg["currency"],
                          "interests": [{"key": i["key"], "label": i["label"]} for i in cfg["explore"]["interests"]],
                          "destinations": N.merge_explore(batches, cfg["destinations"])}

    # --- Flights Calendar (one call per route) ------------------------------------------
    cw = cfg["date_windows"]["calendar"]
    rt = cfg["trip_lengths"]["calendar_round_trip_days"]
    prev_routes = {r["id"]: r for r in (prev.get("calendar") or {}).get("routes", [])}
    routes = []
    for d in flight_destinations(cfg):
        code = d.get("_resolved_airport")
        if not code:
            if d["id"] in prev_routes:
                routes.append(prev_routes[d["id"]])
            continue
        resp = attempt("calendar " + d["id"], lambda: client.get(
            "google_flights_calendar", departure_id=origin, arrival_id=code, type=1,
            date_range_start=day(now, cw["start_offset_days"]), date_range_end=day(now, cw["end_offset_days"]),
            round_trip_days=rt, **G))
        if resp is not None:
            routes.append({"id": d["id"], "name": d["name"], "arrival": code, "round_trip_days": rt,
                           "updated_at": ts, "prices": N.normalize_calendar(resp)})
        elif d["id"] in prev_routes:
            routes.append(prev_routes[d["id"]])  # keeps its old updated_at, so the page greys it out after stale_hours
    if routes:
        out["calendar"] = {"updated_at": ts, "stale_hours": cfg["stale_hours"], "origin": origin, "currency": cfg["currency"], "routes": routes}

    # --- Stays ---------------------------------------------------------------------------
    sc = cfg["stays"]
    days = cfg.get("photos_reviews_refresh_days", 7)
    old = prev_hotels(prev.get("stays"))
    stay_dests = []
    for d in cfg["destinations"]:
        if not d.get("featured") or not d.get("hotels"):
            continue
        hotels = []
        for h in d["hotels"]:
            o = old.get(h["id"], {})
            rec = {"id": h["id"], "name": h["name"], "property_token": h.get("_token"),
                   "link": o.get("link"), "rating": o.get("rating"), "review_count": o.get("review_count"),
                   "hotel_class": o.get("hotel_class"), "address": o.get("address"),
                   "nightly_rate": o.get("nightly_rate"), "rate_check_in": o.get("rate_check_in"),
                   "rate_check_out": o.get("rate_check_out"), "price_updated_at": o.get("price_updated_at"),
                   "calendar": o.get("calendar", []), "photos": o.get("photos", []),
                   "photos_updated_at": o.get("photos_updated_at"), "reviews": o.get("reviews", []),
                   "reviews_updated_at": o.get("reviews_updated_at")}
            token = h.get("_token")
            if token:
                ci, co = day(now, w_off(cfg)), day(now, w_off(cfg) + 1)
                resp = attempt("hotel details " + h["id"], lambda: client.get(
                    "google_hotels", property_token=token, check_in_date=ci, check_out_date=co,
                    adults=cfg["adults"], **G))
                if resp is not None:
                    det = N.normalize_hotel_details(resp)
                    rec.update({k: det[k] for k in ("link", "rating", "review_count", "hotel_class", "address", "nightly_rate")})
                    rec.update({"rate_check_in": ci, "rate_check_out": co, "price_updated_at": ts})
                cal = d.get("calendar_window") or {
                    "start": day(now, cfg["date_windows"]["hotel_calendar_default"]["start_offset_days"]),
                    "end": day(now, cfg["date_windows"]["hotel_calendar_default"]["end_offset_days"])}
                resp = attempt("hotel calendar " + h["id"], lambda: client.get(
                    "google_hotels_price_calendar", property_token=token, start_date=cal["start"], end_date=cal["end"],
                    adults=cfg["adults"], **G))
                if resp is not None:
                    rec["calendar"] = N.normalize_hotel_calendar(resp)
                    rec["price_updated_at"] = ts
                if photos_reviews_due(o, now, days, "photos"):
                    resp = attempt("hotel photos " + h["id"], lambda: client.get("google_hotels_photos", property_token=token))
                    if resp is not None:
                        rec["photos"] = N.normalize_photos(resp, sc["photos_per_hotel"])
                        rec["photos_updated_at"] = ts
                if photos_reviews_due(o, now, days, "reviews"):
                    resp = attempt("hotel reviews " + h["id"], lambda: client.get(
                        "google_hotels_reviews", property_token=token, hl=cfg["hl"]))
                    if resp is not None:
                        rec["reviews"] = N.normalize_reviews(resp, sc["reviews_per_hotel"], sc["review_max_chars"])
                        rec["reviews_updated_at"] = ts
            hotels.append(rec)
        stay_dests.append({"id": d["id"], "name": d["name"], "planned": bool(d.get("planned")), "hotels": hotels})
    if stay_dests:
        out["stays"] = {"updated_at": ts, "stale_hours": cfg["stale_hours"], "currency": cfg["currency"], "destinations": stay_dests}
    return out, warnings


def w_off(cfg):
    return cfg["date_windows"]["hotel_rate_offset_days"]


def main(argv):
    cfg = load(DATA / "config.json", None)
    if cfg is None:
        print("ERROR: data/config.json missing or invalid")
        return 1
    lookup = load(DATA / "lookup.json", {})
    lookup.setdefault("airports", {})
    lookup.setdefault("hotels", {})
    prev = {k: load(DATA / (k + ".json"), None) for k in ("fares", "explore", "calendar", "stays")}
    now = datetime.now(timezone.utc)

    counts = plan_calls(cfg, lookup, prev["stays"], now)
    total = sum(counts.values())
    limit = int(os.environ.get("MAX_CALLS_PER_RUN") or cfg["max_calls_per_run"])
    print("Planned SerpApi calls this run:")
    for k, v in counts.items():
        print("  %-22s %d" % (k, v))
    print("  %-22s %d (limit MAX_CALLS_PER_RUN=%d)" % ("TOTAL", total, limit))
    if total > limit:
        print("ERROR: planned calls exceed MAX_CALLS_PER_RUN. Nothing was fetched. "
              "Trim data/config.json or raise the limit on purpose.")
        return 2
    if "--plan" in argv:
        return 0

    key = os.environ.get("SERPAPI_API_KEY")
    if not key:
        print("ERROR: SERPAPI_API_KEY is not set (add it under Settings > Secrets and variables > Actions)")
        return 1

    client = Client(key, limit)
    work_cfg = deepcopy(cfg)
    try:
        out, warnings = run(work_cfg, lookup, prev, client, now)
    except BudgetExceeded as e:
        print("ERROR:", e, "(files left untouched)")
        return 2
    print("SerpApi calls made: %d, failed: %d" % (client.calls, client.failures))

    if client.calls and client.failures == client.calls:
        print("ERROR: every SerpApi call failed; leaving existing data untouched")
        return 1
    for name, obj in out.items():
        save(DATA / (name + ".json"), obj)
    save(DATA / "lookup.json", lookup)
    print("Wrote:", ", ".join(sorted(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
