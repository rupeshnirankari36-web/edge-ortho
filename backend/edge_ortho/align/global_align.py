"""Stage 6b - canvas geometry and global alignment.

Three things happen here.

1. **Canvas definition.** The output grid is a north-up UTM grid. Pixel
   ``(col, row)`` maps to ``(origin_e + col * gsd, origin_n - row * gsd)``, which
   later becomes a plain GDAL affine transform. Because the grid is UTM-aligned,
   each frame carries its own rotation - there is no hidden rotation term in the
   exported raster.

2. **Global solve.** Per-frame similarity poses ``(s, theta, tx, ty)`` are seeded
   from GPS (+ camera yaw) and then refined by a bounded robust least-squares
   solve over the pairwise inlier correspondences, with a *weak* GPS prior so the
   solution cannot drift arbitrarily far from the flight track.

3. **Homography comparison.** A second placement is built by chaining per-pair
   homographies from the seed frame. Both placements are scored against GPS and
   against each other, so the affine-vs-homography question in the brief is
   answered with numbers from the run rather than an assertion.

Nothing here is a claim of survey-grade accuracy: GPS placement error is measured
relative to the camera's own GPS tags, which are not ground control.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from ..contracts import FrameRecord, GlobalPose, PairTransform
from ..geo.footprints import footprint_polygon
from ..geo.projection import Projector

CANVAS_PADDING_FRACTION = 0.02
CANVAS_PADDING_MIN_M = 5.0


@dataclass
class CanvasGeometry:
    """The output pixel grid and its mapping to projected metres."""

    width: int
    height: int
    gsd_m: float
    origin_e: float
    origin_n: float
    native_gsd_m: float | None
    crs_epsg: int | None
    crs_name: str | None
    extent_m: dict
    capped: bool = False
    cap_message: str | None = None
    georeferenced: bool = False
    basis: str | None = None

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1e6

    def to_canvas(self, east: float, north: float) -> tuple[float, float]:
        return (east - self.origin_e) / self.gsd_m, (self.origin_n - north) / self.gsd_m

    def to_projected(self, col: float, row: float) -> tuple[float, float]:
        return self.origin_e + col * self.gsd_m, self.origin_n - row * self.gsd_m

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "megapixels": self.megapixels,
            "gsd_m": self.gsd_m,
            "native_gsd_m": self.native_gsd_m,
            "origin_e": self.origin_e,
            "origin_n": self.origin_n,
            "crs_epsg": self.crs_epsg,
            "crs_name": self.crs_name,
            "extent_m": self.extent_m,
            "output_capped": self.capped,
            "cap_message": self.cap_message,
            "georeferenced": self.georeferenced,
            "basis": self.basis,
        }


def define_canvas(
    frames: list[FrameRecord],
    projector: Projector | None,
    max_output_megapixels: float,
    output_gsd_m: float | None = None,
) -> CanvasGeometry:
    """Build the output grid from the union of real image footprints."""
    gsds = [f.gsd_m for f in frames if f.gsd_m]
    native_gsd = statistics.median(gsds) if gsds else None

    boxes = []
    for f in frames:
        poly = footprint_polygon(f)
        if poly:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
        elif f.projected_x is not None:
            boxes.append((f.projected_x, f.projected_y, f.projected_x, f.projected_y))
    if not boxes:
        raise ValueError("no frames with usable projected geometry")

    min_e = min(b[0] for b in boxes)
    min_n = min(b[1] for b in boxes)
    max_e = max(b[2] for b in boxes)
    max_n = max(b[3] for b in boxes)

    span_e = max_e - min_e
    span_n = max_n - min_n
    pad = max(CANVAS_PADDING_MIN_M, CANVAS_PADDING_FRACTION * max(span_e, span_n))
    min_e -= pad
    max_e += pad
    min_n -= pad
    max_n += pad
    width_m, height_m = max_e - min_e, max_n - min_n

    georeferenced = native_gsd is not None
    gsd = output_gsd_m or native_gsd or 1.0
    capped = False
    cap_message = None

    # Apply the output pixel cap by coarsening the grid, and say so.
    for _ in range(3):
        w = max(1, math.ceil(width_m / gsd))
        h = max(1, math.ceil(height_m / gsd))
        mp = w * h / 1e6
        if mp <= max_output_megapixels or not georeferenced:
            break
        gsd = gsd * math.sqrt(mp / max_output_megapixels)
        capped = True
    w = max(1, math.ceil(width_m / gsd))
    h = max(1, math.ceil(height_m / gsd))
    if capped:
        cap_message = (
            f"output reduced to {w}x{h} px ({w * h / 1e6:.1f} MP) at {gsd * 100:.2f} cm/px "
            f"to respect the {max_output_megapixels:g} MP cap; native estimate is "
            f"{native_gsd * 100:.2f} cm/px"
        )

    basis = None
    if georeferenced:
        basis = (
            "GPS centres define the canvas extent; pixel size comes from the EXIF-derived "
            "GSD estimate; per-frame rotation and offsets are refined from feature matches."
        )

    return CanvasGeometry(
        width=w,
        height=h,
        gsd_m=gsd,
        origin_e=min_e,
        origin_n=max_n,
        native_gsd_m=native_gsd,
        crs_epsg=projector.epsg if projector else None,
        crs_name=projector.crs_name() if projector else None,
        extent_m={
            "min_e": min_e,
            "max_e": max_e,
            "min_n": min_n,
            "max_n": max_n,
            "width_m": width_m,
            "height_m": height_m,
        },
        capped=capped,
        cap_message=cap_message,
        georeferenced=georeferenced,
        basis=basis,
    )


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------


def _heading_terms(yaw_deg: float | None, sign: float = 1.0, offset_deg: float = 0.0) -> tuple[float, float]:
    """Canvas-space (cos, sin) for a camera heading.

    Canvas y grows south, so a compass-clockwise rotation appears as
    ``[[cos, -sin], [sin, cos]]`` in this frame of reference. ``sign`` and
    ``offset_deg`` are resolved from the data - see
    :func:`resolve_heading_convention`.
    """
    heading = math.radians(sign * (yaw_deg or 0.0) + offset_deg)
    return math.cos(heading), math.sin(heading)


def seed_poses(
    frames: list[FrameRecord],
    canvas: CanvasGeometry,
    yaw_sign: float = 1.0,
    heading_offset_deg: float = 0.0,
) -> dict[str, GlobalPose]:
    """Initial per-frame placement from GPS position, EXIF-derived GSD and yaw.

    Translations are set so that each frame centre lands exactly on its GPS
    position for the chosen rotation; only the rotation depends on the heading
    convention that :func:`resolve_heading_convention` resolves.
    """
    poses: dict[str, GlobalPose] = {}
    for f in frames:
        if f.projected_x is None or f.projected_y is None or not f.width or not f.height:
            continue
        gsd = f.gsd_m or canvas.gsd_m
        scale = gsd / canvas.gsd_m
        cos_t, sin_t = _heading_terms(f.yaw_deg, yaw_sign, heading_offset_deg)
        cx, cy = canvas.to_canvas(f.projected_x, f.projected_y)
        tx = cx - (cos_t * scale * (f.width / 2.0) - sin_t * scale * (f.height / 2.0))
        ty = cy - (sin_t * scale * (f.width / 2.0) + cos_t * scale * (f.height / 2.0))
        poses[f.frame_id] = GlobalPose(
            frame_id=f.frame_id,
            scale=scale,
            theta_rad=math.atan2(sin_t, cos_t),
            tx=tx,
            ty=ty,
            confidence=0.4,
            seed_source="gps",
        )
    return poses


#: Candidate yaw conventions. ``+1`` treats the tag as a compass heading
#: (clockwise from north), ``-1`` as a counter-clockwise angle, ``0`` ignores it.
_HEADING_HYPOTHESES: tuple[tuple[float, str], ...] = (
    (1.0, "cw_compass"),
    (-1.0, "ccw_inverted"),
    (0.0, "yaw_ignored"),
)

#: Sweep range and step for the constant heading offset, in degrees.
HEADING_SWEEP_DEG = 180.0
HEADING_COARSE_STEP_DEG = 5.0
HEADING_FINE_STEP_DEG = 1.0

#: Cap the sweep cost on large datasets.
_SWEEP_MAX_PAIRS = 120
_SWEEP_MAX_POINTS = 8

#: Bound on the per-frame log-scale refinement (exp(0.10) ~= 1.105, i.e. +-10%).
SCALE_DELTA_BOUND = 0.10
#: Bound on the per-frame rotation refinement, in radians (~+-29 degrees).
THETA_DELTA_BOUND = 0.5


def _seed_constraint_rmse(
    poses: dict[str, GlobalPose],
    pairwise: list[tuple[PairTransform, object]],
    stride: int = 1,
    max_points: int | None = None,
) -> tuple[float | None, int]:
    errors: list[float] = []
    for pair, geometry in pairwise[::stride]:
        if geometry is None or pair.status != "ok":
            continue
        if pair.source_id not in poses or pair.target_id not in poses:
            continue
        src, dst = geometry.src_points, geometry.dst_points
        if max_points and len(src) > max_points:
            src, dst = src[:max_points], dst[:max_points]
        diff = _apply(_pose_matrix(poses[pair.source_id]), src) - _apply(
            _pose_matrix(poses[pair.target_id]), dst
        )
        errors.extend(np.linalg.norm(diff, axis=1).tolist())
    if not errors:
        return None, 0
    return float(np.sqrt(np.mean(np.square(errors)))), len(errors)


def resolve_heading_convention(
    frames: list[FrameRecord],
    canvas: CanvasGeometry,
    pairwise: list[tuple[PairTransform, object]],
) -> dict:
    """Resolve the camera-heading convention from the visual constraints.

    Drone firmware differs in two ways that a fixed assumption would get wrong:

    * the sign of the yaw tag (compass-clockwise vs counter-clockwise);
    * a constant mounting/reporting offset, which shows up as every frame being
      rotated by the same extra angle.

    Both are resolved by sweeping sign and a constant offset over the pairwise
    inlier correspondences and keeping the combination with the lowest seed RMSE.
    The winning values, the runner-up and the achievable RMSE are reported, so a
    reader can see how much the data actually constrained the choice. When no
    pair validates, the tag is read as a compass heading with zero offset and the
    run is flagged as unresolved.
    """
    yaw_available = any(f.yaw_deg is not None for f in frames)
    valid = [(p, g) for p, g in pairwise if g is not None and p.status == "ok"]
    stride = max(1, len(valid) // _SWEEP_MAX_PAIRS)

    candidates: list[dict] = []
    for sign, label in _HEADING_HYPOTHESES:
        if not yaw_available and label != "yaw_ignored":
            continue
        best = (None, None)
        offset = -HEADING_SWEEP_DEG
        while offset < HEADING_SWEEP_DEG:
            rmse, _n = _seed_constraint_rmse(
                seed_poses(frames, canvas, sign, offset), valid, stride, _SWEEP_MAX_POINTS
            )
            if rmse is not None and (best[0] is None or rmse < best[1]):
                best = (offset, rmse)
            offset += HEADING_COARSE_STEP_DEG
        if best[0] is not None:
            # refine around the coarse winner
            centre = best[0]
            offset = centre - HEADING_COARSE_STEP_DEG
            while offset <= centre + HEADING_COARSE_STEP_DEG:
                rmse, _n = _seed_constraint_rmse(
                    seed_poses(frames, canvas, sign, offset), valid, stride, _SWEEP_MAX_POINTS
                )
                if rmse is not None and rmse < best[1]:
                    best = (offset, rmse)
                offset += HEADING_FINE_STEP_DEG
        # full-precision RMSE for the reported number
        full_rmse, samples = _seed_constraint_rmse(
            seed_poses(frames, canvas, sign, best[0] or 0.0), valid
        )
        candidates.append(
            {
                "convention": label,
                "yaw_sign": sign,
                "heading_offset_deg": best[0],
                "seed_rmse_px": full_rmse,
                "samples": samples,
            }
        )

    scored = [c for c in candidates if c["seed_rmse_px"] is not None]
    scored.sort(key=lambda c: c["seed_rmse_px"])
    winner = scored[0] if scored else None
    runner_up = scored[1]["seed_rmse_px"] if len(scored) > 1 else None

    if winner is None:
        return {
            "selected": "cw_compass" if yaw_available else "yaw_ignored",
            "yaw_sign": 1.0 if yaw_available else 0.0,
            "heading_offset_deg": 0.0,
            "seed_rmse_px": None,
            "runner_up_rmse_px": None,
            "margin_px": None,
            "candidates": candidates,
            "resolved_from_data": False,
            "yaw_available": yaw_available,
            "note": (
                "No validated pair constraint was available, so the heading convention could "
                "not be resolved from data. The tag is read as a compass heading with no "
                "offset and the run is flagged as unresolved."
            ),
        }

    return {
        "selected": winner["convention"],
        "yaw_sign": winner["yaw_sign"],
        "heading_offset_deg": winner["heading_offset_deg"],
        "seed_rmse_px": winner["seed_rmse_px"],
        "runner_up_rmse_px": runner_up,
        "margin_px": (runner_up - winner["seed_rmse_px"]) if runner_up is not None else None,
        "candidates": candidates,
        "resolved_from_data": True,
        "yaw_available": yaw_available,
        "note": (
            "Camera-heading sign and constant offset chosen by sweeping both against the "
            "validated pairwise correspondences and keeping the lowest seed RMSE. "
            "The offset absorbs a mounting or firmware reporting difference; it is an "
            "inferred quantity, not a measured gimbal angle."
        ),
    }


# ---------------------------------------------------------------------------
# global similarity bundle
# ---------------------------------------------------------------------------


@dataclass
class GlobalAlignmentResult:
    poses: dict[str, GlobalPose] = field(default_factory=dict)
    homography_poses: dict[str, dict] = field(default_factory=dict)
    chained_pose_count: int = 0
    solver: dict = field(default_factory=dict)
    comparison: dict = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    residual_stats: dict = field(default_factory=dict)


def _pose_matrix(pose: GlobalPose) -> np.ndarray:
    c, s = math.cos(pose.theta_rad) * pose.scale, math.sin(pose.theta_rad) * pose.scale
    return np.array([[c, -s, pose.tx], [s, c, pose.ty], [0.0, 0.0, 1.0]], dtype=np.float64)


def _apply(matrix: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Apply a 3x3 similarity/projective matrix to (N,2) points."""
    pts = np.asarray(pts, dtype=np.float64)
    ones = np.ones((pts.shape[0], 1))
    hom = np.hstack([pts, ones]) @ matrix.T
    w = hom[:, 2:3]
    w = np.where(np.abs(w) < 1e-12, 1e-12, w)
    return hom[:, :2] / w


