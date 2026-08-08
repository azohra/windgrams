# Forecast model feed reference

Every builder supplies nine surface fields, five fields on each pressure
level, and model terrain elevation to the shared derivation. Access, resolution,
cadence, horizon, retention, and field semantics vary by model.

Measurements use live service responses checked through 2026-08-08. When provider
documentation and live capabilities disagree, use the live response and update
the verification date.

## HRDPS continental 2.5 km — supported

Environment and Climate Change Canada's High Resolution Deterministic
Prediction System: 2.5 km grid over nearly all of Canada, 48 hourly steps,
four runs a day (00/06/12/18Z).

The pipeline reads it through [GeoMet](https://api.weather.gc.ca/)'s WCS
endpoint — not the Datamart. Every request asks for a tiny GeoTIFF crop
around the catalogued launches at the model's 0.0225° spacing, and each crop
comes back at roughly 2 KB. Measured whole-build transfer costs are in
[How the static forecast pipeline works](../research/static-forecast-pipeline.md).

The trade-off is request count: WCS has no bulk mode, so the build is many
small HTTP calls. The client keeps concurrency at five, retries 429/5xx with
jittered backoff, honours `Retry-After`, and reports its request count in the
published manifest so the cost stays visible.

## HRDPS West 1 km — supported, experimental

ECCC also runs an experimental 1 km HRDPS over BC and western Alberta,
published only as whole-domain GRIB2 on the **alpha Datamart** — no WCS, no
subsetting. The grid is a rotated lat-lon, 1330 × 1180 points; ecCodes handles
the rotation so the sampler only ever speaks geographic coordinates. Runs are
00Z and 12Z only, files are retained for roughly 24 hours, and the feed goes
dark occasionally — the workflow treats a 1 km failure as a warning, never a
blocked 2.5 km publish.

The builder downloads each whole-domain file before sampling the catalogue.
One launch elevation is **1,485 m**; model terrain elevation
is **1,311 m** at 1 km and **1,072 m** at 2.5 km.
The 1 km grid reduces the terrain error from 413 m to 174 m. That 239 m shift
propagates into cloud base, boundary-layer top, and which pressure levels lie
above model terrain.

## RDPS 10 km — supported

The Regional Deterministic Prediction System: 10 km, **84 hourly steps**,
four runs a day. It extends the windgram from HRDPS's two days to three and
a half.

Verified facts:

- Fully available on GeoMet WCS under the **new-style `RDPS_10km_*` layer
  names** (the older `RDPS.ETA_*` convention is on its way out).
- All nine windgram pressure levels (925–600 hPa) exist, and both sensible
  and latent heat fluxes are published — the full derivation runs with no
  substitutions.
- **WCS sampling requirement:** GeoMet stretches whatever resolution you
  request to fit the subset bounding box, so a native-spacing request over
  a small box lands the grid cells in the wrong places and returns
  physically plausible wrong values. Sample finely — 0.0225° reproduced
  GetFeatureInfo exactly at every site for both RDPS and GDPS — and verify
  crop values against GetFeatureInfo at a few points. See
  [Seven forecast-data failures that passed parsing](../research/forecast-data-validation-failures.md).

## GDPS 15 km — supported

The Global Deterministic Prediction System: 15 km, 00Z and 12Z, through
**240 hours**. ECCC's current system
description (checked 2026-08-08) identifies it as a coupled atmosphere,
ocean, and sea-ice forecast whose large-scale temperature and wind are
spectrally nudged toward its GEML data-driven weather model. That is a
material change in lineage even though the open-data contract remains
familiar. A ten-day windgram still has published sensible and latent heat
fluxes rather than proxy surface heating.

Verified facts:

- The old `GDPS.ETA_*` GeoMet layer names are unavailable; current layers use
  the `GDPS_15km_*` prefix.
- All nine pressure levels and both heat fluxes are available — but six of
  the nine levels (900, 875, 800, 750, 650, 600 hPa) **thin to 6-hourly
  after hour 168**; only 925, 850, 700 and the surface fields stay 3-hourly
  to the end. The builder tolerates a level being absent at a valid time, so
  day 8–10 columns ride on the three levels that remain.
- **Precipitation must be differenced.** No fixed-window precipitation layer
  spans the full horizon; the reliable quantity is the run-total
  accumulation, so per-step precipitation is
  `accum(h) − accum(h_prev)` between consecutive published steps.

## HRRR 3 km — supported

NOAA's High-Resolution Rapid Refresh: 3 km over the continental United
States, hourly runs, with the **synoptic runs (00/06/12/18Z) extending to
48 hours**, published to public cloud buckets roughly **T+107 minutes** after
the reference time.

Verified facts:

- **Domain geometry:** The oft-quoted
  47.8°N northern limit is the *eastern* corner of the Lambert conformal
  grid. At −117.7°W the boundary is at **51.24°N** — the southern-BC
  founding sites sit about 215 km inside the domain. Check the corner
  nearest *your* longitude before assuming HRRR excludes you.
- All **54 records the windgram needs live in a single `wrfprs` file per
  hour**, and its `.idx` sidecar lets a client fetch exactly those records
  by byte range. See
  [How the static forecast pipeline works](../research/static-forecast-pipeline.md).
- Heat fluxes are instantaneous values.
- **Winds are grid-relative.** U/V components on the native Lambert
  projection point along grid axes, not geographic east/north. Skip the
  rotation and wind directions bias by 10–15° at these latitudes.

## GFS 0.25° — supported

NOAA's Global Forecast System at 0.25°: the long-horizon leg, out to
**384 hours**. Since the 2021 upgrades the output is **3-hourly all the way
to f384** — the old 12-hourly tail beyond day 10 is gone.

Verified facts:

- **875 hPa does not exist** in the `pgrb2.0p25` files. The windgram's nine
  levels become eight, or 875 is interpolated; either way, don't loop over
  the HRDPS level list and expect nine hits.
- Pressure-level dew point isn't published; **dew point depression must be
  computed from temperature and relative humidity** per level.
- **Flux time semantics:** `SHTFL`/`LHTFL` exist only as *averages over
  a growing window* that resets every 6 hours: f001 averages hour 0–1, f002
  averages 0–2, … f006 averages 0–6, then f007 starts again. Difference the
  window-hours to recover the mean flux over any sub-interval:

  ```
  mean(h1→h2) = ((h2−h0)·A(h2) − (h1−h0)·A(h1)) / (h2−h1)
  ```

  where `h0` is the window start and `A(h)` the published average at hour
  `h`. The builder reconstructs each interval before deriving w\*.

## REPS 10 km ensemble — supported

ECCC's Regional Ensemble Prediction System: **21 members** (a control plus
20 perturbed), rotated lat-lon at 0.09° (~10 km), four runs a day
(00/06/12/18Z), **3-hourly to 72 hours** — no hourly output. Its output
here is not a windgram: every member is derived as its own atmosphere and
the published file carries the percentile spread of the derived quantities.
The first published run is `2026-08-08T00:00:00Z`.
Read the product semantics in
[What ensemble spread can—and cannot—tell you](../research/ensemble-spread.md).

