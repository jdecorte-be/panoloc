"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { FeatureCollection, LineString, Point } from "geojson";
// maplibre-gl 6 is ESM only, named exports; its Map not to shadow the JS Map
import {
  type ExpressionSpecification,
  type GeoJSONSource,
  GeolocateControl,
  getVersion,
  type IControl,
  type MapGeoJSONFeature,
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  ScaleControl,
  setWorkerUrl,
  type StyleSpecification,
} from "maplibre-gl";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type Place, SearchBar } from "@/components/search-bar";
import { SignPanel, type MapStatus } from "@/components/sign-panel";
import basicStyle from "@/lib/basemap/basic-style.json";
import { boxesOf, signLabel } from "@/lib/labels";
import { GlassMarkers } from "@/lib/glass-markers";
import {
  addBlankImage,
  addViewConeImage,
  ICON_PX,
  VIEW_CONE,
} from "@/lib/sign-images";
import { MAX_COUNT_SIZE, MAX_TILES, TILE_DEG, tilesOf } from "@/lib/tiles";
import type {
  CameraTuple,
  CountsResponse,
  Detection,
  LocatedSign,
  Selection,
  SignRay,
  TileSign,
  TotalResponse,
} from "@/lib/types";

// the worker copied by scripts/copy-maplibre-worker.mjs: the bundle loses the one next
// to maplibre-gl.mjs; the version in the URL, a new one for the cache on each upgrade
if (typeof window !== "undefined") {
  setWorkerUrl(`/maplibre/maplibre-gl-worker.mjs?v=${getVersion()}`);
}

const loadPanorama = () =>
  import("@/components/panorama").then((m) => m.Panorama);
// WebGL viewer: browser only, its chunk fetched while the browser is idle
const Panorama = dynamic(loadPanorama, { ssr: false });

// the basemap: MapTiler's open-source "Basic" design (BSD / CC-BY 4.0, see
// lib/basemap/LICENSE.md) on OpenFreeMap's OpenMapTiles vector tiles: no API key
const BASEMAP = basicStyle as StyleSpecification;
const STYLE_CREDIT =
  'Style <a href="https://github.com/openmaptiles/maptiler-basic-gl-style" target="_blank">© MapTiler Basic</a>';
// the first view, without a #zoom/lat/lon in the URL: Paris, whatever the screen
const INITIAL_BOUNDS: [number, number, number, number] = [
  2.22, 48.815, 2.47, 48.905,
];
// the floating panel covers the left of the map from the md breakpoint on
const PANEL_PX = 360;
// without it, before the first fit
const FALLBACK_CENTER: [number, number] = [2.35, 48.86];
const FALLBACK_ZOOM = 11;
// read once, before any map writes its own view in the URL (React's dev double
// mount would take it for a shared view): a shared view wins over Paris
let fitInitial =
  typeof window !== "undefined" &&
  !/^#[\d.]+\/-?[\d.]+\/-?[\d.]+/.test(window.location.hash);
// below that a view has too many tiles to locate: the signs are counted instead
const DETAIL_ZOOM = 16;
// the #n badges of the signs from that zoom on: fewer overlaps
const LABEL_ZOOM = 18;
// width of a square of counted signs on the screen, about
const COUNT_PX = 120;
// zoom of the inset map around the camera of the 360° view
const INSET_ZOOM = 18;
// colors of the Streamlit map (heading_map.py)
const CURRENT = "rgb(230, 80, 40)"; // the camera of the open picture
const SEEN = "rgb(255, 140, 0)"; // the signs it sees, orange like its boxes
const CAMERA = "rgb(100, 116, 139)";
// the cameras stay in the background: the signs are what the map shows
const CAMERA_OPACITY = 0.45;
// the size of every marker: the counts, the discs, the pictograms
const MARKER_SCALE = 1.25;
// radius of the disc behind a pictogram, of the dot of a sign without one
const SIGN_DISC_PX = (ICON_PX / 2 + 3) * MARKER_SCALE;
const SIGN_DOT_PX = 5 * MARKER_SCALE;
// layers a click on a sign may hit
const SIGN_LAYERS = ["sign-discs"];

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };
const COMPACT = new Intl.NumberFormat("en", { notation: "compact" });
// the same array on every render: memos depending on it hold
const NO_DETECTIONS: Detection[] = [];

type CachedSign = Omit<LocatedSign, "number">;

function decode(t: TileSign): CachedSign {
  return {
    ...t,
    id: `${t.sign}@${t.position.join(",")}`,
    rays: t.rays.map(
      ([pictureId, annotationId, lon, lat, bearing, distance]) => ({
        pictureId,
        annotationId,
        camera: [lon, lat],
        bearing,
        distance,
      }),
    ),
  };
}