def solve_global_alignment(
    frames: list[FrameRecord],
    canvas: CanvasGeometry,
    pairwise: list[tuple[PairTransform, object]],
    seed: dict[str, GlobalPose],
    gps_prior_weight: float = 0.05,
    max_nfev: int = 200,
) -> GlobalAlignmentResult:
    """Refine per-frame similarity poses over the pairwise inlier correspondences."""
    result = GlobalAlignmentResult()
    order = [f.frame_id for f in frames if f.frame_id in seed]
    if len(order) < 2:
        result.poses = dict(seed)
        result.messages.append("fewer than two seeded frames: global solve skipped")
        return result
    index = {fid: i for i, fid in enumerate(order)}
    seeds = np.array(
        [[seed[f].scale, seed[f].theta_rad, seed[f].tx, seed[f].ty] for f in order],
        dtype=np.float64,
    )

    constraints: list[tuple[int, int, np.ndarray, np.ndarray]] = []
    for pair, geometry in pairwise:
        if geometry is None or pair.status != "ok":
            continue
        if pair.source_id not in index or pair.target_id not in index:
            continue
        constraints.append(
            (index[pair.source_id], index[pair.target_id], geometry.src_points, geometry.dst_points)
        )
    if not constraints:
        result.poses = dict(seed)
        result.messages.append(
            "no validated pair constraints: frames placed from GPS only "
            "(this is a GPS-placed mosaic, not a visually refined one)"
        )
        result.solver = {"constraints": 0, "solved": False}
        return result

    n = len(order)
    x0 = np.zeros(n * 4, dtype=np.float64)
    lb = np.zeros(n * 4, dtype=np.float64)
    ub = np.zeros(n * 4, dtype=np.float64)
    for i in range(n):
        # delta-log-scale, delta-angle (rad), absolute tx, absolute ty
        x0[i * 4 + 0] = 0.0
        x0[i * 4 + 1] = 0.0
        x0[i * 4 + 2] = seeds[i, 2]
        x0[i * 4 + 3] = seeds[i, 3]
        # Scale is tied to the EXIF-derived GSD rather than left free. A purely
        # visual solve has a near-flat direction in global scale (a uniform
        # scaling of the whole layout barely changes correspondence agreement),
        # so leaving it free lets the solution drift tens of percent away from
        # the metadata. Only a small per-frame refinement is allowed.
        lb[i * 4 + 0], ub[i * 4 + 0] = -SCALE_DELTA_BOUND, SCALE_DELTA_BOUND
        lb[i * 4 + 1], ub[i * 4 + 1] = -THETA_DELTA_BOUND, THETA_DELTA_BOUND
        margin = 8.0 * max(canvas.width, canvas.height)
        lb[i * 4 + 2], ub[i * 4 + 2] = seeds[i, 2] - margin, seeds[i, 2] + margin
        lb[i * 4 + 3], ub[i * 4 + 3] = seeds[i, 3] - margin, seeds[i, 3] + margin

    def poses_from(x: np.ndarray) -> np.ndarray:
        p = x.reshape(n, 4)
        scale = seeds[:, 0] * np.exp(p[:, 0])
        theta = seeds[:, 1] + p[:, 1]
        c = np.cos(theta) * scale
        s = np.sin(theta) * scale
        return np.stack([c, -s, p[:, 2], s, c, p[:, 3]], axis=1)  # (n, 6)

    scale_prior_weight = gps_prior_weight * 20.0

    def residual(x: np.ndarray) -> np.ndarray:
        mats = poses_from(x)
        res = []
        for i, j, src_pts, dst_pts in constraints:
            mi = np.array(
                [[mats[i, 0], mats[i, 1], mats[i, 2]], [mats[i, 3], mats[i, 4], mats[i, 5]], [0, 0, 1]]
            )
            mj = np.array(
                [[mats[j, 0], mats[j, 1], mats[j, 2]], [mats[j, 3], mats[j, 4], mats[j, 5]], [0, 0, 1]]
            )
            a = _apply(mi, src_pts)
            b = _apply(mj, dst_pts)
            res.append((a - b).ravel())
        params = x.reshape(n, 4)
        # weak GPS prior keeps the solution anchored to the flight track
        res.append((params[:, 2] - seeds[:, 2]) * gps_prior_weight)
        res.append((params[:, 3] - seeds[:, 3]) * gps_prior_weight)
        # weak scale prior keeps the GSD-derived pixel size honest
        res.append(params[:, 0] * scale_prior_weight)
        return np.concatenate(res)

    try:
        solution = least_squares(
            residual,
            x0,
            bounds=(lb, ub),
            method="trf",
            loss="soft_l1",
            f_scale=3.0,
            x_scale="jac",
            max_nfev=int(max_nfev),
        )
    except Exception as exc:  # pragma: no cover - solver failure is reported
        result.poses = dict(seed)
        result.messages.append(f"global solve failed ({exc}); frames placed from GPS only")
        result.solver = {"constraints": len(constraints), "solved": False, "error": str(exc)}
        return result

    x = solution.x
    mats = poses_from(x)

    # --- per-frame statistics ---------------------------------------------
    per_frame_residuals: dict[str, list[float]] = {fid: [] for fid in order}
    all_res = []
    for i, j, src_pts, dst_pts in constraints:
        mi = np.array(
            [[mats[i, 0], mats[i, 1], mats[i, 2]], [mats[i, 3], mats[i, 4], mats[i, 5]], [0, 0, 1]]
        )
        mj = np.array(
            [[mats[j, 0], mats[j, 1], mats[j, 2]], [mats[j, 3], mats[j, 4], mats[j, 5]], [0, 0, 1]]
        )
        diff = _apply(mi, src_pts) - _apply(mj, dst_pts)
        errs = np.linalg.norm(diff, axis=1)
        all_res.extend(errs.tolist())
        per_frame_residuals[order[i]].extend(errs.tolist())
        per_frame_residuals[order[j]].extend(errs.tolist())

    weights = {}
    for i, j, _s, _d in constraints:
        weights[order[i]] = weights.get(order[i], 0) + 1
        weights[order[j]] = weights.get(order[j], 0) + 1

    poses: dict[str, GlobalPose] = {}
    gps_errors_m: list[float] = []
    for fid in order:
        i = index[fid]
        poses[fid] = GlobalPose(
            frame_id=fid,
            scale=float(math.hypot(float(mats[i, 0]), float(mats[i, 3]))),
            theta_rad=float(math.atan2(float(mats[i, 3]), float(mats[i, 0]))),
            tx=float(mats[i, 2]),
            ty=float(mats[i, 5]),
            confidence=min(1.0, 0.35 + 0.1 * weights.get(fid, 0)),
            seed_source="gps",
            constraints_used=weights.get(fid, 0),
            reprojection_error_px=(
                float(np.sqrt(np.mean(np.square(per_frame_residuals[fid]))))
                if per_frame_residuals[fid]
                else None
            ),
        )

    # --- GPS placement error (measured, not assumed) ----------------------
    frame_by_id = {f.frame_id: f for f in frames}
    for fid, pose in poses.items():
        f = frame_by_id.get(fid)
        if not f or f.projected_x is None or not f.width or not f.height:
            continue
        m = _pose_matrix(pose)
        center = _apply(m, np.array([[f.width / 2.0, f.height / 2.0]]))[0]
        east, north = canvas.to_projected(float(center[0]), float(center[1]))
        err = math.dist((east, north), (f.projected_x, f.projected_y))
        pose.gps_error_px = err / canvas.gsd_m
        gps_errors_m.append(err)

    result.poses = poses
    result.solver = {
        "solved": True,
        "method": "scipy.optimize.least_squares (trf, soft_l1, jac=2-point)",
        "parameters": n * 4,
        "constraints": len(constraints),
        "correspondences": int(sum(len(c[2]) for c in constraints)),
        "nfev": int(solution.nfev),
        "optimality": float(solution.optimality),
        "gps_prior_weight": gps_prior_weight,
        "bounds": {
            "delta_log_scale": [-SCALE_DELTA_BOUND, SCALE_DELTA_BOUND],
            "delta_theta_rad": [-THETA_DELTA_BOUND, THETA_DELTA_BOUND],
        },
        "scale_prior": (
            "Per-frame scale is confined to +-10% around the EXIF-derived GSD because the "
            "visual constraints barely distinguish a uniform global rescaling."
        ),
    }
    result.residual_stats = {
        "rmse_px": float(np.sqrt(np.mean(np.square(all_res)))) if all_res else None,
        "mean_px": float(np.mean(all_res)) if all_res else None,
        "p95_px": float(np.percentile(all_res, 95)) if all_res else None,
        "max_px": float(np.max(all_res)) if all_res else None,
        "rmse_m": (
            float(np.sqrt(np.mean(np.square(all_res))) * canvas.gsd_m) if all_res else None
        ),
        "samples": len(all_res),
    }
    result.comparison["gps_placement_error_m"] = recompute_gps_stats(frames, canvas, poses)
    return result


