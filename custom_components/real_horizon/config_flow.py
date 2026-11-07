"""Config + options flows for Real Horizon."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    COORD_PRECISION,
    DOMAIN,
    OPT_OVERRIDE_LOG,
    OPT_OVERRIDE_MAX_GAP_DEG,
    OPT_OVERRIDE_MAX_GAP_DEG_DEFAULT,
)
from .overrides import OverrideDiagnostics, analyze_overrides, parse_theodolite_log


class RealHorizonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the integration with one click; lat/lon taken from HA config."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        lat = self.hass.config.latitude
        lon = self.hass.config.longitude

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                description_placeholders={
                    "latitude": f"{lat:.{COORD_PRECISION}f}",
                    "longitude": f"{lon:.{COORD_PRECISION}f}",
                },
            )

        return self.async_create_entry(
            title="Real Horizon",
            data={"latitude": lat, "longitude": lon},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RealHorizonOptionsFlow()


class RealHorizonOptionsFlow(OptionsFlow):
    """Two-step flow: paste log → review parsed diagnostics → save."""

    def __init__(self) -> None:
        self._pending: dict[str, Any] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = self.config_entry.options
        defaults = {
            OPT_OVERRIDE_LOG: current.get(OPT_OVERRIDE_LOG, ""),
            OPT_OVERRIDE_MAX_GAP_DEG: current.get(
                OPT_OVERRIDE_MAX_GAP_DEG, OPT_OVERRIDE_MAX_GAP_DEG_DEFAULT
            ),
        }

        if user_input is not None:
            log = user_input.get(OPT_OVERRIDE_LOG, "").strip()
            max_gap = float(user_input.get(
                OPT_OVERRIDE_MAX_GAP_DEG, OPT_OVERRIDE_MAX_GAP_DEG_DEFAULT
            ))
            defaults = {OPT_OVERRIDE_LOG: log, OPT_OVERRIDE_MAX_GAP_DEG: max_gap}

            if log == "":
                # Empty input -> clear any existing overrides.
                return self.async_create_entry(
                    title="",
                    data={OPT_OVERRIDE_LOG: "", OPT_OVERRIDE_MAX_GAP_DEG: max_gap},
                )

            points = parse_theodolite_log(log)
            if not points:
                errors[OPT_OVERRIDE_LOG] = "no_points_parsed"
            else:
                diag = analyze_overrides(points, max_gap)
                if diag.n_segments == 0:
                    # Every point isolated -> the override would do nothing.
                    errors[OPT_OVERRIDE_LOG] = "no_segments_form"
                else:
                    self._pending = {
                        OPT_OVERRIDE_LOG: log,
                        OPT_OVERRIDE_MAX_GAP_DEG: max_gap,
                    }
                    return await self.async_step_review()

        # Render the input form (initial open, or after an error).
        # Description shows diagnostics for whatever's currently in the field.
        diag = analyze_overrides(
            parse_theodolite_log(defaults[OPT_OVERRIDE_LOG]),
            float(defaults[OPT_OVERRIDE_MAX_GAP_DEG]),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    OPT_OVERRIDE_LOG, default=defaults[OPT_OVERRIDE_LOG]
                ): TextSelector(TextSelectorConfig(
                    multiline=True, type=TextSelectorType.TEXT
                )),
                vol.Optional(
                    OPT_OVERRIDE_MAX_GAP_DEG, default=defaults[OPT_OVERRIDE_MAX_GAP_DEG]
                ): NumberSelector(NumberSelectorConfig(
                    min=5, max=180, step=1, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°",
                )),
            }),
            description_placeholders=_diag_placeholders(diag),
            errors=errors,
        )

    async def async_step_review(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the diagnostics and let the user accept or cancel."""
        assert self._pending is not None

        if user_input is not None:
            return self.async_create_entry(title="", data=self._pending)

        points = parse_theodolite_log(self._pending[OPT_OVERRIDE_LOG])
        diag = analyze_overrides(points, self._pending[OPT_OVERRIDE_MAX_GAP_DEG])
        return self.async_show_form(
            step_id="review",
            data_schema=vol.Schema({}),
            description_placeholders=_diag_placeholders(diag),
        )


def _diag_placeholders(diag: OverrideDiagnostics) -> dict[str, str]:
    """Stringified diagnostics for use in form descriptions."""
    return {
        "n_parsed": str(diag.n_parsed),
        "n_segments": str(diag.n_segments),
        "n_isolated": str(diag.n_isolated),
        "n_magnetic": str(diag.n_magnetic),
        "covered_deg": f"{diag.covered_deg:.0f}",
        "isolated_list": (
            ", ".join(f"{a:.0f}°" for a in diag.isolated_azimuths)
            if diag.isolated_azimuths else "none"
        ),
        "segment_list": (
            ", ".join(
                f"{a:.0f}°→{b:.0f}°"
                for a, b in diag.segments
            )
            if diag.segments else "none"
        ),
    }
