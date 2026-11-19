#!/usr/bin/env python3
"""Build river-gauge flood-category dots (KMZ + KML) from the NWS NWPS API.

Standard library only. Output goes to ./output:
  observed_rivers.kmz   current observed stage dots, icons embedded (use this in Max)
  forecast_rivers.kmz   forecast MAXIMUM stage over each gauge's forecast period
  observed_rivers.kml   icons loaded from raw.githubusercontent.com
  status.json           last update time + counts, for monitoring
"""
import json
import time
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "icons"
OUT_DIR = ROOT / "output"

API = "https://api.water.noaa.gov/nwps/v1/gauges"
RAW_ICON_BASE = "https://raw.githubusercontent.com/justingehrts/river-flood-dots/main/icons"

# Coverage. The full-country request times out on NOAA's side, so it is
# fetched in tiles. Edit TILE_BOUNDS to restrict the map to a region.
# (xmin, ymin, xmax, ymax) in degrees; CONUS by default.
TILE_BOUNDS = (-125.0, 24.0, -66.0, 50.0)
TILE_SIZE = 10.0
TILE_PAUSE = 6.0   # seconds between tile requests, to stay under NOAA's rate limit

# Only these categories are drawn; everything else (not_defined,
# obs_not_current, out_of_service, low_threshold, ...) is hidden.
SHOWN = ["major", "moderate", "minor", "action", "no_flooding"]
LABELS = {
    "major": "Major flooding",
    "moderate": "Moderate flooding",
    "minor": "Minor flooding",
    "action": "Action stage",
    "no_flooding": "No flooding",
}


def fetch_tile(xmin, ymin, xmax, ymax, tries=6):
    qs = urllib.parse.urlencode({
        "bbox.xmin": xmin, "bbox.ymin": ymin,
        "bbox.xmax": xmax, "bbox.ymax": ymax,
        "srid": "EPSG_4326",
    })
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": "river-flood-dots"})
    for attempt in range(tries):
        wait = 30 * (attempt + 1)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r).get("gauges", [])
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                wait = max(wait, 60)
                retry_after = exc.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    wait = max(wait, min(int(retry_after), 180))
            print(f"  tile {xmin},{ymin} attempt {attempt + 1} failed: {exc}")
            if attempt < tries - 1:
                time.sleep(wait)
    raise RuntimeError(f"tile {xmin},{ymin},{xmax},{ymax} failed after {tries} tries")


def fetch_all():
    gauges = {}
    x0, y0, x1, y1 = TILE_BOUNDS
    y = y0
    while y < y1:
        x = x0
        while x < x1:
            box = (x, y, min(x + TILE_SIZE, x1), min(y + TILE_SIZE, y1))
            got = fetch_tile(*box)
            print(f"tile {box}: {len(got)} gauges")
            for g in got:
                gauges[g["lid"]] = g  # de-duplicate across tile edges
            time.sleep(TILE_PAUSE)
            x += TILE_SIZE
        y += TILE_SIZE
    return list(gauges.values())


def placemark(g, cat, icon_base, kind="observed"):
    st = g["status"][kind]
    stage = st.get("primary", -999)
    unit = st.get("primaryUnit", "")
    stage_txt = f"{stage:g} {unit}".strip() if stage not in (None, -999) else "n/a"
    name = f"{g['name']} ({g['lid']})"
    if kind == "forecast":
        desc = f"{LABELS[cat]} (forecast max) - peak stage {stage_txt}"
        if st.get("validTime"):
            desc += f" - peak at {st['validTime']}"
    else:
        desc = f"{LABELS[cat]} - stage {stage_txt}"
        if st.get("validTime"):
            desc += f" - valid {st['validTime']}"
    state = g.get("state", {}).get("abbreviation", "")
    return (
        "    <Placemark>\n"
        f"      <name>{escape(name)}</name>\n"
        f"      <description>{escape(desc)}</description>\n"
        f"      <styleUrl>#{cat}</styleUrl>\n"
        "      <ExtendedData>\n"
        f"        <Data name=\"lid\"><value>{escape(g['lid'])}</value></Data>\n"
        f"        <Data name=\"category\"><value>{cat}</value></Data>\n"
        f"        <Data name=\"stage\"><value>{stage if stage != -999 else ''}</value></Data>\n"
        f"        <Data name=\"unit\"><value>{escape(unit)}</value></Data>\n"
        f"        <Data name=\"state\"><value>{escape(state)}</value></Data>\n"
        f"        <Data name=\"valid_time\"><value>{escape(st.get('validTime', ''))}</value></Data>\n"
        "      </ExtendedData>\n"
        f"      <Point><coordinates>{g['longitude']},{g['latitude']},0</coordinates></Point>\n"
        "    </Placemark>\n"
    )