# ---------------------------------------------------------------------------
# homography chaining (the comparison path)
# ---------------------------------------------------------------------------


def chain_homography_poses(
    frames: list[FrameRecord],
    canvas: CanvasGeometry,
    seed: dict[str, GlobalPose],
    pairwise: list[tuple[PairTransform, object]],
    max_links: int = 8,
) -> dict:
    """Place every frame by chaining validated pair homographies from the seed.

    Returns ``{frame_id: {"matrix": 3x3, "hops": n, "seed": id}}`` for frames that
    could be reached. Unreachable frames are simply absent - the caller reports
    the reachable count instead of filling the gap with a guess.
    """
    adjacency: dict[str, list[tuple[str, np.ndarray, float]]] = {}
    for pair, _geom in pairwise:
        if pair.status != "ok" or pair.model != "homography" or pair.matrix is None:
            continue
        m = np.asarray(pair.matrix, dtype=np.float64)
        if m.shape != (3, 3):
            continue
        try:
            inv = np.linalg.inv(m)
        except np.linalg.LinAlgError:
            continue
        adjacency.setdefault(pair.source_id, []).append((pair.target_id, inv, pair.inlier_ratio or 0.0))
        adjacency.setdefault(pair.target_id, []).append((pair.source_id, m, pair.inlier_ratio or 0.0))

    # Seed = the frame with the most validated homography links and a GPS pose.
    counts = {fid: len(adjacency.get(fid, [])) for fid in seed}
    if not counts:
        return {}
    seed_id = max(counts, key=lambda k: counts[k])

    out: dict[str, dict] = {seed_id: {"matrix": _pose_matrix(seed[seed_id]).tolist(), "hops": 0}}
    visited = {seed_id}
    queue = deque([seed_id])
    while queue:
        current = queue.popleft()
        if len(adjacency.get(current, [])) > max_links:
            links = sorted(adjacency[current], key=lambda t: -t[2])[:max_links]
        else:
            links = adjacency.get(current, [])
        for neighbour, step, _ratio in links:
            if neighbour in visited or neighbour not in seed:
                continue
            h_current = np.asarray(out[current]["matrix"], dtype=np.float64)
            h_neighbour = h_current @ step
            if not np.all(np.isfinite(h_neighbour)):
                continue
            out[neighbour] = {"matrix": h_neighbour.tolist(), "hops": out[current]["hops"] + 1}
            visited.add(neighbour)
            queue.append(neighbour)
    return out


