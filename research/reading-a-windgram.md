# Reading a windgram

A windgram aligns surface forcing with the atmosphere above one model grid cell. Each vertical slice
is a forecast sounding; the horizontal axis connects those soundings through the day. Read the chart
from the flight band outward: usable height, stability and moisture, wind through that height, then
the surface fields driving the change.

## Check lift, climb limits, wind, surface forcing, and pressure

1. **When does usable lift reach launch?** Follow the solid usable-lift line across the horizontal
   launch marker. A valley thermal forecast below launch does not establish a launch cycle.
2. **What stops the climb?** Compare usable lift with the dashed boundary-layer top and dotted cloud
   base. Their order identifies an energy limit, a stable cap, a moisture limit, or a sounding ceiling.
3. **What occupies the flight band?** Read wind from launch to usable-lift top. Cross-hatching puts
   near-saturated model layers inside that band; the 0 °C contour locates the freezing level.
4. **Does the surface support the profile?** Thermal velocity w\* should grow with boundary-layer
   depth. Cloud and precipitation can interrupt the surface heat that feeds it.
5. **Is the synoptic pattern changing?** Pressure tendency can flag an approaching system or a
   building ridge. It cannot select a launch hour by itself.

## Pressure, precipitation, cloud, and w\* use separate scales

The four strips share the time axis but use separate numeric scales:

| Strip | Measurement | Reading limit |
| --- | --- | --- |
| **Pressure · kPa** | Mean sea-level pressure at the grid cell. | The line shows tendency at one point; wind responds to pressure differences across space. |
| **Precip · mm** | Liquid-equivalent precipitation accumulated during the forecast step. | The value does not identify rain, snow, or freezing precipitation. |
| **Cloud · %** | Total cloud fraction in the model column. | Coverage has no height; hatching and cloud base carry vertical information. |
| **w\* · m/s** | Thermal velocity derived from surface heat flux and boundary-layer depth. | It is an energy scale, not a predicted glider climb rate. |

Each vertical slice of the main panel is one atmospheric column at the local time printed below it.
The left axis gives metres above sea level and the right axis gives feet above sea level. The launch
marker, winds, temperature contours, cloud layers, and derived heights therefore share one vertical
coordinate. The coloured field interpolates lapse rate between the model’s pressure levels; it is not
a stack of observed layers.

In the fixed forecast sample, pressure spans 101.0–101.4 kPa, no precipitation reaches the grid cell,
cloud fraction ranges from 0% to 49%, and w\* peaks at 2.8 m/s at 14:00. That peak identifies the hour
with the greatest modelled convective energy. Height, moisture, and wind still decide what that energy
produces.

## Read pressure as a tendency

The pressure strip auto-scales to the day. A four-hectopascal change can fill the strip even though it
is a modest synoptic tendency; the drawn amplitude is not a pressure-gradient map.

Falling pressure often accompanies an approaching low, trough, or front. Read it with thickening cloud,
precipitation, and strengthening or backing winds before inferring deterioration. Rising pressure often
follows a frontal passage or marks a building ridge. Clearing can follow, while subsidence under the
ridge can also strengthen an inversion and trap valley haze or smoke. A flat line says that mean
sea-level pressure changes little at that grid cell during the displayed hours.

Wind responds to the pressure gradient between places, not the pressure value at one launch. Two days
can both read 101.2 kPa and carry different wind because the surrounding isobars differ. Treat the strip
as a regime-change clue, then check forecast maps, winds aloft, and observations.

## Read the stability scale against a rising parcel

The chart reports local environmental lapse rate in degrees Celsius per 1,000 ft. Its sign matters:
negative values mean the environment cools with height; positive values mean temperature increases
with height, which is an inversion.

An unsaturated rising parcel cools at about 3 °C per 1,000 ft. When the environment cools at least that
quickly, the parcel can remain warmer than its surroundings and continue upward. The red and orange
classes at or below −2.5 °C per 1,000 ft therefore mark the least resistance to dry convection. Between
about −2.5 and −1.5, a dry parcel loses buoyancy more readily, while a saturated parcel may continue
because condensation slows its cooling. The exact moist-adiabatic rate changes with temperature and
moisture, so the chart’s fixed “conditional” bins are a reading aid rather than a parcel calculation.
The −1.5 to −1.2 class sits near the moist-adiabatic range and remains condition-dependent. Values
from −1.2 to 0 are stable. Positive grey classes are inversions: temperature warms with height and caps
vertical exchange.

Read the shape before the colour name. A shallow unstable layer under a stable band supports low,
short-lived mixing. A deep unstable column with positive w\* supports a deeper boundary layer and can
mix stronger winds from aloft toward launch. An unstable column ending in a stable lid can produce a
defined top and organized climbs below it. An inversion crossing launch height must erode before
surface-driven air can connect the valley with launch. A red column at night or under zero surface heat
still has no modelled thermal engine; lapse rate describes susceptibility, while w\* supplies forcing.

