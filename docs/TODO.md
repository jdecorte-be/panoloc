# TODO

## Important

- [ ] Triangulation method
- [ ] Monocular depth method
- [ ] Integrate Strasbourg data
- [ ] Evaluate both approaches
- [ ] Try with sd vs hd images (we're advised to use sd)

## To check

- [ ] `ray_length` in `src/panoloc/frontend/votes.py` (from #13): `(side - max(r.size, p)) / d` doesn't cap the drawn ray at `size`, so the lines drawn on the map may not match what `vote()` counts
- [ ] `locate_signs` in `src/panoloc/deduplication.py` ignores `Ray.size`: it uses its own distance windows, so #13's cap of 50 has no effect there

## Nice-to-haves

- [ ] Add colors to logs
- [ ] Integrate panoramax 360 view into the streamlit app
