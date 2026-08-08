import type { Manifest } from "./api";
import type { ModelDef } from "./models";
import { formatAge, hoursSince, runLabel } from "./time";

export interface FreshnessInfo {
  text: string;
  status: "good" | "warning";
}

/**
 * A run is flagged only when it's more than double the model's own
 * documented cadence old — that's a real anomaly (a run got skipped or the
 * upstream is behind), not a guessed threshold applied uniformly to models
 * that publish at very different rates.
 */
export function freshnessInfo(manifest: Manifest, model: ModelDef, stale: boolean): FreshnessInfo {
  const age = hoursSince(manifest.referenceTime);
  const label = `Run ${runLabel(manifest.referenceTime)} · ${formatAge(age)}`;
  if (stale) {
    return { text: `${label} — still syncing across the CDN, showing the last confirmed run`, status: "warning" };
  }
  if (age > model.runIntervalHours * 2) {
    return {
      text: `${label} — later than expected for a model that usually publishes every ${model.runIntervalHours}h`,
      status: "warning",
    };
  }
  return { text: label, status: "good" };
}
