# river-flood-dots

River gauge dots colored by NWS observed flood category, built from the NWPS API for Max.

- `https://justingehrts.github.io/river-flood-dots/observed_rivers.kmz` - use this in Max (icons embedded; same file as `output/observed_rivers.kmz`)
  (needs Settings > Pages > Source = GitHub Actions)
- `https://justingehrts.github.io/river-flood-dots/forecast_rivers.kmz` - forecast MAXIMUM flood category over each gauge's forecast period (same colors; only gauges with a current forecast are shown; the description gives the peak stage and when it is expected)
- `observed_rivers.kml` - plain KML, built locally only (not committed)
- `https://justingehrts.github.io/river-flood-dots/status.json` (also `output/status.json`) - last update time and counts (check this if the map looks stale)

Colors: purple = major, red = moderate, orange = minor, yellow = action, green = no flooding.
Gauges with no flood stages defined, stale observations, or out of service are hidden.

Refreshed twice an hour by `.github/workflows/update.yml` (`scripts/build_river_dots.py`, standard library only).
To limit the area, edit `TILE_BOUNDS` in the script.
