"""Horizon-profile overrides from user-supplied (azimuth, elevation) measurements.

Two input formats are accepted:

1. **Theodolite app export** (the iOS app's plain-text format), with a header
   line and one row per reading.
2. **Simple list**: one `azimuth, elevation` (or `azimuth elevation`) per line.
   Lines beginning with `#` are comments.

The overrides are applied to a base PVGIS profile via `apply_overrides()`:
between consecutive user points that lie within `max_gap_deg`, the user curve
linearly interpolated *replaces* PVGIS. Outside any annotated segment, PVGIS
is kept as-is. This way the user can correct PVGIS where it's wrong (canopy,
phantom ridges) without claiming coverage of the entire horizon.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from .pvgis import HorizonProfile

# Default: only interpolate between two user points if they're within 30° of
# each other. Beyond that, fall back to PVGIS. Configurable in the options flow.
DEFAULT_MAX_GAP_DEG = 30.0

# Final blended profile is resampled at this azimuth resolution.
RESAMPLE_STEP_DEG = 1.0


@dataclass(frozen=True)
class OverridePoint:
    azimuth_deg: float  # compass, 0–360
    elevation_deg: float
    magnetic: bool = False
    """True if the heading was recorded relative to magnetic north."""


@dataclass(frozen=True)
class OverrideDiagnostics:
    """What `apply_overrides()` will actually do with a given input."""

    n_parsed: int
    """Raw readings parsed (before merging repeated azimuths)."""
    segments: tuple[tuple[float, float], ...]
    """List of (start_az, end_az) -- consecutive user points within max_gap."""
    isolated_azimuths: tuple[float, ...]
    """User points with no neighbour close enough -- silently dropped."""
    covered_deg: float
    """Sum of azimuth degrees where the user curve replaces PVGIS."""
    n_magnetic: int = 0
    """Readings whose heading is magnetic rather than true north."""

    @property
    def n_segments(self) -> int:
        return len(self.segments)

    @property
    def n_isolated(self) -> int:
        return len(self.isolated_azimuths)


def parse_theodolite_log(text: str) -> list[OverridePoint]:
    """Parse a Theodolite-app export or a plain `az, elev` list.

    Silently ignores blank lines, comments (`#...`), and rows that can't be
    interpreted. Returns the points in input order.
    """
    raw_lines = [line.rstrip() for line in text.splitlines()]
    lines = [
        line for line in raw_lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        return []

    # Theodolite app header detection.
    if lines[0].lstrip().startswith("DATE_TIME"):
        return _parse_theodolite_full(lines[1:])
    return _parse_simple(lines)


def _parse_theodolite_full(rows: list[str]) -> list[OverridePoint]:
    """Theodolite app columns: DATE_TIME LAT LON POS_STRING ALT ALT_UNITS DATUM
    HDG_DEG HDG_MILS HDG_TYPE VERT HORIZ VH_UNITS NOTE. We need HDG_DEG (index
    7), HDG_TYPE (index 9: TRUE or magnetic) and VERT (index 10). The
    POS_STRING column is double-quoted and contains spaces, so use shlex.
    """
    out: list[OverridePoint] = []
    for row in rows:
        try:
            parts = shlex.split(row)
        except ValueError:
            continue
        if len(parts) < 11:
            continue
        try:
            az = float(parts[7]) % 360
            elev = float(parts[10])
        except ValueError:
            continue
        out.append(OverridePoint(az, elev, magnetic=parts[9].upper() != "TRUE"))
    return out


def _parse_simple(lines: list[str]) -> list[OverridePoint]:
    """One `az, elev` per line; comma or whitespace separated."""
    out: list[OverridePoint] = []
    for line in lines:
        parts = re.split(r"[,\s]+", line.strip())
        if len(parts) < 2:
            continue
        try:
            az = float(parts[0]) % 360
            elev = float(parts[1])
        except ValueError:
            continue
        out.append(OverridePoint(az, elev))
    return out


def _merge_by_azimuth(points: list[OverridePoint]) -> list[tuple[float, float]]:
    """Sort readings by azimuth, averaging repeated readings at the same azimuth.

    Theodolite reports whole-degree headings, so re-measuring a spot is common;
    leaving duplicates in would create zero-width segments and a step in the
    curve.
    """
    by_az: dict[float, list[float]] = {}
    for p in points:
        by_az.setdefault(round(p.azimuth_deg % 360, 3), []).append(p.elevation_deg)
    return sorted((az, sum(e) / len(e)) for az, e in by_az.items())


def _segments(
    user: list[tuple[float, float]], max_gap_deg: float
) -> list[tuple[int, int, float]]:
    """(i, j, gap) for each cyclically consecutive pair within max_gap_deg."""
    n = len(user)
    out: list[tuple[int, int, float]] = []
    if n < 2:
        return out
    for i in range(n):
        j = (i + 1) % n
        gap = (user[j][0] - user[i][0]) % 360
        if 0 < gap <= max_gap_deg:
            out.append((i, j, gap))
    return out


def analyze_overrides(
    points: list[OverridePoint],
    max_gap_deg: float = DEFAULT_MAX_GAP_DEG,
) -> OverrideDiagnostics:
    """Report which segments would form and which points would be ignored.

    Uses the same segmentation as `apply_overrides()` so the diagnostics are
    faithful to what the merge will actually do.
    """
    if not points:
        return OverrideDiagnostics(0, (), (), 0.0)

    user = _merge_by_azimuth(points)
    segs = _segments(user, max_gap_deg)
    in_segment = {k for i, j, _ in segs for k in (i, j)}
    return OverrideDiagnostics(
        n_parsed=len(points),
        segments=tuple((user[i][0], user[j][0]) for i, j, _ in segs),
        isolated_azimuths=tuple(
            user[k][0] for k in range(len(user)) if k not in in_segment
        ),
        covered_deg=sum(gap for _, _, gap in segs),
        n_magnetic=sum(1 for p in points if p.magnetic),
    )


def apply_overrides(
    profile: HorizonProfile,
    points: list[OverridePoint],
    max_gap_deg: float = DEFAULT_MAX_GAP_DEG,
) -> HorizonProfile:
    """Blend user override points into a PVGIS horizon profile.

    Resamples the result at 1° azimuth resolution. For each output azimuth:
      - If two consecutive user points (sorted by az, treated cyclically)
        bracket this azimuth and their gap is ≤ `max_gap_deg`, the user
        linear interpolation wins.
      - Otherwise the PVGIS interpolation at that azimuth is kept.
    """
    if not points:
        return profile

    user = _merge_by_azimuth(points)
    segs = [
        (user[i][0], user[i][1], user[j][1], gap)
        for i, j, gap in _segments(user, max_gap_deg)
    ]

    def user_at(az: float) -> float | None:
        for a0, e0, e1, gap in segs:
            d = (az - a0) % 360
            if d <= gap:
                return e0 + (d / gap) * (e1 - e0)
        return None

    # Sample every whole degree, plus the user points themselves so a peak
    # measured at a fractional azimuth isn't shaved off by resampling.
    azimuths = sorted(
        {float(a) for a in range(0, 360, int(RESAMPLE_STEP_DEG))}
        | {az for az, _ in user}
    )
    blended: list[tuple[float, float]] = []
    for az in azimuths:
        override = user_at(az)
        blended.append((az, override if override is not None else profile.elevation_at(az)))
    # Wrap sentinel for clean interpolation across the 360→0 seam.
    blended.append((360.0, blended[0][1]))
    return HorizonProfile(points=tuple(blended))