/** Numbered as find_signs does: the most seen first. */
function numbered(signs: CachedSign[]): LocatedSign[] {
  return signs
    .toSorted(
      (a, b) =>
        b.rays.length - a.rays.length ||
        a.sign.localeCompare(b.sign) ||
        a.position[0] - b.position[0] ||
        a.position[1] - b.position[1],
    )
    .map((s, i) => ({ ...s, number: i + 1 }));
}

function signPoints(signs: LocatedSign[]): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: signs.map((s) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: s.position },
      // flat properties: MapLibre turns arrays into strings
      properties: {
        id: s.id,
        label: `#${s.number}`,
        seen: s.rays.length,
        ...(s.icon && { icon: s.icon }),
      },
    })),
  };
}

/** From each camera to the sign it sees: the rays find_signs kept. */
function rayLines(signs: LocatedSign[]): FeatureCollection<LineString> {
  return {
    type: "FeatureCollection",
    features: signs.flatMap((s) =>
      s.rays.map((r) => ({
        type: "Feature" as const,
        geometry: {
          type: "LineString" as const,
          coordinates: [r.camera, s.position],
        },
        properties: { id: s.id },
      })),
    ),
  };
}

/** Tiles per side of a square of counts: a power of two, COUNT_PX wide or so. */
function countSize(zoom: number): number {
  const deg = (COUNT_PX * 360) / (512 * 2 ** zoom);
  return Math.min(
    2 ** Math.max(0, Math.round(Math.log2(deg / TILE_DEG))),
    MAX_COUNT_SIZE,
  );
}

// the borders of the counted circles (GlassMarkers): violet by order of magnitude,
// light to dark, apart from the basemap's water and the orange of the open picture
const COUNT_TIERS = [
  { min: 1, border: "#a78bfa" },
  { min: 10, border: "#7c3aed" },
  { min: 100, border: "#5b21b6" },
  { min: 1000, border: "#3b0764" },
] as const;

// a circle of at most that many signs: one click shows them
const FEW_SIGNS = 300;
// area proportional to the count: 1 sign 10 px, 10 000 signs 34 px
const COUNT_RADIUS: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["sqrt", ["get", "count"]],
  1,
  10 * MARKER_SCALE,
  100,
  34 * MARKER_SCALE,
];

function countPoints(
  counts: CountsResponse["counts"],
): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: counts.map(([lon, lat, count]) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lon, lat] },
      properties: { count, label: COMPACT.format(count) },
    })),
  };
}

function cameraPoints(cameras: CameraTuple[]): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: cameras.map(([pictureId, lon, lat]) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lon, lat] },
      properties: { pictureId },
    })),
  };
}

const zoomed = (
  z0: number,
  v0: number,
  z1: number,
  v1: number,
): ExpressionSpecification => [
  "interpolate",
  ["linear"],
  ["zoom"],
  z0,
  v0,
  z1,
  v1,
];

/** A size at full scale from zoom 18.5, smaller below: no pile of signs at zoom 16. */
const bySignZoom = (
  size: ExpressionSpecification | number,
): ExpressionSpecification => [
  "interpolate",
  ["linear"],
  ["zoom"],
  DETAIL_ZOOM,
  ["*", 0.62, size],
  17,
  ["*", 0.8, size],
  18.5,
  size,
];
const HAS_ICON: ExpressionSpecification = ["has", "icon"];

