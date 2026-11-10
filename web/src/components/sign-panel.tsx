"use client";

import { memo, type ReactNode, useMemo, useState } from "react";

import { SignIcon } from "@/components/sign-icon";
import { BASEMAPS, type Basemap } from "@/lib/basemaps";
import { COUNT_TIERS } from "@/lib/counts";
import { signLabel, type Box } from "@/lib/labels";
import { VIEWER } from "@/lib/panoramax";
import type { LocatedSign, Selection, SignRay } from "@/lib/types";

// sign types listed in the legend, the most located first
const LEGEND_SIZE = 10;
// pictures listed for a sign before "show all", the nearest first
const RAYS_SHOWN = 8;
const NUMBER = new Intl.NumberFormat("en");

export type MapStatus =
  | { kind: "loading" }
  | { kind: "counts"; signs: number }
  | { kind: "locating"; pending: number; total: number }
  | { kind: "ready" }
  | { kind: "error"; message: string };

const SECTION = "mt-4 border-t border-line pt-4";
const HEADING = "mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase";
// taller on touch screens
const ROW =
  "flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left transition-colors hover:bg-line/60 md:py-1.5";
const ROW_ACTIVE = " bg-accent/10 font-medium text-accent hover:bg-accent/15";

function Logo() {
  return (
    <svg viewBox="0 0 24 24" className="size-7 shrink-0" aria-hidden>
      <rect width="24" height="24" rx="7" className="fill-accent" />
      <path
        d="M12 5.5a4.5 4.5 0 0 0-4.5 4.5c0 3.2 4.5 8.5 4.5 8.5s4.5-5.3 4.5-8.5A4.5 4.5 0 0 0 12 5.5Z"
        fill="white"
      />
      <circle cx="12" cy="10" r="1.7" className="fill-accent" />
    </svg>
  );
}

function Stat({ value, label, live }: { value: string; label: string; live?: boolean }) {
  return (
    <div className="min-w-0 flex-1 rounded-lg bg-line/50 px-3 py-2">
      <p
        className="truncate text-lg leading-tight font-semibold tabular-nums"
        aria-live={live ? "polite" : undefined}
      >
        {value}
      </p>
      <p className="truncate text-[11px] text-muted">{label}</p>
    </div>
  );
}

function Stats({
  status,
  signs,
  cameras,
  total,
}: {
  status: MapStatus;
  signs: number;
  cameras: number;
  total: number | null;
}) {
  if (status.kind === "error") {
    return (
      <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-red-700 dark:text-red-300">
        {status.message}
      </p>
    );
  }
  const world = total === null ? "…" : NUMBER.format(total);
  if (status.kind === "counts") {
    return (
      <div className="mt-3 flex gap-2">
        <Stat value={NUMBER.format(status.signs)} label="signs in view" live />
        <Stat value={world} label="signs worldwide" />
      </div>
    );
  }
  return (
    <>
      <div className="mt-3 flex gap-2">
        <Stat value={status.kind === "loading" ? "…" : NUMBER.format(signs)} label="signs in view" live />
        <Stat value={NUMBER.format(cameras)} label="pictures" />
        <Stat value={world} label="worldwide" />
      </div>
      {status.kind === "locating" && (
        <p className="mt-1.5 text-xs text-muted">
          Loading {status.pending} more {status.pending === 1 ? "tile" : "tiles"}…
        </p>
      )}
    </>
  );
}

function Toggle({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
}) {
  return (
    <label className="mt-3 flex cursor-pointer items-center justify-between gap-3 text-xs select-none">
      {children}
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="peer sr-only"
      />
      <span
        aria-hidden
        className="relative h-5 w-9 shrink-0 rounded-full bg-line transition-colors peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent/50 after:absolute after:top-0.5 after:left-0.5 after:size-4 after:rounded-full after:bg-white after:shadow after:transition-transform peer-checked:after:translate-x-4"
      />
    </label>
  );
}

