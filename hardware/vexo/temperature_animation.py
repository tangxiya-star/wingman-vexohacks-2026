"""A timed colour animation, not a measurement of skin or chip temperature."""

import time


class TemperatureAnimation:
    """Play five three-second colours after a double tap, then return to blue.

    Call ``colour`` when updating the LED; it also marks a finished animation
    idle. A new ``restart`` begins the full animation again from blue.
    """

    _COLOURS = ("#0000ff", "#00ffff", "#ffff00", "#ff8000", "#ff0000")
    _STEP_SECONDS = 3

    def __init__(self):
        self._started_at = None

    @property
    def started_at(self):
        return self._started_at

    @property
    def is_active(self):
        """Whether the animation is active as of the last colour update."""
        return self._started_at is not None

    def restart(self, now=None):
        self._started_at = time.monotonic() if now is None else now

    def colour(self, now=None):
        if self._started_at is None:
            return self._COLOURS[0]
        now = time.monotonic() if now is None else now
        elapsed = max(0, now - self._started_at)
        if elapsed >= self._STEP_SECONDS * len(self._COLOURS):
            self._started_at = None
            return self._COLOURS[0]
        return self._COLOURS[int(elapsed // self._STEP_SECONDS)]
