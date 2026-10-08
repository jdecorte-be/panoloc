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
import { byTier } from "@/lib/counts";
import { boxesOf } from "@/lib/labels";
import {
  addBlankImage,
  addViewConeImage,
  ICON_PREFIX,
  ICON_PX,
  loadSignImages,
  VIEW_CONE,
} from "@/lib/sign-images";
import { MAX_TILES, TILE_DEG, tilesOf } from "@/lib/tiles";
import type {
  CamerasResponse,
  CountsResponse,
  Detection,
  LocatedResponse,
  LocatedSign,
  Selection,
  SignRay,
  TileSign,
} from "@/lib/types";

// WebGL viewer: browser only
const Panorama = dynamic(() => import("@/components/panorama").then((m) => m.Panorama), {
  ssr: false,
});

// free vector basemap, no API key
const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
// Strasbourg, the default picture of the Streamlit app
const INITIAL_CENTER: [number, number] = [7.741354, 48.589898];
const INITIAL_ZOOM = 17;
// below that a view has too many tiles to locate: the signs are counted instead
const DETAIL_ZOOM = 16;
// width of a square of counted signs on the screen, about
const COUNT_PX = 120;
// zoom of the inset map around the camera of the 360° view
const INSET_ZOOM = 18;
const FADED = 0.3;
// colors of the Streamlit map (heading_map.py)
const CURRENT = "rgb(230, 80, 40)"; // the camera of the open picture
const SEEN = "rgb(255, 140, 0)"; // the signs it sees, orange like its boxes
const CAMERA = "rgb(120, 120, 120)";
// radius of the disc behind a pictogram, of the dot of a sign without one
const SIGN_DISC_PX = ICON_PX / 2 + 3;
const SIGN_DOT_PX = 5;

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
      properties: { id: s.id, label: `#${s.number}`, ...(s.icon && { icon: s.icon }) },
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
  return 2 ** Math.max(0, Math.round(Math.log2(deg / TILE_DEG)));
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

