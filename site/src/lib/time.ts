// All chart/day-tab labels use the founding catalogue's local timezone, per
// research/windgram-derivations.md's flyable-day window (America/Vancouver).
// A future non-Pacific site is a known gap, not a silent bug: it would need
// its own timezone threaded through from sites.json rather than assumed here.
export const DISPLAY_TZ = "America/Vancouver";

const dayKeyFmt = new Intl.DateTimeFormat("en-CA", {
  timeZone: DISPLAY_TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const dayLabelFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: DISPLAY_TZ,
  weekday: "short",
  month: "short",
  day: "numeric",
});

const hourLabelFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: DISPLAY_TZ,
  hour: "numeric",
  hour12: false,
});

export function localDateKey(iso: string): string {
  return dayKeyFmt.format(new Date(iso));
}

export function localDayLabel(iso: string): string {
  return dayLabelFmt.format(new Date(iso));
}

export function localHourLabel(iso: string): string {
  return hourLabelFmt.format(new Date(iso));
}

export function groupByLocalDay<T extends { validAt: string }>(
  hours: T[],
): { dateKey: string; label: string; hours: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const h of hours) {
    const key = localDateKey(h.validAt);
    const arr = groups.get(key);
    if (arr) arr.push(h);
    else groups.set(key, [h]);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([dateKey, hs]) => ({
      dateKey,
      label: localDayLabel(hs[0].validAt),
      hours: hs,
    }));
}

/** Aviation-style run label, e.g. "12Z Aug 7" — matches how pilots already talk about runs. */
export function runLabel(referenceTimeIso: string): string {
  const d = new Date(referenceTimeIso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  return `${hh}Z ${month} ${d.getUTCDate()}`;
}

export function hoursSince(iso: string, now: Date = new Date()): number {
  return (now.getTime() - new Date(iso).getTime()) / 3_600_000;
}

export function formatAge(hours: number): string {
  if (hours < 1) return "under an hour ago";
  const h = Math.round(hours);
  return `${h}h ago`;
}
