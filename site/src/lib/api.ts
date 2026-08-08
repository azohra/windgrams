import type { ModelDef } from "./models";

export const DATA_BASE = "https://raw.githubusercontent.com/azohra/windgrams/main";

export interface SiteCatalogEntry {
  slug: string;
  name: string;
  latitude: number;
  longitude: number;
  elevationM: number;
}

export interface ManifestSiteEntry {
  slug: string;
  name: string;
}

export interface Manifest {
  model: string;
  referenceTime: string;
  generatedAt: string;
  firstForecastHour: number;
  lastForecastHour: number;
  forecastHours: number;
  sites: ManifestSiteEntry[];
}

export interface LevelReading {
  heightM: number;
  pressureHpa: number;
  temperatureC: number;
  dewPointDepressionC: number;
  windSpeedKmh: number;
  windDirectionDeg: number;
  lapseCPer1000Ft: number | null;
  cloud: boolean;
}

export interface HourReading {
  validAt: string;
  surfaceTemperatureC: number;
  windSpeedKmh: number;
  windDirectionDeg: number;
  cloudCoverPercent: number;
  precipitationMm: number;
  pressureKpa: number;
  boundaryLayerTopM: number | null;
  cloudBaseM: number | null;
  thermalVelocityMs: number | null;
  usableLiftTopM: number | null;
  levels: LevelReading[];
}

export interface SiteProfile {
  siteId: string;
  siteName: string;
  model: string;
  referenceTime: string;
  generatedAt: string;
  modelElevationM: number;
  siteAltitudeM: number;
  hours: HourReading[];
}

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new HttpError(res.status, url);
  }
  return (await res.json()) as T;
}

export class HttpError extends Error {
  constructor(
    public status: number,
    public url: string,
  ) {
    super(`${status} fetching ${url}`);
  }
}

export function manifestUrl(model: ModelDef): string {
  return `${DATA_BASE}/data/${model.dataPath}/manifest.json`;
}

export function siteProfileUrl(model: ModelDef, slug: string): string {
  return `${DATA_BASE}/data/${model.dataPath}/sites/${slug}.json`;
}

export async function fetchSitesCatalog(): Promise<SiteCatalogEntry[]> {
  return fetchJSON<SiteCatalogEntry[]>(`${DATA_BASE}/sites.json`);
}

export async function fetchManifest(model: ModelDef): Promise<Manifest> {
  return fetchJSON<Manifest>(manifestUrl(model));
}

/** Returns null when the site simply isn't in this model's domain (404). */
export async function fetchSiteProfile(
  model: ModelDef,
  slug: string,
): Promise<SiteProfile | null> {
  try {
    return await fetchJSON<SiteProfile>(siteProfileUrl(model, slug));
  } catch (err) {
    if (err instanceof HttpError && err.status === 404) return null;
    throw err;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface CachedPair {
  manifest: Manifest;
  profile: SiteProfile;
}

function cacheKey(modelId: string, slug: string): string {
  return `windgrams:${modelId}:${slug}`;
}

function cacheGet(key: string): CachedPair | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as CachedPair) : null;
  } catch {
    return null;
  }
}

function cacheSet(key: string, value: CachedPair): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private browsing or quota — the guard degrades to no-cache, not a crash */
  }
}

export interface GuardedFetch {
  manifest: Manifest;
  profile: SiteProfile;
  /**
   * True when the manifest and site file came from two different runs and
   * didn't converge after a retry — see research/static-forecast-pipeline.md's
   * "reference-time skew guard". The caller should show a "still syncing"
   * note rather than silently mixing two runs.
   */
  stale: boolean;
}

/**
 * Fetches a model's manifest and one site's profile together, enforcing the
 * reference-time skew guard the pipeline's docs specify: raw.githubusercontent's
 * ~5-minute cache means a manifest and a site file can briefly disagree about
 * which run is current. On disagreement, retry once, then fall back to the
 * last known-good pair for this model+site rather than render a mismatch.
 * Returns null when the site isn't published for this model at all.
 */
export async function fetchProfileWithSkewGuard(
  model: ModelDef,
  slug: string,
): Promise<GuardedFetch | null> {
  const key = cacheKey(model.id, slug);
  let manifest: Manifest;
  try {
    manifest = await fetchManifest(model);
  } catch (err) {
    // A 404 here means this model hasn't published a first run at all yet —
    // a known, expected state (see the missing data/rdps-10km etc. legs),
    // not a transient failure. Treat it the same as "site not in this
    // model's domain": nothing to show, not an error to surface as one.
    if (err instanceof HttpError && err.status === 404) return null;
    throw err;
  }
  if (!manifest.sites.some((s) => s.slug === slug)) return null;

  const profile = await fetchSiteProfile(model, slug);
  if (!profile) return null;

  if (profile.referenceTime === manifest.referenceTime) {
    cacheSet(key, { manifest, profile });
    return { manifest, profile, stale: false };
  }

  await sleep(1500);
  const [manifest2, profile2] = await Promise.all([
    fetchManifest(model),
    fetchSiteProfile(model, slug),
  ]);
  if (profile2 && manifest2.referenceTime === profile2.referenceTime) {
    cacheSet(key, { manifest: manifest2, profile: profile2 });
    return { manifest: manifest2, profile: profile2, stale: false };
  }

  const cached = cacheGet(key);
  if (cached) return { ...cached, stale: true };
  return { manifest, profile, stale: true };
}
