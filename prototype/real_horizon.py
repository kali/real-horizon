"""Prototype: fetch PVGIS horizon, compute true sunrise/sunset for today.

Usage:
    python3 real_horizon.py [lat] [lon]
Defaults to the test location in /workspace.

PVGIS azimuth convention: 0 = South, negative = East, positive = West,
+/-180 = North. Astral uses compass azimuth (0 = North, clockwise).
"""

from __future__ import annotations

import json
import math
import sys
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from astral import Observer
from astral.sun import azimuth as sun_azimuth, elevation as sun_elevation

# Yosemite Valley -- dramatic terrain, used as the project's reference location.
DEFAULT_LAT = 37.7387
DEFAULT_LON = -119.5703
CACHE_DIR = Path(__file__).parent / "cache"
PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_3/printhorizon"


# ---------- horizon profile ----------

@dataclass
class HorizonProfile:
    """Local horizon: list of (compass_azimuth_deg, elevation_deg), sorted by az.

    Compass azimuth: 0 = North, 90 = East, 180 = South, 270 = West.
    Wraps: the first point is duplicated at +360 to make interpolation trivial.
    """

    points: list[tuple[float, float]]

    @classmethod
    def from_pvgis(cls, pvgis_json: dict) -> "HorizonProfile":
        raw = pvgis_json["outputs"]["horizon_profile"]
        # PVGIS A: 0=S, -90=E, +90=W, +/-180=N. Compass = (A + 180) mod 360.
        pts: dict[float, float] = {}
        for entry in raw:
            compass = (entry["A"] + 180.0) % 360.0
            # PVGIS gives duplicate ±180 (both = N); average if collision.
            if compass in pts:
                pts[compass] = (pts[compass] + entry["H_hor"]) / 2.0
            else:
                pts[compass] = entry["H_hor"]
        ordered = sorted(pts.items())
        # Wrap-around sentinel for interpolation across 360->0.
        ordered.append((ordered[0][0] + 360.0, ordered[0][1]))
        return cls(points=ordered)

    def elevation_at(self, compass_az_deg: float) -> float:
        """Linear interpolation of horizon elevation at the given azimuth."""
        az = compass_az_deg % 360.0
        xs = [p[0] for p in self.points]
        i = bisect_left(xs, az)
        if i == 0:
            return self.points[0][1]
        if i >= len(self.points):
            return self.points[-1][1]
        x0, y0 = self.points[i - 1]
        x1, y1 = self.points[i]
        t = (az - x0) / (x1 - x0)
        return y0 + t * (y1 - y0)


# ---------- PVGIS fetch + cache ----------

def fetch_horizon(lat: float, lon: float, force: bool = False) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    # 4 decimals ~= 11 m precision, plenty for SRTM-based horizon.
    cache_path = CACHE_DIR / f"pvgis_{lat:.4f}_{lon:.4f}.json"
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text())
    print(f"fetching PVGIS horizon for {lat}, {lon} ...", file=sys.stderr)
    r = requests.get(
        PVGIS_URL,
        params={"lat": lat, "lon": lon, "outputformat": "json"},
        timeout=30,
    )
    r.raise_for_status()
    cache_path.write_text(r.text)
    return r.json()


# ---------- sun crossings ----------

def clearance(observer: Observer, horizon: HorizonProfile, when: datetime) -> float:
    """sun_altitude - local_horizon_at(sun_azimuth), in degrees."""
    alt = sun_elevation(observer, when)
    az = sun_azimuth(observer, when)
    return alt - horizon.elevation_at(az)


def find_crossings(
    observer: Observer,
    horizon: HorizonProfile,
    day: date,
    tz: ZoneInfo,
    step_minutes: int = 1,
) -> list[tuple[datetime, str]]:
    """Find all sign changes of clearance(t) over the local day.

    Returns [(time, 'rise'|'set')] -- rise = − to +, set = + to −.
    Bisects to second-level precision around each sign change.
    """
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=1)
    step = timedelta(minutes=step_minutes)

    times: list[datetime] = []
    t = start
    while t <= end:
        times.append(t)
        t += step

    clearances = [clearance(observer, horizon, t) for t in times]
    crossings: list[tuple[datetime, str]] = []
    for i in range(1, len(times)):
        c0, c1 = clearances[i - 1], clearances[i]
        if c0 == 0 or (c0 < 0) != (c1 < 0):
            kind = "rise" if c1 > c0 else "set"
            # Bisect to ~1 s precision.
            lo, hi = times[i - 1], times[i]
            f_lo = c0
            for _ in range(20):
                mid = lo + (hi - lo) / 2
                f_mid = clearance(observer, horizon, mid)
                if (f_lo < 0) == (f_mid < 0):
                    lo, f_lo = mid, f_mid
                else:
                    hi = mid
            crossings.append((lo + (hi - lo) / 2, kind))
    return crossings


# ---------- main ----------

def main() -> None:
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LAT
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_LON

    pvgis = fetch_horizon(lat, lon)
    horizon = HorizonProfile.from_pvgis(pvgis)
    observer = Observer(latitude=lat, longitude=lon, elevation=0.0)
    tz = ZoneInfo("America/Los_Angeles")
    today = datetime.now(tz).date()

    print(f"location:  lat={lat}  lon={lon}")
    print(f"date:      {today}  ({tz.key})")
    print(f"horizon:   {len(horizon.points)-1} points, "
          f"min={min(p[1] for p in horizon.points):.1f}° "
          f"max={max(p[1] for p in horizon.points):.1f}°")

    # Geometric (flat-horizon) reference, from astral, for comparison.
    from astral.sun import sun as astral_sun
    flat = astral_sun(observer, date=today, tzinfo=tz)
    print()
    print("flat-horizon (astral, sea-level):")
    print(f"  sunrise  {flat['sunrise'].astimezone(tz):%H:%M:%S}")
    print(f"  sunset   {flat['sunset'].astimezone(tz):%H:%M:%S}")

    crossings = find_crossings(observer, horizon, today, tz)
    print()
    print("local-horizon crossings:")
    for t, kind in crossings:
        az = sun_azimuth(observer, t)
        h = horizon.elevation_at(az)
        print(f"  {kind:4s}  {t.astimezone(tz):%H:%M:%S}  "
              f"sun_az={az:6.2f}°  horizon={h:5.2f}°")

    if crossings:
        rise = next((t for t, k in crossings if k == "rise"), None)
        set_ = next((t for t, k in reversed(crossings) if k == "set"), None)
        if rise and set_:
            delta_r = (rise - flat["sunrise"]).total_seconds() / 60
            delta_s = (set_ - flat["sunset"]).total_seconds() / 60
            print()
            print(f"true sunrise is {delta_r:+.1f} min vs flat horizon")
            print(f"true sunset  is {delta_s:+.1f} min vs flat horizon")


if __name__ == "__main__":
    main()
