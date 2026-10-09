"""Global pose graph optimization with weak GPS prior constraints."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from ..ingest.models import FrameRecord
from .ransac import PairTransform


@dataclass
class GlobalPose:
    frame_id: str
    world_x: float  # Canvas X pixel coordinate (or UTM easting)
    world_y: float  # Canvas Y pixel coordinate (or UTM northing)
    scale_x: float
    scale_y: float
    rotation_rad: float
    h_native_to_canvas: np.ndarray  # 3x3 transform: image native pixels -> global canvas pixels
    confidence: float


def _make_2d_transform(
    x: float, y: float, theta: float, scale: float, cx: float, cy: float
) -> np.ndarray:
    """Creates a 3x3 similarity matrix mapping image native coordinates centered at (cx, cy) to canvas."""
    cos_t = math.cos(theta) * scale
    sin_t = math.sin(theta) * scale
    # T_center * R * S * T_inv_center
    # M = [[cos_t, -sin_t, x - cx*cos_t + cy*sin_t],
    #      [sin_t,  cos_t, y - cx*sin_t - cy*cos_t],
    #      [0,      0,     1]]
    tx = x - cx * cos_t + cy * sin_t
    ty = y - cx * sin_t - cy * cos_t
    return np.array([[cos_t, -sin_t, tx], [sin_t, cos_t, ty], [0.0, 0.0, 1.0]], dtype=np.float64)


def solve_global_poses(
    records: Sequence[FrameRecord],
    pair_transforms: Sequence[PairTransform],
    target_gsd: float,
    gps_prior_weight: float = 0.05,
) -> dict[str, GlobalPose]:
    """
    Optimizes global placement of all frames.
    Uses GPS UTM positions as initial estimates and regularizing priors,
    then minimizes pairwise visual alignment errors across the overlap graph.
    """
    if not records:
        return {}

    id_to_idx = {r.frame_id: i for i, r in enumerate(records)}
    num_frames = len(records)

    # 1. Coordinate origin: min UTM Easting and max UTM Northing (for North-up display)
    eastings = [r.utm_easting if r.utm_easting is not None else 0.0 for r in records]
    northings = [r.utm_northing if r.utm_northing is not None else 0.0 for r in records]
    min_e = min(eastings)
    max_n = max(northings)

    # Convert GPS UTM to canvas pixel reference
    # Canvas X increases East, Canvas Y increases South (standard screen/image buffer)
    gps_canvas_x = np.zeros(num_frames, dtype=np.float64)
    gps_canvas_y = np.zeros(num_frames, dtype=np.float64)
    gps_thetas = np.zeros(num_frames, dtype=np.float64)

    for i, r in enumerate(records):
        e = r.utm_easting if r.utm_easting is not None else min_e
        n = r.utm_northing if r.utm_northing is not None else max_n
        gps_canvas_x[i] = (e - min_e) / target_gsd
        gps_canvas_y[i] = (max_n - n) / target_gsd
        # Yaw is degrees clockwise from North. In screen space (Y down), rotation angle matches yaw radians
        yaw_rad = math.radians(r.yaw if r.yaw is not None else 0.0)
        gps_thetas[i] = yaw_rad

    # Parameter vector per frame: [x, y, theta, scale] -> 4 * num_frames
    p0 = np.zeros(num_frames * 4, dtype=np.float64)
    for i in range(num_frames):
        p0[i * 4 + 0] = gps_canvas_x[i]
        p0[i * 4 + 1] = gps_canvas_y[i]
        p0[i * 4 + 2] = gps_thetas[i]
        p0[i * 4 + 3] = 1.0  # nominal scale

    # Valid visual pairwise constraints
    valid_pairs = [
        pt
        for pt in pair_transforms
        if pt.status == "success" and pt.source_id in id_to_idx and pt.target_id in id_to_idx
    ]

    # Pre-calculate center points of frames
    centers = []
    for r in records:
        centers.append((r.width / 2.0, r.height / 2.0))

    # If we have visual pairs, run robust least-squares optimization
    if len(valid_pairs) > 0:

        def residuals(params: np.ndarray) -> np.ndarray:
            res = []
            # 1. Pairwise visual consistency
            for pt in valid_pairs:
                i = id_to_idx[pt.source_id]
                j = id_to_idx[pt.target_id]

                xi, yi, thi, si = params[i * 4 : i * 4 + 4]
                xj, yj, thj, sj = params[j * 4 : j * 4 + 4]

                Hi = _make_2d_transform(xi, yi, thi, si, centers[i][0], centers[i][1])
                Hj = _make_2d_transform(xj, yj, thj, sj, centers[j][0], centers[j][1])

                # Sample 4 test points in source frame
                w, h = records[i].width, records[i].height
                test_pts = np.array(
                    [
                        [w * 0.25, h * 0.25, 1.0],
                        [w * 0.75, h * 0.25, 1.0],
                        [w * 0.25, h * 0.75, 1.0],
                        [w * 0.75, h * 0.75, 1.0],
                    ]
                )

                # Expected position via pairwise matrix: pt_j = H_pair @ pt_i
                pts_in_j = test_pts @ pt.matrix.T
                pts_in_j = pts_in_j[:, :2] / pts_in_j[:, 2:3]
                pts_in_j_homo = np.hstack([pts_in_j, np.ones((4, 1))])

                # Both mapped to global canvas
                canvas_pts_from_i = (test_pts @ Hi.T)[:, :2]
                canvas_pts_from_j = (pts_in_j_homo @ Hj.T)[:, :2]

                diff = (canvas_pts_from_i - canvas_pts_from_j).ravel()
                # Weight by inlier ratio confidence
                weight = float(pt.inlier_ratio)
                res.extend(diff * weight)

            # 2. Weak GPS priors
            for i in range(num_frames):
                xi, yi, thi, si = params[i * 4 : i * 4 + 4]
                res.append((xi - gps_canvas_x[i]) * gps_prior_weight)
                res.append((yi - gps_canvas_y[i]) * gps_prior_weight)
                # Angle difference
                dth = math.atan2(math.sin(thi - gps_thetas[i]), math.cos(thi - gps_thetas[i]))
                res.append(dth * 50.0 * gps_prior_weight)
                # Scale prior (should stay close to 1.0)
                res.append((si - 1.0) * 100.0 * gps_prior_weight)

            return np.array(res, dtype=np.float64)

        try:
            opt_res = least_squares(
                residuals,
                p0,
                loss="cauchy",  # Robust loss against outlier matches
                f_scale=10.0,
                max_nfev=250,
            )
            p_final = opt_res.x
        except Exception:
            p_final = p0
    else:
        p_final = p0

    # Build GlobalPose dictionary
    poses: dict[str, GlobalPose] = {}
    for i, r in enumerate(records):
        xi, yi, thi, si = p_final[i * 4 : i * 4 + 4]
        cx, cy = centers[i]
        H_canvas = _make_2d_transform(xi, yi, thi, si, cx, cy)

        poses[r.frame_id] = GlobalPose(
            frame_id=r.frame_id,
            world_x=float(xi),
            world_y=float(yi),
            scale_x=float(si),
            scale_y=float(si),
            rotation_rad=float(thi),
            h_native_to_canvas=H_canvas,
            confidence=1.0 if len(valid_pairs) > 0 else 0.5,
        )

    return poses