Verified facts (live, 2026-08-08):

- **Both surface heat fluxes exist per member.** GeoMet WCS publishes
  `REPS.MEM.ETA_FC.NN` / `ETA_FV.NN`
  (instantaneous W/m²) and on Datamart as `SHTFL_SFC` / `LHTFL_SFC`
  all-members GRIB2. A test crop of one member's sensible flux at 3 pm MDT
  returned 45–279 W/m² — real afternoon convection, per member.
- **GeoMet serves raw REPS members over WCS** through the same ~2 KB crops and
  `SUBSET=x/y` + `SUBSETTINGCRS=EPSG:4326` mechanics as the deterministic
  builds, including the same silent zero-fill failure if you subset with
  the advertised `long`/`lat` axis names. **Member numbering is off by one
  across transports**: WCS `.01` is the control that Datamart GRIB encodes
  as `perturbationNumber 0`. The builder pins the mapping in one function,
  with a test.
- **The one WCS gap is wind.** No per-member U/V or direction exists on any
  level, so winds come from Datamart's all-members files. REPS's rotated grid
  makes the components grid-relative; skipping the rotation produces a ~24°
  direction error at these latitudes. See
  [Seven forecast-data failures that passed parsing](../research/forecast-data-validation-failures.md).
- **Three of the nine windgram levels exist** (925/850/700), and 925
  typically sits below REPS model terrain elevation near 1,600 m at
  one catalogued launch against 925 hPa's ~780 m. Members are fed a
  **925/850/700/500 column**: 500 hPa
  is not a display level, but it lifts the parcel search's ceiling from
  ~3,150 m to ~5,700 m so strong days differentiate instead of clamping at
  the column top. See
  [What ensemble spread can—and cannot—tell you](../research/ensemble-spread.md).
