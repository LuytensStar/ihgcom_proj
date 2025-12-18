from re import search

from load_django import *
from parser_app.models import ScrapeRun, Hotel, HotelImage, RoomCategory, RoomRate

import json
from datetime import datetime
from decimal import Decimal
from django.db import transaction
from pathlib import Path

def parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()

def import_ihg_parsed_json(json_path: str, store_full_raw_payload: bool = False) -> int:
    with open(json_path, "r", encoding='utf-8') as f:
        payload = json.load(f)

    search = payload.get("search")
    hotels = payload.get("hotels")

    run_kwargs = {
        "source_domain": "ihg.com",
        "lat": search.get("lat"),
        "lon": search.get("lon"),
        "start_date": parse_date(search['start_date']) if search.get("start_date") else None,
        "nights_scraped": search.get("nights_scraped"),
        "adults": search.get("adults"),
        "rooms": search.get("rooms"),
        "raw_payload": payload if store_full_raw_payload else None,
    }

    scrape_run = ScrapeRun.objects.create(**run_kwargs)

    processed = 0

    with transaction.atomic():
        for h in hotels:
            code = h.get("hotel_code")
            if not code:
                continue

            coords = h.get("coordinates") or {}
            lat = coords.get("latitude")
            lon = coords.get("longitude")

            hotel_obj, _ = Hotel.objects.update_or_create(
                hotel_code=code,
                defaults={
                    "hotel_name": h.get("hotel_name"),
                    "address": h.get("address"),
                    "city": h.get("city"),
                    "state_province": h.get("state_province"),
                    "country": h.get("country"),
                    "country_code": h.get("country_code"),
                    "property_url": h.get("property_url"),
                    "latitude": lat,
                    "longitude": lon,
                    "currency": h.get("currency"),
                }
            )

            images =h.get("images") or []
            for i, url in enumerate(images):
                HotelImage.objects.update_or_create(
                    hotel = hotel_obj,
                    url = url,
                    defaults={"sort_order": i}
                )


            rc_map = h.get("room_categories") or {}
            for _, rc in rc_map.items():
                cat_code = rc.get("category_code")
                if not cat_code:
                    continue

                cat_obj, _ = RoomCategory.objects.update_or_create(
                    hotel = hotel_obj,
                    category_code = cat_code,
                    defaults={"description": rc.get("description")},
                )


                for r in (rc.get("rates") or []):
                    stay_date = r.get("date")
                    if not stay_date:
                        continue

                    cash = r.get("cash_rate")
                    pts = r.get("starting_rate_points")
                    RoomRate.objects.update_or_create(
                        room_category = cat_obj,
                        stay_date = parse_date(stay_date),
                        defaults={"cash_rate": Decimal(str(cash)) if cash is not None else None,
                                  "starting_rate_points": int(pts) if pts is not None else None,
                                  "currency" : hotel_obj.currency,}

                    )

            processed +=1
    return processed

if __name__ == "__main__":
    json_path = Path(__file__).resolve().parent.parent / "ihg_parsed.json"
    n = import_ihg_parsed_json(str(json_path), store_full_raw_payload=False)
    print(f"Imported {n} records")
