# Real Horizon

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant integration that knows your **actual** sunrise and sunset — the
time the sun *really* clears the hills, trees, or buildings around you, not the
theoretical time it would rise over a flat ocean horizon.

It also ships a Lovelace card that draws today's sun and moon arcs over a
silhouette of your local terrain.

![Yosemite Valley horizon profile](docs/yosemite_horizon.png)

*Yosemite Valley, today. Granite walls climb to 50° on the southern side —
the winter-solstice sun (blue dashed line) never clears the valley walls at all.*

## What it does

- Fetches the 360° horizon profile for your Home Assistant `latitude` /
  `longitude` from [PVGIS](https://re.jrc.ec.europa.eu/) (free, no key, global,
  built on SRTM elevation data).
- Computes the sun's path and intersects it with the local horizon, so
  *true sunrise* and *true sunset* reflect when the sun actually appears
  and disappears for **you**.
- Computes the moon's position and phase, with the same horizon-aware
  rise/set times.
- Registers a Lovelace card automatically — no manual resource setup.

## Entities

Once configured, the integration creates one device with these entities:

| Entity | Type | What it tells you |
| --- | --- | --- |
| `sensor.real_horizon_true_sunrise` | timestamp | The next time the sun rises above your local horizon |
| `sensor.real_horizon_true_sunset` | timestamp | The next time the sun drops below your local horizon |
| `sensor.real_horizon_sun_clearance` | ° | `sun_altitude − horizon(sun_azimuth)` — positive when the sun is visible |
| `sensor.real_horizon_horizon_at_sun_azimuth` | ° | The horizon height directly under the sun |
| `sensor.real_horizon_local_horizon_profile` | string + attrs | The full 360° profile, sun and moon paths, and crossings (used by the card) |
| `binary_sensor.real_horizon_sun_above_local_horizon` | bool | Whether the sun is currently visible to you |

The moon attributes — current azimuth/elevation/phase, current arc, and
horizon-aware moonrise/moonset times — live on
`sensor.real_horizon_local_horizon_profile`.

## Install

### HACS (recommended)

1. In HACS → **Integrations** → ⋮ → **Custom repositories**, add
   `https://github.com/kali/real-horizon` (category: *Integration*).
2. Install **Real Horizon**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration → Real Horizon.**

The card loads itself. Just add it to any dashboard:

```yaml
type: custom:real-horizon-card
entity: sensor.real_horizon_local_horizon_profile
```

### Manual

1. Copy `custom_components/real_horizon/` into your HA `config/custom_components/`.
2. Restart Home Assistant.
3. Add the integration as above.

## How accurate are the rise/set times?

The horizon comes from PVGIS, which samples SRTM at roughly 90 m resolution.
That captures ridges, hills, and cliffs reliably, but misses close-range
obstructions (trees, neighbouring buildings). Expect agreement with reality
to within a few minutes in open terrain, ~10 min in dense local cover.

The sun position itself is computed with `astral` and is sub-second accurate.
The moon position uses a low-precision Meeus algorithm (main periodic terms)
accurate to a few arcminutes — plenty for moonrise/moonset on land.

Atmospheric refraction (~0.57° lift at the horizon) is **not** applied; this
makes true sunrise ~1–2 min later than reality and true sunset ~1–2 min
earlier on a level horizon. On a 20° terrain horizon the effect is negligible.

## Config

There's nothing to configure beyond clicking *Submit* on the config-flow page:
the integration uses the latitude/longitude already set in your Home Assistant
configuration.

If you change those values later, remove the integration and add it back so
the cached horizon profile is refetched. (A `lat`/`lon`-change reload is on
the todo list.)

## License

MIT. See [LICENSE](LICENSE).
