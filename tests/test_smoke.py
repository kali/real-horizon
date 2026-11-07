"""Smoke test: set up the integration and assert entities populate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.real_horizon.const import DOMAIN

# Yosemite Valley -- dramatic terrain, matches the README screenshot.
LAT = 37.7387
LON = -119.5703

CACHED_PVGIS = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "pvgis_yosemite.json").read_text()
)


@pytest.fixture
def mock_pvgis():
    """Stub fetch_pvgis so tests don't hit the network."""
    async def fake_fetch(session, lat, lon, cache_file, force=False):
        return CACHED_PVGIS

    with patch(
        "custom_components.real_horizon.coordinator.fetch_pvgis",
        side_effect=fake_fetch,
    ):
        yield


async def test_config_flow_and_entities(hass: HomeAssistant, mock_pvgis) -> None:
    hass.config.latitude = LAT
    hass.config.longitude = LON
    hass.config.time_zone = "America/Los_Angeles"

    # User-initiated config flow: show form, then submit empty.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == "create_entry"
    assert result["data"] == {"latitude": LAT, "longitude": LON}

    await hass.async_block_till_done()

    # Expected entities exist with sensible values.
    state = hass.states.get("sensor.real_horizon_local_horizon_profile")
    assert state is not None, [s.entity_id for s in hass.states.async_all()]
    assert state.state == "ok"
    profile = state.attributes["profile"]
    assert len(profile) == 48
    assert all("az" in p and "elev" in p for p in profile)

    rise = hass.states.get("sensor.real_horizon_true_sunrise")
    set_ = hass.states.get("sensor.real_horizon_true_sunset")
    assert rise is not None and set_ is not None
    # Either a real datetime or 'unknown' if today has no crossings (winter at this site!)
    print(f"true sunrise = {rise.state}")
    print(f"true sunset  = {set_.state}")

    clearance = hass.states.get("sensor.real_horizon_sun_clearance")
    assert clearance is not None
    print(f"sun clearance = {clearance.state}°")

    above = hass.states.get("binary_sensor.real_horizon_sun_above_local_horizon")
    assert above is not None
    print(f"above horizon = {above.state}")


async def test_single_instance(hass: HomeAssistant, mock_pvgis) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"latitude": LAT, "longitude": LON}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


def test_large_profile_attributes_are_unrecorded() -> None:
    """The recorder caps attributes at 16 KB; the list-valued ones must be excluded."""
    from custom_components.real_horizon.sensor import LocalHorizonSensor

    assert {"profile", "override_points", "sun_path_today", "moon_path_today"} <= (
        LocalHorizonSensor._unrecorded_attributes
    )
