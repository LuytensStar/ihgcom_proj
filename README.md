# IHG Hotel Scraper (GraphQL + Offers API)

Small Python script that queries IHG public endpoints to collect hotel metadata and nightly rates (cash + optional points/points+cash) and saves a normalized JSON output.

## What it does

1. **GraphQL (Hotel metadata)**
   - Calls `https://apis.ihg.com/graphql/v1/hotels`
   - Returns hotels near a latitude/longitude: name, address, coordinates, images, property URL, etc.
   - Raw response is saved to: `graphql_raw.json`

2. **Offers / Availability (Rates)**
   - Calls `https://apis.ihg.com/availability/v3/hotels/offers`
   - Called **per hotel per night** to get rate plans, room inventory types, daily totals, policies, etc.
   - The returned fields depend on the `fieldset` query param (`OFFERS_FIELDSET_DETAILS`).
   - Parsed results are merged into the final output: `ihg_parsed.json`

## Output

The script produces:
- `graphql_raw.json` — raw GraphQL hotel search response
- `ihg_parsed.json` — merged/normalized output:

```json
{
  "search": { "...": "..." },
  "hotels": [
    {
      "hotel_code": "ATHGR",
      "hotel_name": "...",
      "currency": "EUR",
      "room_categories": {
        "CSTN": {
          "name": "Standard Room",
          "rates": [
            {
              "date": "YYYY-MM-DD",
              "cash_rate": 123.45,
              "starting_rate_points": null,
              "points_cash_extra_cash": null,
              "points_cash_currency": null
            }
          ]
        }
      }
    }
  ]
}
