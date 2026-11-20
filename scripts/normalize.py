"""Pure functions that turn SerpApi responses into the compact JSON the page reads.

No network, no file I/O. Anything SerpApi doesn't return stays None; nothing is
estimated or invented. The page shows "not verified" for None values.
"""
import re

_TAG = re.compile(r"\s+")


def _num(value):
    """Return a positive int/float, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if value > 0 else None


def _str(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _date(value):
    return value if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def normalize_deals(resp, limit=12):
    out = []
    for d in (resp or {}).get("deals") or []:
        price = _num(d.get("price"))
        name = _str(d.get("name"))
        if price is None or name is None:
            continue
        out.append({
            "id": slug("%s-%s-%s" % (name, d.get("start_date"), d.get("end_date"))),
            "destination": name,
            "country": _str(d.get("country")),
            "price": price,
            "average_price": _num(d.get("average_price")),
            "discount_percentage": _num(d.get("discount_percentage")),
            "start_date": _date(d.get("start_date")),
            "end_date": _date(d.get("end_date")),
            "airline": _str(d.get("airline")),
            "stops": d.get("stops") if isinstance(d.get("stops"), int) else None,
            "arrival_airport_code": _str(d.get("arrival_airport_code")),
            "flight_duration": _num(d.get("flight_duration")),
            "thumbnail": _str(d.get("thumbnail")),
        })
    out.sort(key=lambda x: x["price"])
    return out[:limit]


def normalize_explore(resp, interest_key):
    out = []
    for d in (resp or {}).get("destinations") or []:
        name = _str(d.get("name"))
        if name is None:
            continue
        airport = d.get("destination_airport") or {}
        out.append({
            "id": _str(d.get("destination_id")) or slug(name),
            "name": name,
            "country": _str(d.get("country")),
            "price": _num(d.get("flight_price")),
            "start_date": _date(d.get("start_date")),
            "end_date": _date(d.get("end_date")),
            "stops": d.get("number_of_stops") if isinstance(d.get("number_of_stops"), int) else None,
            "flight_duration": _num(d.get("flight_duration")),
            "airline": _str(d.get("airline")),
            "airport": _str(airport.get("code")),
            "thumbnail": _str(d.get("thumbnail")),
            "interests": [interest_key],
        })
    return out


def merge_explore(batches, destinations_cfg):
    """Merge per-interest result lists, union the interests, flag planned destinations."""
    merged = {}
    for batch in batches:
        for item in batch:
            cur = merged.get(item["id"])
            if cur is None:
                merged[item["id"]] = dict(item)
                continue
            cur["interests"] = sorted(set(cur["interests"]) | set(item["interests"]))
            if item["price"] is not None and (cur["price"] is None or item["price"] < cur["price"]):
                for k in ("price", "start_date", "end_date", "stops", "flight_duration", "airline", "airport"):
                    cur[k] = item[k]
    airports = {d.get("airport") for d in destinations_cfg if d.get("planned") and d.get("airport")}
    airports |= {d.get("_resolved_airport") for d in destinations_cfg if d.get("planned") and d.get("_resolved_airport")}
    countries = {(d.get("country") or "").lower() for d in destinations_cfg if d.get("planned")}
    for item in merged.values():
        item["planned"] = bool(
            (item["airport"] and item["airport"] in airports)
            or ((item["country"] or "").lower() in countries)
        )
    return sorted(merged.values(), key=lambda x: (x["price"] is None, x["price"] or 0))


def normalize_calendar(resp):
    out = []
    for p in (resp or {}).get("prices") or []:
        price = _num(p.get("price"))
        od = _date(p.get("outbound_date"))
        if price is None or od is None:
            continue
        out.append({"outbound_date": od, "return_date": _date(p.get("return_date")),
                    "price": price, "low": bool(p.get("low_price"))})
    return out


def normalize_hotel_details(resp):
    r = resp or {}
    rate = r.get("rate_per_night") or {}
    nightly = _num(rate.get("extracted_lowest")) or _num(rate.get("extracted_display_price"))
    return {
        "name": _str(r.get("name")),
        "link": _str(r.get("link")),
        "rating": _num(r.get("overall_rating")),
        "review_count": _num(r.get("reviews")),
        "hotel_class": _num(r.get("extracted_hotel_class")),
        "nightly_rate": nightly,
        "address": _str(r.get("address")),
    }


def normalize_hotel_calendar(resp):
    out = []
    for p in (resp or {}).get("prices") or []:
        price = _num(p.get("extracted_display_price")) or _num(p.get("extracted_before_taxes_fees"))
        d = _date(p.get("date"))
        if price is None or d is None:
            continue
        out.append({"date": d, "price": price})
    return out


def normalize_photos(resp, limit=8):
    out = []
    for section in (resp or {}).get("sections") or []:
        for ph in section.get("photos") or []:
            full = _str(ph.get("photo_url")) or _str(ph.get("thumbnail_url"))
            thumb = _str(ph.get("thumbnail_url")) or full
            if not full:
                continue
            out.append({"thumb": thumb, "url": full, "alt": _str(ph.get("alt")) or ""})
            if len(out) >= limit:
                return out
    return out


def shorten(text, max_chars):
    text = _TAG.sub(" ", text or "").strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",.;:!- ")
    return cut + "\u2026"


def normalize_reviews(resp, limit=3, max_chars=220):
    out = []
    for r in (resp or {}).get("reviews") or []:
        snippet = _str(r.get("snippet"))
        if not snippet or "Translated by Google" in snippet:
            continue
        rating = _num(r.get("rating"))
        user = r.get("user") or {}
        out.append({
            "text": shorten(snippet, max_chars),
            "rating": rating,
            "source": _str(r.get("source")) or "Google",
            "author": _str(user.get("name")),
            "date": _str(r.get("date")),
        })
        if len(out) >= limit:
            break
    return out


def _tokens(text):
    return {t for t in slug(text).split("-") if t and t not in {"hotel", "the", "resort", "and"}}


def pick_airport(resp, preferred_type=None):
    """First airport id from a Flights Autocomplete response, or None."""
    for s in (resp or {}).get("suggestions") or []:
        for a in s.get("airports") or []:
            code = _str(a.get("id"))
            if code and re.fullmatch(r"[A-Z]{3}", code):
                return code
    return None


def pick_property(resp, wanted_name, min_overlap=0.6):
    """property_token for the suggestion that best matches wanted_name, or None.

    Requires type 'accommodation' and at least min_overlap of the wanted name's
    distinctive words present in the suggestion, so a wrong hotel is never picked.
    """
    want = _tokens(wanted_name)
    if not want:
        return None
    best, best_score = None, 0
    for s in (resp or {}).get("suggestions") or []:
        token = _str(s.get("property_token"))
        if s.get("type") != "accommodation" or not token:
            continue
        score = len(want & _tokens(s.get("value") or "")) / len(want)
        if score > best_score:
            best, best_score = token, score
    return best if best_score >= min_overlap else None
