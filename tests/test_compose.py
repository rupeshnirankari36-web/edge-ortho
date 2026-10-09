"""Unit tests for bounded memory tile composition and feather blending."""

import numpy as np

from edge_ortho.compose import (
    blend_accumulator,
    compute_feather_weights,
    finalize_tile,
)


def test_feather_weights_and_blend():
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:80, 20:80] = 1

    weights = compute_feather_weights(mask, feather_radius=10)
    assert weights.shape == (100, 100)
    assert weights[0, 0] == 0.0
    assert weights[50, 50] == 1.0

    accum_c = np.zeros((100, 100, 3), dtype=np.float32)
    accum_w = np.zeros((100, 100), dtype=np.float32)
    patch = np.full((100, 100, 3), 200, dtype=np.uint8)

    blend_accumulator(accum_c, accum_w, patch, mask, feather_radius=10)
    rgb, alpha = finalize_tile(accum_c, accum_w)

    assert rgb.shape == (100, 100, 3)
    assert alpha[50, 50] == 255
    assert alpha[0, 0] == 0
    assert np.allclose(rgb[50, 50], [200, 200, 200], atol=2)
