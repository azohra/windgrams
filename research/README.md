# Research articles

Seven entries explain how Windgrams derives, reads, compares, and publishes soaring forecasts.
Provider paths and field inventories belong in the
[forecast model feed reference](../reference/forecast-model-feeds.md).

- **[Reading a windgram](reading-a-windgram.md)** — read thermal velocity, stability, derived heights,
  and winds from one fixed forecast example.
- **[Why usable lift can sit above the boundary layer](usable-lift-and-boundary-layer.md)** —
  distinguish a lifted-parcel boundary from canadarasp’s strongest-core threshold.
- **[How a windgram is computed](windgram-derivations.md)** — follow the derivation and the
  constants that define each published quantity.
- **[Choosing among six deterministic forecast models](choosing-forecast-models.md)** — match resolution and forecast
  horizon to the question, then diagnose disagreement.
- **[Seven forecast-data failures that passed parsing](forecast-data-validation-failures.md)** — inspect
  plausible wrong answers and the independent witness that caught each one.
- **[How the static forecast pipeline works](static-forecast-pipeline.md)** — use static JSON, git
  commits, selective transport, and append-only history as the publication system.
- **[What ensemble spread can—and cannot—tell you](ensemble-spread.md)** — interpret conditional percentiles,
  member counts, and column censoring without probability claims.
