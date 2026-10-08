// Picture metadata straight from the Panoramax API: MongoDB only holds what the
// geoparquet export has (no image URLs, no lens).

export const API = "https://api.panoramax.xyz/api";
export const VIEWER = "https://api.panoramax.xyz/";

export interface PictureAnnotation {
  id: string;
  /** outline in pixels of the original picture */
  ring: [number, number][];
}

export interface Picture {
  /** "sd" derivative: ~2000 px wide, shown first */
  url: string;
  /** the original picture (5760 px wide for a GoPro Max), swapped in once loaded */
  hdUrl: string | null;
  /** compass bearing of the image center, in degrees */
  azimuth: number | null;
  /** horizontal field of view in degrees, 360 for an equirectangular picture */
  fov: number;
  /** [width, height] of the original picture, the frame of the annotations */
  size: [number, number] | null;
  annotations: PictureAnnotation[];
}

interface StacItem {
  assets: Record<string, { href: string }>;
  properties: {
    "view:azimuth"?: number;
    "pers:interior_orientation"?: {
      field_of_view?: number;
      sensor_array_dimensions?: [number, number];
    };
    annotations?: {
      id: string;
      shape: { type: "Polygon"; coordinates: [number, number][][] } | [number, number, number, number];
    }[];
  };
}

function ring(shape: NonNullable<StacItem["properties"]["annotations"]>[number]["shape"]) {
  if (Array.isArray(shape)) {
    // bbox form: [minx, miny, maxx, maxy]
    const [x0, y0, x1, y1] = shape;
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]] as [number, number][];
  }
  return shape.coordinates[0]; // first ring = outline
}

export async function fetchPicture(pictureId: string, signal?: AbortSignal): Promise<Picture> {
  // by id alone: a ray knows its picture, not its sequence
  const res = await fetch(`${API}/search?ids=${pictureId}`, { signal });
  if (!res.ok) throw new Error(`Panoramax answered ${res.status} for picture ${pictureId}`);
  const item = ((await res.json()) as { features: StacItem[] }).features[0];
  if (!item) throw new Error(`Picture ${pictureId} not found on Panoramax`);
  const orientation = item.properties["pers:interior_orientation"] ?? {};
  return {
    url: (item.assets.sd ?? item.assets.hd).href,
    hdUrl: item.assets.hd?.href ?? null,
    azimuth: item.properties["view:azimuth"] ?? null,
    fov: orientation.field_of_view || 360,
    size: orientation.sensor_array_dimensions ?? null,
    annotations: (item.properties.annotations ?? []).map((a) => ({ id: a.id, ring: ring(a.shape) })),
  };
}

/**
 * Pixel of the original picture -> [yaw, pitch] in radians, yaw 0 at the image
 * center. Linear in x and y, like the panoData given to the viewer: exact for an
 * equirectangular picture, close enough for a flat one.
 */
export function toSpherical(
  [x, y]: [number, number],
  [width, height]: [number, number],
  fovDeg: number,
): [number, number] {
  const fov = (fovDeg * Math.PI) / 180;
  return [(x / width - 0.5) * fov, (0.5 - y / height) * (height / width) * fov];
}
