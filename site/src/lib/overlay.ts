import type { HourReading } from "./api";
import type { ModelDef } from "./models";
import { svgEl, cssVar } from "./svg";
import { localHourLabel } from "./time";

const MARGIN = { top: 20, right: 110, bottom: 40, left: 60 };
const PLOT_WIDTH = 560;
const PLOT_HEIGHT = 260;
const M_TO_FT = 3.28084;
// How finely the min-max envelope is sampled across the shared time axis —
// coarse enough to be cheap, fine enough that a band edge doesn't look
// polygonal next to the smooth-ish model lines it sits behind.
const ENVELOPE_SAMPLES = 96;

export interface OverlaySeries {
  model: ModelDef;
  color: string;
  hours: HourReading[];
}

type Point = [number, number];

/** Linear interpolation within a series' own time coverage — no
 *  extrapolation past a model's first/last point, so a short-horizon model
 *  (HRDPS's 48 h) doesn't get invented values once GFS's 16-day line runs on
 *  past it. */
function yAt(pts: Point[], atX: number): number | null {
  if (pts.length === 0) return null;
  if (atX < pts[0][0] || atX > pts[pts.length - 1][0]) return null;
  for (let i = 0; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[i + 1];
    if (atX > x1) continue;
    if (x1 === x0) return y0;
    return y0 + (y1 - y0) * ((atX - x0) / (x1 - x0));
  }
  return pts[pts.length - 1][1];
}

