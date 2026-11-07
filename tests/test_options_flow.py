"""Options flow: submit a Theodolite log, verify the horizon attribute reflects
the overrides after reload."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant

from custom_components.real_horizon.const import (
    DOMAIN,
    OPT_OVERRIDE_LOG,
    OPT_OVERRIDE_MAX_GAP_DEG,
)

LAT = 37.7387
LON = -119.5703

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CACHED_PVGIS = json.loads((FIXTURES / "pvgis_yosemite.json").read_text())
THEODOLITE_LOG = (FIXTURES / "theodolite_sample.txt").read_text()


@pytest.fixture
def mock_pvgis():
    async def fake_fetch(session, lat, lon, cache_file, force=False):
        return CACHED_PVGIS
    with patch(
        "custom_components.real_horizon.coordinator.fetch_pvgis",
        side_effect=fake_fetch,
    ):
        yield


async def test_options_flow_applies_overrides(hass: HomeAssistant, mock_pvgis) -> None:
    hass.config.latitude = LAT
    hass.config.longitude = LON
    hass.config.time_zone = "America/Los_Angeles"

    # Set up the integration normally.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    # Baseline horizon at az 180° -- whatever PVGIS reports for Yosemite.
    state = hass.states.get("sensor.real_horizon_local_horizon_profile")
    profile = state.attributes["profile"]
    az_to_elev = {round(p["az"]): p["elev"] for p in profile}
    baseline_180 = az_to_elev[180]
    # The fixture sample claims 50° at az 180; only useful if it differs
    # from PVGIS's value (it does, by construction).
    assert baseline_180 != 50.0

    # Open the options flow and submit our sample Theodolite log.
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == "form"
    assert flow["step_id"] == "init"

    # Fixture has points at az 90, 110, 130, 180, 230, 270 -- consecutive gaps
    # 20, 20, 50, 50, 40. max_gap=60 brackets all of them.
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={OPT_OVERRIDE_LOG: THEODOLITE_LOG, OPT_OVERRIDE_MAX_GAP_DEG: 60},
    )
    # First submit → review step with diagnostics.
    assert result["type"] == "form"
    assert result["step_id"] == "review"
    assert result["description_placeholders"]["n_parsed"] == "6"
    assert result["description_placeholders"]["n_segments"] == "5"
    assert result["description_placeholders"]["n_magnetic"] == "0"
    # Confirm.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    # Reload pulls fresh horizon with overrides applied.
    state = hass.states.get("sensor.real_horizon_local_horizon_profile")
    profile = state.attributes["profile"]
    # Find the entry exactly at az 180 (resample produces 1°-spaced points).
    near_180 = min(profile, key=lambda p: abs(p["az"] - 180))
    print(f"baseline @180: {baseline_180}, after override: {near_180['elev']}")
    # User's fixture says 50° at az 180; the linear interpolation between
    # neighbour points lands within 1° of that.
    assert abs(near_180["elev"] - 50.0) < 1.0
    # Raw measurements are exposed for the card to draw.
    assert len(state.attributes["override_points"]) == 6
    assert {"az": 180.0, "elev": 50.0} in state.attributes["override_points"]


async def test_options_flow_rejects_garbage(hass: HomeAssistant, mock_pvgis) -> None:
    hass.config.latitude = LAT
    hass.config.longitude = LON
    hass.config.time_zone = "America/Los_Angeles"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    flow = await hass.config_entries.options.async_init(entry.entry_id)

    # Non-empty but unparseable input -> error, form is shown again.
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={OPT_OVERRIDE_LOG: "this is not data", OPT_OVERRIDE_MAX_GAP_DEG: 30},
    )
    assert result["type"] == "form"
    assert result["errors"] == {OPT_OVERRIDE_LOG: "no_points_parsed"}


async def test_options_flow_rejects_all_isolated(hass: HomeAssistant, mock_pvgis) -> None:
    """Points exist but none have a close-enough neighbour -- reject."""
    hass.config.latitude = LAT
    hass.config.longitude = LON
    hass.config.time_zone = "America/Los_Angeles"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    flow = await hass.config_entries.options.async_init(entry.entry_id)

    # 3 points 90° apart with default max_gap=30 -> all isolated.
    log = "0, 5\n90, 5\n180, 5"
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={OPT_OVERRIDE_LOG: log, OPT_OVERRIDE_MAX_GAP_DEG: 30},
    )
    assert result["type"] == "form"
    assert result["errors"] == {OPT_OVERRIDE_LOG: "no_segments_form"}


async def test_options_flow_empty_input_clears(hass: HomeAssistant, mock_pvgis) -> None:
    """Submitting an empty log clears any previous override silently (no review)."""
    hass.config.latitude = LAT
    hass.config.longitude = LON
    hass.config.time_zone = "America/Los_Angeles"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={OPT_OVERRIDE_LOG: "", OPT_OVERRIDE_MAX_GAP_DEG: 30},
    )
    assert result["type"] == "create_entry"
