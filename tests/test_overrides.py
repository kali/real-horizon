"""Unit tests for the horizon-override module."""

from __future__ import annotations

from pathlib import Path

from custom_components.real_horizon.overrides import (
    OverridePoint,
    analyze_overrides,
    apply_overrides,
    parse_theodolite_log,
)
from custom_components.real_horizon.pvgis import HorizonProfile

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_parse_theodolite_format() -> None:
    text = (FIXTURES / "theodolite_sample.txt").read_text()
    pts = parse_theodolite_log(text)
    assert len(pts) == 6
    assert pts[0] == OverridePoint(90.0, 25.0)
    assert pts[3] == OverridePoint(180.0, 50.0)
    assert pts[-1] == OverridePoint(270.0, 20.0)


def test_parse_simple_format() -> None:
    text = """
    # peaks I see from the kitchen window
    90, 25
    180 50
    270    20
    """
    pts = parse_theodolite_log(text)
    assert [(p.azimuth_deg, p.elevation_deg) for p in pts] == [
        (90.0, 25.0), (180.0, 50.0), (270.0, 20.0),
    ]


def test_parse_skips_garbage() -> None:
    text = """
    not a number, also not
    45, 12
    headers and prose
    """
    pts = parse_theodolite_log(text)
    assert [(p.azimuth_deg, p.elevation_deg) for p in pts] == [(45.0, 12.0)]


def test_apply_overrides_interpolates_within_gap() -> None:
    # Flat 5° PVGIS baseline.
    flat_pts = tuple((float(a), 5.0) for a in range(0, 361, 15))
    base = HorizonProfile(points=flat_pts)
    # User says it's 20° between az 90° and az 110°.
    overrides = [OverridePoint(90.0, 20.0), OverridePoint(110.0, 20.0)]
    blended = apply_overrides(base, overrides, max_gap_deg=30)
    # Inside annotated arc -> user value.
    assert abs(blended.elevation_at(100.0) - 20.0) < 0.1
    # Way outside -> PVGIS.
    assert abs(blended.elevation_at(0.0) - 5.0) < 0.1
    assert abs(blended.elevation_at(200.0) - 5.0) < 0.1


def test_apply_overrides_respects_max_gap() -> None:
    flat = HorizonProfile(points=tuple((float(a), 5.0) for a in range(0, 361, 15)))
    # Two points 100° apart; with max_gap=30° they should NOT be interpolated.
    overrides = [OverridePoint(45.0, 20.0), OverridePoint(145.0, 20.0)]
    blended = apply_overrides(flat, overrides, max_gap_deg=30)
    # Between them at az 90, the gap is too wide -> PVGIS wins.
    assert abs(blended.elevation_at(90.0) - 5.0) < 0.1


def test_apply_overrides_no_points_is_passthrough() -> None:
    base_pts = tuple((float(a), float(a / 36)) for a in range(0, 361, 15))
    base = HorizonProfile(points=base_pts)
    assert apply_overrides(base, []) is base


def test_analyze_overrides_segments_and_isolated() -> None:
    pts = [
        OverridePoint(10, 5),    # neighbour at 20° → in-segment
        OverridePoint(20, 6),    # neighbour at 10° AND 200° (gap 180, not within 30)
        OverridePoint(200, 12),  # alone (gaps 180 and 110)
        OverridePoint(350, 4),   # neighbour at 10° via wrap (gap 20) → in-segment
    ]
    diag = analyze_overrides(pts, max_gap_deg=30)
    assert diag.n_parsed == 4
    # Segments: 10°→20° (gap 10), 350°→10° (gap 20). 200° isolated.
    assert diag.n_segments == 2
    assert (10.0, 20.0) in diag.segments
    assert (350.0, 10.0) in diag.segments
    assert diag.isolated_azimuths == (200.0,)
    assert abs(diag.covered_deg - 30.0) < 0.01  # 10 + 20


def test_analyze_overrides_empty() -> None:
    diag = analyze_overrides([], 30)
    assert diag.n_parsed == 0
    assert diag.n_segments == 0
    assert diag.n_isolated == 0
    assert diag.covered_deg == 0.0


def test_parse_theodolite_flags_magnetic_headings() -> None:
    header = (FIXTURES / "theodolite_sample.txt").read_text().splitlines()[0]
    row = '2026.05.25_20.00.00 37.7 -119.5 "+037.7d / -119.5d" 1209 METERS WGE {az} 0 {kind} 25.0 0.5 DEG'
    text = "\n".join([header, row.format(az=90, kind="TRUE"), row.format(az=100, kind="MAG")])
    pts = parse_theodolite_log(text)
    assert [p.magnetic for p in pts] == [False, True]
    assert analyze_overrides(pts).n_magnetic == 1


def test_repeated_azimuths_are_averaged() -> None:
    flat = HorizonProfile(points=tuple((float(a), 5.0) for a in range(0, 361, 15)))
    # Two readings at 100°: 18 and 22 -> averaged to 20. No step in the curve.
    overrides = [
        OverridePoint(90.0, 20.0),
        OverridePoint(100.0, 18.0),
        OverridePoint(100.0, 22.0),
        OverridePoint(110.0, 20.0),
    ]
    diag = analyze_overrides(overrides, max_gap_deg=30)
    assert diag.n_parsed == 4
    assert diag.segments == ((90.0, 100.0), (100.0, 110.0))
    assert diag.n_isolated == 0
    blended = apply_overrides(flat, overrides, max_gap_deg=30)
    for az in (95.0, 99.5, 100.0, 100.5, 105.0):
        assert abs(blended.elevation_at(az) - 20.0) < 1e-6


def test_fractional_azimuth_peak_is_preserved() -> None:
    flat = HorizonProfile(points=tuple((float(a), 5.0) for a in range(0, 361, 15)))
    overrides = [OverridePoint(99.0, 10.0), OverridePoint(99.5, 30.0), OverridePoint(100.0, 10.0)]
    blended = apply_overrides(flat, overrides, max_gap_deg=30)
    assert abs(blended.elevation_at(99.5) - 30.0) < 1e-6


def test_real_world_log_default_gap() -> None:
    """Real 24-reading Theodolite log (position anonymised): repeats at 84° and 220°, one far point at 306°."""
    pts = parse_theodolite_log((FIXTURES / "theodolite_real.txt").read_text())
    assert len(pts) == 24
    assert not any(p.magnetic for p in pts)
    diag = analyze_overrides(pts, max_gap_deg=30)
    # 22 distinct azimuths; 306° is 44° from its nearest neighbour (262°).
    assert diag.isolated_azimuths == (306.0,)
    assert diag.segments[0] == (82.0, 84.0)
    assert diag.segments[-1] == (253.0, 262.0)
