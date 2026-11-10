// Run by `make db-fake`: fake pictures and located signs, to work on the web map
// without `make populate` + `make push-signs`. Every document is marked `fake: true`:
// only those are replaced here (and removed by `make db-fake-clear`), real data stays.
//
// - Strasbourg (the map's default picture): a grid of streets, a camera every ~12 m,
//   the signs beside them with 1 to 6 rays each: the zoomed-in map, numbers, rays.
// - A few European cities: thousands of signs, for the counts of the zoomed-out map.
// The pictures do not exist on Panoramax: the 360° view of a fake one fails to load.

// FR codes with a pictogram in src/panoloc/frontend/assets/signs, "yes": not classified
const TYPES = [
  "FR:B14[50]", "FR:B14[30]", "FR:AB4", "FR:B1", "FR:C12", "FR:A13B", "FR:B2A",
  "FR:C1A", "FR:AB3A", "FR:B6A1", "FR:B21-1", "FR:C20A", "FR:AB3B", "FR:B3", "yes",
];
const TRAFFIC_SIGN = "osm|traffic_sign";

// the same data on every run
let seed = 7;
const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const pick = (list) => list[Math.floor(random() * list.length)];

const pictures = [];
const signs = [];

/** A street of n cameras from (lon0, lat0), a step of (dlon, dlat), signs beside it. */
function street(name, lon0, lat0, dlon, dlat, n) {
  const at = (k) => [lon0 + dlon * k, lat0 + dlat * k];
  // bearing of the street, for the rays
  const heading = (Math.atan2(dlon * Math.cos((lat0 * Math.PI) / 180), dlat) * 180) / Math.PI;
  for (let k = 0; k < n; k++) {
    const [lon, lat] = at(k);
    const id = `fake-${name}-${k}`;
    pictures.push({
      _id: id,
      fake: true,
      geometry: { type: "Point", coordinates: [lon, lat] },
      semantics: [{ key: TRAFFIC_SIGN, value: pick(TYPES), on: { id: `${id}-a` } }],
    });
    if (random() > 0.45) continue;
    // on one side of the street, ~9 m away, a little jitter
    const side = random() < 0.5 ? 1 : -1;
    const position = [
      lon + side * 0.00012 * (dlat ? 1 : 0) + (random() - 0.5) * 0.00004,
      lat + side * 0.00008 * (dlon ? 1 : 0) + (random() - 0.5) * 0.00004,
    ];
    // seen from this camera and up to 5 before it
    const rays = [];
    for (let back = 0, seen = 1 + Math.floor(random() * 6); back < seen && k - back >= 0; back++) {
      const [clon, clat] = at(k - back);
      const dx = (position[0] - clon) * 111320 * Math.cos((clat * Math.PI) / 180);
      const dy = (position[1] - clat) * 110540;
      const bearing = ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360;
      // [picture id, annotation id, camera lon, camera lat, bearing, distance]
      rays.push([`fake-${name}-${k - back}`, null, clon, clat, Math.round(bearing || heading), Math.hypot(dx, dy)]);
    }
    signs.push({
      fake: true,
      type: pick(TYPES),
      location: { type: "Point", coordinates: position },
      rays,
    });
  }
}

for (let s = 0; s < 14; s++) street(`ns${s}`, 7.733 + s * 0.0012, 48.584, 0, 0.00011, 110);
for (let s = 0; s < 10; s++) street(`ew${s}`, 7.733, 48.5845 + s * 0.0011, 0.00013, 0, 130);

// [lon, lat, signs]: clusters for the zoomed-out map, no picture behind them
const CITIES = [
  [2.35, 48.86, 3000], [4.83, 45.76, 1500], [5.37, 43.3, 900], [1.44, 43.6, 700],
  [-1.55, 47.22, 600], [3.06, 50.63, 800], [13.4, 52.52, 400], [4.35, 50.85, 500],
  [-3.7, 40.42, 250], [12.5, 41.9, 200], [6.13, 49.61, 150], [7.26, 43.7, 350],
];
for (const [lon, lat, n] of CITIES) {
  for (let k = 0; k < n; k++) {
    const angle = random() * 2 * Math.PI;
    const r = Math.sqrt(random()) * 0.12;
    signs.push({
      fake: true,
      type: pick(TYPES),
      location: {
        type: "Point",
        coordinates: [lon + r * Math.cos(angle) * 1.4, lat + r * Math.sin(angle)],
      },
      rays: [],
    });
  }
}

// the collections the web map reads by default (web/.env.example)
const removed = [db.pictures.deleteMany({ fake: true }), db.signs.deleteMany({ fake: true })];
db.pictures.insertMany(pictures);
db.signs.insertMany(signs);
// the indexes the map needs: no-ops when they exist (sql/indexes.js, push_signs.py)
db.pictures.createIndex({ geometry: "2dsphere", "semantics.key": 1 }, { name: "geometry_semantics_key" });
db.signs.createIndex({ location: "2dsphere" });

print(
  `fake data: ${pictures.length} pictures and ${signs.length} signs in ${db.getName()}` +
    ` (${removed[0].deletedCount + removed[1].deletedCount} old fake documents replaced)`,
);
