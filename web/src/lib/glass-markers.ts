import type { Map as MapLibreMap } from "maplibre-gl";

/**
 * The markers drawn as HTML over the map: WebGL can't blur what is under a circle,
 * a backdrop-filter can. Only for show (pointer-events: none): the invisible circle
 * layers below still take the clicks and the hover, and tell this which is which.
 */

export type GlassCount = {
  lngLat: [number, number];
  count: number;
  label: string;
};
export type GlassSign = {
  id: string;
  lngLat: [number, number];
  icon?: string;
  label: string;
  seen: number;
};

export type GlassSizes = {
  scale: number;
  /** zoom from which the signs are shown, the counts below */
  detailZoom: number;
  /** zoom from which the #n badges are shown */
  labelZoom: number;
  /** radius of the disc behind a pictogram, of a sign without one */
  discPx: number;
  dotPx: number;
  iconPx: number;
  /** the borders of the counts by order of magnitude, the first from 1 */
  tiers: readonly { min: number; border: string }[];
};

const lerp = (x: number, stops: [number, number][]): number => {
  if (x <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    const [x1, y1] = stops[i];
    const [x0, y0] = stops[i - 1];
    if (x <= x1) return y0 + ((x - x0) / (x1 - x0)) * (y1 - y0);
  }
  return stops[stops.length - 1][1];
};

export class GlassMarkers {
  private root = document.createElement("div");
  private countEls: HTMLDivElement[] = [];
  private signEls = new Map<string, HTMLDivElement>();
  private counts: GlassCount[] = [];
  private signs: GlassSign[] = [];
  private hoveredCount?: number;
  private hoveredSign?: string;
  private frame = 0;

  constructor(
    private map: MapLibreMap,
    private sizes: GlassSizes,
  ) {
    this.root.className = "glass-markers";
    // in the canvas container, before the popups: the tooltip stays on top
    map.getCanvasContainer().appendChild(this.root);
    map.on("render", this.schedule);
  }

  remove() {
    this.map.off("render", this.schedule);
    cancelAnimationFrame(this.frame);
    this.root.remove();
  }

  setCounts(counts: GlassCount[]) {
    for (const el of this.countEls) el.remove();
    const { scale, tiers } = this.sizes;
    this.counts = counts;
    this.hoveredCount = undefined;
    this.countEls = counts.map(({ count, label }) => {
      const el = document.createElement("div");
      el.className = "glass glass-count";
      const r = lerp(Math.sqrt(count), [
        [1, 10 * scale],
        [100, 34 * scale],
      ]);
      el.style.width = el.style.height = `${2 * r}px`;
      el.style.zIndex = String(count); // the biggest on top
      el.style.borderColor = tiers.findLast((t) => count >= t.min)!.border;
      el.style.fontSize = `${lerp(count, [
        [1, 11],
        [1000, 13],
        [10000, 15],
      ])}px`;
      el.textContent = label;
      this.root.appendChild(el);
      return el;
    });
    this.schedule();
  }

  setSigns(signs: GlassSign[]) {
    const { discPx, dotPx, iconPx } = this.sizes;
    const kept = new Set(signs.map((s) => s.id));
    for (const [id, el] of this.signEls) {
      if (!kept.has(id)) {
        el.remove();
        this.signEls.delete(id);
      }
    }
    for (const sign of signs) {
      let el = this.signEls.get(sign.id);
      if (!el) {
        el = document.createElement("div");
        el.className = "glass glass-sign";
        const d = 2 * (sign.icon ? discPx : dotPx);
        el.style.setProperty("--d", `${d}px`);
        if (sign.icon) {
          const img = document.createElement("img");
          img.src = `/signs/${encodeURIComponent(sign.icon)}.svg`;
          img.alt = "";
          img.style.width = img.style.height = `${(100 * iconPx) / d}%`;
          el.appendChild(img);
        }
        const badge = document.createElement("span");
        badge.className = "glass-badge";
        el.appendChild(badge);
        this.root.appendChild(el);
        this.signEls.set(sign.id, el);
      }
      (el.lastChild as HTMLSpanElement).textContent = sign.label;
      // the most seen above the others
      el.style.zIndex = String(sign.seen);
    }
    this.signs = signs;
    this.schedule();
  }

  /** The open picture: the signs it sees stand out, the others fade; the selected one ringed. */
  highlight(pictureId: string | null, seen: string[], selected: string | null) {
    const isSeen = new Set(seen);
    for (const [id, el] of this.signEls) {
      el.classList.toggle("seen", pictureId !== null && isSeen.has(id));
      el.classList.toggle("faded", pictureId !== null && !isSeen.has(id));
      el.classList.toggle("selected", id === selected);
    }
  }

  hoverCount(index: number | undefined) {
    if (index === this.hoveredCount) return;
    if (this.hoveredCount !== undefined)
      this.countEls[this.hoveredCount]?.classList.remove("hover");
    this.hoveredCount = index;
    if (index !== undefined) this.countEls[index]?.classList.add("hover");
  }

  hoverSign(id: string | undefined) {
    if (id === this.hoveredSign) return;
    if (this.hoveredSign !== undefined)
      this.signEls.get(this.hoveredSign)?.classList.remove("hover");
    this.hoveredSign = id;
    if (id !== undefined) this.signEls.get(id)?.classList.add("hover");
  }

  /** Once per frame at most, however many "render" events. */
  private schedule = () => {
    if (!this.frame) {
      this.frame = requestAnimationFrame(() => {
        this.frame = 0;
        this.place();
      });
    }
  };

  private place() {
    const { map } = this;
    const zoom = map.getZoom();
    const { detailZoom, labelZoom } = this.sizes;
    const detailed = zoom >= detailZoom;
    const { clientWidth: w, clientHeight: h } = map.getContainer();
    const margin = 60;

    const position = (
      el: HTMLElement,
      lngLat: [number, number],
      show: boolean,
    ) => {
      if (!show) {
        el.style.display = "none";
        return;
      }
      const { x, y } = map.project(lngLat);
      if (x < -margin || y < -margin || x > w + margin || y > h + margin) {
        el.style.display = "none";
        return;
      }
      el.style.display = "";
      el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
    };

    this.counts.forEach((c, i) =>
      position(this.countEls[i], c.lngLat, !detailed),
    );
    // smaller below zoom 18.5: no pile of signs at zoom 16
    this.root.style.setProperty(
      "--s",
      String(
        lerp(zoom, [
          [detailZoom, 0.62],
          [17, 0.8],
          [18.5, 1],
        ]),
      ),
    );
    this.root.classList.toggle("badges", zoom >= labelZoom);
    for (const sign of this.signs) {
      const el = this.signEls.get(sign.id);
      if (el) position(el, sign.lngLat, detailed);
    }
  }
}
