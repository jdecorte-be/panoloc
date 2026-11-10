"use client";

import { useSyncExternalStore } from "react";

import { type Basemap, isBasemap } from "@/lib/basemaps";

// The basemap the viewer picked, kept in this browser; none: it follows the color scheme.
const KEY = "panoloc:basemap";
const DARK = "(prefers-color-scheme: dark)";
const listeners = new Set<() => void>();
// the choice when storage is blocked: kept until the page is reloaded
let memory: Basemap | null = null;

function readChoice(): Basemap | null {
  try {
    const value = localStorage.getItem(KEY);
    return isBasemap(value) ? value : null;
  } catch {
    return null; // storage blocked
  }
}

export function setBasemapChoice(basemap: Basemap): void {
  try {
    localStorage.setItem(KEY, basemap);
  } catch {
    memory = basemap;
  }
  for (const l of listeners) l();
}

/** The basemap to draw now: the viewer's choice, else light or dark as the system. */
export function currentBasemap(): Basemap {
  return readChoice() ?? memory ?? (window.matchMedia(DARK).matches ? "dark" : "light");
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const media = window.matchMedia(DARK);
  media.addEventListener("change", listener);
  return () => {
    listeners.delete(listener);
    media.removeEventListener("change", listener);
  };
}

export function useBasemap(): Basemap {
  return useSyncExternalStore(subscribe, currentBasemap, () => "light");
}
