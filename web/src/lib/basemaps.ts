import type { StyleSpecification } from "maplibre-gl";

// The label fonts of every basemap, and of the layers of the map: OpenFreeMap's.
const GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";

// the standard OpenStreetMap tiles, no API key
const OSM_RASTER: StyleSpecification = {
  version: 8,
  glyphs: GLYPHS,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

export const BASEMAPS = {
  // muted vector basemaps (OpenFreeMap, no API key): the signs stand out
  light: { label: "Light", style: "https://tiles.openfreemap.org/styles/positron" },
  dark: { label: "Dark", style: "https://tiles.openfreemap.org/styles/dark" },
  streets: { label: "Streets", style: "https://tiles.openfreemap.org/styles/liberty" },
  osm: { label: "OSM", style: OSM_RASTER },
} as const satisfies Record<string, { label: string; style: string | StyleSpecification }>;

export type Basemap = keyof typeof BASEMAPS;

export const isBasemap = (v: unknown): v is Basemap =>
  typeof v === "string" && Object.hasOwn(BASEMAPS, v);

/** The basemap drawn under dark labels: the colors of the layers follow it. */
export const isDarkBasemap = (b: Basemap) => b === "dark";
