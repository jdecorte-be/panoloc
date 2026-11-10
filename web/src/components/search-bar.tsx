"use client";

import { useEffect, useId, useRef, useState } from "react";

/** A place found: a point, and the box it spans when it is more than a point. */
export type Place = {
  name: string;
  detail: string;
  center: [number, number];
  /** west, south, east, north */
  bounds?: [number, number, number, number];
};

type PhotonFeature = {
  geometry: { coordinates: [number, number] };
  properties: {
    name?: string;
    street?: string;
    housenumber?: string;
    city?: string;
    county?: string;
    state?: string;
    country?: string;
    // west, north, east, south
    extent?: [number, number, number, number];
  };
};

// Photon (komoot): OpenStreetMap's places, typed as you go, no API key
const PHOTON = "https://photon.komoot.io/api/";
const DEBOUNCE_MS = 250;

function placeOf({ geometry, properties: p }: PhotonFeature): Place {
  const street = [p.housenumber, p.street].filter(Boolean).join(" ");
  const name = p.name ?? (street || p.city || p.country || "?");
  const detail = [
    street !== name && street,
    p.city !== name && p.city,
    p.country,
  ]
    .filter(Boolean)
    .join(", ");
  const e = p.extent;
  return {
    name,
    detail,
    center: geometry.coordinates,
    bounds: e && [e[0], e[3], e[2], e[1]],
  };
}

export function SearchBar({
  near,
  onPick,
}: {
  /** the center of the map: the places near it first */
  near: () => [number, number] | undefined;
  onPick: (place: Place) => void;
}) {
  const [query, setQuery] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(false);
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const q = query.trim();
    // too short: no request, the list is hidden
    if (q.length < 2) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      const params = new URLSearchParams({ q, limit: "6" });
      const center = near();
      if (center) {
        params.set("lon", center[0].toFixed(4));
        params.set("lat", center[1].toFixed(4));
      }
      try {
        const response = await fetch(`${PHOTON}?${params}`, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Photon: ${response.status}`);
        const body = (await response.json()) as { features: PhotonFeature[] };
        setPlaces(body.features.map(placeOf));
        setActive(0);
        setError(false);
      } catch {
        if (!controller.signal.aborted) setError(true);
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, near]);

  const pick = (place: Place) => {
    onPick(place);
    setQuery(place.name);
    setOpen(false);
    input.current?.blur();
  };

  const shown = open && query.trim().length >= 2;

  return (
    <div className="search-bar absolute top-2 right-14 left-2 z-20 md:top-3 md:right-auto md:left-3 md:w-[min(19rem,calc(100%-5rem))]">
      <div className="flex items-center gap-2 rounded border border-line bg-surface px-2.5 shadow-md focus-within:ring-2 focus-within:ring-accent/40">
        <svg
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          className="shrink-0 text-muted"
          aria-hidden
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          ref={input}
          type="search"
          value={query}
          placeholder="Search a place"
          aria-label="Search a place"
          role="combobox"
          aria-expanded={shown && places.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
          spellCheck={false}
          className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              if (!places.length) return;
              const step = e.key === "ArrowDown" ? 1 : -1;
              setActive((i) => (i + step + places.length) % places.length);
              setOpen(true);
            } else if (e.key === "Enter" && places[active]) {
              e.preventDefault();
              pick(places[active]);
            } else if (e.key === "Escape") {
              // not the Escape that closes the 360° view
              e.stopPropagation();
              setOpen(false);
            }
          }}
        />
      </div>
      {shown && (places.length > 0 || error) && (
        <ul
          id={listId}
          role="listbox"
          className="mt-1 overflow-hidden rounded border border-line bg-surface py-1 text-sm shadow-md"
        >
          {error && !places.length ? (
            <li className="px-3 py-2 text-muted">
              The search is unavailable for now.
            </li>
          ) : (
            places.map((place, i) => (
              <li
                key={`${place.center.join(",")}-${i}`}
                role="option"
                aria-selected={i === active}
                className={
                  "cursor-pointer px-3 py-1.5 " +
                  (i === active ? "bg-line/60" : "")
                }
                // before the input's blur closes the list
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(place);
                }}
                onMouseEnter={() => setActive(i)}
              >
                <div className="truncate font-medium">{place.name}</div>
                {place.detail && (
                  <div className="truncate text-xs text-muted">
                    {place.detail}
                  </div>
                )}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
