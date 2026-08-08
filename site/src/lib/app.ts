import { fetchSitesCatalog, fetchProfileWithSkewGuard, type SiteCatalogEntry, type SiteProfile } from "./api";
import { PROFILE_MODELS, modelById } from "./models";
import { renderWindgramSVG } from "./chart";
import { renderOverlaySVG, type OverlaySeries } from "./overlay";
import { groupByLocalDay, localHourLabel } from "./time";
import { freshnessInfo } from "./captions";

const LAST_SITE_KEY = "windgrams:lastSite";
const LAST_MODEL_KEY = "windgrams:lastModel";
const MODEL_COLOR_VARS = ["--model-1", "--model-2", "--model-3", "--model-4", "--model-5", "--model-6"];

function el<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`missing #${id}`);
  return found as T;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

let sites: SiteCatalogEntry[] = [];
let currentSite = "";
let currentModel = "hrdps-2p5km";
let currentDateKey: string | null = null;
const appRoot = document.querySelector<HTMLElement>(".wg-app");
let overlayOn = appRoot?.dataset.defaultCompare === "true";
if (appRoot) appRoot.dataset.comparing = String(overlayOn);
let currentProfile: SiteProfile | null = null;

const siteSelect = el<HTMLSelectElement>("site-select");
const modelSelect = el<HTMLSelectElement>("model-select");
const overlayToggle = el<HTMLInputElement>("overlay-toggle");
const dayTabs = el<HTMLDivElement>("day-tabs");
const freshnessEl = el<HTMLDivElement>("freshness");
const hourReadoutEl = el<HTMLDivElement>("hour-readout");
const chartMount = el<HTMLDivElement>("chart-mount");
const statusEl = el<HTMLDivElement>("status");
const overlaySection = el<HTMLDivElement>("overlay-section");
const overlayMount = el<HTMLDivElement>("overlay-mount");
const overlayStatus = el<HTMLDivElement>("overlay-status");

function populateModelSelect() {
  modelSelect.innerHTML = "";
  for (const m of PROFILE_MODELS) {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = m.experimental ? `${m.shortLabel} (experimental)` : m.shortLabel;
    modelSelect.appendChild(opt);
  }
  modelSelect.value = currentModel;
}

function populateSiteSelect() {
  siteSelect.innerHTML = "";
  for (const [index, s] of sites.entries()) {
    const opt = document.createElement("option");
    opt.value = s.slug;
    opt.textContent = `Sample grid cell ${String.fromCharCode(65 + index)}`;
    siteSelect.appendChild(opt);
  }
  siteSelect.value = currentSite;
}

function renderDayTabs(days: { dateKey: string; label: string }[]) {
  dayTabs.innerHTML = "";
  for (const d of days) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = d.label;
    btn.className = "day-tab" + (d.dateKey === currentDateKey ? " active" : "");
    btn.addEventListener("click", () => {
      currentDateKey = d.dateKey;
      renderChartForCurrentDay();
      renderDayTabs(days);
      if (overlayOn) loadOverlay();
    });
    dayTabs.appendChild(btn);
  }
}

function renderChartForCurrentDay() {
  if (!currentProfile || !currentDateKey) return;
  const days = groupByLocalDay(currentProfile.hours);
  const day = days.find((d) => d.dateKey === currentDateKey) ?? days[0];
  if (!day) {
    chartMount.innerHTML = "<p>No flyable hours in this run.</p>";
    hourReadoutEl.textContent = "";
    return;
  }
  const selected = day.hours.reduce((best, hour) =>
    (hour.thermalVelocityMs ?? 0) > (best.thermalVelocityMs ?? 0) ? hour : best,
  );
  const usable = selected.usableLiftTopM == null ? "none" : `${Math.round(selected.usableLiftTopM).toLocaleString()} m`;
  hourReadoutEl.textContent = `${localHourLabel(selected.validAt)}:00 · ${Math.round(selected.surfaceTemperatureC)} °C · w* ${(selected.thermalVelocityMs ?? 0).toFixed(1)} m/s · usable lift ${usable} · cloud ${Math.round(selected.cloudCoverPercent)}%`;
  chartMount.innerHTML = "";
  chartMount.appendChild(
    renderWindgramSVG({
      hours: day.hours,
      modelElevationM: currentProfile.modelElevationM,
      siteAltitudeM: currentProfile.siteAltitudeM,
    }),
  );
}

