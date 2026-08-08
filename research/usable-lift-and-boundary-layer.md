# Why usable lift can sit above the boundary layer

The solid usable-lift line on this project’s charts often rides above the dashed boundary-layer line.
It looks contradictory only if both lines are assumed to mean “thermal top.” They do not. One comes
from a lifted parcel; the other comes from an updraft profile, a sink-rate threshold, and a coefficient
choice made in canadarasp’s source.

## Hcrit is not one universal quantity

Dr. John “Dr Jack” Glendening’s BLIPMAP documentation defines **Hcrit** as the height where an
*average dry updraft* falls below 225 ft/min—about 1.14 m/s. He presents it as a practical maximum
thermalling height over flat ground. He also says that the assumptions lack quantitative validation
and that boundary-layer top may work better over complex terrain.

canadarasp inherits the name and the idea of a sink threshold, but its windgram code asks a different
question: how high might the **strongest core** still beat a 1 m/s sink rate? That is the number this
repository ports. “Hcrit” therefore names a family of methods, not a portable value that every
forecast system computes identically.

## Average-profile and strongest-core formulas

Lenschow and Stephens fitted aircraft observations of convective thermals with a normalized mean
updraft shape. In canadarasp’s notation, for height *z* inside a boundary layer of depth *D*:

```
w_average = w* × 1.34 × (z/D)⅓ × (1 − 0.8·z/D)
```

The source then says the peak at a thermal’s centre is roughly three times stronger. The
implementation uses 4.0 instead of 1.34:

```
w_core = w* × 4.0 × (z/D)⅓ × (1 − 0.8·z/D)
```

It first rejects the hour if the curve’s maximum—about `2.02 × w*`—cannot beat the 1 m/s sink rate.
Otherwise it walks upward from 0.25 D, interpolates the first sink-threshold crossing, and stops at
cloud base because flying into cloud is not a usable answer.

## Why usable-lift top can cross boundary-layer top

The boundary-layer line is a thermodynamic crossing: lift a dry surface parcel and find where it is no
longer warmer than the model environment. The usable-lift line is a kinematic crossing: evaluate a
modelled core until its vertical speed falls to the sink threshold. A strong core carries momentum
into the entrainment zone and the canadarasp curve is evaluated beyond `z/D = 1`, so its threshold can
land above the parcel-derived boundary-layer top. Smoothing cloud base and usable-lift top separately
can also change the hour-to-hour gap.

The solid line is not “more correct.” The 4.0 coefficient is a pragmatic extrapolation from an average
profile. The underlying 1980 observations came from aircraft legs over the ocean
during AMTEX, not from paragliders centring thermals in a mountain valley. The code is precise; the
physical transfer is an assumption.

## Usable-lift top has not been calibrated against flights

Neither coefficient establishes a calibrated flight ceiling for mountain soaring. The archive can be
paired with IGC tracks to measure bias by site, hour, wind regime, and pilot population; that study has
not been done. The chart therefore names the ported quantity **usable-lift top**, not predicted maximum
altitude. [Reading a windgram](reading-a-windgram.md) keeps the boundary-layer and usable-lift lines as
different questions.

Primary trail: [Dr Jack’s BLIPMAP parameter documentation](https://www.drjack.info/BLIP/INFO/parameter.html),
[Lenschow & Stephens (1980), DOI 10.1007/BF00122351](https://doi.org/10.1007/BF00122351), and the
[canadarasp implementation](https://github.com/ajberkley/canadarasp/blob/master/continental-test/plot-generation/windgram-continental.ncl#L377-L408).