function addLayers(map: MapLibreMap) {
  for (const id of ["cameras", "rays", "view"]) {
    map.addSource(id, { type: "geojson", data: EMPTY });
  }
  // the feature state of a sign follows its id: hover, selection
  map.addSource("signs", { type: "geojson", data: EMPTY, promoteId: "id" });
  map.addSource("counts", { type: "geojson", data: EMPTY, generateId: true });
  const halo = "#ffffff";

  // zoomed out: the signs counted by squares, the area growing with the count;
  // drawn by GlassMarkers, this invisible layer takes the clicks and the hover
  map.addLayer({
    id: "count-circles",
    type: "circle",
    source: "counts",
    maxzoom: DETAIL_ZOOM,
    paint: {
      "circle-radius": COUNT_RADIUS,
      "circle-opacity": 0,
      "circle-stroke-opacity": 0,
    },
  });

  // zoomed in: the signs themselves
  map.addLayer({
    id: "rays",
    type: "line",
    source: "rays",
    minzoom: DETAIL_ZOOM,
    layout: { visibility: "none", "line-cap": "round" },
    paint: {
      "line-color": CAMERA,
      "line-width": 1,
      "line-opacity": 0.5,
    },
  });
  map.addLayer({
    id: "rays-selected",
    type: "line",
    source: "rays",
    minzoom: DETAIL_ZOOM,
    filter: ["==", ["get", "id"], ""],
    layout: { "line-cap": "round" },
    paint: { "line-color": SEEN, "line-width": 2.5, "line-opacity": 0.9 },
  });
  map.addLayer({
    id: "cameras",
    type: "circle",
    source: "cameras",
    minzoom: DETAIL_ZOOM,
    paint: {
      "circle-radius": zoomed(DETAIL_ZOOM, 1.6, 19, 3.5),
      "circle-color": CAMERA,
      "circle-opacity": CAMERA_OPACITY,
      "circle-stroke-color": halo,
      "circle-stroke-width": zoomed(17.5, 0, 19, 1),
      "circle-stroke-opacity": CAMERA_OPACITY,
    },
  });
  addViewConeImage(map);
  map.addLayer({
    id: "view-cone",
    type: "symbol",
    source: "view",
    filter: ["has", "bearing"],
    layout: {
      "icon-image": VIEW_CONE,
      "icon-rotate": ["get", "bearing"],
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
  });
  map.addLayer({
    id: "view-camera",
    type: "circle",
    source: "view",
    paint: {
      "circle-radius": 7,
      "circle-color": CURRENT,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2.5,
    },
  });
  // the signs: drawn by GlassMarkers, this invisible layer takes the clicks and
  // the hover
  map.addLayer({
    id: "sign-discs",
    type: "circle",
    source: "signs",
    minzoom: DETAIL_ZOOM,
    paint: {
      "circle-radius": bySignZoom([
        "case",
        HAS_ICON,
        SIGN_DISC_PX,
        SIGN_DOT_PX,
      ]),
      "circle-opacity": 0,
      "circle-stroke-opacity": 0,
    },
  });
}

/** The open picture: its camera, the rays of the selected sign (the signs: GlassMarkers). */
function highlight(
  map: MapLibreMap,
  pictureId: string | null,
  sign: string | null,
) {
  const isCamera: ExpressionSpecification = [
    "==",
    ["get", "pictureId"],
    pictureId ?? "",
  ];
  const cameraOpacity: ExpressionSpecification | number = pictureId
    ? ["case", isCamera, 1, CAMERA_OPACITY / 2]
    : CAMERA_OPACITY;
  map.setPaintProperty("cameras", "circle-opacity", cameraOpacity);
  map.setPaintProperty("cameras", "circle-stroke-opacity", cameraOpacity);
  map.setFilter("rays-selected", ["==", ["get", "id"], sign ?? ""]);
}

/** Camera of the 360° view on the map, with its view direction when known. */
function setView(
  map: MapLibreMap,
  position: [number, number] | null,
  bearing: number | null = null,
) {
  map.getSource<GeoJSONSource>("view")?.setData({
    type: "FeatureCollection",
    features: position
      ? [
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: position },
            properties: bearing === null ? {} : { bearing },
          },
        ]
      : [],
  });
}

async function getJson<T extends object>(
  url: string,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(url, { signal });
  const body = (await res.json()) as T | { error: string };
  if ("error" in body) throw new Error(body.error);
  return body;
}

/**
 * Ask for the missing tiles of a view, MAX_TILES per request, all requests at once;
 * each answer is stored, then onBatch is called.
 */
async function fetchTiles<T>(
  endpoint: string,
  missing: string[],
  store: (tile: string, value: T) => void,
  signal: AbortSignal,
  onBatch: () => void | Promise<void>,
): Promise<void> {
  const batches: string[][] = [];
  for (let k = 0; k < missing.length; k += MAX_TILES)
    batches.push(missing.slice(k, k + MAX_TILES));
  await Promise.all(
    batches.map(async (asked) => {
      // sorted: the same tiles, the same URL, a hit of the HTTP cache
      const url = `${endpoint}?tiles=${asked.toSorted().join(",")}`;
      const body = await getJson<{ tiles: Record<string, T> }>(url, signal);
      if (signal.aborted) return;
      for (const [tile, value] of Object.entries(body.tiles))
        store(tile, value);
      await onBatch();
    }),
  );
}

function errorStatus(error: unknown): MapStatus {
  return {
    kind: "error",
    message: error instanceof Error ? error.message : String(error),
  };
}

/** The tooltip of a sign under the pointer: built with the DOM, no HTML injected. */
function tooltipOf(sign: LocatedSign): HTMLElement {
  const root = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = signLabel(sign.number, sign.name);
  const detail = document.createElement("span");
  const pictures = sign.rays.length;
  detail.textContent = `seen in ${pictures} picture${pictures === 1 ? "" : "s"} · click to view`;
  root.append(title, detail);
  return root;
}

