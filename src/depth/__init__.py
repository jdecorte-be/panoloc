import sys
import time
from math import cos, radians, sin
from pathlib import Path
from typing import Any

import depth_pro
import numpy as np
import requests
from numpy.typing import NDArray
from scipy.ndimage.morphology import binary_fill_holes as imfill

from panoloc.annotations import annotation_heading

"""
# Status

On our hardware, the bellow code takes about 25 seconds per image and yields
wrong results.

## Correctness

Apple's Depth Pro model is trained on flat images and we currently hand it 360
images.
To solve this, we could either:

1. Swap it with a model specialised in 360 images such as
[CRF360D](https://vlislab22.github.io/CRF360D/). (cons: dataset is not public).

2. (preferred) Split the 360 image into flat images. (using parts of panoflat).

## Speed

The images we tested are about 75.5 megapixels, which is 33 times bigger than
the 2.25 megapixels images the paper recommends. Additionally, we didn't have
access to gpu computing, which could further speed it up.

Using smaller (sd) or split images would be ideal but it requires transposing
the signs's pixels coordinates into the new images.
"""


class PictureNotFound(Exception):
    """The requested picture was not found with the API"""


TIMEOUT_S = 10
_SESSION = requests.Session()


class DepthEstimator:
    def __init__(
        self,
        temp_pic: str = "data/imgs/img2depth.jpg",
        api_url: str = "https://api.panoramax.xyz/api",
        verbose: bool = False,
    ) -> None:
        self.temp_pic: Path = Path(temp_pic)
        if self.temp_pic.is_dir() or not self.temp_pic.suffix == ".jpg":
            raise ValueError("temp_pic must point to a .jpg file")
        self.api_url: str = api_url
        self.verbose: bool = verbose
        self.model_transform: tuple[Any, Any] | None = None

    def _log(self, *args, **kwargs) -> None:
        if self.verbose:
            print(*args, **kwargs)

    def _get_picture(self, pic_id: str) -> dict[str, Any]:
        r = _SESSION.get(
            f"{self.api_url}/search", params={"ids": pic_id}, timeout=TIMEOUT_S
        )
        r.raise_for_status()
        features = r.json()["features"]
        if not features:
            raise PictureNotFound(pic_id)
        return features[0]

    def _get_depth_pro(self) -> None:
        """Ensure the model is downloaded"""
        model = Path("checkpoints/depth_pro.pt")
        if model.exists():
            return
        model.parent.mkdir(exist_ok=True)
        self._log("downloading model...")
        # Write the model chunk-by-chunk to avoid filling the memory
        chunk_size = 131072  # 128kb
        url = "https://ml-site.cdn-apple.com/models/depth-pro/depth_pro.pt"
        with requests.get(url, stream=True) as r, open(model, "wb") as f:
            for chunk in r.iter_content(chunk_size):
                if chunk:
                    f.write(chunk)

    def _load_model(self):
        """Download and load the model only once.

        Raises:
            ValueError: When loading the model fails.
        """
        self._get_depth_pro()

        if self.model_transform is not None:
            return
        self._log("loading model")
        start = time.time()
        self.model_transform = depth_pro.create_model_and_transforms()
        if self.model_transform is None:
            raise ValueError("loading model failed")
        (model, _) = self.model_transform
        model.eval()
        self._log("loaded model in", time.time() - start, "s")

    def _get_depth(self) -> NDArray[Any]:
        """Get the estimated depths values of an image.

        Returns:
            A numpy array with the depth values.
        """
        self._load_model()
        if self.model_transform is None:
            raise ValueError("loading model failed")
        (model, transform) = self.model_transform

        self._log("loading image")
        start = time.time()
        image, _, f_px = depth_pro.load_rgb(self.temp_pic)
        image = transform(image)
        self._log("loaded image in", time.time() - start, "s")

        self._log("inferring depth")
        start = time.time()
        prediction = model.infer(image, f_px=f_px)
        self._log("inference took", time.time() - start, "s")

        return np.array(prediction["depth"])

    def _to_lonlat(
        self, pic: dict[str, Any], angle: float, distance: float
    ) -> tuple[float, float]:
        rad = radians(angle)
        geometry = pic["geometry"]
        img_lon, img_lat = geometry["coordinates"]
        return img_lon + (cos(rad) * distance), img_lat + (sin(rad) * distance)

    def from_picture(self, pic: dict[str, Any]) -> list[tuple[float, float]]:
        first_start = time.time()

        pic_id = pic["id"]
        self._log(" - PICTURE:", pic_id)

        try:
            is360 = (
                pic["properties"]["pers:interior_orientation"]["field_of_view"]
                == 360
            )
        except KeyError:
            is360 = False
        if not is360:
            self._log("This script only supports 360 images at the moment")
            sys.exit(1)

        picture = pic["assets"]["hd"]["href"]
        signs = list(
            filter(
                lambda a: any(
                    s["key"] == "osm|traffic_sign" for s in a["semantics"]
                ),
                pic["properties"]["annotations"],
            )
        )

        if not signs:
            self._log("no signs in the picture")
            sys.exit(0)
        self._log(len(signs), "signs in the picture")

        dl = _SESSION.get(picture)
        with open(self.temp_pic, "wb") as f:
            f.write(dl.content)

        depth = self._get_depth()

        res: list[tuple[float, float]] = []
        processed_signs = 0

        for sign in signs:
            angle: float | None = annotation_heading(
                sign["shape"], pic["properties"]
            )
            if angle is None:
                self._log("could not get the sign's heading")
                continue

            self._log(" - SIGN:", sign["id"], end=" at ", flush=True)
            polygon = np.array(sign["shape"]["coordinates"][0])

            # PERF: necessary ?
            depth_b = depth.copy()

            # Apply the mask and extract the polygon
            mask = np.zeros(depth_b.shape, dtype=bool)
            mask[polygon[:, 1], polygon[:, 0]] = 1
            out = depth_b[imfill(mask)]

            distance = out.sum() / len(out)
            processed_signs += 1
            coords = self._to_lonlat(pic, angle, distance)
            res.append(coords)
            self._log(
                round(distance, 3), f"meters, lon={coords[0]} lat={coords[1]}"
            )

        total_time = time.time() - first_start
        ratio = len(signs) / total_time
        ratio_s = f"{round(ratio, 2)}/s"
        if ratio < 1:
            ratio = total_time / len(signs)
            ratio_s = f"{round(ratio, 2)}s/sign"
        self._log(
            f"processed {processed_signs}/{len(signs)} signs in",
            round(total_time),
            f"seconds ({ratio_s})",
        )

        return res

    def from_id(self, pic_id: str) -> list[tuple[float, float]]:
        self.temp_pic.parent.mkdir(parents=True, exist_ok=True)

        pic = self._get_picture(pic_id)
        return self.from_picture(pic)
