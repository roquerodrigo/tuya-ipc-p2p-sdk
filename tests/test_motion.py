from tuya_ipc_p2p_sdk.motion_detector import MotionDetector


class Clock:
    """A clock the tests move by hand, so the hold can be exercised without waiting."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def still_frames(count: int, base: int = 17850) -> list[int]:
    """Frame sizes as a real camera produces them on a still scene."""
    return [base + (index % 5) * 12 - 24 for index in range(count)]


def test_a_still_scene_never_reports_motion():
    events: list[bool] = []
    detector = MotionDetector(events.append)
    for size in still_frames(60):
        detector.sample(size)
    assert events == []


def test_a_frame_that_differs_sharply_reports_motion_once_confirmed():
    events: list[bool] = []
    detector = MotionDetector(events.append)
    for size in still_frames(20):
        detector.sample(size)
    detector.sample(23000)
    assert events == []
    detector.sample(26000)
    assert events == [True]
    assert detector.detected is True


def test_an_isolated_jump_is_ignored():
    # The camera adjusts its own exposure, which shows up as a single frame that
    # differs sharply from both its neighbours. That is not motion.
    events: list[bool] = []
    detector = MotionDetector(events.append)
    for size in still_frames(20):
        detector.sample(size)
    detector.sample(23000)
    for size in still_frames(10, 23000):
        detector.sample(size)
    assert events == []


def test_motion_is_held_then_clears_once_the_scene_settles():
    events: list[bool] = []
    clock = Clock()
    detector = MotionDetector(events.append, sensitivity=4, clock=clock)
    for size in still_frames(20):
        detector.sample(size)

    detector.sample(23000)
    detector.sample(26000)
    assert events == [True]

    clock.advance(5)
    detector.sample(26010)
    assert events == [True]

    clock.advance(20)
    detector.sample(26020)
    assert events == [True, False]


def test_a_held_state_clears_on_a_poll_even_without_a_new_frame():
    events: list[bool] = []
    clock = Clock()
    detector = MotionDetector(events.append, sensitivity=4, clock=clock)
    for size in still_frames(20):
        detector.sample(size)
    detector.sample(23000)
    detector.sample(26000)
    assert events == [True]

    clock.advance(60)
    detector.poll()
    assert events == [True, False]


def test_the_typical_difference_follows_a_noisier_scene():
    events: list[bool] = []
    detector = MotionDetector(events.append)
    for index in range(80):
        detector.sample(7000 + (70 if index % 2 else 0))
    assert events == []
    assert detector.typical_difference_percent > 0


def test_an_almost_perfectly_still_scene_still_needs_a_real_change():
    events: list[bool] = []
    detector = MotionDetector(events.append)
    for _ in range(30):
        detector.sample(10000)
    # Without a floor under the threshold, a tenth of a percent would trigger.
    detector.sample(10010)
    assert events == []
    detector.sample(12000)
    detector.sample(14000)
    assert events == [True]


def test_sensitivity_is_configurable():
    strict: list[bool] = []
    loose: list[bool] = []
    strict_detector = MotionDetector(strict.append, sensitivity=60)
    loose_detector = MotionDetector(loose.append, sensitivity=2)
    for size in still_frames(20):
        strict_detector.sample(size)
        loose_detector.sample(size)
    for size in (18200, 18570):
        strict_detector.sample(size)
        loose_detector.sample(size)
    assert strict == []
    assert loose == [True]


def test_the_first_frame_cannot_be_compared_to_anything():
    events: list[bool] = []
    detector = MotionDetector(events.append)
    detector.sample(17850)
    assert events == []
    assert detector.last_difference_percent == 0


def test_a_reset_clears_a_held_state():
    events: list[bool] = []
    detector = MotionDetector(events.append, sensitivity=4)
    for size in still_frames(20):
        detector.sample(size)
    detector.sample(23000)
    detector.sample(26000)
    assert events == [True]
    detector.reset()
    assert events == [True, False]
    assert detector.typical_difference_percent == 0
