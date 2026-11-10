/** One traffic sign type of one box of a picture. */
export interface Detection {
  annotationId: string;
  /** OSM traffic_sign value, e.g. "FR:B14[50]" */
  sign: string;
  /** pictogram served at /signs/<icon>.svg, absent when there is none */
  icon?: string;
  /** French name of the pictogram, else the sign code */
  name: string;
}

/** [picture id, lon, lat] of a picture with a traffic sign. */
export type CameraTuple = [string, number, number];

export interface CamerasResponse {
  /** tile "i:j" -> its pictures with a traffic sign, for every tile asked */
  tiles: Record<string, CameraTuple[]>;
}

/** A picture that sees a located sign: its camera and the box of the sign. */
export interface SignRay {
  pictureId: string;
  annotationId: string | null;
  camera: [number, number];
  /** compass bearing from the camera to the box, in degrees */
  bearing: number;
  /** from the camera to the located sign, in meters */
  distance: number;
}

/** [picture id, annotation id, camera lon, camera lat, bearing, distance]: a SignRay, small. */
export type RayTuple = [string, string | null, number, number, number, number];

/** A sign of a tile at its triangulated position (find_signs), as /api/located sends it. */
export interface TileSign {
  /** OSM traffic_sign value, e.g. "FR:B14[50]" */
  sign: string;
  icon?: string;
  name: string;
  position: [number, number];
  /** one per picture that sees it, the nearest first: none from `make push-signs` */
  rays: RayTuple[];
}

export interface LocatedResponse {
  /** tile "i:j" -> its signs, for every tile asked */
  tiles: Record<string, TileSign[]>;
}

export interface CountsResponse {
  /** [lon, lat, count]: the located signs of a square of tiles, at their mean position */
  counts: [number, number, number][];
}

export interface TotalResponse {
  /** the located signs of the whole world */
  total: number;
}

/** A sign on the map. */
export interface LocatedSign extends Omit<TileSign, "rays"> {
  /** stable while the map moves: type and position */
  id: string;
  /** 1 = the most seen sign in view, as in the Streamlit map */
  number: number;
  rays: SignRay[];
}

/** The picture opened in the 360° view. */
export interface Selection {
  pictureId: string;
  /** camera position */
  position: [number, number];
  /** annotation to look at, none: the camera's own direction */
  focus?: string;
  /** id of the located sign the view was opened for */
  sign?: string;
}
