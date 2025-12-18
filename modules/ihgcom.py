"""
IHG hotel scraper (GraphQL + Offers API).

This script:
1) Queries the IHG GraphQL endpoint to get hotels near a given location (metadata only).
2) Queries the IHG offers endpoint per hotel per night to collect rates.
3) Merges results into a single JSON output: ihg_parsed.json

The output schema is:
{
  "search": {...},
  "hotels": [
    {
      "hotel_code": str,
      "hotel_name": str,
      "address": str,
      "city": str|None,
      "state_province": str|None,
      "country": str|None,
      "property_url": str|None,
      "images": [str, ...],
      "coordinates": {"latitude": float|None, "longitude": float|None},
      "currency": str|None,
      "room_categories": {
        "<category_code>": {
          "category_code": str,
          "name": str,
          "rates": [
            {
              "date": "YYYY-MM-DD",
              "cash_rate": float|None,
              "starting_rate_points": int|None,
              "points_cash_extra_cash": float|None,
              "points_cash_currency": str|None
            }
          ]
        }
      }
    }
  ]
}

Notes:
- The script intentionally prints debug logs from parsers.
- The offers endpoint fieldset controls which nested fields are returned.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

import requests

GRAPHQL_URL = "https://apis.ihg.com/graphql/v1/hotels"
OFFERS_URL = "https://apis.ihg.com/availability/v3/hotels/offers"

# Fieldset controls which fields are returned by the offers endpoints
OFFERS_FIELDSET_DETAILS = "rateDetails,rateDetails.policies,rateDetails.bonusRates,rateDetails.upsells,alternatePayments"

API_KEY = os.getenv("API_KEY")
IHG_SESSION_ID = os.getenv("IHG_SESSION_ID")

# Kept for compatibility;currently not used(cookies are established via warmup_session)
COOKIE = r""

GRAPHQL_OPERATION_NAME = "GetHotelDetails"
GRAPHQL_QUERY = """
query GetHotelDetails($detailsInput: HotelArgs, $mediaArgs: MediaArgs) {
  getHotels(input: $detailsInput) {
    hotelInfo {
      hotelCode
      address { street1 street2 street3 city zip state { code name } country { name code } }
      profile {
        name seoCity nonIhgCrsUrl independentNonIHGWebsiteURL
        latLong { lon lat }
      }
      media(input: $mediaArgs) {
        primaryPhotos {
          allPhotos { originalUrl }
        }
      }
    }
  }
}
"""


def warmup_session(s: requests.Session) -> None:
    """
        Warm up a requests session by visiting IHG pages.

        Purpose:
            Establish cookies and reduce the chance of API blocks.

        Args:
            s: Requests session that will be reused for API calls.

        Returns:
            None. Any network errors are silently ignored.
        """

    warm_headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "uk,en-US;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "pragma": "no-cache",
    }
    for url in (
            "https://www.ihg.com/",
            "https://www.ihg.com/hotels/us/en/reservation",
            "https://apis.ihg.com/",
    ):
        try:
            s.get(url, headers=warm_headers, timeout=30, allow_redirects=True)
        except Exception:
            pass


def as_list(x: Any) -> List[Any]:
    """
        Normalize an unknown JSON value into a list.

        Args:
            x: Any value (list/dict/other).

        Returns:
            - If x is a list: returns x
            - If x is a dict: returns [x]
            - Otherwise: returns []
        """
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return [x]
    return []


def pick_images(hotel: Dict[str, Any], limit: int = 5) -> List[str]:
    """
        Extract up to `limit` unique image URLs from a GraphQL hotel payload.

        Args:
            hotel: One hotel object from GraphQL response.
            limit: Max number of URLs to return.

        Returns:
            List of image URLs (strings), possibly empty.
        """
    photos = (((hotel.get("media") or {}).get("primaryPhotos") or {}).get("allPhotos") or [])
    out = []
    for p in photos:
        if not isinstance(p, dict):
            continue
        u = p.get("originalUrl")
        if u and u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def parse_cash_rate_from_rate_detail(rd: dict) -> float | None:
    # print(f'Raw rd{rd}')
    """
        Parse the cash rate from a rate-detail-like object.

        Expected structure:
            rd["offers"][0]["productUses"][0]["rates"]["dailyRates"][0]["dailyTotalRate"]["amountAfterTax"]

        Args:
            rd: Dictionary that contains an "offers" list in the above shape.

        Returns:
            The cash price (amountAfterTax) as float if found, otherwise None.

        Side effects:
            Prints debug messages when expected keys/types are missing.
        """

    offers = rd.get("offers") or []
    if not isinstance(offers, list) or not offers or not isinstance(offers[0], dict):
        print(f'Offers not a dict')
        return None

    print(f'0 off offers {offers[0]}')

    pus = offers[0].get("productUses") or []
    print(f'0 pus {pus}')
    if not isinstance(pus, list) or not pus or not isinstance(pus[0], dict):
        print(f'PUS not a dict')
        return None

    rates = pus[0].get("rates") or []
    if not isinstance(rates, dict):
        print(f'rates not a dict')
        return None

    daily_rates = rates.get("dailyRates") or []
    if not isinstance(daily_rates, list) or not daily_rates or not isinstance(daily_rates[0], dict):
        print(f'dailyRates not a dict')
        return None

    dtr = daily_rates[0].get("dailyTotalRate") or {}
    if not isinstance(dtr, dict):
        print(f'dailyTotalRate not a dict')
        return None

    v = dtr.get("amountAfterTax")
    if v is None:
        print(f'v = {v} before float')
        print(f'amount after tax is none')
        return None

    try:
        print(f'v = {v} after float')
        return float(v)
    except Exception:
        return None


def parse_points_from_offer(offer: dict, stay_date: str):
    """
        Parse reward-night points information from an offer object.

        Expected structure:
            offer["rewardNights"]["pointsOnly"]["daily"] contains items like:
                {"stayDate": "YYYY-MM-DD", "points": 26000}
            offer["rewardNights"]["pointsCash"]["options"] contains items like:
                {"totalPoints": 24000, "totalCash": 19, "currency": "USD", ...}

        Args:
            offer: Offer object (dict) that may include "rewardNights".
            stay_date: Date string ("YYYY-MM-DD") used to pick matching daily points.

        Returns:
            Tuple:
                (points_only, points_cash_points, points_cash_cash, points_cash_currency)

            Where:
                points_only: int|None
                points_cash_points: int|None (best/lowest totalPoints)
                points_cash_cash: number|None (paired cash value for the selected option)
                points_cash_currency: str|None
        """
    rn = offer.get("rewardNights") or {}
    if not isinstance(rn, dict):
        return None, None, None, None

    point_only = None
    po = rn.get("pointsOnly") or {}
    if isinstance(po, dict):
        daily = po.get("daily") or []
        if isinstance(daily, list):
            for d in daily:
                if isinstance(d, dict) and d.get("stayDate") == stay_date:
                    p = d.get("points")
                    if isinstance(p, int):
                        point_only = p
                        break
        if point_only is None:
            tp = po.get("totalPoints")
            if isinstance(tp, int):
                point_only = tp

    pc_pts = pc_cash = pc_cur = None
    pc = rn.get("pointsCash") or {}
    opts = pc.get("options") or []
    if isinstance(opts, list):
        best = None
        for o in opts:
            if isinstance(o, dict) and isinstance(o.get("totalPoints"), int):
                if best is None or o["totalPoints"] < best["totalPoints"]:
                    best = o
        if best:
            pc_pts = best.get("totalPoints")
            pc_cash = best.get("totalCash")
            pc_cur = best.get("currency")

    return point_only, pc_pts, pc_cash, pc_cur


def full_address(addr: Dict[str, Any]) -> str:
    """
        Build a human-readable full address string.

        Args:
            addr: Address dict from GraphQL hotelInfo.address.

        Returns:
            A comma-separated address string (may be empty).
        """
    state = addr.get("state") or {}
    country = addr.get("country") or {}
    parts = [
        addr.get("street1"),
        addr.get("street2"),
        addr.get("street3"),
        addr.get("zip"),
        addr.get("city"),
        (state.get("name") or state.get("code")) if isinstance(state, dict) else None,
        (country.get("name")) if isinstance(country, dict) else None,
    ]
    return ", ".join([p for p in parts if p])


def make_graphql_variables(rebrand_start_date: str, lat: float, lon: float, radius_km: int = 375, size: int = 120) -> \
        Dict[str, Any]:
    """
        Create GraphQL variables for geo-based hotel search.

        Args:
            rebrand_start_date: Date string used by the API (typically check-in date).
            lat: Latitude.
            lon: Longitude.
            radius_km: Search radius in kilometers.
            size: Max number of hotels to return.

        Returns:
            Variables dict for the GraphQL query.
        """

    return {
        "detailsInput": {
            "rebrandStartDate": rebrand_start_date,
            "geoLocation": {"lat": lat, "lon": lon, "radius": radius_km},
            "geoLocationDistance": {"distanceType": "STRAIGHT_LINE", "distanceUnit": "KM"},
            "fallbackSearch": {"minHotels": 1, "maxRadius": 100, "incrementRadiusBy": 70},
            "size": size,
            "sortBy": "DISTANCE",
        },
        "mediaArgs": {"formats": [{"aspectHeight": "3", "aspectWidth": "4"}]},
    }


def dig_amount(x: Any) -> Optional[float]:
    """
       Recursively find a numeric amount in a nested dict/list.

       Args:
           x: Any nested JSON-like object.

       Returns:
           First amount found as float, otherwise None.
       """
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, dict):
        for k in ("amountAfterTax", "amount", "baseAmount", "amountBeforeTax", "total", "value"):
            v = x.get(k)
            if isinstance(v, (int, float)):
                return float(v)
        for v in x.values():
            out = dig_amount(v)
            if out is not None:
                return out
    if isinstance(x, list):
        for v in x:
            out = dig_amount(v)
            if out is not None:
                return out
    return None


def parse_hotels_from_graphql(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
        Convert GraphQL response into the internal hotels_map structure.

        Args:
            payload: Full GraphQL JSON response.

        Returns:
            Dict keyed by hotel_code, each value containing hotel metadata and empty room_categories.
        """
    hotels = (((payload.get("data") or {}).get("getHotels") or {}).get("hotelInfo") or [])
    out: Dict[str, Dict[str, Any]] = {}
    for h in hotels:
        if not isinstance(h, dict):
            continue
        code = h.get("hotelCode") or ""
        addr = h.get("address") or {}
        profile = h.get("profile") or {}
        latlong = profile.get("latLong") or {}
        country = (addr.get("country") or {}) if isinstance(addr, dict) else {}
        state = (addr.get("state") or {}) if isinstance(addr, dict) else {}

        out[code] = {
            "hotel_code": code,
            "hotel_name": profile.get("name") or "",
            "address": full_address(addr if isinstance(addr, dict) else {}),
            "city": (addr.get("city") if isinstance(addr, dict) else None),
            "state_province": (state.get("name") or state.get("code")) if isinstance(state, dict) else None,
            "country": (country.get("name")) if isinstance(country, dict) else None,
            "property_url": profile.get("nonIhgCrsUrl") or profile.get("independentNonIHGWebsiteURL"),
            "images": pick_images(h, limit=5),
            "coordinates": {
                "latitude": latlong.get("lat") if isinstance(latlong, dict) else None,
                "longitude": latlong.get("lon") if isinstance(latlong, dict) else None,
            },
            "currency": None,
            "room_categories": {},  # key -> {category_code,name,rates:[...]}
        }
    return out


