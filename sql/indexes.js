// Run by `make db-index` (and after `make populate`, whose --drop removes the indexes).
// The web map asks for the traffic signs of the pictures in its viewport:
// a 2dsphere index on the camera position, narrowed by the semantics keys.
db.pictures.createIndex(
  { geometry: "2dsphere", "semantics.key": 1 },
  { name: "geometry_semantics_key" },
);
// The Streamlit app asks for the pictures of one sequence around a picture
// (bbox.fetch_sequence_items): the sequence first, then the position, so only
// that sequence's pictures are read, not every sequence passing by.
db.pictures.createIndex(
  { collection: 1, geometry: "2dsphere" },
  { name: "collection_geometry" },
);
printjson(db.pictures.getIndexes().map((i) => i.name));
