#!/usr/bin/env python3
"""Build river-gauge flood-category dots (KMZ + KML) from the NWS NWPS API.

Standard library only. Output goes to ./output:
  observed_rivers.kmz   icons embedded, self-contained (use this in Max)
  observed_rivers.kml   icons loaded from raw.githubusercontent.com
  status.json           last update time + counts, for monitoring
"""
import json
import time
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


def fetch_tile(xmin, ymin, xmax, ymax, tries=3):
    qs = urllib.parse.urlencode({
        "bbox.xmin": xmin, "bbox.ymin": ymin,
        "bbox.xmax": xmax, "bbox.ymax": ymax,
        "srid": "EPSG_4326",
    })
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": "river-flood-dots"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r).get("gauges", [])
        except Exception as exc:  # noqa: BLE001
            print(f"  tile {xmin},{ymin} attempt {attempt + 1} failed: {exc}")
            time.sleep(5 * (attempt + 1))
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
            x += TILE_SIZE
        y += TILE_SIZE
    return list(gauges.values())


def placemark(g, cat, icon_base):
    obs = g["status"]["observed"]
    stage = obs.get("primary", -999)
    unit = obs.get("primaryUnit", "")
    stage_txt = f"{stage:g} {unit}".strip() if stage not in (None, -999) else "n/a"
    name = f"{g['name']} ({g['lid']})"
    desc = f"{LABELS[cat]} - stage {stage_txt}"
    if obs.get("validTime"):
        desc += f" - valid {obs['validTime']}"
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
        "      </ExtendedData>\n"
        f"      <Point><coordinates>{g['longitude']},{g['latitude']},0</coordinates></Point>\n"
        "    </Placemark>\n"
    )


def build_kml(rows, icon_base, stamp):
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n',
        "  <Document>\n",
        "    <name>NWPS Live Observed Stages</name>\n",
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
            out.append(placemark(g, cat, icon_base))
    out.append("  </Document>\n</kml>\n")
    return "".join(out)


def main():
    t0 = time.time()
    gauges = fetch_all()
    raw_counts = Counter(g["status"]["observed"]["floodCategory"] for g in gauges)

    rows = {c: [] for c in SHOWN}
    for g in gauges:
        cat = str(g["status"]["observed"].get("floodCategory", "")).strip().lower()
        if cat in rows and g.get("latitude") is not None and g.get("longitude") is not None:
            rows[cat].append(g)
    shown_total = sum(len(v) for v in rows.values())
    if shown_total == 0:
        raise SystemExit("No gauges to show - refusing to overwrite output with an empty file")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUT_DIR.mkdir(exist_ok=True)

    (OUT_DIR / "observed_rivers.kml").write_text(
        build_kml(rows, RAW_ICON_BASE, stamp), encoding="utf-8")

    with zipfile.ZipFile(OUT_DIR / "observed_rivers.kmz", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", build_kml(rows, "icons", stamp))
        for cat in SHOWN:
            z.write(ICON_DIR / f"dot_{cat}.png", f"icons/dot_{cat}.png")

    status = {
        "updated_utc": stamp,
        "gauges_fetched": len(gauges),
        "gauges_shown": shown_total,
        "shown_by_category": {c: len(rows[c]) for c in SHOWN},
        "hidden_by_category": {k: v for k, v in raw_counts.items() if k not in SHOWN},
        "seconds": round(time.time() - t0, 1),
    }
    (OUT_DIR / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
