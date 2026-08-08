# Windgrams

Windgrams publishes pilot-oriented soaring profiles as static JSON after each supported weather-model run. Profiles include surface conditions, winds and temperatures aloft, thermal velocity, boundary-layer top, cloud base, and usable-lift top.

[Research articles](research/README.md) · [Forecast model feed reference](reference/forecast-model-feeds.md) · [Site catalogue](sites.json)

## Published data

No API key is required. GitHub’s CDN serves every model through the same paths:

```text
https://raw.githubusercontent.com/azohra/windgrams/main/data/<model>/manifest.json
https://raw.githubusercontent.com/azohra/windgrams/main/data/<model>/sites/<slug>.json
```

| Model path | Grid | Forecast steps | Horizon | Source |
| --- | ---: | ---: | ---: | --- |
| `hrdps-1km-west` | 1 km | 1 h | 48 h | [ECCC experimental feed](https://eccc-msc.github.io/open-data/msc-data/nwp_hrdps/readme_hrdps-datamart-alpha_en/) |
| `hrdps-2p5km` | 2.5 km | 1 h | 48 h | [ECCC HRDPS](https://eccc-msc.github.io/open-data/msc-data/nwp_hrdps/readme_hrdps_en/) |
| `hrrr-conus` | 3 km | 1 h | 48 h | [NOAA HRRR](https://registry.opendata.aws/noaa-hrrr-pds/) |
| `reps-10km` | 10 km | 3 h | 72 h | [ECCC REPS](https://eccc-msc.github.io/open-data/msc-data/nwp_reps/readme_reps_en/) |
| `rdps-10km` | 10 km | 1 h | 84 h | [ECCC RDPS](https://eccc-msc.github.io/open-data/msc-data/nwp_rdps/readme_rdps_en/) |
| `gdps-15km` | 15 km | 3 h | 240 h | [ECCC GDPS](https://eccc-msc.github.io/open-data/msc-data/nwp_gdps/readme_gdps_en/) |
| `gfs-global` | 25 km | 3 h | 384 h | [NOAA GFS](https://registry.opendata.aws/noaa-gfs-bdp-pds/) |

The 1 km HRDPS feed is experimental and occasionally unavailable. Sites outside a model’s domain have no profile for that model.

```sh
curl -sS https://raw.githubusercontent.com/azohra/windgrams/main/data/hrdps-2p5km/sites/dundee.json \
  | jq '.hours[] | {validAt, thermalVelocityMs, usableLiftTopM, windSpeedKmh}'
```

## Data contract

`manifest.json` identifies the published model run and its available sites. Each site profile contains:

- model and launch metadata;
- daytime forecast hours from 07:00 through 21:00 Pacific;
- surface pressure, temperature, precipitation, cloud cover, and wind;
- pressure-level height, temperature, moisture, and wind;
- derived thermal velocity, boundary-layer top, cloud base, and usable-lift top.

Past forecasts are append-only gzip archives at:

```text
data/<model>/history/<slug>/<year>.jsonl.gz
```

Each decompressed line is one model run:

```sh
zcat data/hrdps-2p5km/history/dundee/2026.jsonl.gz | jq -r .referenceTime
```

The [forecast model feed reference](reference/forecast-model-feeds.md) records provider paths, schedules, field semantics, and verification dates.

## Repository

| Path | Contents |
| --- | --- |
| [`data/`](data/) | Published manifests, current profiles, and forecast history |
| [`windgrams/`](windgrams/) | Provider clients, model builders, derivation, and publishing code |
| [`tests/`](tests/) | Derivation, transport, and publication tests |
| [`research/`](research/) | Methods, interpretation, wfailures, and uncertainty |
| [`reference/`](reference/) | Dated provider reference |
| [`site/`](site/) | Astro site and SVG windgram renderer |

## Build

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required.

```sh
uv run python -m windgrams.build       # HRDPS 2.5 km
uv run python -m windgrams.build_1km   # HRDPS West 1 km
uv run python -m windgrams.build_hrrr  # HRRR 3 km
uv run python -m windgrams.build_rdps  # RDPS 10 km
uv run python -m windgrams.build_gdps  # GDPS 15 km
uv run python -m windgrams.build_gfs   # GFS 25 km
uv run python -m windgrams.build_reps  # REPS 10 km ensemble
uv run pytest
```

GeoMet builds make small WCS requests with concurrency capped at five. The 1 km builder downloads roughly 1.2 GB of whole-domain GRIB2 per run; HRRR and GFS use byte-range requests. Do not run a builder more often than its model publishes.

## Add a site

Add its slug, name, launch coordinates, and elevation to [`sites.json`](sites.json). The next successful build publishes it for every model whose domain covers the coordinates.

## Licence

ECCC source data is used under the [Environment and Climate Change Canada Data Server End-use Licence](https://eccc-msc.github.io/open-data/licence/readme_en/); derived profiles retain its attribution requirement. NOAA HRRR and GFS data are public-domain products distributed through the [Open Data Dissemination program](https://www.noaa.gov/information-technology/open-data-dissemination). Code is [MIT licensed](LICENSE).
