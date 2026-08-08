import type { HourReading, LevelReading } from "./api";
import { svgEl, cssVar } from "./svg";
import { localHourLabel } from "./time";

const METRIC_TOP = 20;
const METRIC_BAND_HEIGHT = 25;
const METRIC_BAND_GAP = 5;
const PROFILE_TOP = 148;
const MARGIN_LEFT = 60;
const MARGIN_RIGHT = 60;
const COL_WIDTH = 44;
const PLOT_HEIGHT = 340;
const M_TO_FT = 3.28084;
const WIND_BARB_SCALE = 0.85;
const FIELD_COLUMNS_PER_HOUR = 24;
const FIELD_ROW_HEIGHT = 1.5;

// Legend geometry, anchored to plotBottom (= PROFILE_TOP + PLOT_HEIGHT) so the
// bottom margin and the actual drawing offsets can never drift apart.
const HOUR_LABEL_DY = 18;
const SERIES_LEGEND_DY = 42;
const WIND_LEGEND_DY = 64;
const STAB_SWATCH_DY = 90;
const STAB_SWATCH_H = 16;
const STAB_THRESHOLD_DY = STAB_SWATCH_DY + STAB_SWATCH_H + 12;
const STAB_GROUP_DY = STAB_THRESHOLD_DY + 14;
const BOTTOM_PADDING = 14;
const MARGIN_BOTTOM = STAB_GROUP_DY + BOTTOM_PADDING;
// A narrow day (as few as 5 flyable hours) draws fewer columns than the
// legend needs to lay out its rows — widen the canvas rather than clip it.
const LEGEND_MIN_WIDTH = 560;

export interface WindgramOptions {
  hours: HourReading[];
  modelElevationM: number;
  siteAltitudeM: number;
}

// lapseCPer1000Ft is (T_next - T)/(z_next - z) x 304.8 — literally dT/dz, not
// the conventional (sign-flipped) "lapse rate". So it reads NEGATIVE in a
// normal, unstable atmosphere (temperature falling with height, near -3.0
// at the dry adiabatic rate) and POSITIVE only in an inversion (temperature
// rising with height). Confirmed against real site output before wiring
// this up — do not "simplify" the sign back to the intuitive-looking one.
//
// Stability classing and thresholds mirror the sibling renderer. The field
// interpolates the underlying lapse rate before classification, preserving
// discrete meanings without drawing one rectangular block per source level.
interface StabilityClass {
  key: string;
  maxLapse: number;
  cssVar: string;
  fallback: string;
  label: string;
}

const STABILITY_CLASSES: StabilityClass[] = [
  { key: "very-unstable", maxLapse: -3, cssVar: "--stab-very-unstable", fallback: "#b3543a", label: "Very unstable" },
  { key: "unstable", maxLapse: -2.5, cssVar: "--stab-unstable", fallback: "#c17847", label: "Unstable" },
  {
    key: "conditional-strong",
    maxLapse: -2,
    cssVar: "--stab-conditional-strong",
    fallback: "#c99b5f",
    label: "Strong conditional",
  },
  { key: "conditional", maxLapse: -1.5, cssVar: "--stab-conditional", fallback: "#b7a37c", label: "Conditional" },
  { key: "near-neutral", maxLapse: -1.2, cssVar: "--stab-near-neutral", fallback: "#93958a", label: "Near neutral" },
  { key: "stable", maxLapse: 0, cssVar: "--stab-stable", fallback: "#6c8598", label: "Stable" },
  { key: "inverted", maxLapse: 0.5, cssVar: "--stab-inverted", fallback: "#52697c", label: "Inverted" },
  {
    key: "strong-inversion",
    maxLapse: Number.POSITIVE_INFINITY,
    cssVar: "--stab-strong-inversion",
    fallback: "#3a4b58",
    label: "Strong inversion",
  },
];

// Legend grouping — coarser semantic bands spanning several classes each,
// so the legend reads as a story ("unstable... to inverted") instead of an
// unlabelled row of eight swatches.
const STABILITY_GROUPS: { label: string; keys: string[] }[] = [
  { label: "Unstable", keys: ["very-unstable", "unstable"] },
  { label: "Conditional instability", keys: ["conditional-strong", "conditional", "near-neutral"] },
  { label: "Stable", keys: ["stable"] },
  { label: "Inverted", keys: ["inverted", "strong-inversion"] },
];

function stabilityEntry(lapse: number): StabilityClass {
  return STABILITY_CLASSES.find((c) => lapse <= c.maxLapse) ?? STABILITY_CLASSES[STABILITY_CLASSES.length - 1];
}