const GITHUB_PATH =
  "M12 .3a12 12 0 0 0-3.8 23.38c.6.12.83-.26.83-.57L9 21.07c-3.34.72-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.08-.74.09-.73.09-.73 1.2.09 1.83 1.24 1.83 1.24 1.07 1.83 2.81 1.3 3.5 1 .1-.78.42-1.31.76-1.61-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.14-.3-.54-1.52.1-3.18 0 0 1-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.28-1.55 3.29-1.23 3.29-1.23.64 1.66.24 2.88.12 3.18a4.65 4.65 0 0 1 1.23 3.22c0 4.61-2.8 5.63-5.48 5.92.42.36.81 1.1.81 2.22l-.01 3.29c0 .31.2.69.82.57A12 12 0 0 0 12 .3";
const CODEBERG_PATH =
  "M11.999.747A11.974 11.974 0 0 0 0 12.75c0 2.254.635 4.465 1.833 6.376L11.837 6.19c.072-.092.251-.092.323 0l4.178 5.402h-2.992l.065.239h3.113l.882 1.138h-3.674l.103.374h3.86l.777 1.003h-4.358l.135.483h4.593l.695.894h-5.038l.165.589h5.326l.609.785h-5.717l.182.65h6.038l.562.727h-6.397l.183.65h6.717A12.003 12.003 0 0 0 24 12.75 11.977 11.977 0 0 0 11.999.747zm3.654 19.104.182.65h5.326c.18-.212.353-.425.513-.65zm.385 1.388.18.65h3.335c.3-.205.596-.419.88-.65zm.383 1.38.182.65h1.821c.47-.19.926-.41 1.367-.65z";

const SOURCE_LINKS = [
  {
    title: "Source on GitHub",
    href: "https://github.com/jdecorte-be/panoloc",
    path: GITHUB_PATH,
  },
  {
    title: "Source on Codeberg",
    href: "https://codeberg.org/PierreBorine/panoloc",
    path: CODEBERG_PATH,
  },
];

// links to the source, styled as map buttons so they follow the map into the inset
class SourceControl implements IControl {
  private el?: HTMLDivElement;

  onAdd() {
    const el = document.createElement("div");
    el.className = "maplibregl-ctrl source-links";
    el.innerHTML = SOURCE_LINKS.map(
      ({ title, href, path }) =>
        `<a href="${href}" target="_blank" rel="noopener noreferrer" title="${title}" aria-label="${title}">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d="${path}"/></svg>
        </a>`,
    ).join("");
    this.el = el;
    return el;
  }

  onRemove() {
    this.el?.remove();
  }
}

