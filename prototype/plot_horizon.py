"""Plot the local horizon profile with today's sun path overlaid.

Outputs PNG + SVG next to the script.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
from astral import Observer
from astral.sun import azimuth as sun_azimuth, elevation as sun_elevation, sun as astral_sun

from real_horizon import (
    DEFAULT_LAT,
    DEFAULT_LON,
    HorizonProfile,
    fetch_horizon,
    find_crossings,
)


def pvgis_arc_to_compass(arc: list[dict], az_key: str, h_key: str) -> tuple[list[float], list[float]]:
    """PVGIS solstice arcs use S=0 azimuth; convert to compass and sort."""
    pts = [((e[az_key] + 180.0) % 360.0, e[h_key]) for e in arc]
    pts.sort()
    return [p[0] for p in pts], [p[1] for p in pts]


def main() -> None:
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LAT
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_LON
    tz_name = sys.argv[3] if len(sys.argv) > 3 else "America/Los_Angeles"
    label = sys.argv[4] if len(sys.argv) > 4 else f"{lat:.4f}, {lon:.4f}"

    pvgis = fetch_horizon(lat, lon)
    horizon = HorizonProfile.from_pvgis(pvgis)
    observer = Observer(latitude=lat, longitude=lon, elevation=0.0)
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()

    # Sun path for today: sample every 2 minutes, drop below-horizon nighttime.
    start = datetime.combine(today, datetime.min.time(), tzinfo=tz)
    samples = [start + timedelta(minutes=2 * i) for i in range(720)]
    sun_pts = [(sun_azimuth(observer, t), sun_elevation(observer, t), t) for t in samples]
    sun_pts_day = [(a, h, t) for a, h, t in sun_pts if h > -5]  # daylight only

    crossings = find_crossings(observer, horizon, today, tz)

    # Solstice envelope from PVGIS (only the above-horizon portion).
    w_az, w_h = pvgis_arc_to_compass(pvgis["outputs"]["winter_solstice"], "A_sun(w)", "H_sun(w)")
    s_az, s_h = pvgis_arc_to_compass(pvgis["outputs"]["summer_solstice"], "A_sun(s)", "H_sun(s)")

    # Horizon as plot-ready arrays (already wrapped to 360).
    hx = [p[0] for p in horizon.points]
    hy = [p[1] for p in horizon.points]

    fig, ax = plt.subplots(figsize=(13, 5.5))

    # Sky background gradient (simple: just a light blue fill above horizon).
    ax.set_facecolor("#e8f1fb")

    # Horizon silhouette.
    ax.fill_between(hx, hy, 0, color="#3a2e22", alpha=0.85, zorder=2, label="local horizon (PVGIS)")
    ax.plot(hx, hy, color="#1c160f", lw=1.2, zorder=3)

    # Solstice envelope.
    s_az_up = [(a, h) for a, h in zip(s_az, s_h) if h > 0]
    w_az_up = [(a, h) for a, h in zip(w_az, w_h) if h > 0]
    if s_az_up:
        ax.plot([a for a, _ in s_az_up], [h for _, h in s_az_up],
                "--", color="#d97706", lw=1, alpha=0.7, label="summer solstice")
    if w_az_up:
        ax.plot([a for a, _ in w_az_up], [h for _, h in w_az_up],
                "--", color="#2563eb", lw=1, alpha=0.7, label="winter solstice")

    # Today's sun arc.
    sx = [a for a, _, _ in sun_pts_day]
    sy = [h for _, h, _ in sun_pts_day]
    ax.plot(sx, sy, color="#eab308", lw=2.4, zorder=4, label=f"sun path {today}")

    # Hour ticks on today's arc.
    for a, h, t in sun_pts_day:
        if t.minute == 0 and t.second == 0 and h > -2:
            ax.plot(a, h, "o", color="#eab308", markeredgecolor="#854d0e", ms=4, zorder=5)
            ax.annotate(f"{t.hour:02d}h", (a, h), textcoords="offset points",
                        xytext=(0, 7), ha="center", fontsize=7, color="#713f12", zorder=6)

    # Crossings.
    for t, kind in crossings:
        az = sun_azimuth(observer, t)
        h = sun_elevation(observer, t)
        color = "#dc2626" if kind == "set" else "#16a34a"
        ax.plot(az, h, marker="*", color=color, markeredgecolor="black",
                ms=16, zorder=7, label=f"true {'sunrise' if kind == 'rise' else 'sunset'} {t:%H:%M}")

    # Current sun position if up.
    now = datetime.now(tz)
    now_alt = sun_elevation(observer, now)
    now_az = sun_azimuth(observer, now)
    if now_alt > horizon.elevation_at(now_az):
        ax.plot(now_az, now_alt, "o", color="#fde047", markeredgecolor="#854d0e",
                ms=14, zorder=8, label=f"sun now {now:%H:%M}")

    # Cardinal direction markers along the bottom.
    cardinals = [(0, "N"), (45, "NE"), (90, "E"), (135, "SE"),
                 (180, "S"), (225, "SW"), (270, "W"), (315, "NW"), (360, "N")]
    ax.set_xticks([c[0] for c in cardinals])
    ax.set_xticklabels([c[1] for c in cardinals])

    ax.set_xlim(0, 360)
    ymax = max(max(hy) + 5, max(sy) + 5)
    ax.set_ylim(0, ymax)
    ax.set_xlabel("azimuth (compass)")
    ax.set_ylabel("elevation (degrees)")
    ax.set_title(f"real horizon — {label} — {today}")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)

    safe = label.lower().replace(" ", "_").replace(",", "").replace(".", "")
    out_png = Path(__file__).parent / f"horizon_{safe}.png"
    out_svg = Path(__file__).parent / f"horizon_{safe}.svg"
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)
    fig.savefig(out_svg)
    print(f"wrote {out_png}")
    print(f"wrote {out_svg}")


if __name__ == "__main__":
    main()
