# panoloc web

Next.js (App Router, TypeScript, Tailwind) map of the traffic signs detected in
Panoramax pictures, read from the MongoDB filled by `make populate`.

Each sign is drawn **where it stands**: the position `find_signs`
(`src/panoloc/deduplication.py`) triangulates from the pictures that see it,
numbered `#n` like the Streamlit map (1 = the most seen sign in view). The gray
dots are the cameras; "Show the rays" draws the rays find_signs kept.

`/api/located` and `/api/counts` read the `signs` collection that
`make push-signs` fills (`src/panoloc/push_signs.py`: type, position and rays):
nothing is located while the map is open, run `make push-signs` again after an
algorithm change. The map asks for fixed tiles of 0.0025° (~280 x 185 m), and the
browser keeps the tiles it got: panning back costs no request. Zoomed out, the
signs are counted per tile, held in memory by the server and read again every
10 minutes.

The 360° view shows the `sd` picture at once, then the original one (`hd`, 5760 px
wide for a GoPro Max) in its place once downloaded.

## Run

From the repository root:

```sh
make populate      # once: imports the Panoramax pictures, then creates the indexes
make install       # the Python project
SIGNS_URI=mongodb://panoloc:panoloc@localhost:27017/?authSource=admin make push-signs
make web-install
cp web/.env.example web/.env.local
make web-dev       # http://localhost:3000
```

If the collection was imported before `db-index` existed, run `make db-index`
once: without the 2dsphere index every map move scans the whole collection.

The map view is kept in the URL (`#zoom/lat/lon`), so views can be shared.

Click a sign to open the nearest picture that sees it in a 360° view, turned
toward it, its boxes labelled as in Streamlit (`#3 Stop · 12 m`, `?` when not
located); the panel lists the other pictures that see it. Click a camera dot to
open its picture. The map then shrinks to the
bottom-right corner: the orange dot is the camera, the cone where the view looks.
Click a sign in the side panel to turn toward it; `Esc` or "Full map" closes the view.
The picture and its annotations come from the Panoramax API (`sd` derivative).

## Layout

| Path | Role |
| --- | --- |
| `src/app/api/located/route.ts` | `GET /api/located?tiles=i:j,…`: the located signs of these tiles, from `signs` |
| `src/app/api/counts/route.ts` | `GET /api/counts?bbox=w,s,e,n&size=n`: the signs counted by squares of n x n tiles |
| `src/lib/signs.ts` | The queries of the `signs` collection, and its counts per tile held in memory |
| `src/app/api/cameras/route.ts` | `GET /api/cameras?bbox=w,s,e,n`: the cameras, `[id, lon, lat]` |
| `src/app/api/pictures/[id]/route.ts` | `GET /api/pictures/<id>`: the signs detected in one picture, by box |
| `src/components/sign-map.tsx` | MapLibre map: clusters, pictograms; full screen, or inset beside the 360° view |
| `src/components/panorama.tsx` | 360° view ([Photo Sphere Viewer](https://photo-sphere-viewer.js.org/)) with the annotation boxes |
| `src/lib/panoramax.ts` | Picture metadata from the Panoramax API, annotation pixels -> view angles |
| `src/components/sign-panel.tsx` | Status, legend of the signs in view, signs of the open picture |
| `src/lib/labels.ts` | Box labels, TS port of `sign_label` / `sign_numbers` / `sign_distances` |
| `src/lib/tiles.ts` | The tiles of `locate.py` (keep `TILE_DEG` in sync) |
| `src/lib/sign-codes.ts` | TS port of `sign_types_of` / `icon_key` (keep in sync with the Python) |
| `src/lib/sign-images.ts` | Rasterizes the SVG pictograms for MapLibre |
| `scripts/copy-signs.mjs` | Copies `src/panoloc/frontend/assets/signs` to `public/signs` before `dev` / `build` |

The basemap is [OpenFreeMap](https://openfreemap.org/) (no API key).
