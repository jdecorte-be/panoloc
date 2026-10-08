# Panoloc

Precisely geolocate the objects detected in Panoramax pictures, beyond the approximate position where each picture was taken.

## Approach

- **Extract**: fetch pictures of a sequence and their metadata from the Panoramax API.
- **Rays**: the position of each detected object in the image + the camera coordinates and orientation allow us to trace an oriented half-line in the world.
- **Locate**, 2 methods to benchmark against each other:
  - *Triangulation* (intersect the rays of the same sign seen from several pictures).
  - *Monocular depth* (estimate the distance along a single ray with a depth model, in this case Apple's Depth Pro.
- **Evaluate**: display the error in meters against a reference position.

## Requirements

- [uv](https://docs.astral.sh/uv/)

## Usage

```sh
uv run streamlit run src/panoloc/app.py

# Click the LOAD button in the streamlit app
# It will fetch the metadata of the pictures you requested from the Panoramax API
# Check "Download pictures" in the sidebar to also download the HD pictures
# The corresponding files are stored in data/raw/<sequence_id>/<picture_id>.{jpg,json}
```

Query the metadata with the DuckDB cli:

```sh
SELECT * FROM read_json('data/raw/*/*.json');
```

## Dependencies

| Package | Used for |
| --- | --- |
| `requests` | HTTP calls to the Panoramax API and picture downloads |
| `streamlit` | The local web app, written in plain Python |
| `pydeck` | The app's map: camera positions and headings |
| `pillow` | Open pictures and draw the annotation bounding boxes |
| `watchdog` | Reloads the app as soon as a file is saved (notified by the OS instead of polling) |

## Resources

- [maxspeed-map](https://source.cipherbliss.com/tykayn/maxspeed-map): deduplication of Panoramax sign detections
- [Panneaux strasbourgs](https://data.strasbourg.eu/explore/dataset/signalisation_verticale/table/)
- [Depth Pro](https://github.com/apple-aiml-research/ml-depth-pro): monocular metric depth + focal length estimation
- [Krylov et al. 2018](https://arxiv.org/abs/1708.08417): geotagging objects from street view imagery, combining depth and triangulation
- [maxspeed-map](https://source.cipherbliss.com/tykayn/maxspeed-map): deduplication of Panoramax sign detections
