/** Run once when a server starts: before its first request needs them, the sign counts. */
export async function register() {
  // MongoDB: the Node.js server only, not the edge runtime
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const { warmTileCounts } = await import("@/lib/signs");
  // not awaited: the server serves at once, the counts come in behind
  warmTileCounts();
}
