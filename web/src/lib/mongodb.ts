import { MongoClient, type Collection, type Document } from "mongodb";

const uri = process.env.MONGODB_URI;
const dbName = process.env.MONGODB_DB ?? "panoloc";
const collectionName = process.env.MONGODB_COLLECTION ?? "pictures";
// where `make push-signs` writes (its SIGNS_URI, --db, --collection): the pictures' MongoDB by default
const signsUri = process.env.SIGNS_URI ?? uri;
const signsDbName = process.env.SIGNS_DB ?? "panoloc";
const signsCollectionName = process.env.SIGNS_COLLECTION ?? "signs";

// One client per URI and server process: dev hot reloads re-run this module, so the
// connections are kept on globalThis instead of a module variable.
const globalForMongo = globalThis as typeof globalThis & {
  _mongoClients?: Map<string, Promise<MongoClient>>;
};

function client(url: string | undefined): Promise<MongoClient> {
  if (!url) {
    throw new Error("MONGODB_URI is not set: copy .env.example to .env.local");
  }
  globalForMongo._mongoClients ??= new Map();
  let connected = globalForMongo._mongoClients.get(url);
  if (!connected) {
    connected = new MongoClient(url).connect();
    globalForMongo._mongoClients.set(url, connected);
  }
  return connected;
}

/** The pictures imported by `make populate` (see ../sql/populate.sql). */
export async function pictures<T extends Document = Document>(): Promise<Collection<T>> {
  return (await client(uri)).db(dbName).collection<T>(collectionName);
}

/** A sign located by find_signs, as `make push-signs` writes it. */
export interface SignDoc {
  /** OSM traffic_sign value, e.g. "FR:B14[50]" */
  type: string;
  location: { type: "Point"; coordinates: [number, number] };
}

/** The located signs pushed by `make push-signs` (src/panoloc/push_signs.py). */
export async function signs(): Promise<Collection<SignDoc>> {
  return (await client(signsUri)).db(signsDbName).collection<SignDoc>(signsCollectionName);
}
