"use client";

import { useState } from "react";

import { SignIcon } from "@/components/sign-icon";
import { signLabel, type Box } from "@/lib/labels";
import { VIEWER } from "@/lib/panoramax";
import type { LocatedSign, Selection, SignRay } from "@/lib/types";

// sign types listed in the legend, the most located first
const LEGEND_SIZE = 12;
// pictures listed for a sign before "show all", the nearest first
const RAYS_SHOWN = 8;

export type MapStatus =
  | { kind: "loading" }
  | { kind: "zoom"; minZoom: number }
  | { kind: "locating"; pending: number }
  | { kind: "ready" }
  | { kind: "error"; message: string };

function StatusLine({
  status,
  signs,
  cameras,
}: {
  status: MapStatus;
  signs: number;
  cameras: number;
}) {
  if (status.kind === "error") {
    return <p className="text-red-600 dark:text-red-400">{status.message}</p>;
  }
  if (status.kind === "zoom") {
    return <p className="text-muted">Zoom in (level {status.minZoom}+) to locate the signs.</p>;
  }
  return (
    <p>
      <strong>{signs}</strong> signs located from {cameras} pictures
      {status.kind === "locating" && (
        <span className="text-muted"> · locating {status.pending} more tiles…</span>
      )}
    </p>
  );
}

function Legend({ located }: { located: LocatedSign[] }) {
  const top = [...Map.groupBy(located, (s) => s.sign).values()]
    .sort((a, b) => b.length - a.length)
    .slice(0, LEGEND_SIZE);
  if (!top.length) return null;
  return (
    <ul className="mt-3 space-y-1 border-t border-line pt-3">
      {top.map(([s, ...rest]) => (
        <li key={s.sign} className="flex items-center gap-2">
          <SignIcon icon={s.icon} />
          <span className="min-w-0 flex-1 truncate" title={`${s.name} (${s.sign})`}>
            {s.name}
          </span>
          <span className="tabular-nums text-muted">{rest.length + 1}</span>
        </li>
      ))}
    </ul>
  );
}

// taller on touch screens
const ROW = "flex w-full items-center gap-2 rounded px-1.5 py-2 text-left hover:bg-line md:py-1";

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
    <section className="mt-3 border-t border-line pt-3">
      <h2 className="flex items-center gap-2 font-semibold">
        <SignIcon icon={sign.icon} />
        {signLabel(sign.number, sign.name)}
      </h2>
      <p className="mt-1 text-xs text-muted">
        <code>{sign.sign}</code> · seen in {sign.rays.length} pictures
      </p>
      <ul className="mt-2 space-y-0.5">
        {rays.map((r) => (
          <li key={`${r.pictureId}:${r.annotationId}`}>
            <button
              type="button"
              onClick={() => onPicture(r)}
              aria-pressed={r.pictureId === pictureId}
              className={ROW + (r.pictureId === pictureId ? " bg-line font-medium" : "")}
            >
              <span className="flex-1">Picture {r.distance.toFixed(0)} m away</span>
              <span className="tabular-nums text-xs text-muted">
                bearing {r.bearing.toFixed(0)}°
              </span>
            </button>
          </li>
        ))}
      </ul>
      {sign.rays.length > rays.length && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="mt-1 px-1.5 text-xs font-medium text-accent hover:underline"
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
    <section className="mt-3 border-t border-line pt-3">
      <h2 className="font-semibold">Boxes of this picture</h2>
      <ul className="mt-2 space-y-0.5">
        {boxes.map((b) => (
          <li key={b.annotationId}>
            <button
              type="button"
              onClick={() => onFocus(b.annotationId)}
              aria-pressed={b.annotationId === selected.focus}
              className={ROW + (b.annotationId === selected.focus ? " bg-line font-medium" : "")}
            >
              <SignIcon icon={b.icon} />
              <span className="min-w-0 flex-1">{b.label}</span>
            </button>
          </li>
        ))}
      </ul>
      <a
        href={`${VIEWER}?pic=${selected.pictureId}`}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-3 inline-block font-medium text-accent hover:underline"
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
  selected: Selection | null;
  boxes: Box[];
  showRays: boolean;
  onShowRays: (show: boolean) => void;
  onFocus: (annotationId: string) => void;
  onPicture: (ray: SignRay) => void;
  onClose: () => void;
}

export function SignPanel({
  status,
  located,
  cameras,
  selected,
  boxes,
  showRays,
  onShowRays,
  onFocus,
  onPicture,
  onClose,
}: SignPanelProps) {
  // phones: a bottom sheet below the map, its details folded away by default
  const [expanded, setExpanded] = useState(false);
  const details = expanded ? "" : " max-md:hidden";
  const sign = selected && located.find((s) => s.id === selected.sign);
  return (
    <aside className="relative z-10 max-h-[50dvh] shrink-0 overflow-y-auto border-t border-line bg-surface px-4 py-3 text-sm md:absolute md:top-4 md:left-4 md:max-h-[calc(100%-2rem)] md:w-[min(20rem,calc(100%-5rem))] md:rounded-lg md:border-0 md:p-4 md:shadow-lg">
      <div className="flex items-center gap-2">
        <h1 className="flex-1 text-base font-semibold">panoloc</h1>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          className="rounded px-2 py-1 text-xs font-medium text-accent hover:bg-line md:hidden"
        >
          {expanded ? "Less ▾" : "More ▴"}
        </button>
        {selected && (
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 py-1 text-muted hover:bg-line md:px-1.5 md:py-0"
            aria-label="Close the 360° view (Esc)"
            title="Close the 360° view (Esc)"
          >
            ✕
          </button>
        )}
      </div>
      <p className={"mb-2 text-xs text-muted" + details}>
        Traffic signs at their triangulated position (find_signs), from the Panoramax pictures
        that see them.
      </p>
      <StatusLine status={status} signs={located.length} cameras={cameras} />
      <div className={details}>
        <label className="mt-2 flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={showRays}
            onChange={(e) => onShowRays(e.target.checked)}
          />
          Show the rays from the cameras
        </label>
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
          </>
        ) : (
          <Legend located={located} />
        )}
      </div>
    </aside>
  );
}