def pair_seed_residuals(
    poses: dict[str, GlobalPose],
    pairwise: list[tuple[PairTransform, object]],
) -> list[tuple[PairTransform, float]]:
    """Per-pair median correspondence error under the GPS-seeded placement.

    The absolute GPS positions may be lagged, but the *relative* geometry of a
    GPS track is reliable. A pair whose visual transform disagrees with the
    GPS-seeded relative placement is therefore a suspect match - typically a
    repetitive-texture alias - and should not be allowed to distort the solve.
    """
    out: list[tuple[PairTransform, float]] = []
    for pair, geometry in pairwise:
        if geometry is None or pair.status != "ok":
            continue
        if pair.source_id not in poses or pair.target_id not in poses:
            continue
        diff = _apply(_pose_matrix(poses[pair.source_id]), geometry.src_points) - _apply(
            _pose_matrix(poses[pair.target_id]), geometry.dst_points
        )
        errs = np.linalg.norm(diff, axis=1)
        out.append((pair, float(np.median(errs))))
    return out


def filter_pairs_by_seed_consistency(
    poses: dict[str, GlobalPose],
    pairwise: list[tuple[PairTransform, object]],
    absolute_floor_px: float = 60.0,
    median_multiple: float = 3.0,
) -> tuple[list[tuple[PairTransform, object]], dict]:
    """Drop pairs that contradict the GPS-seeded relative placement.

    The cutoff is ``max(absolute_floor_px, median_multiple x median residual)``,
    so it adapts to the dataset's own scale instead of a fixed pixel budget.
    Everything dropped is counted and reported - the run never silently discards
    evidence.
    """
    scored = pair_seed_residuals(poses, pairwise)
    if not scored:
        return list(pairwise), {"evaluated": 0, "rejected": 0, "cutoff_px": None, "rejected_pairs": []}
    values = np.array([s[1] for s in scored])
    median = float(np.median(values))
    cutoff = max(absolute_floor_px, median_multiple * median)
    rejected = [(p, v) for p, v in scored if v > cutoff]
    dropped_ids = {(p.source_id, p.target_id) for p, _ in rejected}
    kept = [(p, g) for p, g in pairwise if (p.source_id, p.target_id) not in dropped_ids]
    detail = {
        "evaluated": len(scored),
        "rejected": len(rejected),
        "cutoff_px": cutoff,
        "median_residual_px": median,
        "max_residual_px": float(values.max()),
        "rejected_pairs": [
            {
                "pair": f"{p.source_id}->{p.target_id}",
                "median_residual_px": v,
                "inliers": p.inliers,
                "inlier_ratio": p.inlier_ratio,
            }
            for p, v in sorted(rejected, key=lambda t: -t[1])[:25]
        ],
        "method": (
            "A validated pair is dropped when its inlier correspondences disagree with the "
            "GPS-seeded relative placement by more than max(60 px, 3x median residual). "
            "Relative GPS geometry is used because it is unaffected by a constant GPS lag."
        ),
    }
    return kept, detail


