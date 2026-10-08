import sys

from . import DepthEstimator

depth = DepthEstimator(verbose=True)
depth.from_id(sys.argv[1])