function BasemapPicker({
  basemap,
  onBasemap,
}: {
  basemap: Basemap;
  onBasemap: (b: Basemap) => void;
}) {
  return (
    <div className="mt-3" role="radiogroup" aria-label="Basemap">
      <div className="grid grid-cols-4 gap-0.5 rounded-lg bg-line/60 p-0.5 text-xs">
        {(Object.keys(BASEMAPS) as Basemap[]).map((key) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={key === basemap}
            onClick={() => onBasemap(key)}
            className={
              "rounded-md px-1.5 py-1 font-medium transition-colors " +
              (key === basemap
                ? "bg-background text-foreground shadow-sm"
                : "text-muted hover:text-foreground")
            }
          >
            {BASEMAPS[key].label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** The colors of the counted squares, and what a click does. */
function CountLegend() {
  return (
    <section className={SECTION}>
      <h2 className={HEADING}>Signs per area</h2>
      <ul className="flex flex-wrap gap-x-3 gap-y-1.5 text-xs">
        {COUNT_TIERS.map((t) => (
          <li key={t.min} className="flex items-center gap-1.5">
            <span
              className="size-3 rounded-full ring-2 ring-white dark:ring-white/80"
              style={{ backgroundColor: t.fill }}
            />
            {t.label}
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-xs text-muted">Click a group to zoom in on its signs.</p>
    </section>
  );
}

const Legend = memo(function Legend({ located }: { located: LocatedSign[] }) {
  const top = useMemo(
    () =>
      [...Map.groupBy(located, (s) => s.sign).values()]
        .sort((a, b) => b.length - a.length)
        .slice(0, LEGEND_SIZE),
    [located],
  );
  if (!top.length) return null;
  const max = top[0].length;
  return (
    <section className={SECTION}>
      <h2 className={HEADING}>Most common in view</h2>
      <ul className="space-y-1.5">
        {top.map((group) => {
          const s = group[0];
          return (
            <li key={s.sign} className="flex items-center gap-2.5">
              <SignIcon icon={s.icon} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="min-w-0 flex-1 truncate" title={`${s.name} (${s.sign})`}>
                    {s.name}
                  </span>
                  <span className="text-xs text-muted tabular-nums">{group.length}</span>
                </div>
                <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-line/70">
                  <div
                    className="h-full rounded-full bg-accent/70"
                    style={{ width: `${(group.length / max) * 100}%` }}
                  />
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-muted">Click a sign on the map to see it in 360°.</p>
    </section>
  );
});

/** The sign the view was opened for, and the pictures that see it. */
function SignSection({
  sign,
  pictureId,
  onPicture,
}: {
  sign: LocatedSign;
  pictureId: string;
  onPicture: (ray: SignRay) => void;
}) {
  const [all, setAll] = useState(false);
  const rays = all ? sign.rays : sign.rays.slice(0, RAYS_SHOWN);
  return (
    <section className={SECTION}>
      <div className="flex items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-white shadow-sm ring-1 ring-black/5">
          <SignIcon icon={sign.icon} />
        </span>
        <div className="min-w-0">
          <h2 className="truncate font-semibold">{signLabel(sign.number, sign.name)}</h2>
          <p className="text-xs text-muted">
            <code className="font-mono">{sign.sign}</code> · seen in {sign.rays.length}{" "}
            {sign.rays.length === 1 ? "picture" : "pictures"}
          </p>
        </div>
      </div>
      <ul className="mt-3 space-y-0.5">
        {rays.map((r) => {
          const active = r.pictureId === pictureId;
          return (
            <li key={`${r.pictureId}:${r.annotationId}`}>
              <button
                type="button"
                onClick={() => onPicture(r)}
                aria-pressed={active}
                className={ROW + (active ? ROW_ACTIVE : "")}
              >
                <span
                  className={
                    "size-1.5 shrink-0 rounded-full " + (active ? "bg-accent" : "bg-muted/50")
                  }
                />
                <span className="flex-1">{r.distance.toFixed(0)} m away</span>
                <span className="text-xs text-muted tabular-nums">{r.bearing.toFixed(0)}°</span>
              </button>
            </li>
          );
        })}
      </ul>
      {sign.rays.length > rays.length && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="mt-1 px-2 text-xs font-medium text-accent hover:underline"
        >
          Show all {sign.rays.length} pictures
        </button>
      )}
    </section>
  );
}

/** The boxes of the open picture. */
function PictureSection({
  selected,
  boxes,
  onFocus,
}: {
  selected: Selection;
  boxes: Box[];
  onFocus: (annotationId: string) => void;
}) {
  return (
    <section className={SECTION}>
      <h2 className={HEADING}>In this picture</h2>
      {boxes.length > 0 && (
        <ul className="space-y-0.5">
          {boxes.map((b) => {
            const active = b.annotationId === selected.focus;
            return (
              <li key={b.annotationId}>
                <button
                  type="button"
                  onClick={() => onFocus(b.annotationId)}
                  aria-pressed={active}
                  className={ROW + (active ? ROW_ACTIVE : "")}
                >
                  <SignIcon icon={b.icon} />
                  <span className="min-w-0 flex-1">{b.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <a
        href={`${VIEWER}?pic=${selected.pictureId}`}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-3 inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-opacity hover:opacity-90"
      >
        Open in Panoramax ↗
      </a>
    </section>
  );
}

interface SignPanelProps {
  status: MapStatus;
  located: LocatedSign[];
  cameras: number;
  /** the signs of the whole world, once counted */
  total: number | null;
  selected: Selection | null;
  boxes: Box[];
  showRays: boolean;
  onShowRays: (show: boolean) => void;
  onFocus: (annotationId: string) => void;
  onPicture: (ray: SignRay) => void;
  onClose: () => void;
  basemap: Basemap;
  onBasemap: (basemap: Basemap) => void;
}

export function SignPanel({
  status,
  located,
  cameras,
  total,
  selected,
  boxes,
  showRays,
  onShowRays,
  onFocus,
  onPicture,
  onClose,
  basemap,
  onBasemap,
}: SignPanelProps) {
  // phones: a bottom sheet below the map, its details folded away by default
  const [expanded, setExpanded] = useState(false);
  const details = expanded ? "" : " max-md:hidden";
  const sign = selected && located.find((s) => s.id === selected.sign);
  return (
    <aside className="panel relative z-10 max-h-[50dvh] shrink-0 overflow-y-auto border-t border-line bg-surface px-4 py-3 text-sm backdrop-blur-xl md:absolute md:top-4 md:left-4 md:max-h-[calc(100%-2rem)] md:w-[min(21rem,calc(100%-5rem))] md:rounded-2xl md:border md:p-4 md:shadow-2xl">
      <div className="flex items-center gap-2.5">
        <Logo />
        <div className="min-w-0 flex-1">
          <h1 className="text-base leading-tight font-semibold tracking-tight">panoloc</h1>
          <p className="truncate text-[11px] text-muted">Traffic signs, precisely located</p>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          className="rounded-md px-2 py-1 text-xs font-medium text-accent hover:bg-line md:hidden"
        >
          {expanded ? "Less ▾" : "More ▴"}
        </button>
        {selected && (
          <button
            type="button"
            onClick={onClose}
            className="grid size-7 place-items-center rounded-md text-muted transition-colors hover:bg-line hover:text-foreground"
            aria-label="Close the 360° view (Esc)"
            title="Close the 360° view (Esc)"
          >
            ✕
          </button>
        )}
      </div>
      <p className={"mt-2 text-xs leading-relaxed text-muted" + details}>
        Each sign stands where it is triangulated from the{" "}
        <a
          href="https://panoramax.fr"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:underline"
        >
          Panoramax
        </a>{" "}
        pictures that see it.
      </p>
      <Stats status={status} signs={located.length} cameras={cameras} total={total} />
      <div className={details}>
        {!selected && <BasemapPicker basemap={basemap} onBasemap={onBasemap} />}
        {status.kind !== "counts" && (
          <Toggle checked={showRays} onChange={onShowRays}>
            Show the rays from the cameras
          </Toggle>
        )}
        {selected ? (
          <>
            {sign && (
              <SignSection
                key={sign.id}
                sign={sign}
                pictureId={selected.pictureId}
                onPicture={onPicture}
              />
            )}
            <PictureSection selected={selected} boxes={boxes} onFocus={onFocus} />
            <p className="mt-3 text-[11px] text-muted max-md:hidden">
              <kbd className="rounded border border-line px-1 font-mono">Esc</kbd> returns to the
              full map.
            </p>
          </>
        ) : status.kind === "counts" ? (
          <CountLegend />
        ) : (
          <Legend located={located} />
        )}
      </div>
    </aside>
  );
}
