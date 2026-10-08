import { MongoClient, type Collection, type Document } from "mongodb";

const uri = process.env.MONGODB_URI;
const dbName = process.env.MONGODB_DB ?? "panoloc";
const collectionName = process.env.MONGODB_COLLECTION ?? "pictures";

// One client per server process: dev hot reloads re-run this module, so the
// connection is kept on globalThis instead of a module variable.
const globalForMongo = globalThis as typeof globalThis & {
  _mongoClient?: Promise<MongoClient>;
};

function client(): Promise<MongoClient> {
  if (!uri) {
    throw new Error("MONGODB_URI is not set: copy .env.example to .env.local");
  }
  globalForMongo._mongoClient ??= new MongoClient(uri).connect();
  return globalForMongo._mongoClient;
}

/** The pictures imported by `make populate` (see ../sql/populate.sql). */
export async function pictures<T extends Document = Document>(): Promise<Collection<T>> {
  return (await client()).db(dbName).collection<T>(collectionName);
}