## Separate cloud cover, cloud base, and cross-hatching

Cloud percentage is the model’s total column coverage. It does not say where the cloud sits. The dotted
cloud-base line is a lifted-condensation-level estimate for a parcel starting at model terrain. It asks
where that surface parcel would first saturate.

Cross-hatching asks a different question. The renderer marks interpolated regions where pressure-level
dew-point depression is below 0.5 °C. Those layers are already near saturation in the model sounding.
A hatched layer above a high surface cloud base can therefore represent mid-level or upper cloud that
the surface parcel did not create. Hatching through the flight band means the model places cloud in the
air pilots would occupy.

The three moisture signals can disagree without contradicting each other. Total cloud may be high while
none of the sparse pressure levels lands inside a thin saturated layer. A low surface cloud base may cap
usable lift while total coverage remains small. Hatching can appear with zero precipitation because
cloud need not produce precipitation at the ground.

## Precipitation is not automatically rain

The precipitation strip reports liquid-equivalent depth for each model step. An hourly model column
contains an hourly total; a three-hourly model column contains a three-hour total. Comparing their bar
heights as rates would exaggerate the three-hourly model.

The strip does not classify phase. The 0 °C contour shows the dry-bulb freezing level, and the hatched
layers show where the sampled column is near saturation. Precipitation reaching a launch in air well
above 0 °C is likely rain. A subfreezing column supports snow. A warm layer above a subfreezing launch
can melt snow and permit refreezing, so a precise phase call needs the full temperature and wet-bulb
profile; the freezing contour alone cannot supply it.

In the wet stable column, GDPS publishes 10.5 mm for a three-hour step and
80% cloud cover. The launch-level air is about 12 °C, the freezing level is near 3,490 m, and two sampled
layers are cross-hatched. This is rain at launch with cloud through parts of the column, not “10.5 mm of
rain everywhere below cloud base.” Thermal velocity is only 0.5 m/s and the usable-lift top remains
below launch.

## Boundary-layer top, usable-lift top, and cloud base answer different questions

- **Boundary-layer top — dashed amber.** A dry parcel lifted from the model surface becomes no warmer
  than the environment at this elevation. It describes thermodynamic depth.
- **Usable-lift top — solid blue.** canadarasp’s strongest-core profile falls to a 1 m/s sink threshold
  here, unless cloud base stops it first. It describes a modelled climb limit.
- **Cloud base — dotted slate.** A surface parcel reaches saturation here. When this line pins the solid
  line, moisture limits usable height.

Thin isotherms show the elevation of fixed temperatures. The emphasized 0 °C contour is the freezing
level. Cross-hatching and cloud base remain separate because existing model cloud and a lifted surface
parcel are separate pieces of evidence.

The boundary-layer and usable-lift lines can cross because they do not estimate the same quantity.
[Why usable lift can sit above the boundary layer](usable-lift-and-boundary-layer.md) explains the
updraft coefficient and sink threshold behind the solid line.

## Wind barbs: read the flight band

The shaft points toward the direction the wind comes **from**. A half tick counts 5 units, a full tick
10, and a pennant 50; a circle means calm. The unit is a chart convention, not part of the symbol.
Aviation charts commonly count knots; canadarasp and this project count km/h. Read the printed unit
before decoding the feathers.

Scan vertically at the hour of interest. Start near launch, continue through the usable-lift band, and
read the wind just above its top. Speed increasing with height implies stronger drift and can bring
faster air toward launch as mixing deepens. A directional change through the band marks shear and can
place part of the climb in lee flow even when the launch-level barb looks acceptable. Then scan through
time for the arrival of valley circulation, strengthening synoptic flow, or a reversal.

## What the chart cannot decide

A windgram is a forecast at a grid cell, not an observation or a go/no-go tool. It cannot resolve rotor
behind a spur, a launch cycle inside the grid cell, smoke suppressing surface heat, precipitation phase
without a fuller thermodynamic profile, or an early valley-wind arrival. Compare it with current
observations, aviation forecasts, radar or satellite, forecast maps, and local site knowledge.

The stability interpretation follows the
[FAA Glider Flying Handbook](https://www.faa.gov/sites/faa.gov/files/regulations_policies/handbooks_manuals/aviation/glider_handbook/faa-h-8083-13a.pdf),
and pressure tendency follows the
[National Weather Service observing handbook](https://www.weather.gov/media/safety/ObservingHandbook1_2010_508_compliant.pdf).
The rendering lineage lives in the
[canadarasp windgram source](https://github.com/ajberkley/canadarasp/blob/master/continental-test/plot-generation/windgram-continental.ncl)
and [acrophobia.ca’s windgram component](https://github.com/azohra/acrophobia.ca/blob/main/src/components/sites/Windgram.tsx).
