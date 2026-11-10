"use client";

import { memo, useMemo, useState } from "react";

import { SignIcon } from "@/components/sign-icon";
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

const SECTION = "mt-3 border-t border-line pt-3";
const HEADING = "mb-1.5 text-xs text-muted";
// taller on touch screens
const ROW = "flex w-full items-center gap-2 px-1 py-1.5 text-left hover:bg-line/50 md:py-1";
const ROW_ACTIVE = " bg-accent-soft/35 font-medium";

/** The signs in view, how many in all: one line of text. */
function Summary({
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
  if (status.kind === "error") return <p className="text-red-700">{status.message}</p>;
  const all = total === null ? null : ` of ${NUMBER.format(total)}`;
  if (status.kind === "counts") {
    return (
      <p aria-live="polite">
        <strong className="tabular-nums">{NUMBER.format(status.signs)}</strong> signs in view
        <span className="text-muted">{all}</span>
      </p>
    );
  }
  return (
    <p aria-live="polite">
      <strong className="tabular-nums">{status.kind === "loading" ? "…" : NUMBER.format(signs)}</strong>{" "}
      signs in view<span className="text-muted">{all}</span>
      <span className="text-muted">
        {" "}
        · {NUMBER.format(cameras)} pictures
        {status.kind === "locating" && " · loading…"}
      </span>
    </p>
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
  return (
    <section className={SECTION}>
      <h2 className={HEADING}>In view</h2>
      <ul className="space-y-1">
        {top.map((group) => {
          const s = group[0];
          return (
            <li key={s.sign} className="flex items-center gap-2">
              <SignIcon icon={s.icon} />
              <span className="min-w-0 flex-1 truncate" title={`${s.name} (${s.sign})`}>
                {s.name}
              </span>
              <span className="text-muted tabular-nums">{group.length}</span>
            </li>
          );
        })}
      </ul>
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
      <h2 className="flex items-center gap-2 font-semibold">
        <SignIcon icon={sign.icon} />
        {signLabel(sign.number, sign.name)}
      </h2>
      <p className="mt-0.5 text-xs text-muted">
        {sign.sign} · seen in {sign.rays.length} {sign.rays.length === 1 ? "picture" : "pictures"}
      </p>
      <ul className="mt-2">
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
                <span className="flex-1">Picture {r.distance.toFixed(0)} m away</span>
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
          className="mt-1 px-1 text-xs text-accent hover:underline"
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
        <ul>
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
        className="mt-2 inline-block text-accent hover:underline"
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
}: SignPanelProps) {
  // phones: a bottom sheet below the map, its details folded away by default
  const [expanded, setExpanded] = useState(false);
  const details = expanded ? "" : " max-md:hidden";
  const sign = selected && located.find((s) => s.id === selected.sign);
  return (
    <aside className="panel relative z-10 max-h-[50dvh] shrink-0 overflow-y-auto border-t border-line bg-surface px-3 py-2.5 text-sm md:absolute md:top-3 md:left-3 md:max-h-[calc(100%-1.5rem)] md:w-[min(19rem,calc(100%-5rem))] md:rounded md:border md:shadow-md">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <Summary status={status} signs={located.length} cameras={cameras} total={total} />
        </div>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          className="text-xs text-accent md:hidden"
        >
          {expanded ? "Less" : "More"}
        </button>
        {selected && (
          <button
            type="button"
            onClick={onClose}
            className="leading-none text-muted hover:text-foreground"
            aria-label="Close the 360° view (Esc)"
            title="Close the 360° view (Esc)"
          >
            ✕
          </button>
        )}
      </div>
      <div className={details}>
        {status.kind !== "counts" && (
          <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs select-none">
            <input
              type="checkbox"
              checked={showRays}
              onChange={(e) => onShowRays(e.target.checked)}
              className="accent-accent-soft"
            />
            Show the camera rays
          </label>
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
          </>
        ) : status.kind === "counts" ? (
          <p className="mt-1 text-xs text-muted">Click a circle to zoom in.</p>
        ) : (
          <Legend located={located} />
        )}
      </div>
    </aside>
  );
}