async function loadSite() {
  const model = modelById(currentModel);
  if (!model) return;
  statusEl.textContent = "Loading…";
  chartMount.innerHTML = "";
  freshnessEl.textContent = "";

  try {
    const result = await fetchProfileWithSkewGuard(model, currentSite);
    if (!result) {
      statusEl.textContent = `${model.label} doesn't cover this launch — it's likely outside the model's domain, or the model hasn't published its first run yet.`;
      dayTabs.innerHTML = "";
      return;
    }
    statusEl.textContent = "";
    currentProfile = result.profile;

    const fresh = freshnessInfo(result.manifest, model, result.stale);
    freshnessEl.textContent = fresh.text;
    freshnessEl.dataset.status = fresh.status;

    const days = groupByLocalDay(result.profile.hours);
    if (!days.some((d) => d.dateKey === currentDateKey)) {
      currentDateKey = days[0]?.dateKey ?? null;
    }
    renderDayTabs(days);
    renderChartForCurrentDay();

    try {
      localStorage.setItem(LAST_SITE_KEY, currentSite);
      localStorage.setItem(LAST_MODEL_KEY, currentModel);
    } catch {}

    if (overlayOn) loadOverlay();
  } catch (err) {
    statusEl.textContent = `Couldn't load ${model.label} for this launch — the model's data may be temporarily unavailable. (${(err as Error).message})`;
  }
}

async function loadOverlay() {
  if (!currentDateKey) return;
  overlaySection.hidden = false;
  overlayMount.innerHTML = "";
  overlayStatus.textContent = "Comparing models…";

  const results = await Promise.all(
    PROFILE_MODELS.map(async (m) => {
      try {
        const r = await fetchProfileWithSkewGuard(m, currentSite);
        return r ? { model: m, profile: r.profile } : null;
      } catch {
        return null;
      }
    }),
  );

  const series: OverlaySeries[] = [];
  results.forEach((r, i) => {
    if (!r) return;
    const days = groupByLocalDay(r.profile.hours);
    const day = days.find((d) => d.dateKey === currentDateKey);
    if (!day) return;
    series.push({ model: r.model, color: cssVar(MODEL_COLOR_VARS[i % MODEL_COLOR_VARS.length]), hours: day.hours });
  });

  if (series.length < 2) {
    overlayStatus.textContent = "Not enough models cover this launch and day yet to compare.";
    return;
  }
  overlayStatus.textContent = "";
  overlayMount.appendChild(renderOverlaySVG(series));
}

function init() {
  populateModelSelect();
  overlayToggle.checked = overlayOn;

  let savedSite = "";
  let savedModel = "";
  try {
    savedSite = localStorage.getItem(LAST_SITE_KEY) ?? "";
    savedModel = localStorage.getItem(LAST_MODEL_KEY) ?? "";
  } catch {}
  if (savedModel && modelById(savedModel)) {
    currentModel = savedModel;
    modelSelect.value = savedModel;
  }

  fetchSitesCatalog()
    .then((catalog) => {
      sites = catalog;
      currentSite = savedSite && catalog.some((s) => s.slug === savedSite) ? savedSite : (catalog[0]?.slug ?? "");
      populateSiteSelect();
      if (currentSite) loadSite();
    })
    .catch((err) => {
      statusEl.textContent = `Couldn't load the site catalogue. (${(err as Error).message})`;
    });

  siteSelect.addEventListener("change", () => {
    currentSite = siteSelect.value;
    currentDateKey = null;
    loadSite();
  });
  modelSelect.addEventListener("change", () => {
    currentModel = modelSelect.value;
    currentDateKey = null;
    loadSite();
  });
  overlayToggle.addEventListener("change", () => {
    overlayOn = overlayToggle.checked;
    if (appRoot) appRoot.dataset.comparing = String(overlayOn);
    if (overlayOn) loadOverlay();
    else overlaySection.hidden = true;
  });
}

init();