function heightDomain(hours: HourReading[], floor: number, siteAltitudeM: number): [number, number] {
  let top = Math.max(floor + 800, siteAltitudeM);
  for (const h of hours) {
    if (h.cloudBaseM && h.cloudBaseM > top) top = h.cloudBaseM;
    if (h.usableLiftTopM && h.usableLiftTopM > top) top = h.usableLiftTopM;
    for (const lvl of h.levels) {
      if (lvl.heightM > top) top = lvl.heightM;
    }
  }
  return [floor, top * 1.04];
}

function short(value: number) {
  return Number(value.toFixed(2));
}

type PlotPoint = { x: number; y: number };

function curvedPath(points: PlotPoint[]) {
  if (points.length === 0) return "";
  if (points.length === 1) return `M${short(points[0].x)},${short(points[0].y)}`;
  if (points.length === 2) {
    return `M${short(points[0].x)},${short(points[0].y)} L${short(points[1].x)},${short(points[1].y)}`;
  }
  let result = `M${short(points[0].x)},${short(points[0].y)}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const previous = points[Math.max(0, index - 1)];
    const current = points[index];
    const next = points[index + 1];
    const following = points[Math.min(points.length - 1, index + 2)];
    const firstX = current.x + (next.x - previous.x) / 6;
    const firstY = current.y + (next.y - previous.y) / 6;
    const secondX = next.x - (following.x - current.x) / 6;
    const secondY = next.y - (following.y - current.y) / 6;
    result += ` C${short(firstX)},${short(firstY)} ${short(secondX)},${short(secondY)} ${short(next.x)},${short(next.y)}`;
  }
  return result;
}

function segmentedPath(
  hours: HourReading[],
  xAt: (index: number) => number,
  yAt: (value: number) => number,
  valueAt: (hour: HourReading) => number | null,
) {
  const paths: string[] = [];
  let segment: PlotPoint[] = [];
  for (let index = 0; index <= hours.length; index += 1) {
    const reading = index < hours.length ? valueAt(hours[index]) : null;
    if (reading != null && Number.isFinite(reading)) {
      segment.push({ x: xAt(index), y: yAt(reading) });
      continue;
    }
    if (segment.length > 0) paths.push(curvedPath(segment));
    segment = [];
  }
  return paths.join(" ");
}

function lapseNodesForHour(hour: HourReading, floor: number) {
  const levels = [...hour.levels].sort((a, b) => a.heightM - b.heightM);
  const first = levels[0];
  if (!first || first.heightM <= floor) return [];

  const surfaceLapse =
    ((first.temperatureC - hour.surfaceTemperatureC) / (first.heightM - floor)) * 304.8;
  let lastLapse = surfaceLapse;
  const nodes = [{ altitudeM: floor, value: surfaceLapse }];
  for (const level of levels) {
    if (level.lapseCPer1000Ft != null) lastLapse = level.lapseCPer1000Ft;
    nodes.push({ altitudeM: level.heightM, value: lastLapse });
  }
  return nodes;
}

function dewPointNodesForHour(hour: HourReading, floor: number) {
  const levels = [...hour.levels].sort((a, b) => a.heightM - b.heightM);
  const first = levels[0];
  if (!first) return [];
  return [
    { altitudeM: floor, value: first.dewPointDepressionC },
    ...levels.map((level) => ({
      altitudeM: level.heightM,
      value: level.dewPointDepressionC,
    })),
  ];
}

function interpolateVertical(
  nodes: Array<{ altitudeM: number; value: number }>,
  altitudeM: number,
) {
  if (
    nodes.length === 0 ||
    altitudeM < nodes[0].altitudeM ||
    altitudeM > nodes[nodes.length - 1].altitudeM
  ) {
    return null;
  }
  for (let index = 0; index < nodes.length - 1; index += 1) {
    const lower = nodes[index];
    const upper = nodes[index + 1];
    if (altitudeM > upper.altitudeM) continue;
    const fraction =
      (altitudeM - lower.altitudeM) / Math.max(0.001, upper.altitudeM - lower.altitudeM);
    return lower.value + (upper.value - lower.value) * fraction;
  }
  return nodes.at(-1)?.value ?? null;
}

function sampledFieldPaths({
  classify,
  floor,
  hours,
  left,
  nodesByHour,
  plotTop,
  plotBottom,
  plotWidth,
  top,
}: {
  classify: (value: number) => string | null;
  floor: number;
  hours: HourReading[];
  left: number;
  nodesByHour: Array<Array<{ altitudeM: number; value: number }>>;
  plotTop: number;
  plotBottom: number;
  plotWidth: number;
  top: number;
}) {
  const valueAt = (hourIndex: number, altitudeM: number) => {
    const nodes = nodesByHour[hourIndex];
    return interpolateVertical(
      nodes,
      Math.min(altitudeM, nodes.at(-1)?.altitudeM ?? altitudeM),
    );
  };
  const valueAcrossTime = (timePosition: number, altitudeM: number) => {
    const lowerIndex = Math.floor(timePosition);
    const upperIndex = Math.min(hours.length - 1, Math.ceil(timePosition));
    const lower = valueAt(lowerIndex, altitudeM);
    const upper = valueAt(upperIndex, altitudeM);
    if (lower == null) return upper;
    if (upper == null) return lower;
    if (lowerIndex === upperIndex) return lower;
    return lower + (upper - lower) * (timePosition - lowerIndex);
  };

  const columns = Math.max(1, hours.length * FIELD_COLUMNS_PER_HOUR);
  const rows = Math.ceil((plotBottom - plotTop) / FIELD_ROW_HEIGHT);
  const columnWidth = plotWidth / columns;
  const rowHeight = (plotBottom - plotTop) / rows;
  const chunks = new Map<string, string[]>();

  for (let row = 0; row < rows; row += 1) {
    const altitudeM = top - ((row + 0.5) / rows) * (top - floor);
    let activeClass: string | null = null;
    let runStart = 0;
    for (let column = 0; column <= columns; column += 1) {
      let nextClass: string | null = null;
      if (column < columns) {
        const timePosition = Math.min(
          hours.length - 1,
          Math.max(0, ((column + 0.5) / columns) * hours.length - 0.5),
        );
        const value = valueAcrossTime(timePosition, altitudeM);
        nextClass = value == null ? null : classify(value);
      }
      if (nextClass === activeClass) continue;
      if (activeClass != null) {
        const runWidth = (column - runStart) * columnWidth;
        const path = `M${short(left + runStart * columnWidth)} ${short(
          plotTop + row * rowHeight,
        )}h${short(runWidth)}v${short(rowHeight + 0.35)}h-${short(runWidth)}Z`;
        chunks.set(activeClass, [...(chunks.get(activeClass) ?? []), path]);
      }
      activeClass = nextClass;
      runStart = column;
    }
  }

  return Object.fromEntries(
    [...chunks].map(([className, paths]) => [className, paths.join("")]),
  );
}

function sampledStabilityPaths(options: {
  floor: number;
  hours: HourReading[];
  left: number;
  plotTop: number;
  plotBottom: number;
  plotWidth: number;
  top: number;
}) {
  return sampledFieldPaths({
    ...options,
    classify: (value) => stabilityEntry(value).key,
    nodesByHour: options.hours.map((hour) => lapseNodesForHour(hour, options.floor)),
  });
}

function sampledCondensationPath(options: {
  floor: number;
  hours: HourReading[];
  left: number;
  plotTop: number;
  plotBottom: number;
  plotWidth: number;
  top: number;
}) {
  return sampledFieldPaths({
    ...options,
    classify: (value) => (value < 0.5 ? "cloud" : null),
    nodesByHour: options.hours.map((hour) => dewPointNodesForHour(hour, options.floor)),
  }).cloud;
}

// The shaft points toward the direction the wind is coming FROM. This
// renderer follows canadarasp and the operational acrophobia chart: feather
// values are 5, 10, and 50 km/h. Many aviation charts use the same shapes for
// knots, so the printed unit is part of the symbol key.
function windBarbGeometry(speedKmh: number) {
  const rounded = Math.max(0, Math.round(speedKmh / 5) * 5);
  const pennants = Math.floor(rounded / 50);
  const afterPennants = rounded - pennants * 50;
  const fullBarbs = Math.floor(afterPennants / 10);
  const halfBarb = afterPennants - fullBarbs * 10 >= 5;
  return { calm: speedKmh < 2.5, pennants, fullBarbs, halfBarb };
}

function windBarbPaths(speedKmh: number): { shaft: string; pennants: string[] } {
  const { pennants, fullBarbs, halfBarb } = windBarbGeometry(speedKmh);
  const pennantHeight = 5;
  const pennantSpacing = 7;
  const barbSpacing = 3.8;
  const pennantPaths: string[] = [];
  for (let i = 0; i < pennants; i++) {
    const barbY = -16 + i * pennantSpacing;
    pennantPaths.push(`M0 ${barbY} L9.5 ${barbY + pennantHeight} L0 ${barbY + pennantHeight} Z`);
  }
  const featherOffset = pennants * pennantSpacing + (pennants > 0 ? 1.5 : 0);
  const featherPaths: string[] = [];
  for (let i = 0; i < fullBarbs; i++) {
    const barbY = -16 + featherOffset + i * barbSpacing;
    featherPaths.push(`M0 ${barbY} L8 ${barbY + 4.4}`);
  }
  if (halfBarb) {
    const halfGap = pennants === 0 && fullBarbs === 0 ? 2.2 : 0;
    const barbY = -16 + featherOffset + fullBarbs * barbSpacing + halfGap;
    featherPaths.push(`M0 ${barbY} L4.5 ${barbY + 2.4}`);
  }
  return { shaft: [`M0 5 L0 -16`, ...featherPaths].join(" "), pennants: pennantPaths };
}

/** A dark halo drawn under the ink-coloured barb/glyph keeps it legible over
 *  any of the eight (fairly light) stability fills — ink-on-sand or
 *  ink-on-lavender otherwise reads as barely-there. */
function windBarb(
  cx: number,
  cy: number,
  speedKmh: number,
  directionDeg: number,
  color: string,
  halo: string,
  scale = 1,
): SVGGElement {
  const { calm } = windBarbGeometry(speedKmh);
  const g = svgEl("g", {});
  if (calm) {
    g.appendChild(svgEl("circle", { cx, cy, r: 3.6 * scale, fill: "none", stroke: halo, "stroke-width": 2.4 }));
    g.appendChild(svgEl("circle", { cx, cy, r: 3.6 * scale, fill: "none", stroke: color, "stroke-width": 1.1 }));
    return g;
  }
  const { shaft, pennants } = windBarbPaths(speedKmh);
  g.setAttribute("transform", `translate(${cx} ${cy}) rotate(${directionDeg}) scale(${scale})`);
  g.appendChild(
    svgEl("path", { d: shaft, stroke: halo, "stroke-width": 2.6, fill: "none", "stroke-linecap": "round" }),
  );
  for (const p of pennants) g.appendChild(svgEl("path", { d: p, fill: halo, stroke: halo, "stroke-width": 1 }));
  g.appendChild(
    svgEl("path", { d: shaft, stroke: color, "stroke-width": 1.3, fill: "none", "stroke-linecap": "round" }),
  );
  for (const p of pennants) g.appendChild(svgEl("path", { d: p, fill: color, stroke: color, "stroke-width": 1 }));
  return g;
}

// --- glyph markers: the sport-specific reinforcement the dash/dot lines ---
// alone couldn't give — a small wing at usable-lift-top, a small cloud at
// cloud base, both haloed the same way as the wind barbs.
function wingMarker(cx: number, cy: number, color: string, halo: string, scale = 1): SVGGElement {
  const d = "M-8 2Q0-6.5 8 2Q0-1.5-8 2Z";
  const g = svgEl("g", { transform: `translate(${cx} ${cy}) scale(${scale})` });
  g.appendChild(svgEl("path", { d, fill: halo, stroke: halo, "stroke-width": 2.4 }));
  g.appendChild(svgEl("path", { d, fill: color, stroke: color, "stroke-width": 0.6 }));
  return g;
}

function cloudMarker(cx: number, cy: number, color: string, halo: string, scale = 1): SVGGElement {
  const d = "M-7 2.5h14a3.2 3.2 0 0 0-.6-6.3A5 5 0 0 0-3-5a4 4 0 0 0-4 4 3 3 0 0 0 0 3.5Z";
  const g = svgEl("g", { transform: `translate(${cx} ${cy}) scale(${scale})` });
  g.appendChild(svgEl("path", { d, fill: halo, stroke: halo, "stroke-width": 2.4 }));
  g.appendChild(svgEl("path", { d, fill: color, stroke: color, "stroke-width": 0.6 }));
  return g;
}

function haloedPath(
  svg: SVGSVGElement,
  d: string,
  color: string,
  halo: string,
  widthPx: number,
  dash?: string,
) {
  if (!d) return;
  const base: Record<string, string | number> = {
    d,
    fill: "none",
    stroke: halo,
    "stroke-width": widthPx + 1.8,
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  };
  if (dash) base["stroke-dasharray"] = dash;
  svg.appendChild(svgEl("path", base));
  const top: Record<string, string | number> = {
    d,
    fill: "none",
    stroke: color,
    "stroke-width": widthPx,
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  };
  if (dash) top["stroke-dasharray"] = dash;
  svg.appendChild(svgEl("path", top));
}

function temperatureCrossing(hour: HourReading, floor: number, temperatureC: number) {
  const points = [
    { heightM: floor, temperatureC: hour.surfaceTemperatureC },
    ...hour.levels,
  ].sort((a, b) => a.heightM - b.heightM);
  for (let index = 0; index < points.length - 1; index += 1) {
    const lower = points[index];
    const upper = points[index + 1];
    if ((temperatureC - lower.temperatureC) * (temperatureC - upper.temperatureC) > 0) continue;
    const span = upper.temperatureC - lower.temperatureC;
    if (span === 0) continue;
    return (
      lower.heightM +
      ((temperatureC - lower.temperatureC) / span) * (upper.heightM - lower.heightM)
    );
  }
  return null;
}

let chartInstance = 0;

export function renderWindgramSVG(opts: WindgramOptions): SVGSVGElement {
  const { hours, modelElevationM, siteAltitudeM } = opts;
  const [floor, top] = heightDomain(hours, modelElevationM, siteAltitudeM);
  const plotWidth = COL_WIDTH * Math.max(hours.length, 1);
  const width = Math.max(MARGIN_LEFT + MARGIN_RIGHT + plotWidth, LEGEND_MIN_WIDTH);
  const plotBottom = PROFILE_TOP + PLOT_HEIGHT;
  const height = plotBottom + MARGIN_BOTTOM;

  const y = (m: number) => PROFILE_TOP + PLOT_HEIGHT * (1 - (m - floor) / (top - floor));
  const x = (i: number) => MARGIN_LEFT + i * COL_WIDTH;
  const xCenter = (i: number) => x(i) + COL_WIDTH / 2;

  const ink = cssVar("--ink", "#f2f1ec");
  const inkSoft = cssVar("--ink-soft", "#b7c2c0");
  const inkMute = cssVar("--ink-mute", "#77878a");
  const rule = cssVar("--rule", "#2b3739");
  const surface = cssVar("--surface", "#fffdf8");
  const pressureColor = cssVar("--chart-pressure", "#963f36");
  const rainColor = cssVar("--chart-rain", "#207a83");
  const cloudColor = cssVar("--chart-cloud", "#5b6969");
  const liftColor = cssVar("--chart-lift", "#9a7500");
  const usableColor = cssVar("--chart-usable", "#2179ad");
  const boundaryColor = cssVar("--chart-boundary", "#a46b10");
  const windColor = cssVar("--chart-wind", "#355963");
  const freezingColor = cssVar("--chart-freezing", "#2b748f");
  const halo = surface;
  const selectedIndex = hours.reduce(
    (best, hour, index) =>
      (hour.thermalVelocityMs ?? 0) > (hours[best]?.thermalVelocityMs ?? 0) ? index : best,
    0,
  );
  const selectedX = xCenter(selectedIndex);
  const cloudPatternId = `windgram-cloud-${chartInstance++}`;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label":
      "Windgram with pressure, rain, cloud cover and thermal-lift strips above a time-height stability field; cloud base, usable lift, boundary layer, launch elevation, isotherms, condensation and winds aloft are drawn over the profile.",
    style: `width:${width}px;max-width:none;height:auto;display:block;margin:0 auto;`,
  });

  const defs = svgEl("defs");
  const cloudPattern = svgEl("pattern", {
    id: cloudPatternId,
    width: 7,
    height: 7,
    patternUnits: "userSpaceOnUse",
    patternTransform: "rotate(45)",
  });
  cloudPattern.appendChild(
    svgEl("line", { x1: 0, y1: 0, x2: 0, y2: 7, stroke: inkSoft, "stroke-width": 1.2 }),
  );
  defs.appendChild(cloudPattern);
  svg.appendChild(defs);

  const metricBands = [
    {
      label: "Pressure",
      unit: "kPa",
      values: hours.map((hour) => hour.pressureKpa),
      minimum: Math.floor(Math.min(...hours.map((hour) => hour.pressureKpa)) * 10) / 10,
      maximum: Math.ceil(Math.max(...hours.map((hour) => hour.pressureKpa)) * 10) / 10,
      color: pressureColor,
    },
    {
      label: "Precip",
      unit: "mm",
      values: hours.map((hour) => hour.precipitationMm),
      minimum: 0,
      maximum: Math.max(0.5, ...hours.map((hour) => hour.precipitationMm)),
      color: rainColor,
    },
    {
      label: "Cloud",
      unit: "%",
      values: hours.map((hour) => hour.cloudCoverPercent),
      minimum: 0,
      maximum: 100,
      color: cloudColor,
    },
    {
      label: "w*",
      unit: "m/s",
      values: hours.map((hour) => hour.thermalVelocityMs ?? 0),
      minimum: 0,
      maximum: Math.max(3, ...hours.map((hour) => hour.thermalVelocityMs ?? 0)),
      color: liftColor,
    },
  ];

  metricBands.forEach((band, bandIndex) => {
    const bandTop = METRIC_TOP + bandIndex * (METRIC_BAND_HEIGHT + METRIC_BAND_GAP);
    const bandBottom = bandTop + METRIC_BAND_HEIGHT;
    const range = Math.max(0.001, band.maximum - band.minimum);
    const points = band.values.map((value, index) => ({
      x: xCenter(index),
      y: bandBottom - ((value - band.minimum) / range) * METRIC_BAND_HEIGHT,
    }));
    const line = curvedPath(points);
    const area = `${line} L${short(xCenter(hours.length - 1))},${bandBottom} L${short(xCenter(0))},${bandBottom} Z`;
    svg.appendChild(
      svgEl("rect", {
        x: MARGIN_LEFT,
        y: bandTop,
        width: plotWidth,
        height: METRIC_BAND_HEIGHT,
        fill: "#f2f4f1",
        stroke: rule,
        "stroke-width": 0.7,
      }),
    );
    svg.appendChild(
      svgEl("line", {
        x1: MARGIN_LEFT,
        y1: bandTop + METRIC_BAND_HEIGHT / 2,
        x2: MARGIN_LEFT + plotWidth,
        y2: bandTop + METRIC_BAND_HEIGHT / 2,
        stroke: rule,
        "stroke-width": 0.6,
        "stroke-dasharray": "2 4",
        opacity: 0.45,
      }),
    );
    svg.appendChild(svgEl("path", { d: area, fill: band.color, opacity: 0.3 }));
    svg.appendChild(
      svgEl("path", {
        d: line,
        fill: "none",
        stroke: band.color,
        "stroke-width": 1.7,
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
      }),
    );
    svg.appendChild(
      svgEl(
        "text",
        { x: MARGIN_LEFT - 8, y: bandTop + 11, "text-anchor": "end", "font-size": 10.5, "font-weight": 700, fill: ink },
        [band.label],
      ),
    );
    svg.appendChild(
      svgEl(
        "text",
        { x: MARGIN_LEFT - 8, y: bandTop + 22, "text-anchor": "end", "font-size": 9.5, fill: inkMute },
        [band.unit],
      ),
    );
  });

  // chart surface + hairline frame
  svg.appendChild(
    svgEl("rect", {
      x: MARGIN_LEFT,
      y: PROFILE_TOP,
      width: plotWidth,
      height: PLOT_HEIGHT,
      fill: surface,
      stroke: rule,
    }),
  );

  // Sample the continuous time-height lapse field, then classify it. The
  // meanings stay discrete while the geometry follows the atmosphere instead
  // of exposing the source hour/pressure-level rectangles.
  const stabilityPaths = sampledStabilityPaths({
    floor,
    hours,
    left: MARGIN_LEFT,
    plotTop: PROFILE_TOP,
    plotBottom,
    plotWidth,
    top,
  });
  for (const entry of STABILITY_CLASSES) {
    const d = stabilityPaths[entry.key];
    if (!d) continue;
    svg.appendChild(
      svgEl("path", {
        d,
        fill: cssVar(entry.cssVar, entry.fallback),
        class: `stability ${entry.key}`,
      }),
    );
  }

  const condensationPath = sampledCondensationPath({
    floor,
    hours,
    left: MARGIN_LEFT,
    plotTop: PROFILE_TOP,
    plotBottom,
    plotWidth,
    top,
  });
  if (condensationPath) {
    svg.appendChild(svgEl("path", { d: condensationPath, fill: `url(#${cloudPatternId})` }));
  }

  svg.appendChild(
    svgEl("rect", {
      x: x(selectedIndex),
      y: METRIC_TOP,
      width: COL_WIDTH,
      height: plotBottom - METRIC_TOP,
      fill: cssVar("--accent", "#913b0c"),
      opacity: 0.05,
    }),
  );
  svg.appendChild(
    svgEl("line", {
      x1: selectedX,
      x2: selectedX,
      y1: METRIC_TOP,
      y2: plotBottom,
      stroke: cssVar("--accent", "#913b0c"),
      "stroke-width": 1,
      "stroke-dasharray": "3 4",
    }),
  );

  // gridlines + axis ticks (metres left, feet right)
  const ticks = 5;
  for (let t = 0; t <= ticks; t++) {
    const m = floor + ((top - floor) * t) / ticks;
    const yy = y(m);
    svg.appendChild(
      svgEl("line", {
        x1: MARGIN_LEFT,
        y1: yy,
        x2: MARGIN_LEFT + plotWidth,
        y2: yy,
        stroke: rule,
        "stroke-width": "1",
      }),
    );
    svg.appendChild(
      svgEl(
        "text",
        { x: MARGIN_LEFT - 8, y: yy + 3, "text-anchor": "end", "font-size": "10.5", fill: inkMute },
        [`${Math.round(m)}m`],
      ),
    );
    svg.appendChild(
      svgEl(
        "text",
        { x: MARGIN_LEFT + plotWidth + 8, y: yy + 3, "font-size": "10.5", fill: inkMute },
        [`${Math.round(m * M_TO_FT)}ft`],
      ),
    );
  }

  // hour labels
  hours.forEach((h, i) => {
    if (i % 2 === 0) {
      svg.appendChild(
        svgEl("line", {
          x1: xCenter(i),
          x2: xCenter(i),
          y1: PROFILE_TOP,
          y2: plotBottom,
          stroke: ink,
          "stroke-width": 0.6,
          opacity: 0.15,
        }),
      );
    }
    svg.appendChild(
      svgEl(
        "text",
        {
          x: xCenter(i),
          y: plotBottom + HOUR_LABEL_DY,
          "text-anchor": "middle",
          "font-size": "11",
          "font-family": "ui-monospace, monospace",
          fill: inkMute,
        },
        [localHourLabel(h.validAt)],
      ),
    );
  });

  if (siteAltitudeM >= floor && siteAltitudeM <= top) {
    const launchY = y(siteAltitudeM);
    svg.appendChild(
      svgEl("line", {
        x1: MARGIN_LEFT,
        x2: MARGIN_LEFT + plotWidth,
        y1: launchY,
        y2: launchY,
        stroke: ink,
        "stroke-width": 1,
        "stroke-dasharray": "2 4",
        opacity: 0.68,
      }),
    );
    svg.appendChild(
      svgEl(
        "text",
        {
          x: MARGIN_LEFT + 7,
          y: launchY - 6,
          "font-size": 10.5,
          "font-weight": 600,
          fill: ink,
          stroke: halo,
          "stroke-width": 2.5,
          "paint-order": "stroke",
        },
        [`launch ${Math.round(siteAltitudeM)} m`],
      ),
    );
  }

  for (const temperatureC of [0, 10, 20]) {
    const isothermPath = segmentedPath(
      hours,
      xCenter,
      y,
      (hour) => temperatureCrossing(hour, floor, temperatureC),
    );
    haloedPath(
      svg,
      isothermPath,
      temperatureC === 0 ? freezingColor : ink,
      halo,
      temperatureC === 0 ? 1.7 : 1,
      temperatureC === 0 ? "7 3 1 3" : undefined,
    );
    const labelIndex = hours.findLastIndex(
      (hour) => temperatureCrossing(hour, floor, temperatureC) != null,
    );
    if (labelIndex >= 0) {
      const altitude = temperatureCrossing(hours[labelIndex], floor, temperatureC)!;
      svg.appendChild(
        svgEl(
          "text",
          {
            x: xCenter(labelIndex) - 4,
            y: y(altitude) - 5,
            "text-anchor": "end",
            "font-size": 10.5,
            "font-weight": 700,
            fill: temperatureC === 0 ? freezingColor : ink,
            stroke: halo,
            "stroke-width": 2.5,
            "paint-order": "stroke",
          },
          [`${temperatureC}°`],
        ),
      );
    }
  }

  const boundaryPath = segmentedPath(hours, xCenter, y, (hour) => hour.boundaryLayerTopM);
  const cloudBasePath = segmentedPath(hours, xCenter, y, (hour) => hour.cloudBaseM);
  const usablePath = segmentedPath(hours, xCenter, y, (hour) => hour.usableLiftTopM);
  haloedPath(svg, boundaryPath, boundaryColor, halo, 2, "10 5");
  haloedPath(svg, cloudBasePath, windColor, halo, 1.8, "1 5");
  haloedPath(svg, usablePath, usableColor, halo, 2.3);

  const selected = hours[selectedIndex];
  if (selected?.usableLiftTopM != null) {
    svg.appendChild(wingMarker(selectedX, y(selected.usableLiftTopM), usableColor, halo));
  }
  if (selected?.cloudBaseM != null) {
    svg.appendChild(cloudMarker(selectedX, y(selected.cloudBaseM), windColor, halo));
  }

  // wind barbs — thin the hour columns if there are many, and thin a tall
  // level stack too (always keeping the topmost level so the sounding's
  // ceiling still gets a reading)
  const stride = hours.length > 9 ? 2 : 1;
  hours.forEach((h, i) => {
    if (i % stride !== 0) return;
    const cx = xCenter(i);
    svg.appendChild(
      windBarb(cx, y(modelElevationM), h.windSpeedKmh, h.windDirectionDeg, windColor, halo, WIND_BARB_SCALE),
    );
    const levels: LevelReading[] = h.levels;
    const levelStride = levels.length > 6 ? 2 : 1;
    levels.forEach((lvl, li) => {
      if (li % levelStride !== 0 && li !== levels.length - 1) return;
      svg.appendChild(
        windBarb(cx, y(lvl.heightM), lvl.windSpeedKmh, lvl.windDirectionDeg, windColor, halo, WIND_BARB_SCALE),
      );
    });
  });

  renderLegend(svg, {
    plotBottom,
    plotWidth,
    inkSoft,
    inkMute,
    usableColor,
    boundaryColor,
    windColor,
    halo,
  });

  return svg;
}

