// TypeScript port of sign_types_of (src/panoloc/deduplication.py) and
// icon_key (src/panoloc/frontend/signs.py): keep them in sync.

// split a traffic_sign value, but not inside brackets ("D21[A, B]")
const SEGMENT_SEP = /[;,](?![^[]*\])/;
const PREFIX = /^\s*[A-Z]{1,3}:/;

/** Sign types of one annotation, from its osm|traffic_sign values. */
export function signTypesOf(values: string[]): string[] {
  // "yes": a sign was detected but not classified
  const known = values.filter((v) => v !== "yes");
  // "stop", "no_entry"...: the same sign as the code next to them
  const coded = known.filter((v) => v.includes(":"));
  const types = (coded.length ? coded : known)
    .flatMap((v) => v.split(";"))
    .map((t) => t.trim())
    .filter(Boolean);
  return [...new Set(types)];
}

/**
 * Pictogram of a sign: "FR:B14[50]" -> "B14[50]", else its bare code "B14".
 * Undefined when there is no pictogram for it.
 */
export function iconKey(
  trafficSign: string,
  manifest: Record<string, string>,
): string | undefined {
  const first = trafficSign.toUpperCase().split(SEGMENT_SEP)[0];
  const exact = first.replace(PREFIX, "").trim();
  return [exact, exact.split("[")[0]].find((key) => key in manifest);
}