export function SignMap() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  // tile "i:j" -> its signs, its cameras: a tile is asked for once per page load
  const tilesRef = useRef(new Map<string, CachedSign[]>());
  const camerasRef = useRef(new Map<string, CameraTuple[]>());
  // request URL -> its counts, as long as the page is open
  const countsRef = useRef(new Map<string, CountsResponse["counts"]>());
  // the map's handlers are bound once: they read the latest signs here
  const locatedRef = useRef<LocatedSign[]>([]);
  // what was last drawn: nothing is redrawn while it is the same
  const drawnRef = useRef({ signs: "", cameras: "", counts: "" });
  const bearingRef = useRef<number | null>(null);
  const [status, setStatus] = useState<MapStatus>({ kind: "loading" });
  const [located, setLocated] = useState<LocatedSign[]>([]);
  const [cameraCount, setCameraCount] = useState(0);
  const [total, setTotal] = useState<number | null>(null);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [showRays, setShowRays] = useState(false);
  const glassRef = useRef<GlassMarkers | null>(null);
  const [picture, setPicture] = useState<{
    id: string;
    detections: Detection[];
  } | null>(null);
  // bumped each time the style is (re)loaded: the layers are new, draw them again
  const [styleEpoch, setStyleEpoch] = useState(0);

  /** Draw the cached signs of the view, and one tile around: no gap while panning. */
  const render = useCallback(async (map: MapLibreMap) => {
    const b = map.getBounds();
    const near = tilesOf(
      b.getWest() - TILE_DEG,
      b.getSouth() - TILE_DEG,
      b.getEast() + TILE_DEG,
      b.getNorth() + TILE_DEG,
    ).filter((t) => tilesRef.current.has(t));
    const key = near.join(",");
    if (key === drawnRef.current.signs && map.getSource("signs")) return;
    const signs = numbered(near.flatMap((t) => tilesRef.current.get(t)!));
    if (mapRef.current !== map) return; // removed meanwhile (React's dev double mount)
    map.getSource<GeoJSONSource>("signs")?.setData(signPoints(signs));
    glassRef.current?.setSigns(
      signs.map((s) => ({
        id: s.id,
        lngLat: s.position,
        icon: s.icon ?? undefined,
        label: `#${s.number}`,
        seen: s.rays.length,
      })),
    );
    drawnRef.current.signs = key;
    locatedRef.current = signs;
    setLocated(signs);
  }, []);

  /** Draw the cached cameras of the view. */
  const renderCameras = useCallback((map: MapLibreMap) => {
    const b = map.getBounds();
    const near = tilesOf(
      b.getWest(),
      b.getSouth(),
      b.getEast(),
      b.getNorth(),
    ).filter((t) => camerasRef.current.has(t));
    const key = near.join(",");
    if (key === drawnRef.current.cameras) return;
    const cameras = near.flatMap((t) => camerasRef.current.get(t)!);
    map.getSource<GeoJSONSource>("cameras")?.setData(cameraPoints(cameras));
    drawnRef.current.cameras = key;
    setCameraCount(cameras.length);
  }, []);

  /** The located signs of the view, counted by squares: nothing is located. */
  const loadCounts = useCallback(
    async (map: MapLibreMap, signal: AbortSignal) => {
      const size = countSize(map.getZoom());
      // snapped on the squares, one square around: no square cut by the edge of the
      // view, and the same URL as long as the view stays on the same squares
      const step = size * TILE_DEG;
      const b = map.getBounds();
      const bbox = [
        Math.max(Math.floor(b.getWest() / step) * step - step, -180),
        Math.max(Math.floor(b.getSouth() / step) * step - step, -90),
        Math.min(Math.ceil(b.getEast() / step) * step + step, 180),
        Math.min(Math.ceil(b.getNorth() / step) * step + step, 90),
      ];
      const url = `/api/counts?bbox=${bbox.map((v) => v.toFixed(6)).join(",")}&size=${size}`;
      try {
        let counts = countsRef.current.get(url);
        if (!counts) {
          counts = (await getJson<CountsResponse>(url, signal)).counts;
          countsRef.current.set(url, counts);
        }
        // removed meanwhile, or the style not loaded yet: "style.load" draws again
        if (
          mapRef.current !== map ||
          signal.aborted ||
          !map.getSource("counts")
        )
          return;
        if (drawnRef.current.counts !== url) {
          map.getSource<GeoJSONSource>("counts")?.setData(countPoints(counts));
          glassRef.current?.setCounts(
            counts.map(([lon, lat, count]) => ({
              lngLat: [lon, lat],
              count,
              label: COMPACT.format(count),
            })),
          );
          drawnRef.current.counts = url;
        }
        const inView = counts.filter(([lon, lat]) => b.contains([lon, lat]));
        setStatus({
          kind: "counts",
          signs: inView.reduce((sum, [, , n]) => sum + n, 0),
        });
      } catch (error) {
        if (!signal.aborted) setStatus(errorStatus(error));
      }
    },
    [],
  );

  const refresh = useCallback(
    async (map: MapLibreMap, signal: AbortSignal) => {
      if (map.getZoom() < DETAIL_ZOOM) {
        await loadCounts(map, signal);
        return; // the signs already drawn stay, shown again when zooming in
      }
      const b = map.getBounds();
      const inView = tilesOf(
        b.getWest(),
        b.getSouth(),
        b.getEast(),
        b.getNorth(),
      );
      renderCameras(map);
      await render(map);

      // the tiles never asked for: signs and cameras at once
      const missingSigns = inView.filter((t) => !tilesRef.current.has(t));
      const missingCameras = inView.filter((t) => !camerasRef.current.has(t));
      if (!missingSigns.length) setStatus({ kind: "ready" });
      else
        setStatus({
          kind: "locating",
          pending: missingSigns.length,
          total: missingSigns.length,
        });

      try {
        await Promise.all([
          fetchTiles<TileSign[]>(
            "/api/located",
            missingSigns,
            (tile, tileSigns) =>
              tilesRef.current.set(tile, tileSigns.map(decode)),
            signal,
            async () => {
              const pending = missingSigns.filter(
                (t) => !tilesRef.current.has(t),
              ).length;
              if (pending)
                setStatus({
                  kind: "locating",
                  pending,
                  total: missingSigns.length,
                });
              await render(map);
            },
          ),
          fetchTiles<CameraTuple[]>(
            "/api/cameras",
            missingCameras,
            (tile, cameras) => camerasRef.current.set(tile, cameras),
            signal,
            () => {
              if (mapRef.current === map) renderCameras(map);
            },
          ).catch((error) => {
            // the signs can do without them
            if (!signal.aborted)
              console.warn("Could not load the cameras:", error);
          }),
        ]);
        if (!signal.aborted) setStatus({ kind: "ready" });
      } catch (error) {
        if (!signal.aborted) setStatus(errorStatus(error));
      }
    },
    [render, renderCameras, loadCounts],
  );

  useEffect(() => {
    if (!container.current) return;
    const map = new MapLibreMap({
      container: container.current,
      style: BASEMAP,
      center: FALLBACK_CENTER,
      zoom: FALLBACK_ZOOM,
      hash: true, // the view is kept in the URL: #zoom/lat/lon
      // fits the inset map too; the design's credit (CC-BY), OpenFreeMap's beside it
      attributionControl: { compact: true, customAttribution: STYLE_CREDIT },
      fadeDuration: 150, // labels settle faster
      maxPitch: 60,
    });
    mapRef.current = map;
    map.addControl(
      new NavigationControl({ visualizePitch: true }),
      "top-right",
    );
    map.addControl(
      new GeolocateControl({ positionOptions: { enableHighAccuracy: true } }),
      "top-right",
    );
    map.addControl(new ScaleControl({}), "bottom-right");
    map.addControl(new SourceControl(), "bottom-right");
    const glass = new GlassMarkers(map, {
      scale: MARKER_SCALE,
      detailZoom: DETAIL_ZOOM,
      labelZoom: LABEL_ZOOM,
      discPx: SIGN_DISC_PX,
      dotPx: SIGN_DOT_PX,
      iconPx: ICON_PX * MARKER_SCALE,
      tiers: COUNT_TIERS,
    });
    glassRef.current = glass;

    let controller = new AbortController();
    const reload = () => {
      controller.abort(); // only the last view keeps asking
      controller = new AbortController();
      void refresh(map, controller.signal);
    };

    // the icons the basemap's sprite lacks: drawn as nothing, no warning each
    map.setMissingStyleImageResolver((id) => addBlankImage(map, id));
    // the style loaded: the layers of the map on top of it
    map.on("style.load", () => {
      addLayers(map);
      drawnRef.current = { signs: "", cameras: "", counts: "" };
      if (fitInitial) {
        // fitted once the container has its final size, not while the page lays out
        fitInitial = false;
        map.resize();
        map.fitBounds(INITIAL_BOUNDS, {
          duration: 0,
          padding: window.matchMedia("(min-width: 768px)").matches
            ? { top: 24, bottom: 24, right: 24, left: PANEL_PX }
            : 16,
        });
      }
      setStyleEpoch((e) => e + 1);
      reload();
    });
    map.on("moveend", reload);

    // a sign -> the nearest picture that sees it, facing it
    const selectSign = (e: { features?: MapGeoJSONFeature[] }) => {
      const id = e.features?.[0]?.properties.id as string | undefined;
      const sign = locatedRef.current.find((s) => s.id === id);
      const ray = sign?.rays.find((r) => r.annotationId) ?? sign?.rays[0];
      if (!sign || !ray) return;
      setSelected({
        pictureId: ray.pictureId,
        position: ray.camera,
        focus: ray.annotationId ?? undefined,
        sign: sign.id,
      });
      // the rays shown with it: which pictures see the sign, from where
      setShowRays(true);
    };
    for (const layer of SIGN_LAYERS) {
      map.on("click", layer, (e) => {
        e.preventDefault(); // not the camera below
        selectSign(e);
      });
    }

    // a sign under the pointer: bigger, and its name in a tooltip
    const tooltip = new Popup({
      closeButton: false,
      closeOnClick: false,
      offset: SIGN_DISC_PX + 6,
      className: "sign-tooltip",
      maxWidth: "260px",
    });
    let hoveredSign: string | undefined;
    const hoverSign = (id: string | undefined) => {
      // the hover drawn by GlassMarkers only: no feature state, no repaint of the
      // map under the blur
      if (id === hoveredSign) return;
      hoveredSign = id;
      glass.hoverSign(id);
      const sign =
        id === undefined
          ? undefined
          : locatedRef.current.find((s) => s.id === id);
      if (!sign || id === undefined) {
        tooltip.remove();
        return;
      }
      tooltip
        .setLngLat(sign.position)
        .setDOMContent(tooltipOf(sign))
        .addTo(map);
    };
    map.on("mousemove", "sign-discs", (e) =>
      hoverSign(e.features?.[0]?.properties.id as string),
    );
    map.on("mouseleave", "sign-discs", () => hoverSign(undefined));
    map.on("movestart", () => hoverSign(undefined));

    // a circle of counts -> zoomed in on it: a few hundred signs, straight to them;
    // more, a big step (Europe -> the signs in three clicks, not five)
    map.on("click", "count-circles", (e) => {
      const feature = e.features?.[0];
      const point = feature?.geometry as Point | undefined;
      if (!feature || !point) return;
      const few = Number(feature.properties.count) <= FEW_SIGNS;
      map.easeTo({
        center: point.coordinates as [number, number],
        zoom: few
          ? DETAIL_ZOOM + 1
          : Math.min(map.getZoom() + 5, DETAIL_ZOOM + 1),
      });
    });
    // the square under the pointer stands out
    const setHover = (id: number | string | undefined) =>
      glass.hoverCount(id === undefined ? undefined : Number(id));
    map.on("mousemove", "count-circles", (e) => setHover(e.features?.[0]?.id));
    map.on("mouseleave", "count-circles", () => setHover(undefined));
    // a camera -> its picture, facing the way the camera did
    map.on("click", "cameras", (e) => {
      const camera = e.features?.[0];
      if (e.defaultPrevented || !camera) return;
      setSelected({
        pictureId: camera.properties.pictureId as string,
        position: (camera.geometry as Point).coordinates as [number, number],
      });
    });
    for (const layer of [...SIGN_LAYERS, "cameras", "count-circles"]) {
      map.on(
        "mouseenter",
        layer,
        () => (map.getCanvas().style.cursor = "pointer"),
      );
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }

    return () => {
      controller.abort();
      tooltip.remove();
      glass.remove();
      glassRef.current = null;
      const { hash } = window.location;
      map.remove(); // also clears the #zoom/lat/lon of the URL
      // put it back: React's dev double mount then starts from the same view
      if (hash) window.history.replaceState(window.history.state, "", hash);
      mapRef.current = null;
    };
  }, [refresh]);

  // the 360° viewer's code, fetched before the first click
  useEffect(() => {
    const prefetch = () => void loadPanorama();
    if ("requestIdleCallback" in window) {
      const id = window.requestIdleCallback(prefetch, { timeout: 4000 });
      return () => window.cancelIdleCallback(id);
    }
    const id = setTimeout(prefetch, 2000);
    return () => clearTimeout(id);
  }, []);

  const pictureId = selected?.pictureId ?? null;
  const position = selected?.position;
  const signId = selected?.sign ?? null;

  // the boxes of the open picture, by type
  useEffect(() => {
    if (!pictureId) return;
    const controller = new AbortController();
    getJson<{ detections: Detection[] }>(
      `/api/pictures/${pictureId}`,
      controller.signal,
    )
      .then((body) =>
        setPicture({ id: pictureId, detections: body.detections }),
      )
      .catch((error) => {
        if (!controller.signal.aborted)
          console.warn("Could not load the picture:", error);
      });
    return () => controller.abort();
  }, [pictureId]);
  const detections =
    picture?.id === pictureId ? picture.detections : NO_DETECTIONS;

  const boxes = useMemo(
    () => (pictureId ? boxesOf(pictureId, detections, located) : []),
    [pictureId, detections, located],
  );
  const labels = useMemo(
    () => Object.fromEntries(boxes.map((b) => [b.annotationId, b.label])),
    [boxes],
  );
  const seen = useMemo(
    () =>
      located
        .filter((s) => s.rays.some((r) => r.pictureId === pictureId))
        .map((s) => s.id),
    [located, pictureId],
  );

  // the signs of the whole world: asked for once per page load
  useEffect(() => {
    const controller = new AbortController();
    getJson<TotalResponse>("/api/total", controller.signal)
      .then((body) => setTotal(body.total))
      .catch((error) => {
        if (!controller.signal.aborted)
          console.warn("Could not count the signs:", error);
      });
    return () => controller.abort();
  }, []);

  // full map <-> inset map centered on the camera of the 360° view
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.resize(); // its box just changed
    if (!position) bearingRef.current = null;
    if (!map.getLayer("sign-discs")) return; // style not loaded yet
    setView(map, position ?? null, bearingRef.current);
  }, [pictureId, position, styleEpoch]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && position)
      map.easeTo({
        center: position,
        zoom: Math.max(map.getZoom(), INSET_ZOOM),
      });
  }, [pictureId, position]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("sign-discs")) highlight(map, pictureId, signId);
    glassRef.current?.highlight(pictureId, seen, signId);
  }, [pictureId, seen, signId, styleEpoch]);

  // rays: all of them only when asked for, else those of the selected sign
  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer("rays")) return;
    map.setLayoutProperty("rays", "visibility", showRays ? "visible" : "none");
    const drawn = showRays ? located : located.filter((s) => s.id === signId);
    map.getSource<GeoJSONSource>("rays")?.setData(rayLines(drawn));
  }, [showRays, located, signId, styleEpoch]);

  useEffect(() => {
    if (!pictureId) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSelected(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pictureId]);

  const onBearing = useCallback(
    (bearing: number | null) => {
      bearingRef.current = bearing;
      if (mapRef.current?.getSource("view") && position)
        setView(mapRef.current, position, bearing);
    },
    [position],
  );
  // a box of the open picture: look at it, and select its sign when it is located
  const onFocus = useCallback(
    (focus: string) =>
      setSelected((s) => {
        if (!s) return s;
        const box = boxes.find((b) => b.annotationId === focus);
        return { ...s, focus, sign: box?.sign ?? s.sign };
      }),
    [boxes],
  );
  // another picture that sees the selected sign
  const onPicture = useCallback(
    (ray: SignRay) =>
      setSelected(
        (s) =>
          s && {
            ...s,
            pictureId: ray.pictureId,
            position: ray.camera,
            focus: ray.annotationId ?? undefined,
          },
      ),
    [],
  );
  const onClose = useCallback(() => setSelected(null), []);

  // the search: the places near the view first; a place found -> the full map on it
  const near = useCallback(
    () => mapRef.current?.getCenter().toArray() as [number, number] | undefined,
    [],
  );
  const onSearch = useCallback((place: Place) => {
    const map = mapRef.current;
    if (!map) return;
    setSelected(null);
    const padding = window.matchMedia("(min-width: 768px)").matches
      ? { top: 24, bottom: 24, right: 24, left: PANEL_PX }
      : 16;
    if (place.bounds) {
      map.fitBounds(place.bounds, { padding, maxZoom: DETAIL_ZOOM + 1 });
    } else {
      map.flyTo({ center: place.center, zoom: DETAIL_ZOOM + 1 });
    }
  }, []);

  const busy = status.kind === "loading" || status.kind === "locating";
  const progress =
    status.kind === "locating"
      ? 1 - status.pending / Math.max(status.total, 1)
      : null;

  return (
    // phones: the panel below the map; wider screens: floating over it
    <div className="relative flex h-full w-full flex-col overflow-hidden md:block">
      <div className="relative min-h-0 flex-1 md:absolute md:inset-0">
        <SearchBar near={near} onPick={onSearch} />
        {selected && (
          <Panorama
            key={selected.pictureId}
            pictureId={selected.pictureId}
            labels={labels}
            focus={selected.focus}
            onFocus={onFocus}
            onBearing={onBearing}
          />
        )}
        <div
          className={
            selected
              ? // above the navbar of the 360° view, smaller on phones
                "map-inset absolute right-2 bottom-12 z-10 h-[min(16rem,35%)] w-[min(24rem,50%)] overflow-hidden rounded shadow-lg ring-1 ring-black/20 md:right-4 md:bottom-14 md:h-[min(16rem,40%)] md:w-[min(24rem,calc(100%-2rem))]"
              : "absolute inset-0"
          }
        >
          {/* sized, not positioned: maplibre-gl.css makes it position: relative */}
          <div ref={container} className="h-full w-full" />
          {/* the tiles being located: a thin bar along the top edge */}
          <div
            className={
              "pointer-events-none absolute inset-x-0 top-0 h-0.5 overflow-hidden transition-opacity duration-300 " +
              (busy ? "opacity-100" : "opacity-0")
            }
            aria-hidden
          >
            {progress === null ? (
              <div className="loading-bar h-full w-1/3 bg-accent-soft" />
            ) : (
              <div
                className="h-full bg-accent-soft transition-[width] duration-300"
                style={{ width: `${Math.max(progress, 0.08) * 100}%` }}
              />
            )}
          </div>
          {selected && (
            <button
              type="button"
              onClick={onClose}
              className="absolute top-2 left-2 rounded border border-line bg-surface px-2 py-1 text-xs shadow-sm hover:bg-line/40"
            >
              ⤢ Full map
            </button>
          )}
        </div>
      </div>
      <SignPanel
        status={status}
        located={located}
        cameras={cameraCount}
        total={total}
        selected={selected}
        boxes={boxes}
        showRays={showRays}
        onShowRays={setShowRays}
        onFocus={onFocus}
        onPicture={onPicture}
        onClose={onClose}
      />
    </div>
  );
}
