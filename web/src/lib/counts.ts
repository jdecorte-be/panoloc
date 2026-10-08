import type { ExpressionSpecification } from "maplibre-gl";

/**
 * Colors of the squares of counted signs, by order of magnitude: one violet, light
 * to dark, apart from the basemap's water and the orange of the open picture.
 * The text clears 4.5:1 on each.
 */
export const COUNT_TIERS = [
  { min: 1, label: "1–9", fill: "#a78bfa", text: "#2e1065" },
  { min: 10, label: "10–99", fill: "#7c3aed", text: "#ffffff" },
  { min: 100, label: "100–999", fill: "#5b21b6", text: "#ffffff" },
  { min: 1000, label: "1K+", fill: "#3b0764", text: "#ffffff" },
] as const;

/** ["step", count, tier 1, 10, tier 2, ...]: a tier's value for a square. */
export function byTier(key: "fill" | "text"): ExpressionSpecification {
  const [first, ...rest] = COUNT_TIERS;
  return ["step", ["get", "count"], first[key], ...rest.flatMap((t) => [t.min, t[key]])];
}