export function renderOverlaySVG(series: OverlaySeries[]): SVGSVGElement {
  const width = MARGIN.left + MARGIN.right + PLOT_WIDTH;
  const height = MARGIN.top + PLOT_HEIGHT + MARGIN.bottom;

  const allHours = series.flatMap((s) => s.hours);
  const times = allHours.map((h) => new Date(h.validAt).getTime());
  let tMin = Math.min(...times);
  let tMax = Math.max(...times);
  if (!Number.isFinite(tMin) || tMin === tMax) {
    tMin = tMin - 3_600_000;
    tMax = tMax + 3_600_000;
  }

  let floor = Math.min(...series.map((s) => s.hours[0]?.boundaryLayerTopM ?? Infinity), Infinity);
  let top = 0;
  for (const s of series) {
    for (const h of s.hours) {
      if (h.boundaryLayerTopM != null) {
        floor = Math.min(floor, h.boundaryLayerTopM);
        top = Math.max(top, h.boundaryLayerTopM);
      }
      if (h.usableLiftTopM != null) top = Math.max(top, h.usableLiftTopM);
    }
  }
  if (!Number.isFinite(floor)) floor = 0;
  if (top <= floor) top = floor + 500;
  floor = Math.max(0, floor - (top - floor) * 0.15);
  top = top * 1.08;

  const x = (t: number) => MARGIN.left + ((t - tMin) / (tMax - tMin)) * PLOT_WIDTH;
  const y = (m: number) => MARGIN.top + PLOT_HEIGHT * (1 - (m - floor) / (top - floor));

  const rule = cssVar("--rule", "#2b3739");
  const inkMute = cssVar("--ink-mute", "#77878a");
  const inkSoft = cssVar("--ink-soft", "#b7c2c0");
  const surface = cssVar("--surface", "#1b2426");

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label":
      "Overlay of boundary layer top (dashed) and usable lift top (solid) across the published models for this site and day, one colour per model, with a translucent band showing the min-to-max spread of usable lift top wherever two or more models cover that hour — a thick band means the models disagree, a thin band means they agree, and no band means too few models overlap there to compare.",
    style: "width:100%;height:auto;display:block;",
  });

  svg.appendChild(
    svgEl("rect", {
      x: MARGIN.left,
      y: MARGIN.top,
      width: PLOT_WIDTH,
      height: PLOT_HEIGHT,
      fill: surface,
      stroke: rule,
    }),
  );

  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const m = floor + ((top - floor) * t) / ticks;
    const yy = y(m);
    svg.appendChild(
      svgEl("line", { x1: MARGIN.left, y1: yy, x2: MARGIN.left + PLOT_WIDTH, y2: yy, stroke: rule }),
    );
    svg.appendChild(
      svgEl("text", { x: MARGIN.left - 8, y: yy + 3, "text-anchor": "end", "font-size": "10.5", fill: inkMute }, [
        `${Math.round(m)}m`,
      ]),
    );
    svg.appendChild(
      svgEl("text", { x: MARGIN.left + PLOT_WIDTH + 8, y: yy + 3, "font-size": "10.5", fill: inkMute }, [
        `${Math.round(m * M_TO_FT)}ft`,
      ]),
    );
  }

  // hour ticks across the shared time axis, from the series with the most points
  const dense = series.reduce((a, b) => (a.hours.length >= b.hours.length ? a : b), series[0]);
  for (const h of dense?.hours ?? []) {
    const xx = x(new Date(h.validAt).getTime());
    svg.appendChild(
      svgEl(
        "text",
        {
          x: xx,
          y: MARGIN.top + PLOT_HEIGHT + 16,
          "text-anchor": "middle",
          "font-size": "10.5",
          "font-family": "ui-monospace, monospace",
          fill: inkMute,
        },
        [localHourLabel(h.validAt)],
      ),
    );
  }

  function polyline(points: Point[], color: string, dashed: boolean, widthPx: number) {
    if (points.length < 2) return;
    const attrs: Record<string, string | number> = {
      points: points.map(([px, py]) => `${px},${py}`).join(" "),
      fill: "none",
      stroke: color,
      "stroke-width": widthPx,
    };
    if (dashed) attrs["stroke-dasharray"] = "5,4";
    svg.appendChild(svgEl("polyline", attrs));
  }

  // Precompute every series' pixel points once — the envelope band needs
  // liftPts from ALL series before anything is drawn (it goes behind the
  // lines), and the per-model draw pass below reuses the same points.
  const prepared = series.map((s) => {
    const sorted = [...s.hours].sort((a, b) => new Date(a.validAt).getTime() - new Date(b.validAt).getTime());
    const blPts: Point[] = sorted
      .filter((h) => h.boundaryLayerTopM != null)
      .map((h) => [x(new Date(h.validAt).getTime()), y(h.boundaryLayerTopM as number)]);
    const liftPts: Point[] = sorted
      .filter((h) => h.usableLiftTopM != null)
      .map((h) => [x(new Date(h.validAt).getTime()), y(h.usableLiftTopM as number)]);
    return { s, blPts, liftPts };
  });

  // --- disagreement, made visible: a min-max envelope of usable lift top ---
  // across models, drawn BEHIND the coloured lines. This is the literal
  // point of the multi-model overlay: where the band is thin, the models
  // agree; where it's thick, they diverge. Sampled at a
  // fixed cadence across the shared time axis and linearly interpolated per
  // model within that model's own coverage — no extrapolation past a short-horizon
  // model's last hour.
  //
  // Absence of a band is deliberately ambiguous between two different
  // truths — "models agree exactly" and "fewer than two models have a
  // reading here" (e.g. before a 3-hourly model's first published hour) —
  // and the >=2 gate below can't tell those apart from geometry alone. That
  // ambiguity is named in the legend text rather than hidden, so a gap never
  // reads as false confidence.
  const bandPaths: string[] = [];
  {
    type BandPoint = { x: number; minY: number; maxY: number };
    let run: BandPoint[] = [];
    const flush = () => {
      if (run.length >= 2) {
        const upper = run.map((p) => `${p.x},${p.minY}`).join(" L");
        const lower = [...run]
          .reverse()
          .map((p) => `${p.x},${p.maxY}`)
          .join(" L");
        bandPaths.push(`M${upper} L${lower} Z`);
      }
      run = [];
    };
    for (let i = 0; i <= ENVELOPE_SAMPLES; i++) {
      const sampleX = MARGIN.left + (PLOT_WIDTH * i) / ENVELOPE_SAMPLES;
      const ys: number[] = [];
      for (const { liftPts } of prepared) {
        const v = yAt(liftPts, sampleX);
        if (v != null) ys.push(v);
      }
      // A band needs at least two models covering this instant — a single
      // model has nothing to disagree with.
      if (ys.length >= 2) {
        run.push({ x: sampleX, minY: Math.min(...ys), maxY: Math.max(...ys) });
      } else {
        flush();
      }
    }
    flush();
  }
  for (const d of bandPaths) {
    svg.appendChild(
      svgEl("path", {
        d,
        fill: inkSoft,
        "fill-opacity": "0.16",
        stroke: inkSoft,
        "stroke-opacity": "0.3",
        "stroke-width": "1",
      }),
    );
  }
  if (bandPaths.length) {
    svg.appendChild(
      svgEl("rect", {
        x: MARGIN.left + 4,
        y: MARGIN.top + 8,
        width: 14,
        height: 10,
        fill: inkSoft,
        "fill-opacity": "0.28",
        stroke: inkSoft,
        "stroke-opacity": "0.4",
      }),
    );
    svg.appendChild(
      svgEl(
        "text",
        { x: MARGIN.left + 22, y: MARGIN.top + 16, "font-size": "10.5", fill: inkMute },
        ["model spread (min–max usable lift top, where 2+ models cover the hour)"],
      ),
    );
  }

  const pendingLabels: { x: number; y: number; color: string; text: string }[] = [];

  for (const { s, blPts, liftPts } of prepared) {
    polyline(blPts, s.color, true, 1.4);
    polyline(liftPts, s.color, false, 2.2);

    const labelPts = liftPts.length ? liftPts : blPts;
    if (labelPts.length) {
      const [lx, ly] = labelPts[labelPts.length - 1];
      pendingLabels.push({ x: lx + 8, y: ly + 3, color: s.color, text: s.model.shortLabel });
    }
  }

  // Direct end-labels can land within a few px of each other when two
  // models converge (HRDPS 2.5 km and 1 km often do near dusk) — stack them
  // vertically with a minimum gap instead of letting them overlap.
  const MIN_GAP = 13;
  pendingLabels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < pendingLabels.length; i++) {
    if (pendingLabels[i].y - pendingLabels[i - 1].y < MIN_GAP) {
      pendingLabels[i].y = pendingLabels[i - 1].y + MIN_GAP;
    }
  }
  for (const label of pendingLabels) {
    svg.appendChild(
      svgEl(
        "text",
        { x: label.x, y: label.y, "font-size": "11", "font-weight": "600", fill: label.color },
        [label.text],
      ),
    );
  }

  return svg;
}
