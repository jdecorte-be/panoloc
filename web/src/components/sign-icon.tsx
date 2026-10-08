/** Pictogram of a sign (public/signs), a gray placeholder when there is none. */
export function SignIcon({ icon }: { icon?: string }) {
  if (!icon) {
    return <span className="inline-block h-6 w-6 shrink-0 rounded-full bg-line" aria-hidden />;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- tiny local SVGs
    <img
      src={`/signs/${encodeURIComponent(icon)}.svg`}
      alt=""
      className="h-6 w-6 shrink-0 object-contain"
    />
  );
}
