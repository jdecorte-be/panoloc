import sys
import time
from pathlib import Path
from typing import Any

import depth_pro
import numpy as np
import requests
from scipy.ndimage.morphology import binary_fill_holes as imfill


class PictureNotFound(Exception):
    """The requested picture was not found with the API"""


API = "https://api.panoramax.xyz/api"

TIMEOUT_S = 10
_SESSION = requests.Session()


class DepthEstimator:
    def __init__(
        self, temp_pic: str = "data/imgs/img2depth.jpg", verbose: bool = False
    ) -> None:
        self.temp_pic: Path = Path(temp_pic)
        if self.temp_pic.is_dir() or not self.temp_pic.suffix == ".jpg":
            raise ValueError("temp_pic must point to a .jpg file")
        self.verbose: bool = verbose
        self.model_transform: tuple[Any, Any] | None = None

    def _log(self, *args, **kwargs) -> None:
        if self.verbose:
            print(*args, **kwargs)

    def _get_picture(self, pic_id: str) -> dict[str, Any]:
        r = _SESSION.get(
            f"{API}/search", params={"ids": pic_id}, timeout=TIMEOUT_S
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
        chunk_size = 131072 # 128kb
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

    def from_picture(self, pic: dict[str, Any]) -> list[float]:
        pic_id = pic["id"]
        self._log(" - PICTURE:", pic_id)
        first_start = time.time()

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

        # ensure the model is loaded
        self._load_model()
        if self.model_transform is None:
            raise ValueError("loading model failed")
        (model, transform) = self.model_transform

        # Load and preprocess an image.
        self._log("loading image")
        start = time.time()
        image, _, f_px = depth_pro.load_rgb(self.temp_pic)
        image = transform(image)
        self._log("loaded image in", time.time() - start, "s")
        self._log("inferring depth")
        start = time.time()
        prediction = model.infer(image, f_px=f_px)
        self._log("inference took", time.time() - start, "s")
        depth = np.array(prediction["depth"])

        res: list[float] = []

        for sign in signs:
            id = sign["id"]
            self._log(" - SIGN:", id, end=" at ", flush=True)
            polygon = np.array(sign["shape"]["coordinates"][0])

            depth_b = depth.copy()

            # Apply the mask and extract the polygon
            mask = np.zeros(depth_b.shape, dtype=bool)
            mask[polygon[:, 1], polygon[:, 0]] = 1
            out = depth_b[imfill(mask)]

            avg = out.sum() / len(out)
            res.append(avg)
            self._log(round(avg, 3), "meters")

        total_time = time.time() - first_start
        ratio = len(signs) / total_time
        ratio_s = f"{round(ratio, 2)}/s"
        if ratio < 1:
            ratio = total_time / len(signs)
            ratio_s = f"{round(ratio, 2)}s/sign"
        self._log(
            f"processed {len(signs)} signs in",
            round(total_time),
            f"seconds ({ratio_s})",
        )

        return res

    def from_id(self, pic_id: str) -> list[float]:
        self.temp_pic.parent.mkdir(parents=True, exist_ok=True)

        pic = self._get_picture(pic_id)
        return self.from_picture(pic)


def main() -> None:
    depth = DepthEstimator(verbose=True)
    depth.from_id(sys.argv[1])