def parse_offers_into_one_hotel(hotel_obj: Dict[str, Any], offers_json: Dict[str, Any], stay_date: str) -> None:
    """
        Merge offers response (one hotel, one night) into a hotel object.

        Expected offers_json structure (simplified):
            offers_json["hotels"][0]["rateDetails"]["offers"] is a list of offer dicts,
            each offer has "productUses" which defines the inventoryTypeCode (room category).

        What gets added/updated:
            hotel_obj["currency"] (if missing)
            hotel_obj["room_categories"][<inventoryTypeCode>]["rates"] appended for stay_date

        Args:
            hotel_obj: The mutable hotel object from hotels_map (output of parse_hotels_from_graphql).
            offers_json: Raw JSON response from OFFERS_URL.
            stay_date: Current date being processed (YYYY-MM-DD).

        Returns:
            None (mutates hotel_obj in place).

        Side effects:
            Prints debug logs for offers and parsed values.
        """
    root = offers_json.get("data") or offers_json
    hotels = root.get("hotels") or []
    if not hotels:
        return
    h = hotels[0]
    if not isinstance(h, dict):
        return

    if h.get("propertyCurrency") and not hotel_obj.get("currency"):
        hotel_obj["currency"] = h.get("propertyCurrency")

    room_name_by_key: Dict[str, str] = {}
    for pd in as_list(h.get("productDefinitions")):
        if not isinstance(pd, dict):
            continue
        name = pd.get("synthInventoryTypeName") or pd.get("inventoryTypeName") or pd.get("inventoryTypeCode") or ""
        inv = pd.get("inventoryTypeCode")
        if inv:
            room_name_by_key[str(inv)] = str(name)

    rate_details = h.get("rateDetails") or {}
    offers = rate_details.get("offers") or []

    for offer in offers:
        print('offer in parseoffersafteroffer')
        print(offer)
        if not isinstance(offer, dict):
            continue

        pus = offer.get("productUses") or []
        inv = pus[0].get("inventoryTypeCode") if isinstance(pus, list) and pus and isinstance(pus[0], dict) else None
        key = str(inv or "UNKNOWN")
        room_name = room_name_by_key.get(str(inv)) or key

        cash_rate = parse_cash_rate_from_rate_detail({"offers": [offer]})

        point_only, pc_pts, pc_cash, pc_cur = parse_points_from_offer(offer, stay_date)
        print(point_only, pc_pts, pc_cash, pc_cur)

        best_pts = None
        for v in (point_only, pc_pts):
            print(point_only, pc_pts, pc_cash, pc_cur)
            if isinstance(v, int):
                best_pts = v if best_pts is None else min(best_pts, v)

        if not hotel_obj.get("currency"):
            pol_cur = (((offer.get("policies") or {}).get("cancellationNoShow") or {}).get("amountCurrency"))
            hotel_obj["currency"] = pol_cur or h.get("propertyCurrency") or pc_cur

        cats = hotel_obj["room_categories"]
        if key not in cats:
            cats[key] = {"category_code": key, "name": room_name, "rates": []}

        if any(x.get("date") == stay_date for x in cats[key]["rates"]):
            continue

        cats[key]["rates"].append({
            "date": stay_date,
            "cash_rate": cash_rate,
            "starting_rate_points": best_pts,
            "points_cash_extra_cash": float(pc_cash) if isinstance(pc_cash, (int, float)) else None,
            "points_cash_currency": pc_cur,
        })


