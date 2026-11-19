"""Content-aware 9:16 reframing (offline, synthetic frames)."""
import numpy as np

from carlecool import reframe
from carlecool.reframe import Crop, FrameSamples, crop_filter, needs_reframe, plan_crop

H = 108  # sample height for a 1920x1080 source at 192 px width


def _samples(positions, size=20, src=(1920, 1080), static_texture=False):
    """Bright moving square at sample-column `positions[i]` on a flat background."""
    frames = np.full((len(positions), H, reframe.SAMPLE_WIDTH), 0.2, dtype=np.float32)
    for i, x in enumerate(positions):
        frames[i, 40:40 + size, x:x + size] = 1.0
        if static_texture:
            frames[i, :, :40] = np.tile([0.0, 1.0], (H, 20))  # busy but motionless left edge
    times = (np.arange(len(positions)) + 0.5) / reframe.SAMPLE_FPS
    return FrameSamples(frames, times, *src)


def test_only_wide_footage_is_reframed():
    assert needs_reframe(1920, 1080) and needs_reframe(1280, 720)
    assert not needs_reframe(1080, 1920) and not needs_reframe(1080, 1350 * 1.4)


def test_window_follows_off_centre_subject():
    crop = plan_crop(_samples([150, 152, 150, 153, 151, 150]), 0.0, 2.0)
    assert crop.width == 608
    subject_left = 150 * 1920 / reframe.SAMPLE_WIDTH
    assert crop.x_start <= subject_left and crop.x_start + crop.width >= subject_left + 200
    assert crop.x_start == crop.x_end  # small jitter does not cause a pan


def test_moving_subject_beats_static_texture():
    crop = plan_crop(_samples([120, 124, 128, 132, 136, 140], static_texture=True), 0.0, 2.0)
    assert crop.x_start > 800  # follows the moving square, not the busy left edge


def test_pan_is_eased_and_speed_limited():
    crop = plan_crop(_samples(list(range(10, 160, 10))), 0.0, 1.0)
    assert crop.x_end > crop.x_start
    assert crop.x_end - crop.x_start <= reframe.MAX_PAN_PER_SECOND * 1920 * 1.0 + 2
    expr = crop_filter(crop, 1080, 1.0)
    assert expr.startswith("crop=608:1080:'") and "3-2*" in expr


def test_static_filter_and_bounds():
    assert crop_filter(Crop(608, 400, 400), 1080, 2.0) == "crop=608:1080:400:0"
    crop = plan_crop(_samples([185, 185, 185], size=7), 0.0, 1.0)
    assert 0 <= crop.x_start <= 1920 - 608
