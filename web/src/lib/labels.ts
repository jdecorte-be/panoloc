// Labels of the boxes, as the Streamlit app writes them (src/panoloc/frontend/drawing.py).
import type { Detection, LocatedSign } from "@/lib/types";

/** "#n name": the same sign in every picture. "? name": not located. */
export function signLabel(number: number | undefined, name: string): string {
  return `${number === undefined ? "?" : `#${number}`} ${name}`;
}

export interface Box {
  annotationId: string;
  /** one signLabel per sign of the box, then how far its sign is when located */
  label: string;
  /** id of the located sign of the box, its most seen one when it shows several */
  sign?: string;
  icon?: string;
}

/** The boxes of one picture, labelled. */
export function boxesOf(
  pictureId: string,
  detections: Detection[],
  located: LocatedSign[],
): Box[] {
  // (annotation, sign type) -> the located sign, see sign_numbers
  const numbers = new Map<string, LocatedSign>();
  // annotation id -> meters to its most seen sign, see sign_distances
  const distances = new Map<string, number>();
  // annotation id -> sign type -> its sign: the detections of the picture, and the
  // located signs it sees (from the map, before its detections arrive)
  const types = new Map<string, Map<string, { name: string; icon?: string }>>();
  const add = (annotationId: string, sign: string, name: string, icon?: string) => {
    if (!types.has(annotationId)) types.set(annotationId, new Map());
    types.get(annotationId)!.set(sign, { name, icon });
  };

  for (const s of located) {
    // most seen first
    for (const r of s.rays) {
      if (!r.annotationId) continue;
      numbers.set(`${r.annotationId}|${s.sign}`, s);
      if (!distances.has(r.annotationId)) distances.set(r.annotationId, r.distance);
      if (r.pictureId === pictureId) add(r.annotationId, s.sign, s.name, s.icon);
    }
  }
  for (const d of detections) add(d.annotationId, d.sign, d.name, d.icon);

  return [...types].map(([annotationId, signs]) => {
    const found = [...signs].map(([sign, s]) => ({
      ...s,
      located: numbers.get(`${annotationId}|${sign}`),
    }));
    const label = found.map((s) => signLabel(s.located?.number, s.name)).join(" + ");
    const distance = distances.get(annotationId);
    const best = found
      .flatMap((s) => (s.located ? [s.located] : []))
      .sort((a, b) => a.number - b.number)[0];
    return {
      annotationId,
      label: distance === undefined ? label : `${label} · ${distance.toFixed(0)} m`,
      sign: best?.id,
      icon: found[0]?.icon,
    };
  });
}