- No dew point in any form — derive it from temperature and relative
  humidity. Precipitation is run-total accumulation, differenced at 3 h
  (the GDPS pattern). Fluxes and accumulations are absent at hour 000.
- The hybrid build moves ~1.5 GiB per run for the display schedule:
  kilobytes of WCS crops plus ~10–18 MB per un-croppable Datamart wind
  file.
- Datamart retention is ~30 days (`dd.weather.gc.ca`), ~52 on the
  `hpfx.collab.science.gc.ca` mirror; GeoMet keeps only ~2 days of
  reference times, which permits 15-minute polling but not backfill. The legacy
  `/ensemble/reps/` tree is dead (404); everything lives under the
  date-based `YYYYMMDD/WXO-DD/ensemble/reps/10km/grib2/HH/hhh/` tree.

## GEPS 0.5° ensemble — evaluated, not adopted

ECCC's Global Ensemble Prediction System: 21 members, regular 0.5° global
grid, 00Z and 12Z, **3-hourly to 192 hours then 6-hourly to 384** — sixteen
days — with the Thursday 00Z run extending to 936 hours. Verified live on
2026-08-07 and not yet adopted:

- **Per-member heat fluxes exist to the full horizon.** Unlike REPS's instantaneous values, GEPS fluxes are
  **interval accumulations** that must be differenced back to W/m², and the
  accumulation convention beyond the first step is unverified.
- **Datamart only.** GeoMet has no per-member GEPS layers — statistical
  products alone, with no fluxes among them. The fetch unit is the
  all-members GRIB2 file, ~102 MB per forecast step, **~9.6 GB per run**.
  This transfer cost is the reason the feed was not adopted.
- Three of the nine windgram pressure levels exist (925/850/700). Dew point
  is absent, and run-total precipitation requires 6-hourly differencing
  beyond hour 192.
- **Verify every download against Content-Length.** One GEPS fetch returned
  another model's bytes, correct on retry; the Datamart client now
  length-checks every download because of it. See
  [Seven forecast-data failures that passed parsing](../research/forecast-data-validation-failures.md).
- Retention matches REPS; the legacy `/ensemble/geps/` tree is likewise
  dead.

## ECMWF IFS open data — evaluated, not adopted

ECMWF's open-data IFS offers a 15-day horizon (360 h at 00/12Z since cycle
50r1) under CC-BY-4.0. Two missing inputs ruled it out:

- **No surface heat fluxes are published.** w\* has no direct input. The physics would need
  a radiation-proxy flux: net solar radiation partitioned by an *assumed*
  Bowen ratio. That method produces a less defensible forecast than models
  that publish surface fluxes and requires a different product label.
- **Only four of our nine pressure levels exist** in the open-data set
  (925/850/700/600) — and at the founding mountain sites, 925 hPa is below
  the model terrain. Three usable levels do not define a sounding;
  interpolation would dominate the boundary-layer and stability estimates.

The 15-day horizon could support a labelled proxy-physics outlook. It cannot
support the same windgram contract as models that publish surface fluxes and
a deeper pressure column.

## Licensing and attribution

- **ECCC** (HRDPS, RDPS, GDPS): used under the
  [Environment and Climate Change Canada Data Server End-use Licence](https://eccc-msc.github.io/open-data/licence/readme_en/).
  Derived profiles carry the attribution requirement.
- **NOAA** (HRRR, GFS): U.S. government open data. Attribution is requested,
  and use implies no NOAA endorsement of this project.
- **ECMWF** open data is CC-BY-4.0 — relevant only if an IFS-based leg is
  adopted later.

Provider overviews: [HRDPS](https://eccc-msc.github.io/open-data/msc-data/nwp_hrdps/readme_hrdps_en/),
[RDPS](https://eccc-msc.github.io/open-data/msc-data/nwp_rdps/readme_rdps_en/),
[GDPS](https://eccc-msc.github.io/open-data/msc-data/nwp_gdps/readme_gdps_en/),
[REPS](https://eccc-msc.github.io/open-data/msc-data/nwp_reps/readme_reps_en/),
[HRRR](https://registry.opendata.aws/noaa-hrrr-pds/), and
[GFS](https://registry.opendata.aws/noaa-gfs-bdp-pds/).
