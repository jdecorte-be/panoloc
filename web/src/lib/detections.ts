import { manifest } from "@/lib/manifest";
import { iconKey, signTypesOf } from "@/lib/sign-codes";
import type { Detection } from "@/lib/types";

export const TRAFFIC_SIGN = "osm|traffic_sign";

/** The osm|traffic_sign tags of a picture, one per annotation and value. */
export interface SignTag {
  value: string;
  annotation: string | null;
}

/** One Detection per sign type of each annotation, as sign_types_of reads them. */
export async function detectionsOf(pictureId: string, tags: SignTag[]): Promise<Detection[]> {
  const icons = await manifest();
  const byAnnotation = Map.groupBy(tags, (t) => t.annotation ?? pictureId);
  return [...byAnnotation].flatMap(([annotationId, sems]) =>
    signTypesOf(sems.map((t) => t.value)).map((sign) => {
      const icon = iconKey(sign, icons);
      return { annotationId, sign, ...(icon && { icon }), name: (icon && icons[icon]) || sign };
    }),
  );
}
