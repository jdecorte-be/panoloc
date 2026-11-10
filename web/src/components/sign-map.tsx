"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { FeatureCollection, LineString, Point } from "geojson";
import maplibregl, {
  type ExpressionSpecification,
  type GeoJSONSource,
  type MapGeoJSONFeature,
  type Map as MapLibreMap,
} from "maplibre-gl";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { SignPanel, type MapStatus } from "@/components/sign-panel";
import { currentBasemap, setBasemapChoice, useBasemap } from "@/lib/basemap-store";
import { BASEMAPS, type Basemap } from "@/lib/basemaps";
import { byTier } from "@/lib/counts";
import { boxesOf, signLabel } from "@/lib/labels";
import {
  addBadgeImage,
  addBlankImage,
  addViewConeImage,
  BADGE,
  ICON_PREFIX,
  ICON_PX,
  loadSignImages,
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

const loadPanorama = () => import("@/components/panorama").then((m) => m.Panorama);
// WebGL viewer: browser only, its chunk fetched while the browser is idle
const Panorama = dynamic(loadPanorama, { ssr: false });

// the first view, without a #zoom/lat/lon in the URL: Europe, whatever the screen
const INITIAL_BOUNDS: [number, number, number, number] = [-11, 35, 32, 62];
// the floating panel covers the left of the map from the md breakpoint on
const PANEL_PX = 360;
// without it, before the first fit
const FALLBACK_CENTER: [number, number] = [10, 50];
const FALLBACK_ZOOM = 3.5;
// read once, before any map writes its own view in the URL (React's dev double
// mount would take it for a shared view): a shared view wins over Europe
let fitEurope =
  typeof window !== "undefined" && !/^#[\d.]+\/-?[\d.]+\/-?[\d.]+/.test(window.location.hash);
// below that a view has too many tiles to locate: the signs are counted instead
const DETAIL_ZOOM = 16;
// the #n badges of the signs from that zoom on: fewer overlaps
const LABEL_ZOOM = 18;
// width of a square of counted signs on the screen, about
const COUNT_PX = 120;
// zoom of the inset map around the camera of the 360° view
const INSET_ZOOM = 18;
const FADED = 0.25;
// colors of the Streamlit map (heading_map.py)
const CURRENT = "rgb(230, 80, 40)"; // the camera of the open picture
const SEEN = "rgb(255, 140, 0)"; // the signs it sees, orange like its boxes
const CAMERA = "rgb(100, 116, 139)";
// the cameras stay in the background: the signs are what the map shows
const CAMERA_OPACITY = 0.45;
// radius of the disc behind a pictogram, of the dot of a sign without one
const SIGN_DISC_PX = ICON_PX / 2 + 3;
const SIGN_DOT_PX = 5;
// layers a click on a sign may hit
const SIGN_LAYERS = ["sign-discs", "sign-icons", "sign-labels"];

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };
const COMPACT = new Intl.NumberFormat("en", { notation: "compact" });
// the same array on every render: memos depending on it hold
const NO_DETECTIONS: Detection[] = [];

type CachedSign = Omit<LocatedSign, "number">;

function decode(t: TileSign): CachedSign {
  return {
    ...t,
    id: `${t.sign}@${t.position.join(",")}`,
    rays: t.rays.map(([pictureId, annotationId, lon, lat, bearing, distance]) => ({
      pictureId,
      annotationId,
      camera: [lon, lat],
      bearing,
      distance,
    })),
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
        geometry: { type: "LineString" as const, coordinates: [r.camera, s.position] },
        properties: { id: s.id },
      })),
    ),
  };
}

/** Tiles per side of a square of counts: a power of two, COUNT_PX wide or so. */
function countSize(zoom: number): number {
  const deg = (COUNT_PX * 360) / (512 * 2 ** zoom);
  return Math.min(2 ** Math.max(0, Math.round(Math.log2(deg / TILE_DEG))), MAX_COUNT_SIZE);
}