function renderLegend(
  svg: SVGSVGElement,
  ctx: {
    plotBottom: number;
    plotWidth: number;
    inkSoft: string;
    inkMute: string;
    usableColor: string;
    boundaryColor: string;
    windColor: string;
    halo: string;
  },
) {
  const { plotBottom, plotWidth, inkSoft, inkMute, usableColor, boundaryColor, windColor, halo } = ctx;
  const CHAR_W = 5.9;
  const seriesY = plotBottom + SERIES_LEGEND_DY;
  const windY = plotBottom + WIND_LEGEND_DY;

  // row 1 — line + glyph key for the three derived series
  let cursor = MARGIN_LEFT;
  const seriesItem = (
    label: string,
    dash: string | undefined,
    color: string,
    glyph?: (cx: number, cy: number) => SVGGElement,
  ) => {
    const lineY = seriesY - 4;
    const attrs: Record<string, string | number> = {
      x1: cursor,
      x2: cursor + 22,
      y1: lineY,
      y2: lineY,
      stroke: color,
      "stroke-width": 2,
    };
    if (dash) attrs["stroke-dasharray"] = dash;
    svg.appendChild(svgEl("line", attrs));
    let textX = cursor + 30;
    if (glyph) {
      svg.appendChild(glyph(cursor + 30, lineY));
      textX += 14;
    }
    svg.appendChild(svgEl("text", { x: textX, y: seriesY, "font-size": "11", fill: inkSoft }, [label]));
    cursor = textX + label.length * CHAR_W + 22;
  };
  seriesItem("Boundary layer top", "10,5", boundaryColor);
  seriesItem("Cloud base", "1,5", windColor, (cx, cy) => cloudMarker(cx, cy, windColor, halo, 0.85));
  seriesItem("Usable lift top", undefined, usableColor, (cx, cy) => wingMarker(cx, cy, usableColor, halo, 0.85));

  // row 2 — wind key, drawn with the same windBarb() geometry as the chart
  // so the legend icons are literally what's on the plot, not an approximation
  svg.appendChild(svgEl("text", { x: MARGIN_LEFT, y: windY, "font-size": "11", fill: inkMute }, ["Wind (km/h):"]));
  cursor = MARGIN_LEFT + 88;
  const windItem = (label: string, speedKmh: number) => {
    const cy = windY - 4;
    svg.appendChild(windBarb(cursor, cy, speedKmh, 0, windColor, halo, WIND_BARB_SCALE));
    svg.appendChild(svgEl("text", { x: cursor + 12, y: windY, "font-size": "11", fill: inkSoft }, [label]));
    cursor += 12 + label.length * CHAR_W + 22;
  };
  windItem("calm", 0);
  windItem("5", 5);
  windItem("10", 10);
  windItem("50", 50);

  // row 3 — the 8-class stability key, grouped
  const segW = plotWidth / STABILITY_CLASSES.length;
  const swatchTop = plotBottom + STAB_SWATCH_DY;
  svg.appendChild(
    svgEl(
      "text",
      { x: MARGIN_LEFT - 11, y: swatchTop + STAB_SWATCH_H - 3, "text-anchor": "end", "font-size": "10", fill: inkMute },
      ["Stability"],
    ),
  );
  STABILITY_CLASSES.forEach((entry, i) => {
    svg.appendChild(
      svgEl("rect", {
        x: MARGIN_LEFT + segW * i,
        y: swatchTop,
        width: segW,
        height: STAB_SWATCH_H,
        fill: cssVar(entry.cssVar, entry.fallback),
      }),
    );
  });
  // thresholds between classes — every boundary if there's room, else every other
  const showEveryThreshold = segW >= 3 * CHAR_W + 6;
  STABILITY_CLASSES.slice(0, -1).forEach((entry, i) => {
    if (!showEveryThreshold && i % 2 !== 1) return;
    svg.appendChild(
      svgEl(
        "text",
        {
          x: MARGIN_LEFT + segW * (i + 1),
          y: swatchTop + STAB_SWATCH_H + 11,
          "text-anchor": "middle",
          "font-size": "9.5",
          fill: inkMute,
        },
        [String(entry.maxLapse)],
      ),
    );
  });
  // grouped labels, only when the span is wide enough to hold the word
  let groupStart = 0;
  for (const group of STABILITY_GROUPS) {
    const span = group.keys.length;
    const centreX = MARGIN_LEFT + segW * (groupStart + span / 2);
    const spanWidth = segW * span;
    if (spanWidth >= group.label.length * CHAR_W) {
      svg.appendChild(
        svgEl(
          "text",
          {
            x: centreX,
            y: plotBottom + STAB_GROUP_DY,
            "text-anchor": "middle",
            "font-size": "10",
            "font-weight": "600",
            fill: inkMute,
          },
          [group.label],
        ),
      );
    }
    groupStart += span;
  }
}
