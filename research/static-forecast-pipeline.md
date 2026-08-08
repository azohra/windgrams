# How the static forecast pipeline works

Windgrams publishes profiles as static JSON. Weather centres run the numerical models, GitHub Actions
derives each site profile, git records each publication, and browsers fetch the files. The project
operates no application server, database service, queue, or API; it still depends on provider and
GitHub infrastructure.

## Each model builder follows the same run contract

A scheduled workflow wakes every 15 minutes. Each builder has the same contract:

1. Discover the newest upstream cycle.
2. Probe its final required forecast hour; exit if the run is incomplete.
3. Compare the cycle with the local manifest; exit if nothing is new.
4. Fetch only the fields and locations required.
5. Validate, derive, and serialize deterministically.
6. Write one model directory and append its history records.
7. Commit all completed model updates once.

A concurrency group prevents overlapping schedules from racing. Experimental or less reliable feeds
can warn without blocking the baseline publish. Quiet no-op exits make aggressive polling cheap and
polite: most schedules perform one discovery request and stop.

## Git records each publication

Each completed model run contributes one deterministic change set to the workflow commit:

- `git log data/<model>/manifest.json` shows its publication history.
- Diffs expose field, site, and serialization changes.
- Manifests record request count, byte volume, and duration for the build.
- A bad publication can be reverted with ordinary repository history.

Stable, small output makes Git viable. Key order is deliberate; integral floats are normalized; each
builder writes only its own model directory. Append-oriented files measured in kilobytes per site remain
reviewable. Arbitrary mutable binaries would not.

The Python derivation reproduces the original acrophobia.ca TypeScript output within one double ULP.
Serialization preserves the TypeScript representation: integral floats become integers and dictionary
key order remains stable. When diffs are the audit trail, representation is part of correctness.

## Match every profile to its manifest

Consumers read files from `raw.githubusercontent.com`. A manifest and a site profile are cached
independently, so immediately after a commit a browser may receive a new manifest and an older profile—or
the reverse.

Every profile therefore carries its own `referenceTime`. The client accepts the file only when that time
matches the manifest it just read. On mismatch it retains the previous good copy and retries later. A
few lines at the trust boundary replace server-side transactions for this update pattern.

## GRIB ranges and WCS crops reduce transferred bytes

Most weather-data cost comes from moving bytes the derivation will discard. The pipeline prefers GRIB
record ranges, uses WCS crops where available, and downloads whole domains only when neither exists.

### GRIB index byte ranges

NOAA places a plain-text `.idx` file beside each GRIB2 object. It lists record names and byte offsets,
so HTTP range requests can retrieve the needed variables without downloading the whole file. A single
HRRR pressure file is roughly 546 MB; one windgram hour needs 54 records spread through it. Range reads
turn a file-scale transfer into record-scale transfers.

### WCS crops

ECCC GeoMet can crop a coverage around the catalogued points. A typical response is about 2 KB; a full
HRDPS 2.5 km build moves roughly 6 MB in the measured runs. The local GeoTIFF reader deliberately accepts
only the narrow uncompressed-float form the service currently returns. A surprise encoding is treated as
a provider change, not guessed around.

### Whole-domain files

The experimental HRDPS West 1 km feed has neither suitable WCS access nor record indexes. It downloads
about 1.2 GB per run to sample four launches. That 200-fold transfer difference is why subsetting is an
architectural feature, not an optimization pass.

All transports identify the project with a real User-Agent, honor `Retry-After`, and retry 429 and 5xx
responses with jitter. Free public data remains viable when clients are visible and bounded.

## Append history as concatenated gzip members

Each publication also appends one JSON line to:

```
data/<model>/history/<slug>/<year>.jsonl.gz
```

The line is compressed as its own gzip member and appended byte-for-byte. The gzip format permits
concatenated members, so `zcat` and Python’s `gzip` expose one continuous JSONL stream while existing
compressed bytes never change. About 12 KB per site per run buys the dataset needed for forecast
verification, bias studies, and later calibration.

## The static pipeline has no query API or atomic multi-file read

The static pipeline also provides no database index or service-level agreement.
GitHub’s availability and acceptable-use rules are dependencies. History queries require downloading
the archive, and a large site catalogue would eventually outgrow repository ergonomics.

The catalogue has four sites, small JSON profiles, and model cycles no faster than hourly. A larger
catalogue can keep the derivation and file schema while moving publication and history to another store.

The predecessor makes the tradeoff concrete. The public
[canadarasp operations README](https://github.com/ajberkley/canadarasp#readme) describes an EC2 pipeline
costing roughly CAD $1,300 per year and moving about 10 GB of compressed HRDPS input per run. Windgrams
publishes site columns rather than national maps, so its architecture serves a narrower job.

Executable details: [the workflow](../.github/workflows/build.yml),
[`windgrams/publish.py`](../windgrams/publish.py), and the per-provider builders in `windgrams/`.