def categorize(gauges, kind):
    rows = {c: [] for c in SHOWN}
    for g in gauges:
        cat = str(g["status"][kind].get("floodCategory", "")).strip().lower()
        if cat in rows and g.get("latitude") is not None and g.get("longitude") is not None:
            rows[cat].append(g)
    return rows


def build_kml(rows, icon_base, stamp, kind="observed"):
    title = ("NWPS Forecast Maximum Stages" if kind == "forecast"
             else "NWPS Live Observed Stages")
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n',
        "  <Document>\n",
        f"    <name>{title}</name>\n",
        f"    <description>Updated {stamp}</description>\n",
    ]
    for cat in SHOWN:
        out.append(
            f'    <Style id="{cat}"><IconStyle><scale>1.0</scale>'
            f"<Icon><href>{icon_base}/dot_{cat}.png</href></Icon></IconStyle>"
            "<LabelStyle><scale>0</scale></LabelStyle></Style>\n"
        )
    # Draw worst categories last so they sit on top of green dots.
    for cat in SHOWN[::-1]:
        for g in rows[cat]:
            out.append(placemark(g, cat, icon_base, kind))
    out.append("  </Document>\n</kml>\n")
    return "".join(out)


def write_kmz(path, rows, stamp, kind):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", build_kml(rows, "icons", stamp, kind))
        for cat in SHOWN:
            z.write(ICON_DIR / f"dot_{cat}.png", f"icons/dot_{cat}.png")


def main():
    t0 = time.time()
    try:
        gauges = fetch_all()
    except RuntimeError as exc:
        # Nothing has been written yet, so the previous output stays in place.
        # Exit nonzero so the run shows red instead of silently going stale.
        print(f"::error::NOAA fetch failed, previous output kept: {exc}")
        sys.exit(1)
    raw_counts = Counter(g["status"]["observed"]["floodCategory"] for g in gauges)

    rows = categorize(gauges, "observed")
    shown_total = sum(len(v) for v in rows.values())
    if shown_total == 0:
        raise SystemExit("No gauges to show - refusing to overwrite output with an empty file")
    frows = categorize(gauges, "forecast")
    fshown_total = sum(len(v) for v in frows.values())

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUT_DIR.mkdir(exist_ok=True)

    (OUT_DIR / "observed_rivers.kml").write_text(
        build_kml(rows, RAW_ICON_BASE, stamp), encoding="utf-8")
    write_kmz(OUT_DIR / "observed_rivers.kmz", rows, stamp, "observed")
    if fshown_total:
        write_kmz(OUT_DIR / "forecast_rivers.kmz", frows, stamp, "forecast")
    else:
        # Don't replace the last good forecast file with an empty one.
        print("::warning::No forecast gauges found, keeping previous forecast_rivers.kmz")

    status = {
        "updated_utc": stamp,
        "gauges_fetched": len(gauges),
        "gauges_shown": shown_total,
        "shown_by_category": {c: len(rows[c]) for c in SHOWN},
        "hidden_by_category": {k: v for k, v in raw_counts.items() if k not in SHOWN},
        "forecast_gauges_shown": fshown_total,
        "forecast_shown_by_category": {c: len(frows[c]) for c in SHOWN},
        "seconds": round(time.time() - t0, 1),
    }
    (OUT_DIR / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