function addLayers(map: MapLibreMap) {
  for (const id of ["cameras", "rays", "signs", "view"]) {
    map.addSource(id, { type: "geojson", data: EMPTY });
  }
  map.addSource("counts", { type: "geojson", data: EMPTY, generateId: true });
  // zoomed out: the signs counted by squares, the area growing with the count,
  // the biggest drawn on top
  const hovered: ExpressionSpecification = ["boolean", ["feature-state", "hover"], false];
  map.addLayer({
    id: "count-halos",
    type: "circle",
    source: "counts",
    maxzoom: DETAIL_ZOOM,
    layout: { "circle-sort-key": ["get", "count"] },
    paint: {
      "circle-radius": ["+", COUNT_RADIUS, ["case", hovered, 9, 6]],
      "circle-color": byTier("fill"),
      "circle-opacity": ["case", hovered, 0.35, 0.2],
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
      "circle-stroke-color": "#ffffff",
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
    layout: { visibility: "none" },
    paint: { "line-color": CAMERA, "line-width": 1, "line-opacity": 0.6 },
  });
  map.addLayer({
    id: "rays-selected",
    type: "line",
    source: "rays",
    minzoom: DETAIL_ZOOM,
    filter: ["==", ["get", "id"], ""],
    paint: { "line-color": SEEN, "line-width": 2 },
  });
  map.addLayer({
    id: "cameras",
    type: "circle",
    source: "cameras",
    minzoom: DETAIL_ZOOM,
    paint: {
      "circle-radius": 4,
      "circle-color": CAMERA,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1,
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
      "circle-stroke-width": 2,
    },
  });
  // a disc behind each pictogram (readable on the map), a dot without
  map.addLayer({
    id: "sign-discs",
    type: "circle",
    source: "signs",
    minzoom: DETAIL_ZOOM,
    paint: {
      "circle-radius": ["case", ["has", "icon"], SIGN_DISC_PX, SIGN_DOT_PX],
      "circle-color": "#ffffff",
      "circle-stroke-color": "rgba(0, 0, 0, 0.35)",
      "circle-stroke-width": 1,
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
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
  });
  map.addLayer({
    id: "sign-labels",
    type: "symbol",
    source: "signs",
    minzoom: DETAIL_ZOOM,
    layout: {
      "text-field": ["get", "label"],
      "text-font": ["Noto Sans Bold"],
      "text-size": 12,
      "text-anchor": "bottom",
      "text-offset": ["case", ["has", "icon"], ["literal", [0, -1.6]], ["literal", [0, -0.6]]],
    },
    paint: { "text-color": "#141414", "text-halo-color": "#ffffff", "text-halo-width": 2 },
  });
}

/** The open picture: its camera, the signs it sees, the rays of the selected sign. */
function highlight(map: MapLibreMap, pictureId: string | null, seen: string[], sign: string | null) {
  const isSeen: ExpressionSpecification = ["in", ["get", "id"], ["literal", seen]];
  const isCamera: ExpressionSpecification = ["==", ["get", "pictureId"], pictureId ?? ""];
  const signOpacity: ExpressionSpecification | number = pictureId
    ? ["case", isSeen, 1, FADED]
    : 1;
  map.setPaintProperty("sign-discs", "circle-color", ["case", isSeen, SEEN, "#ffffff"]);
  map.setPaintProperty("sign-discs", "circle-opacity", signOpacity);
  map.setPaintProperty("sign-icons", "icon-opacity", signOpacity);
  map.setPaintProperty("sign-labels", "text-opacity", signOpacity);
  map.setPaintProperty("cameras", "circle-opacity", pictureId ? ["case", isCamera, 1, FADED] : 1);
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

async function getJson<T extends object>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  const body = (await res.json()) as T | { error: string };
  if ("error" in body) throw new Error(body.error);
  return body;
}

export function SignMap() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  // tile "i:j" -> its signs: a tile is asked for once per page load
  const tilesRef = useRef(new Map<string, CachedSign[]>());
  // the map's click handlers are bound once: they read the latest signs here
  const locatedRef = useRef<LocatedSign[]>([]);
  const [status, setStatus] = useState<MapStatus>({ kind: "loading" });
  const [located, setLocated] = useState<LocatedSign[]>([]);
  const [cameraCount, setCameraCount] = useState(0);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [showRays, setShowRays] = useState(false);
  const [picture, setPicture] = useState<{ id: string; detections: Detection[] } | null>(null);

  /** Draw the cached signs of the view, and one tile around: no gap while panning. */
  const render = useCallback(async (map: MapLibreMap) => {
    const b = map.getBounds();
    const near = tilesOf(
      b.getWest() - TILE_DEG,
      b.getSouth() - TILE_DEG,
      b.getEast() + TILE_DEG,
      b.getNorth() + TILE_DEG,
    );
    const signs = numbered(near.flatMap((t) => tilesRef.current.get(t) ?? []));
    await loadSignImages(map, signs.flatMap((s) => (s.icon ? [s.icon] : [])));
    if (mapRef.current !== map) return; // removed meanwhile (React's dev double mount)
    map.getSource<GeoJSONSource>("signs")?.setData(signPoints(signs));
    locatedRef.current = signs;
    setLocated(signs);
  }, []);

  const loadCameras = useCallback(async (map: MapLibreMap, bbox: string, signal: AbortSignal) => {
    try {
      const body = await getJson<CamerasResponse>(`/api/cameras?bbox=${bbox}`, signal);
      if (mapRef.current !== map) return;
      map.getSource<GeoJSONSource>("cameras")?.setData({
        type: "FeatureCollection",
        features: body.cameras.map(([pictureId, lon, lat]) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [lon, lat] },
          properties: { pictureId },
        })),
      });
      setCameraCount(body.cameras.length);
    } catch (error) {
      if (!signal.aborted) console.warn("Could not load the cameras:", error);
    }
  }, []);

  /** The located signs of the view, counted by squares: nothing is located. */
  const loadCounts = useCallback(async (map: MapLibreMap, signal: AbortSignal) => {
    const size = countSize(map.getZoom());
    // one square around: no square cut by the edge of the view
    const pad = size * TILE_DEG;
    const b = map.getBounds();
    const bbox = [
      Math.max(b.getWest() - pad, -180),
      Math.max(b.getSouth() - pad, -90),
      Math.min(b.getEast() + pad, 180),
      Math.min(b.getNorth() + pad, 90),
    ];
    try {
      const body = await getJson<CountsResponse>(
        `/api/counts?bbox=${bbox.map((v) => v.toFixed(6)).join(",")}&size=${size}`,
        signal,
      );
      if (mapRef.current !== map) return;
      map.removeFeatureState({ source: "counts" }); // the ids are new: no hover left behind
      map.getSource<GeoJSONSource>("counts")?.setData(countPoints(body.counts));
      const inView = body.counts.filter(([lon, lat]) => b.contains([lon, lat]));
      setStatus({ kind: "counts", signs: inView.reduce((sum, [, , n]) => sum + n, 0) });
    } catch (error) {
      if (signal.aborted) return;
      setStatus({
        kind: "error",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }, []);

  const refresh = useCallback(
    async (map: MapLibreMap, signal: AbortSignal) => {
      if (map.getZoom() < DETAIL_ZOOM) {
        await loadCounts(map, signal);
        return; // the signs already drawn stay, shown again when zooming in
      }
      const b = map.getBounds();
      const [w, s, e, n] = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
      void loadCameras(map, [w, s, e, n].map((v) => v.toFixed(6)).join(","), signal);
      await render(map);

      // the tiles never asked for, at most MAX_TILES per request
      let missing = tilesOf(w, s, e, n).filter((t) => !tilesRef.current.has(t));
      try {
        while (missing.length && !signal.aborted) {
          setStatus({ kind: "locating", pending: missing.length });
          const asked = missing.slice(0, MAX_TILES);
          const body = await getJson<LocatedResponse>(
            `/api/located?tiles=${asked.join(",")}`,
            signal,
          );
          for (const [tile, signs] of Object.entries(body.tiles)) {
            tilesRef.current.set(tile, signs.map(decode));
          }
          await render(map);
          missing = missing.slice(MAX_TILES);
        }
        if (!signal.aborted) setStatus({ kind: "ready" });
      } catch (error) {
        if (signal.aborted) return;
        setStatus({
          kind: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      }
    },
    [render, loadCameras, loadCounts],
  );

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: STYLE_URL,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      hash: true, // the view is kept in the URL: #zoom/lat/lon
      attributionControl: { compact: true }, // fits the inset map too
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.GeolocateControl({}), "top-right");
    map.addControl(new maplibregl.ScaleControl({}), "bottom-right");

    let controller = new AbortController();
    const reload = () => {
      controller.abort(); // only the last view keeps asking
      controller = new AbortController();
      void refresh(map, controller.signal);
    };

    map.on("styleimagemissing", (e) => addBlankImage(map, e.id));
    map.on("load", () => {
      addLayers(map);
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
    for (const layer of ["sign-discs", "sign-icons", "sign-labels"]) {
      map.on("click", layer, (e) => {
        e.preventDefault(); // not the camera below
        selectSign(e);
      });
    }
    // a square of counts -> zoomed in on it
    const zoomIn = (e: { features?: MapGeoJSONFeature[] }) => {
      const point = e.features?.[0]?.geometry as Point | undefined;
      if (!point) return;
      map.easeTo({
        center: point.coordinates as [number, number],
        zoom: Math.min(map.getZoom() + 3, DETAIL_ZOOM + 1),
      });
    };
    map.on("click", "count-circles", zoomIn);
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
    for (const layer of [
      "sign-discs",
      "sign-icons",
      "sign-labels",
      "cameras",
      "count-circles",
    ]) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }

    return () => {
      controller.abort();
      const { hash } = window.location;
      map.remove(); // also clears the #zoom/lat/lon of the URL
      // put it back: React's dev double mount then starts from the same view
      if (hash) window.history.replaceState(window.history.state, "", hash);
      mapRef.current = null;
    };
  }, [refresh]);

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

  // full map <-> inset map centered on the camera of the 360° view
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.resize(); // its box just changed
    if (!map.getLayer("sign-discs")) return; // style not loaded yet
    setView(map, position ?? null);
    if (position) map.easeTo({ center: position, zoom: Math.max(map.getZoom(), INSET_ZOOM) });
  }, [pictureId, position]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("sign-discs")) highlight(map, pictureId, seen, signId);
  }, [pictureId, seen, signId]);

  // rays: all of them only when asked for, else those of the selected sign
  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer("rays")) return;
    map.setLayoutProperty("rays", "visibility", showRays ? "visible" : "none");
    const drawn = showRays ? located : located.filter((s) => s.id === signId);
    map.getSource<GeoJSONSource>("rays")?.setData(rayLines(drawn));
  }, [showRays, located, signId]);

  useEffect(() => {
    if (!pictureId) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSelected(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pictureId]);

  const onBearing = useCallback(
    (bearing: number | null) => {
      if (mapRef.current && position) setView(mapRef.current, position, bearing);
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
                "absolute right-2 bottom-12 z-10 h-[min(16rem,35%)] w-[min(24rem,50%)] overflow-hidden rounded-lg shadow-xl ring-2 ring-white/80 md:right-4 md:bottom-14 md:h-[min(16rem,40%)] md:w-[min(24rem,calc(100%-2rem))] [&_.maplibregl-ctrl-top-right]:hidden"
              : "absolute inset-0"
          }
        >
          {/* sized, not positioned: maplibre-gl.css makes it position: relative */}
          <div ref={container} className="h-full w-full" />
          {selected && (
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="absolute top-2 left-2 rounded bg-surface px-2 py-1 text-xs font-medium shadow hover:bg-background"
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
        selected={selected}
        boxes={boxes}
        showRays={showRays}
        onShowRays={setShowRays}
        onFocus={onFocus}
        onPicture={onPicture}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