def post_json(session: requests.Session, url: str, headers: Dict[str, str], payload: Dict[str, Any],
              params: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """
       POST JSON to a URL and return parsed JSON on HTTP 200.

       Args:
           session: Requests session to use.
           url: Target URL.
           headers: Request headers.
           payload: JSON body to send.
           params: Optional query string parameters.

       Returns:
           Parsed JSON dict on status code 200, otherwise None.
       """

    try:
        r = session.post(url, headers=headers, params=params, json=payload, timeout=60, allow_redirects=False)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


if __name__ == "__main__":
    # Search Parameters
    LAT = 37.978718
    LON = 23.751395
    START_DATE = "2025-12-17"
    DAYS = 2
    ROOMS = 1
    ADULTS = 2

    session = requests.Session()
    session.trust_env = False
    warmup_session(session)

    headers = {
        "referer": "https://www.ihg.com/",
        "origin": "https://www.ihg.com",
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json; charset=UTF-8",
        "accept-language": "uk,en-US;q=0.9,en;q=0.8",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "x-ihg-api-key": API_KEY,
        "ihg-language": "en-US",
        "ihg-sessionid": IHG_SESSION_ID,
        "accept-encoding": "gzip, deflate",
    }

    # 1) GraphQL:
    gql_payload = {
        "operationName": GRAPHQL_OPERATION_NAME,
        "query": GRAPHQL_QUERY,
        "variables": make_graphql_variables(START_DATE, LAT, LON),
    }

    graphql_json = post_json(session, GRAPHQL_URL, headers, gql_payload) or {}
    with open("../graphql_raw.json", "w", encoding="utf-8") as f:
        json.dump(graphql_json, f, ensure_ascii=False, indent=2)

    hotels_map = parse_hotels_from_graphql(graphql_json)
    hotel_codes = [c for c in hotels_map.keys() if c]

    # 2) Rates
    start_dt = datetime.strptime(START_DATE, "%Y-%m-%d").date()

    for day_i in range(DAYS):
        d1 = start_dt + timedelta(days=day_i)
        d2 = d1 + timedelta(days=1)
        s1 = d1.strftime("%Y-%m-%d")
        s2 = d2.strftime("%Y-%m-%d")

        for code in hotel_codes:
            payload = {
                "startDate": s1,
                "endDate": s2,
                "hotelMnemonics": [code],
                "products": [
                    {
                        "productCode": "SR",
                        "startDate": s1,
                        "endDate": s2,
                        "quantity": ROOMS,
                        "guestCounts": [{"otaCode": "AQC10", "count": ADULTS}],
                    }
                ],
                "options": {
                    "disabilityMode": "ACCESSIBLE_AND_NON_ACCESSIBLE",
                    "returnAdditionalRatePlanDescriptions": True,
                    "rateDetails": {"includePackageDetails": True},
                },
            }

            offers_json = post_json(
                session,
                OFFERS_URL,
                headers,
                payload,
                params={"fieldset": OFFERS_FIELDSET_DETAILS},
            )

            if offers_json:
                os.makedirs("../offers_raw", exist_ok=True)
                out_path = f'offers_raw/{code}_{s1}_{s2}.json'
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(offers_json, f, ensure_ascii=False, indent=2)

            if not offers_json:
                continue

            parse_offers_into_one_hotel(hotels_map[code], offers_json, stay_date=s1)

        print("done date:", s1)

    result = {
        "search": {
            "location": {"lat": LAT, "lon": LON},
            "check_in": START_DATE,
            "check_out": (start_dt + timedelta(days=DAYS)).strftime("%Y-%m-%d"),
            "rooms": ROOMS,
            "adults": ADULTS,
            "days_scraped": DAYS,
            "fieldset": OFFERS_FIELDSET_DETAILS,
        },
        "hotels": list(hotels_map.values()),
    }

    with open("../ihg_parsed.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("saved ihg_parsed.json")
