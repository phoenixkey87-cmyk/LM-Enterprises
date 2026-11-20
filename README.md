# LM Enterprises

Static site hosted on GitHub Pages.

## Phoenix Travel data (SerpApi)

`phoenix-travel.html` shows fares and hotel stays from Google Flights and Google Hotels. The page **only reads static JSON files** in `/data`. A scheduled GitHub Action calls SerpApi, writes those files and commits them. Nothing in the browser calls SerpApi and the API key never appears in the repo.

```
data/config.json     <- you edit this
data/lookup.json     <- cached airport codes / hotel tokens (written by the script)
data/*.json          <- fares, explore, calendar, stays (written by the script)
data/schema/         <- JSON schemas checked before every commit
scripts/             <- fetch_travel_data.py, normalize.py, validate_data.py
tests/               <- normalizer + budget tests using mocked SerpApi responses
assets/travel-data.* <- page CSS and JS
.github/workflows/travel-data.yml
```

### 1. Add the API key
Repo **Settings → Secrets and variables → Actions → New repository secret**. Name it `SERPAPI_API_KEY` and paste your SerpApi key. It must be an *Actions* secret (not a Codespaces or Dependabot one).

### 2. Run it
**Actions → Refresh travel data → Run workflow.** It also runs automatically every Monday and Thursday at 09:17 UTC. The job runs the tests, prints the planned call count, fetches, validates against the schemas, and commits `data/*.json` only if validation passes. The first run also resolves airport codes and hotel IDs and saves them in `data/lookup.json`, so later runs skip those calls.

### 3. Edit what is fetched (`data/config.json`)
- **Add a destination:** add an object to `destinations` with `id`, `name`, `country`, `planned` and either `airport` (3-letter code) or `flight_query` (a city name the script resolves once). Set `"flights": false` for places without a usable airport.
- **Add a featured stay:** set `"featured": true` on the destination and list `hotels` with `id`, `name` and `query`. If the automatic match is not confident the hotel is skipped and the log says so. Then paste its `property_token` into the hotel entry.
- **Dates and trip lengths:** `date_windows` and `trip_lengths`. Windows are offsets from today. Vietnam hotels use a fixed `calendar_window` around November 2027.
- **Budget:** `max_calls_per_run` (or the `MAX_CALLS_PER_RUN` env var / manual run input). If the planned count exceeds it, the run stops before making any call.

### 4. SerpApi usage (sized for the Free plan: 250 searches/month)
The workflow runs **Mondays and Thursdays** (about 9 runs a month). Each run makes about **19 calls**: 1 deals, 4 explore, 7 route calendars, 3 hotel details and 3 hotel calendars. Photos and reviews refresh weekly, which adds roughly 2 calls per run on average. The first run adds 8 one-time lookups (5 airports, 3 hotels), so it makes about 32. Expect roughly **190 calls a month**, under the Free plan's 250. SerpApi's plan sizes are from serpapi.com/pricing; check your own usage at serpapi.com/dashboard.

Seven routes fetch flight calendars: Hanoi, Ho Chi Minh City, Bali, Aruba, Mexico, Dominican Republic and Jamaica. Belize, Colombia, Spain and Puerto Rico are in the config with "flights": false. Remove that flag to turn one on, which costs about 9 more calls a month per route. Swap routes rather than adding them if you want to stay under 250.

Prices are up to 4 days old between runs, so the page treats data as stale after **120 hours** (stale_hours in config.json) and greys it out, showing "not verified". Running more often costs more calls; run python scripts/fetch_travel_data.py --plan to see the count before changing anything.
### 5. Local checks
```
python -m pip install jsonschema
python -m unittest discover -s tests
python scripts/validate_data.py
```

### Troubleshooting
- **"SERPAPI_API_KEY is not set"**: the secret is missing or misnamed.
- **"planned calls exceed MAX_CALLS_PER_RUN"**: trim `config.json` or raise the limit deliberately.
- **A section says "not verified"**: SerpApi returned no price, or the data is older than stale_hours (120 hours by default). Check the Action log for `WARN` lines.
- **Hotel missing**: the log shows `no confident property match`. Add its `property_token` to the config.
- **Validation failed**: the Action fails and nothing is committed. The log lists the offending fields.
- **Page shows an error box**: a JSON file is missing or malformed. Other sections keep working.
- **Action cannot push**: Settings → Actions → General → Workflow permissions → Read and write.

### Compliance notes
The page labels prices "starting from / subject to change", shows last-updated times, credits Google Flights / Google Hotels through SerpApi, and states that Phoenix Travel does not sell these fares or rooms. Review excerpts are short and attributed. Never edit the JSON by hand to fill gaps. A missing value must stay missing.