// area proportional to the count: 1 sign 10 px, 10 000 signs 34 px
const COUNT_RADIUS: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["sqrt", ["get", "count"]],
  1,
  10,
  100,
  34,
];

function countPoints(counts: CountsResponse["counts"]): FeatureCollection<Point> {
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

const zoomed = (z0: number, v0: number, z1: number, v1: number): ExpressionSpecification => [
  "interpolate",
  ["linear"],
  ["zoom"],
  z0,
  v0,
  z1,
  v1,
];

/** A size at full scale from zoom 18.5, smaller below: no pile of signs at zoom 16. */
const bySignZoom = (size: ExpressionSpecification | number): ExpressionSpecification => [
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
// white behind a pictogram, a slate dot without
const DISC_COLOR: ExpressionSpecification = ["case", HAS_ICON, "#ffffff", "rgb(100, 116, 139)"];

function addLayers(map: MapLibreMap, dark: boolean) {
  for (const id of ["cameras", "rays", "view"]) {
    map.addSource(id, { type: "geojson", data: EMPTY });
  }
  // the feature state of a sign follows its id: hover, selection
  map.addSource("signs", { type: "geojson", data: EMPTY, promoteId: "id" });
  map.addSource("counts", { type: "geojson", data: EMPTY, generateId: true });
  const hovered: ExpressionSpecification = ["boolean", ["feature-state", "hover"], false];
  const halo = dark ? "#0b0b0f" : "#ffffff";

  // zoomed out: the signs counted by squares, the area growing with the count,
  // the biggest drawn on top
  map.addLayer({
    id: "count-halos",
    type: "circle",
    source: "counts",
    maxzoom: DETAIL_ZOOM,
    layout: { "circle-sort-key": ["get", "count"] },
    paint: {
      "circle-radius": ["+", COUNT_RADIUS, ["case", hovered, 10, 6]],
      "circle-color": byTier("fill"),
      "circle-opacity": ["case", hovered, 0.4, 0.2],
      "circle-blur": 0.4,
    },
  });
  map.addLayer({
    id: "count-circles",
    type: "circle",
    source: "counts",
    maxzoom: DETAIL_ZOOM,
    layout: { "circle-sort-key": ["get", "count"] },
    paint: {
      "circle-radius": COUNT_RADIUS,
      "circle-color": byTier("fill"),
      "circle-stroke-color": halo,
      "circle-stroke-width": ["case", hovered, 3, 2],
    },
  });
  map.addLayer({
    id: "count-labels",
    type: "symbol",
    source: "counts",
    maxzoom: DETAIL_ZOOM,
    layout: {
      "text-field": ["get", "label"],
      "text-font": ["Noto Sans Bold"],
      "text-size": ["interpolate", ["linear"], ["get", "count"], 1, 11, 1000, 13, 10000, 15],
      "text-allow-overlap": true,
      "text-ignore-placement": true,
      "symbol-sort-key": ["get", "count"],
    },
    paint: { "text-color": byTier("text") },
  });

  // zoomed in: the signs themselves
  map.addLayer({
    id: "rays",
    type: "line",
    source: "rays",
    minzoom: DETAIL_ZOOM,
    layout: { visibility: "none", "line-cap": "round" },
    paint: {
      "line-color": dark ? "rgb(148, 163, 184)" : CAMERA,
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
      "circle-color": dark ? "rgb(148, 163, 184)" : CAMERA,
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
  // a soft shadow under each sign: it lifts off any basemap
  map.addLayer({
    id: "sign-shadows",
    type: "circle",
    source: "signs",
    minzoom: DETAIL_ZOOM,
    paint: {
      "circle-radius": bySignZoom(["case", HAS_ICON, SIGN_DISC_PX + 2, SIGN_DOT_PX + 2]),
      "circle-color": "#000000",
      "circle-opacity": 0.28,
      "circle-blur": 0.7,
      "circle-translate": [0, 1.5],
    },
  });
  // the selected sign, ringed
  map.addLayer({
    id: "sign-selected",
    type: "circle",
    source: "signs",
    minzoom: DETAIL_ZOOM,
    filter: ["==", ["get", "id"], ""],
    paint: {
      "circle-radius": bySignZoom(["case", HAS_ICON, SIGN_DISC_PX + 6, SIGN_DOT_PX + 6]),
      "circle-color": "rgba(255, 140, 0, 0.18)",
      "circle-stroke-color": SEEN,
      "circle-stroke-width": 2.5,
    },
  });
  // a disc behind each pictogram (readable on the map), a dot without
  map.addLayer({
    id: "sign-discs",
    type: "circle",
    source: "signs",
    minzoom: DETAIL_ZOOM,
    paint: {
      "circle-radius": bySignZoom([
        "+",
        ["case", HAS_ICON, SIGN_DISC_PX, SIGN_DOT_PX],
        ["case", hovered, 3, 0],
      ]),
      // a sign without pictogram: a slate dot, not an empty disc
      "circle-color": DISC_COLOR,
      "circle-stroke-color": ["case", hovered, SEEN, HAS_ICON, "rgba(0, 0, 0, 0.18)", "#ffffff"],
      "circle-stroke-width": ["case", hovered, 2.5, HAS_ICON, 1, 1.5],
    },
  });
  map.addLayer({
    id: "sign-icons",
    type: "symbol",
    source: "signs",
    minzoom: DETAIL_ZOOM,
    filter: ["has", "icon"],
    layout: {
      "icon-image": ["concat", ICON_PREFIX, ["get", "icon"]],
      "icon-size": [
        "interpolate",
        ["linear"],
        ["zoom"],
        DETAIL_ZOOM,
        0.62,
        17,
        0.8,
        18.5,
        1,
      ],
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
  });
  // the #n of each sign: a small dark badge at its top right, as on the boxes
  addBadgeImage(map);
  map.addLayer({
    id: "sign-labels",
    type: "symbol",
    source: "signs",
    minzoom: LABEL_ZOOM,
    layout: {
      "text-field": ["get", "label"],
      "text-font": ["Noto Sans Bold"],
      "text-size": 9.5,
      "text-anchor": "bottom-left",
      // its corner on the edge of the disc, like a notification badge
      "text-offset": ["case", HAS_ICON, ["literal", [1.25, -1.05]], ["literal", [0.6, -0.5]]],
      "icon-image": BADGE,
      "icon-text-fit": "both",
      "icon-text-fit-padding": [0.5, 3.5, 0, 3.5],
      // the most seen signs keep their badge when they collide
      "symbol-sort-key": ["-", ["get", "seen"]],
      "text-padding": 1,
    },
    paint: { "text-color": "#ffffff" },
  });
}

/** The open picture: its camera, the signs it sees, the rays of the selected sign. */
function highlight(map: MapLibreMap, pictureId: string | null, seen: string[], sign: string | null) {
  const isSeen: ExpressionSpecification = ["in", ["get", "id"], ["literal", seen]];
  const isCamera: ExpressionSpecification = ["==", ["get", "pictureId"], pictureId ?? ""];
  const signOpacity: ExpressionSpecification | number = pictureId
    ? ["case", isSeen, 1, FADED]
    : 1;
  map.setPaintProperty("sign-discs", "circle-color", ["case", isSeen, SEEN, DISC_COLOR]);
  map.setPaintProperty("sign-discs", "circle-opacity", signOpacity);
  map.setPaintProperty("sign-discs", "circle-stroke-opacity", signOpacity);
  map.setPaintProperty("sign-shadows", "circle-opacity", pictureId ? ["case", isSeen, 0.28, 0.08] : 0.28);
  map.setPaintProperty("sign-icons", "icon-opacity", signOpacity);
  map.setPaintProperty("sign-labels", "text-opacity", signOpacity);
  map.setPaintProperty("sign-labels", "icon-opacity", signOpacity);
  const cameraOpacity: ExpressionSpecification | number = pictureId
    ? ["case", isCamera, 1, CAMERA_OPACITY / 2]
    : CAMERA_OPACITY;
  map.setPaintProperty("cameras", "circle-opacity", cameraOpacity);
  map.setPaintProperty("cameras", "circle-stroke-opacity", cameraOpacity);
  map.setFilter("rays-selected", ["==", ["get", "id"], sign ?? ""]);
  map.setFilter("sign-selected", ["==", ["get", "id"], sign ?? ""]);
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

async function getJson<T extends object>(url: string, signal?: AbortSignal): Promise<T> {
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
  for (let k = 0; k < missing.length; k += MAX_TILES) batches.push(missing.slice(k, k + MAX_TILES));
  await Promise.all(
    batches.map(async (asked) => {
      // sorted: the same tiles, the same URL, a hit of the HTTP cache
      const url = `${endpoint}?tiles=${asked.toSorted().join(",")}`;
      const body = await getJson<{ tiles: Record<string, T> }>(url, signal);
      if (signal.aborted) return;
      for (const [tile, value] of Object.entries(body.tiles)) store(tile, value);
      await onBatch();
    }),
  );
}

function errorStatus(error: unknown): MapStatus {
  return { kind: "error", message: error instanceof Error ? error.message : String(error) };
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

export function SignMap() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  // the basemap the map is drawn with now
  const appliedRef = useRef<Basemap | null>(null);
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
  const [picture, setPicture] = useState<{ id: string; detections: Detection[] } | null>(null);
  // bumped each time the style is (re)loaded: the layers are new, draw them again
  const [styleEpoch, setStyleEpoch] = useState(0);
  const basemap = useBasemap();

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
    await loadSignImages(map, signs.flatMap((s) => (s.icon ? [s.icon] : [])));
    if (mapRef.current !== map) return; // removed meanwhile (React's dev double mount)
    map.getSource<GeoJSONSource>("signs")?.setData(signPoints(signs));
    drawnRef.current.signs = key;
    locatedRef.current = signs;
    setLocated(signs);
  }, []);

  /** Draw the cached cameras of the view. */
  const renderCameras = useCallback((map: MapLibreMap) => {
    const b = map.getBounds();
    const near = tilesOf(b.getWest(), b.getSouth(), b.getEast(), b.getNorth()).filter((t) =>
      camerasRef.current.has(t),
    );
    const key = near.join(",");
    if (key === drawnRef.current.cameras) return;
    const cameras = near.flatMap((t) => camerasRef.current.get(t)!);
    map.getSource<GeoJSONSource>("cameras")?.setData(cameraPoints(cameras));
    drawnRef.current.cameras = key;
    setCameraCount(cameras.length);
  }, []);

  /** The located signs of the view, counted by squares: nothing is located. */
  const loadCounts = useCallback(async (map: MapLibreMap, signal: AbortSignal) => {
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
      // removed meanwhile, or another basemap loading: "style.load" draws again
      if (mapRef.current !== map || signal.aborted || !map.getSource("counts")) return;
      if (drawnRef.current.counts !== url) {
        map.removeFeatureState({ source: "counts" }); // the ids are new: no hover left behind
        map.getSource<GeoJSONSource>("counts")?.setData(countPoints(counts));
        drawnRef.current.counts = url;
      }
      const inView = counts.filter(([lon, lat]) => b.contains([lon, lat]));
      setStatus({ kind: "counts", signs: inView.reduce((sum, [, , n]) => sum + n, 0) });
    } catch (error) {
      if (!signal.aborted) setStatus(errorStatus(error));
    }
  }, []);

  const refresh = useCallback(
    async (map: MapLibreMap, signal: AbortSignal) => {
      if (map.getZoom() < DETAIL_ZOOM) {
        await loadCounts(map, signal);
        return; // the signs already drawn stay, shown again when zooming in
      }
      const b = map.getBounds();
      const inView = tilesOf(b.getWest(), b.getSouth(), b.getEast(), b.getNorth());
      renderCameras(map);
      await render(map);

      // the tiles never asked for: signs and cameras at once
      const missingSigns = inView.filter((t) => !tilesRef.current.has(t));
      const missingCameras = inView.filter((t) => !camerasRef.current.has(t));
      if (!missingSigns.length) setStatus({ kind: "ready" });
      else setStatus({ kind: "locating", pending: missingSigns.length, total: missingSigns.length });

      try {
        await Promise.all([
          fetchTiles<TileSign[]>(
            "/api/located",
            missingSigns,
            (tile, tileSigns) => tilesRef.current.set(tile, tileSigns.map(decode)),
            signal,
            async () => {
              const pending = missingSigns.filter((t) => !tilesRef.current.has(t)).length;
              if (pending) setStatus({ kind: "locating", pending, total: missingSigns.length });
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
            if (!signal.aborted) console.warn("Could not load the cameras:", error);
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
    const initial = currentBasemap();
    appliedRef.current = initial;
    const map = new maplibregl.Map({
      container: container.current,
      style: BASEMAPS[initial].style,
      center: FALLBACK_CENTER,
      zoom: FALLBACK_ZOOM,
      hash: true, // the view is kept in the URL: #zoom/lat/lon
      attributionControl: { compact: true }, // fits the inset map too
      fadeDuration: 150, // labels settle faster
      maxPitch: 60,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(
      new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true } }),
      "top-right",
    );
    map.addControl(new maplibregl.ScaleControl({}), "bottom-right");

    let controller = new AbortController();
    const reload = () => {
      controller.abort(); // only the last view keeps asking
      controller = new AbortController();
      void refresh(map, controller.signal);
    };

    map.on("styleimagemissing", (e) => addBlankImage(map, e.id));
    // the first style, and each basemap change: the layers of the map on top of it
    map.on("style.load", () => {
      addLayers(map, appliedRef.current === "dark");
      drawnRef.current = { signs: "", cameras: "", counts: "" };
      if (fitEurope) {
        // fitted once the container has its final size, not while the page lays out
        fitEurope = false;
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
    };
    for (const layer of SIGN_LAYERS) {
      map.on("click", layer, (e) => {
        e.preventDefault(); // not the camera below
        selectSign(e);
      });
    }

    // a sign under the pointer: bigger, and its name in a tooltip
    const tooltip = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: SIGN_DISC_PX + 6,
      className: "sign-tooltip",
      maxWidth: "260px",
    });
    let hoveredSign: string | undefined;
    const hoverSign = (id: string | undefined) => {
      if (id === hoveredSign) return;
      if (hoveredSign !== undefined && map.getSource("signs")) {
        map.setFeatureState({ source: "signs", id: hoveredSign }, { hover: false });
      }
      hoveredSign = id;
      const sign = id === undefined ? undefined : locatedRef.current.find((s) => s.id === id);
      if (!sign || id === undefined) {
        tooltip.remove();
        return;
      }
      map.setFeatureState({ source: "signs", id }, { hover: true });
      tooltip.setLngLat(sign.position).setDOMContent(tooltipOf(sign)).addTo(map);
    };
    map.on("mousemove", "sign-discs", (e) => hoverSign(e.features?.[0]?.properties.id as string));
    map.on("mouseleave", "sign-discs", () => hoverSign(undefined));
    map.on("movestart", () => hoverSign(undefined));

    // a square of counts -> zoomed in on it
    map.on("click", "count-circles", (e) => {
      const point = e.features?.[0]?.geometry as Point | undefined;
      if (!point) return;
      map.easeTo({
        center: point.coordinates as [number, number],
        zoom: Math.min(map.getZoom() + 3, DETAIL_ZOOM + 1),
      });
    });
    // the square under the pointer stands out
    let hover: number | string | undefined;
    const setHover = (id: number | string | undefined) => {
      if (hover !== undefined) map.setFeatureState({ source: "counts", id: hover }, { hover: false });
      hover = id;
      if (id !== undefined) map.setFeatureState({ source: "counts", id }, { hover: true });
    };
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
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }

    return () => {
      controller.abort();
      tooltip.remove();
      const { hash } = window.location;
      map.remove(); // also clears the #zoom/lat/lon of the URL
      // put it back: React's dev double mount then starts from the same view
      if (hash) window.history.replaceState(window.history.state, "", hash);
      mapRef.current = null;
    };
  }, [refresh]);

  // another basemap: the style is replaced, "style.load" puts the layers back
  useEffect(() => {
    const map = mapRef.current;
    // the hydration render holds the server's "light": only the browser's value counts
    if (!map || appliedRef.current === basemap || basemap !== currentBasemap()) return;
    appliedRef.current = basemap;
    map.setStyle(BASEMAPS[basemap].style, { diff: false });
  }, [basemap]);

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
    getJson<{ detections: Detection[] }>(`/api/pictures/${pictureId}`, controller.signal)
      .then((body) => setPicture({ id: pictureId, detections: body.detections }))
      .catch((error) => {
        if (!controller.signal.aborted) console.warn("Could not load the picture:", error);
      });
    return () => controller.abort();
  }, [pictureId]);
  const detections = picture?.id === pictureId ? picture.detections : NO_DETECTIONS;

  const boxes = useMemo(
    () => (pictureId ? boxesOf(pictureId, detections, located) : []),
    [pictureId, detections, located],
  );
  const labels = useMemo(
    () => Object.fromEntries(boxes.map((b) => [b.annotationId, b.label])),
    [boxes],
  );
  const seen = useMemo(
    () => located.filter((s) => s.rays.some((r) => r.pictureId === pictureId)).map((s) => s.id),
    [located, pictureId],
  );

  // the signs of the whole world: asked for once per page load
  useEffect(() => {
    const controller = new AbortController();
    getJson<TotalResponse>("/api/total", controller.signal)
      .then((body) => setTotal(body.total))
      .catch((error) => {
        if (!controller.signal.aborted) console.warn("Could not count the signs:", error);
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
    if (map && position) map.easeTo({ center: position, zoom: Math.max(map.getZoom(), INSET_ZOOM) });
  }, [pictureId, position]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("sign-discs")) highlight(map, pictureId, seen, signId);
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
      if (mapRef.current?.getSource("view") && position) setView(mapRef.current, position, bearing);
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

  const busy = status.kind === "loading" || status.kind === "locating";
  const progress =
    status.kind === "locating" ? 1 - status.pending / Math.max(status.total, 1) : null;

  return (
    // phones: the panel below the map; wider screens: floating over it
    <div className="relative flex h-full w-full flex-col overflow-hidden md:block">
      <div className="relative min-h-0 flex-1 md:absolute md:inset-0">
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
                "map-inset absolute right-2 bottom-12 z-10 h-[min(16rem,35%)] w-[min(24rem,50%)] overflow-hidden rounded-xl shadow-2xl ring-2 ring-white/90 md:right-4 md:bottom-14 md:h-[min(16rem,40%)] md:w-[min(24rem,calc(100%-2rem))]"
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
              <div className="loading-bar h-full w-1/3 bg-accent" />
            ) : (
              <div
                className="h-full bg-accent transition-[width] duration-300"
                style={{ width: `${Math.max(progress, 0.08) * 100}%` }}
              />
            )}
          </div>
          {selected && (
            <button
              type="button"
              onClick={onClose}
              className="absolute top-2 left-2 rounded-md bg-surface px-2 py-1 text-xs font-medium shadow-md backdrop-blur hover:bg-background"
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
        basemap={basemap}
        onBasemap={setBasemapChoice}
      />
    </div>
  );
}
