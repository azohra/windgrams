# Seven forecast-data failures that passed parsing

These seven failures returned HTTP 200, decoded as GRIB or GeoTIFF, and produced values a chart could
draw. Parsing proved the payload was readable; an independent witness showed that it represented the
wrong place, direction, time interval, model, or run state.

## A WCS crop sampled the wrong cells

GeoMet WCS returned a correctly shaped terrain crop at the requested “native” resolution. The sampled
RDPS elevation was 1,426 geopotential metres, a plausible value for a mountain site. GeoMet’s point
query reported 1,168 gpm for the same model cell, and 2 m temperatures differed by as much as 2.5 °C
at half the test sites. A finely oversampled crop reproduced the point values.

The builders now compare several crop values with an independent point query before trusting the
georeferencing. A WCS crop is a rendered coverage, not proof of nearest-cell sampling.

## A broken WCS request returned valid zeros

DescribeCoverage advertised `long` and `lat` axes. Subsetting with those names returned HTTP 200 and a
valid GeoTIFF filled with zeros. But zero sensible heat flux on a sunny afternoon implied no convection
across the entire crop. This request shape required the undocumented `x`/`y` axes and an explicit
`SUBSETTINGCRS=EPSG:4326`.

Each field now passes physical plausibility checks. The check matters most when zero can mean either a
valid measurement or a broken request.

## Grid-relative winds were not rotated

U and V components decoded normally and produced realistic wind speeds. HRRR’s Lambert grid and REPS’s
rotated latitude–longitude grid, however, define those components along grid axes rather than true east
and north. In one REPS verification, the unrotated member read 261° and the transformed value 236.6°,
bracketed by deterministic forecasts at 250° and 238°. HRRR errors at these longitudes were 10–15°.

The rotation was checked three ways: ecCodes geolocation to about 10⁻⁶ degrees, member-for-member speed
against GeoMet, and directional comparison with sibling models.

The builders read each grid’s vector convention from GRIB projection metadata and rotate grid-relative
components before deriving direction. A correct magnitude does not prove a correct direction.

## A model URL returned another model’s grid

A GEPS orography URL returned 4.3 MB of decodable GRIB, but the grid inside was REPS-shaped. The body
length also disagreed with the server’s `Content-Length` and ETag. An immediate retry returned the
expected bytes; the upstream cause remains unknown.

The download client now checks every full response against its declared length and retries mismatches.
A valid file format cannot identify the model inside it.

## Flux fields used different time intervals

Several models expose sensible heat flux in units reducible to W/m², but the clocks differ. HRRR and
REPS publish instantaneous values. GFS publishes averages over growing windows that reset every six
hours. GEPS publishes accumulations that require differencing. Treating all three as instantaneous
smears afternoon heating into the morning while leaving believable values.

The builders read product-definition and time-range metadata, then test sequences across window resets.
A variable name and unit do not define its time semantics.

## A model run was only partly published

Early forecast hours for a new cycle downloaded while the provider was still publishing later hours.
The final scheduled hour was absent. A build started then would have failed after thousands of requests.

The pipeline probes the final required forecast hour first. A run does not exist until its last expected
product answers.

## Provider paths changed before their documentation

Documentation, examples, and old forum answers referenced layer families such as `GDPS.ETA_*`,
`RDPS.ETA_*`, and legacy ensemble directory trees. Live capabilities and directory listings had moved.
Some names returned 404; others survived as aliases with different availability.

Provider identifiers are dated observations. The
[forecast model feed reference](../reference/forecast-model-feeds.md) records what was live-verified and when; the service is
authoritative when prose and capability metadata disagree.

## Validation must test identity, location, projection, and time semantics

Schema validation proves shape. Each trust boundary also compares the payload with an independent fact
about identity, location, projection, or time semantics. The check lives beside the code that crosses
the boundary.

The provider’s relevant vector warning is explicit in the
[ECCC RDPS data specification](https://eccc-msc.github.io/open-data/msc-data/nwp_rdps/readme_rdps-datamart_en/):
U and V must be resolved relative to the defined grid. The incident-specific countermeasures live in
the builders and shared download clients in this repository.