def umeyama_similarity(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, float]:
    """Least-squares 2D similarity (scale, rotation, translation) mapping src -> dst.

    Closed-form Umeyama solution, restricted to non-reflecting transforms.
    Returns a 3x3 matrix and the RMS residual in the units of ``dst``.
    """
    src = np.asarray(src, dtype=np.float64).reshape(-1, 2)
    dst = np.asarray(dst, dtype=np.float64).reshape(-1, 2)
    n = src.shape[0]
    if n < 2:
        return np.eye(3), 0.0
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    sc = src - mu_s
    dc = dst - mu_d
    cov = (dc.T @ sc) / n
    u, d, vt = np.linalg.svd(cov)
    s_matrix = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        s_matrix[1, 1] = -1
    rot = u @ s_matrix @ vt
    var_s = (sc**2).sum() / n
    scale = 1.0 if var_s <= 0 else float((d * np.diag(s_matrix)).sum() / var_s)
    trans = mu_d - scale * (rot @ mu_s)
    m = np.eye(3)
    m[:2, :2] = scale * rot
    m[:2, 2] = trans
    resid = (sc @ (scale * rot).T + trans) - dc
    rms = float(np.sqrt((resid**2).sum(axis=1).mean())) if n else 0.0
    return m, rms


def anchor_to_gps(
    frames: list[FrameRecord],
    canvas: CanvasGeometry,
    poses: dict[str, GlobalPose],
) -> dict:
    """Rigidly align the visually-solved placement onto the GPS positions.

    The weak GPS prior keeps the solve near the flight track but deliberately
    does not dominate it: forcing the visual geometry onto GPS would introduce
    seam error if the GPS tags carry a constant lag. Instead the solved layout is
    treated as a rigid body and one similarity transform is fitted to bring the
    frame centres as close as possible to their GPS positions. Internal geometry
    is therefore preserved exactly while the mosaic is placed in the CRS as well
    as the tags allow.

    Mutates ``poses`` in place and returns before/after statistics.
    """
    frame_by_id = {f.frame_id: f for f in frames}
    ids, solved_centres, gps_centres = [], [], []
    for fid, pose in poses.items():
        f = frame_by_id.get(fid)
        if not f or f.projected_x is None or not f.width or not f.height:
            continue
        c = _apply(_pose_matrix(pose), np.array([[f.width / 2.0, f.height / 2.0]]))[0]
        ids.append(fid)
        solved_centres.append(c)
        gps_centres.append(canvas.to_canvas(f.projected_x, f.projected_y))
    if len(ids) < 2:
        return {"applied": False, "reason": "fewer than two frames with GPS"}

    solved = np.asarray(solved_centres)
    gps = np.asarray(gps_centres)
    m, rms_canvas = umeyama_similarity(solved, gps)

    def err(arr: np.ndarray) -> list[float]:
        return [float(np.linalg.norm(a - b) * canvas.gsd_m) for a, b in zip(arr, gps, strict=True)]

    before = err(solved)
    aligned = (np.hstack([solved, np.ones((len(solved), 1))]) @ m.T)[:, :2]
    after = err(aligned)

    for fid in ids:
        pose = poses[fid]
        combined = m @ _pose_matrix(pose)
        pose.theta_rad = float(math.atan2(combined[1, 0], combined[0, 0]))
        pose.scale = float(math.hypot(combined[0, 0], combined[1, 0]))
        pose.tx = float(combined[0, 2])
        pose.ty = float(combined[1, 2])

    return {
        "applied": True,
        "method": "closed-form 2D similarity (Umeyama) fitted to frame GPS centres",
        "frames": len(ids),
        "translation_m": [float(m[0, 2] * canvas.gsd_m), float(m[1, 2] * canvas.gsd_m)],
        "rotation_deg": float(math.degrees(math.atan2(m[1, 0], m[0, 0]))),
        "scale_factor": float(math.hypot(m[0, 0], m[1, 0])),
        "rms_canvas_px": rms_canvas,
        "gps_error_before_m": {
            "mean": statistics.fmean(before),
            "median": statistics.median(before),
            "max": max(before),
        },
        "gps_error_after_m": {
            "mean": statistics.fmean(after),
            "median": statistics.median(after),
            "max": max(after),
        },
        "note": (
            "A remaining residual here means the visual layout and the GPS tags cannot be "
            "reconciled by a rigid motion - typically GPS lag during flight or tag noise. "
            "It is a consistency check, not ground-control accuracy."
        ),
    }


