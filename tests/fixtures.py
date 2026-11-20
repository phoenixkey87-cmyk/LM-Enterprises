"""Mocked SerpApi responses, trimmed from the shapes in SerpApi's public docs."""

DEALS = {"deals": [
    {"name": "Cancun", "country": "Mexico", "price": 289, "average_price": 540, "discount_percentage": 46,
     "start_date": "2026-10-03", "end_date": "2026-10-09", "airline": "Spirit", "stops": 0,
     "arrival_airport_code": "CUN", "flight_duration": 190, "thumbnail": "https://example.test/t.jpg"},
    {"name": "Nowhere", "country": "X", "price": None},          # no price: dropped
    {"price": 100},                                              # no name: dropped
    {"name": "Aruba", "country": "Aruba", "price": 410, "start_date": "bad-date", "stops": "one"},
]}

EXPLORE_BEACH = {"destinations": [
    {"destination_id": "/m/0a", "name": "Cancun", "country": "Mexico", "flight_price": 300, "start_date": "2026-11-02",
     "number_of_stops": 0, "flight_duration": 190, "airline": "Spirit", "destination_airport": {"code": "CUN"}},
    {"destination_id": "/m/0b", "name": "Reykjavik", "country": "Iceland", "flight_price": 450,
     "start_date": "2026-12-01", "number_of_stops": 1, "destination_airport": {"code": "KEF"}},
]}
EXPLORE_POPULAR = {"destinations": [
    {"destination_id": "/m/0a", "name": "Cancun", "country": "Mexico", "flight_price": 280, "start_date": "2026-11-09",
     "number_of_stops": 1, "destination_airport": {"code": "CUN"}},
    {"destination_id": "/m/0c", "name": "Hanoi", "country": "Vietnam", "flight_price": None,
     "destination_airport": {"code": "HAN"}},
]}

CALENDAR = {"prices": [
    {"outbound_date": "2026-10-01", "return_date": "2026-10-08", "price": 1200},
    {"outbound_date": "2026-10-02", "return_date": "2026-10-09", "price": 980, "low_price": True},
    {"outbound_date": "2026-10-03", "return_date": "2026-10-10"},          # no price: dropped
]}

HOTEL_DETAILS = {"name": "Hotel Grand Saigon", "link": "https://example.test/h", "overall_rating": 4.4,
                 "reviews": 5120, "extracted_hotel_class": 5, "address": "8 Dong Khoi",
                 "rate_per_night": {"extracted_lowest": 120, "extracted_display_price": 100}}
HOTEL_DETAILS_NO_PRICE = {"name": "Hotel Grand Saigon", "overall_rating": 4.4}

HOTEL_CALENDAR = {"prices": [
    {"date": "2027-11-21", "extracted_display_price": 132},
    {"date": "2027-11-22", "extracted_before_taxes_fees": 140},
    {"date": "2027-11-23"},
]}

PHOTOS = {"sections": [{"title": "At a glance", "photos": [
    {"thumbnail_url": "https://example.test/a_t.jpg", "photo_url": "https://example.test/a.jpg", "alt": "Lobby"},
    {"thumbnail_url": "https://example.test/b_t.jpg", "alt": "Pool"},
    {"alt": "no urls"},
]}]}

REVIEWS = {"reviews": [
    {"user": {"name": "Ricy"}, "source": "Google", "rating": 5, "date": "2 weeks ago",
     "snippet": "I had a wonderful stay and truly enjoyed the overall experience. " * 6},
    {"user": {"name": "Sam"}, "rating": 3, "snippet": "Fine."},
    {"user": {"name": "Lee"}, "rating": 5, "snippet": "(Translated by Google) Muy bien"},
    {"user": {"name": "NoText"}, "rating": 5},
]}

FLIGHT_AUTOCOMPLETE = {"suggestions": [
    {"name": "Cancun", "type": "city", "airports": [{"id": "CUN", "name": "Cancun International"}]}]}

HOTEL_AUTOCOMPLETE = {"suggestions": [
    {"value": "Hotel Grand Saigon", "type": "accommodation", "property_token": "TOKEN_GRAND"},
    {"value": "Grand Saigon Tours", "type": "search", "property_token": "NOPE"},
    {"value": "Saigon Hotel Restaurant", "type": "accommodation", "property_token": "TOKEN_OTHER"},
]}
