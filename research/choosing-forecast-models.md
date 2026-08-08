# Choosing among six deterministic forecast models

The six deterministic models publish the same windgram fields at different resolutions and lead times.
Choose by lead time and required detail, then use disagreement to locate sensitivity in the day.

## Choose by lead time and required terrain detail

| Question | Begin with | Then compare |
| --- | --- | --- |
| What will the launch do today? | HRDPS 1 km / 2.5 km, HRRR 3 km | each other, then observations |
| How stable is tomorrow’s forecast? | the same high-resolution models | RDPS |
| Is the weekend worth protecting? | RDPS, GDPS | GFS trend |
| Is next week worth watching? | GDPS / GFS | wait for shorter-range guidance |

A global model can identify a ridge or trough many days out. It cannot resolve the launch cycle on a
particular mountain face. Use long-range guidance to allocate attention, not to choose an hour.

## Grid resolution controls terrain and local detail

Each grid cell averages terrain and atmosphere across its footprint. A finer grid can place model
terrain elevation closer to a launch and represent smaller weather features; a coarser grid describes
the regional setup. Neither resolution guarantees the right answer.

Model terrain elevation changes pressure-level filtering and every height derived from the surface
parcel. [How a windgram is computed](windgram-derivations.md) explains that dependency. Current
grid spacing, domains, and verified model terrain elevations belong in the
[forecast model feed reference](../reference/forecast-model-feeds.md).

## Time steps and pressure levels limit chart detail

Some windgrams contain hourly columns; others contain three-hourly columns. Their curves may look
equally continuous, but the latter carry fewer observations of the model state. A narrow peak between
three-hour steps is interpolation, not another forecast sample.

Vertical sampling imposes the same limit. Missing or widely spaced pressure levels reduce the detail
available for lapse rate, wind shear, parcel crossings, and cloud layers. Compare the structure and
sample positions behind a line before treating two smooth traces as equivalent evidence.

## Use model disagreement to locate forecast sensitivity

Similar traces support the conclusion that the large-scale setup is straightforward. Separated traces
identify sensitivity—to timing, moisture, initialization, terrain, or model physics—but a majority is
not automatically correct. Related systems can share errors, and a coarse model can reach the right
answer for the wrong local reason.

Use the comparison to locate the split:

| Pattern | First suspect |
| --- | --- |
| early timing split | boundary-layer development |
| persistent vertical offset | model terrain elevation or moisture |
| late-day fan | cloud development or collapsing surface heat |

The shaded **inter-model range** reports the minimum and maximum across available models. It carries no
probability calibration. Return to the single-model windgrams to inspect the atmospheric structure
behind it.
