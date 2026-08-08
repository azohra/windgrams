# What ensemble spread can—and cannot—tell you

A deterministic windgram draws the same crisp line on an easy forecast and a sensitive one. REPS runs
21 related atmospheres from perturbed initial conditions. Agreement shows that those model
realizations respond similarly; separation shows that one deterministic line hides sensitivity.

## The ensemble publishes four scalar distributions

REPS exposes only three pressure levels through the displayed windgram band. At the catalogued mountain
launches, the lowest is often below model terrain elevation. Twenty-one full windgrams drawn from those
sparse columns would add authority without adding vertical evidence.

The ensemble product therefore publishes member spread for cloud base, boundary-layer top, thermal
velocity, and usable-lift top. It does not publish 21 atmospheric profiles. The
[forecast model feed reference](../reference/forecast-model-feeds.md) holds the current level inventory and
provider paths.

## Calculate percentiles from derived member values

Each member passes through the complete nonlinear derivation as its own atmosphere. Percentiles are
calculated across the resulting scalar values. Averaging temperature, moisture, and heat flux first
would manufacture an atmosphere no member predicted, and its boundary-layer top would not equal the
average of the members’ tops.

Per forecast hour and scalar, the schema is:

```json
"usableLiftTopM": {
  "ceiledMembers": 0,
  "members": 21,
  "p10": 3222.3,
  "p25": 3355.1,
  "p50": 3503.9,
  "p75": 3530.2,
  "p90": 3647.3
}
```

`members` separates occurrence from magnitude: a member with no usable lift does not enter the height
ranking. `ceiledMembers` counts values clamped at the top of the available column, where the reported
height is a lower bound. Wind direction has no percentiles because circular values cannot be ranked
linearly: the midpoint of 350° and 10° is not 180°.

## The column ceiling and 500 hPa

One strong forecast hour placed all 21 members at the 700 hPa column ceiling, about 3,150 m. Their
boundary-layer tops differed by only 16 m. The narrow spread described the shared input ceiling, not
the weather.

Adding 500 hPa as computational headroom raised the ceiling to about 5,700 m. For the same hour, the
boundary-layer spread widened from 16 m to 205 m and usable-lift spread widened to 425 m. Hours that
had already terminated below 700 hPa remained bit-for-bit unchanged. `ceiledMembers` preserves the
warning if a later atmosphere reaches the higher ceiling.

## Read spread in this order

1. **Member fraction:** “18 of 21 members produce usable lift” comes before any height band.
2. **Median:** p50 is the ensemble centre, not the deterministic HRDPS line.
3. **Conditional range:** p10–p90 describes members that produced the quantity.
4. **Ceiling count:** a nonzero count makes the upper statistics lower-bound evidence.

Do not draw the REPS range as an error bar around HRDPS. Different model terrain elevations and physics
can put a deterministic line outside the ensemble range on an ordinary day.

## Spread is not probability

Member fraction measures agreement among model realizations. “18 of 21” does not establish an 86%
chance of usable lift. Probability requires calibration against archived forecasts and observations;
this project does not yet have that evidence.

Provider and transport details live in the
[forecast model feed reference](../reference/forecast-model-feeds.md). ECCC documents the underlying system
on its [REPS open-data page](https://eccc-msc.github.io/open-data/msc-data/nwp_reps/readme_reps_en/).