def recompute_gps_stats(
    frames: list[FrameRecord],
    canvas: CanvasGeometry,
    poses: dict[str, GlobalPose],
) -> dict:
    """Refresh each pose's GPS displacement and summarise it.

    Always measured against the *camera's own GPS tag*. Reported as a
    consistency metric, never as accuracy against ground control.
    """
    frame_by_id = {f.frame_id: f for f in frames}
    errors: list[float] = []
    for fid, pose in poses.items():
        f = frame_by_id.get(fid)
        if not f or f.projected_x is None or not f.width or not f.height:
            continue
        c = _apply(_pose_matrix(pose), np.array([[f.width / 2.0, f.height / 2.0]]))[0]
        east, north = canvas.to_projected(float(c[0]), float(c[1]))
        err = math.dist((east, north), (f.projected_x, f.projected_y))
        pose.gps_error_px = err / canvas.gsd_m
        errors.append(err)
    return {
        "mean": statistics.fmean(errors) if errors else None,
        "median": statistics.median(errors) if errors else None,
        "max": max(errors) if errors else None,
        "samples": len(errors),
        "note": (
            "Distance between each refined frame centre and that frame's own GPS tag. "
            "This is a consistency check against camera GPS, not ground-control accuracy."
        ),
    }


def compare_alignment_paths(
    frames: list[FrameRecord],
    canvas: CanvasGeometry,
    similarity_poses: dict[str, GlobalPose],
    homography_poses: dict[str, dict],
) -> dict:
    """Score the similarity solve against the homography chain."""
    frame_by_id = {f.frame_id: f for f in frames}

    def gps_error(matrix: np.ndarray, fid: str) -> float | None:
        f = frame_by_id.get(fid)
        if not f or f.projected_x is None or not f.width or not f.height:
            return None
        c = _apply(matrix, np.array([[f.width / 2.0, f.height / 2.0]]))[0]
        east, north = canvas.to_projected(float(c[0]), float(c[1]))
        return math.dist((east, north), (f.projected_x, f.projected_y))

    sim_errs, homo_errs, disagreements = [], [], []
    for fid, pose in similarity_poses.items():
        m_sim = _pose_matrix(pose)
        e_sim = gps_error(m_sim, fid)
        if e_sim is not None:
            sim_errs.append(e_sim)
        if fid in homography_poses:
            m_homo = np.asarray(homography_poses[fid]["matrix"], dtype=np.float64)
            e_homo = gps_error(m_homo, fid)
            if e_homo is not None:
                homo_errs.append(e_homo)
            f = frame_by_id.get(fid)
            if f and f.width and f.height:
                c_sim = _apply(m_sim, np.array([[f.width / 2.0, f.height / 2.0]]))[0]
                c_homo = _apply(m_homo, np.array([[f.width / 2.0, f.height / 2.0]]))[0]
                px = float(np.linalg.norm(c_sim - c_homo))
                disagreements.append(px * canvas.gsd_m)

    reachable = len(homography_poses)
    return {
        "available": reachable > 1,
        "similarity": {
            "frames": len(similarity_poses),
            "mean_gps_error_m": statistics.fmean(sim_errs) if sim_errs else None,
            "median_gps_error_m": statistics.median(sim_errs) if sim_errs else None,
            "max_gps_error_m": max(sim_errs) if sim_errs else None,
        },
        "homography_chain": {
            "frames_reachable": reachable,
            "frames_total": len(similarity_poses),
            "coverage": reachable / len(similarity_poses) if similarity_poses else None,
            "mean_gps_error_m": statistics.fmean(homo_errs) if homo_errs else None,
            "median_gps_error_m": statistics.median(homo_errs) if homo_errs else None,
            "max_gps_error_m": max(homo_errs) if homo_errs else None,
        },
        "mean_placement_disagreement_m": (
            statistics.fmean(disagreements) if disagreements else None
        ),
        "max_placement_disagreement_m": max(disagreements) if disagreements else None,
        "note": (
            "Homography chaining places each frame through the seed; errors accumulate with "
            "hop count, so a lower similarity error here is expected rather than a defect."
        ),
    }
