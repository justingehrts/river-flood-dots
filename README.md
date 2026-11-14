# river-flood-dots

River gauge dots colored by NWS observed flood category, built from the NWPS API for Max.

- `output/observed_rivers.kmz` - use this in Max (icons embedded)
- `observed_rivers.kml` - plain KML, built locally only (not committed)
- `output/status.json` - last update time and counts (check this if the map looks stale)

Colors: purple = major, red = moderate, orange = minor, yellow = action, green = no flooding.
Gauges with no flood stages defined, stale observations, or out of service are hidden.

Refreshed twice an hour by `.github/workflows/update.yml` (`scripts/build_river_dots.py`, standard library only).
To limit the area, edit `TILE_BOUNDS` in the script.
