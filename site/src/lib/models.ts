// Registry of the models the pipeline publishes. Facts here are sourced from
// reference/forecast-model-feeds.md and the builders themselves (windgrams/build_*.py) —
// if this drifts from either, believe those and fix this file.

export interface ModelDef {
  id: string;
  /** This model's own subdirectory under data/ — every model gets one, none live at the bare data/ root. */
  dataPath: string;
  label: string;
  shortLabel: string;
  resolution: string;
  /** ECCC's own designation for this feed, not an editorial judgment. */
  experimental: boolean;
  /** Hours between scheduled runs — used only to flag an unusually stale run. */
  runIntervalHours: number;
  horizonHours: number;
  /** Publishes ensemble percentile spread rather than a windgram profile;
   * excluded from the chart's model picker and comparison overlay. */
  ensemble?: boolean;
}

export const MODELS: ModelDef[] = [
  {
    id: "hrdps-2p5km",
    dataPath: "hrdps-2p5km",
    label: "HRDPS continental 2.5 km",
    shortLabel: "HRDPS 2.5 km",
    resolution: "2.5 km",
    experimental: false,
    runIntervalHours: 6,
    horizonHours: 48,
  },
  {
    id: "hrdps-1km",
    dataPath: "hrdps-1km-west",
    label: "HRDPS West 1 km",
    shortLabel: "HRDPS 1 km",
    resolution: "1 km",
    experimental: true,
    runIntervalHours: 12,
    horizonHours: 48,
  },
  {
    id: "rdps-10km",
    dataPath: "rdps-10km",
    label: "RDPS regional 10 km",
    shortLabel: "RDPS 10 km",
    resolution: "10 km",
    experimental: false,
    runIntervalHours: 6,
    horizonHours: 84,
  },
  {
    id: "gdps-15km",
    dataPath: "gdps-15km",
    label: "GDPS global 15 km",
    shortLabel: "GDPS 15 km",
    resolution: "15 km",
    experimental: false,
    runIntervalHours: 12,
    horizonHours: 240,
  },
  {
    id: "hrrr-conus",
    dataPath: "hrrr-conus",
    label: "HRRR CONUS 3 km",
    shortLabel: "HRRR 3 km",
    resolution: "3 km",
    experimental: false,
    runIntervalHours: 6,
    horizonHours: 48,
  },
  {
    id: "gfs-global",
    dataPath: "gfs-global",
    label: "GFS global 0.25°",
    shortLabel: "GFS 25 km",
    resolution: "25 km",
    experimental: false,
    runIntervalHours: 6,
    horizonHours: 384,
  },
  {
    id: "reps-10km",
    dataPath: "reps-10km",
    label: "REPS regional ensemble 10 km",
    shortLabel: "REPS 10 km",
    resolution: "10 km",
    experimental: false,
    runIntervalHours: 6,
    horizonHours: 72,
    ensemble: true,
  },
];

/** The models whose output is a windgram profile the chart can render. */
export const PROFILE_MODELS: ModelDef[] = MODELS.filter((m) => !m.ensemble);

export function modelById(id: string): ModelDef | undefined {
  return MODELS.find((m) => m.id === id);
}
