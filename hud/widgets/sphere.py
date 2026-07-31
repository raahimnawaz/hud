"""CoreSphere — the rotating wireframe "thinking node".

What keeps this from being a screensaver is that it is bound to real state: it
spins up while plugins poll, pulses when an action fires, wobbles red when a
host drops, and contracts while a shutdown confirm is being held. You can read
what the HUD is doing from across the room.

Performance shape: the point cloud is built once per resize, never per frame.
Each frame applies one rotation matrix and rasterises into the braille canvas.
Depth drives brightness, which is what actually sells the third dimension —
back-facing points stay visible but dim, giving the translucent hologram look.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from enum import Enum

from rich.text import Text
from textual.app import RenderResult
from textual.widget import Widget

from hud.widgets.braille import BrailleCanvas, build_ramp


class SphereState(Enum):
    IDLE = "idle"
    POLLING = "polling"
    ACTION = "action"
    ERROR = "error"
    POWER_ARMED = "power_armed"


@dataclass(frozen=True)
class StateParams:
    spin: float
    """Yaw radians per second."""
    scale: float
    jitter: float
    color: str = ""
    """Empty means inherit the theme accent."""
    wobble: float = 0.0
    pulse: bool = False


STATE_PARAMS: dict[SphereState, StateParams] = {
    SphereState.IDLE: StateParams(spin=0.35, scale=1.0, jitter=0.0),
    SphereState.POLLING: StateParams(spin=1.6, scale=1.03, jitter=0.0),
    SphereState.ACTION: StateParams(spin=0.9, scale=1.0, jitter=0.0, pulse=True),
    SphereState.ERROR: StateParams(
        spin=0.45, scale=0.97, jitter=0.9, color="#ff4d4d", wobble=0.22
    ),
    SphereState.POWER_ARMED: StateParams(
        spin=3.4, scale=0.82, jitter=0.35, color="#ff2222"
    ),
}


Cloud = tuple[list[float], list[float], list[float]]


def build_cloud(radius: float) -> Cloud:
    """Lat/long wireframe as unit vectors, sized for a sphere of `radius` dots.

    Density is driven by the drawn radius rather than the canvas, because what
    matters is dots-per-arc: sampling below the circumference is what makes a
    wireframe read as scattered dots instead of continuous lines. Oversampling
    by 1.4x keeps the rings solid at every panel size while holding the point
    count in a range pure Python transforms comfortably 30 times a second.
    """
    # Spacing is the thing to tune, not raw count: rings closer than ~4 dots at
    # the equator stop reading as separate lines and the sphere fills into a
    # blob. Dividing the radius keeps equator spacing roughly constant as the
    # panel grows.
    circumference = 2 * math.pi * max(4.0, radius)
    samples = int(min(260, max(60, circumference * 1.4)))
    lat_rings = max(6, min(11, int(radius / 4.0)))
    meridians = max(8, min(13, int(radius / 3.2)))

    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []

    for i in range(1, lat_rings):
        lat = -math.pi / 2 + math.pi * i / lat_rings
        cos_lat, sin_lat = math.cos(lat), math.sin(lat)
        for j in range(samples):
            lon = 2 * math.pi * j / samples
            xs.append(cos_lat * math.cos(lon))
            ys.append(sin_lat)
            zs.append(cos_lat * math.sin(lon))

    for i in range(meridians):
        lon = 2 * math.pi * i / meridians
        cos_lon, sin_lon = math.cos(lon), math.sin(lon)
        for j in range(samples):
            lat = -math.pi / 2 + math.pi * j / samples
            cos_lat = math.cos(lat)
            xs.append(cos_lat * cos_lon)
            ys.append(math.sin(lat))
            zs.append(cos_lat * sin_lon)

    return xs, ys, zs


def rasterize(
    canvas: BrailleCanvas,
    cloud: Cloud,
    *,
    cos_y: float,
    sin_y: float,
    cos_p: float,
    sin_p: float,
    cx: float,
    cy: float,
    radius: float,
    jitter: float = 0.0,
) -> None:
    """Rotate the cloud and plot it. Kept a free function so it can be
    benchmarked and tested without a running Textual app.
    """
    rand = random.random
    plot = canvas.plot
    xs, ys, zs = cloud

    for i in range(len(xs)):
        x, y, z = xs[i], ys[i], zs[i]

        # yaw about Y
        rx = x * cos_y + z * sin_y
        rz = -x * sin_y + z * cos_y
        # pitch about X
        ry = y * cos_p - rz * sin_p
        rz = y * sin_p + rz * cos_p

        # Nothing is culled: depth-driven brightness keeps back-facing points
        # dim, which is what produces the translucent hologram look.
        depth = (rz + 1.0) * 0.5

        px = cx + rx * radius
        py = cy + ry * radius
        if jitter and rand() < jitter * 0.06:
            px += (rand() - 0.5) * 5.0
            py += (rand() - 0.5) * 3.0

        plot(int(px), int(py), depth)


class CoreSphere(Widget):
    """A lat/long wireframe sphere rendered into braille cells."""

    DEFAULT_CSS = """
    CoreSphere {
        width: 1fr;
        height: 1fr;
        content-align: center middle;
    }
    """

    def __init__(self, *, fps: int = 20, accent: str = "#00d9ff", **kwargs) -> None:
        super().__init__(**kwargs)
        self.fps = fps
        self.accent = accent
        self._state = SphereState.IDLE
        self._yaw = 0.0
        self._pulse = 0.0
        self._elapsed = 0.0
        self._last = time.monotonic()
        self._canvas: BrailleCanvas | None = None
        self._cloud: tuple[list[float], list[float], list[float]] = ([], [], [])
        self._ramp_cache: dict[str, list[str]] = {}
        self._timer = None

    # ----- lifecycle -------------------------------------------------------

    def on_mount(self) -> None:
        self._timer = self.set_interval(1 / self.fps, self._tick)

    def on_resize(self) -> None:
        self._canvas = None  # rebuilt lazily on next render at the new size

    def pause(self) -> None:
        """Stop animating entirely.

        This matters more than any micro-optimisation: the HUD spends most of
        its life hidden behind a hotkey with the process still alive, and a
        rotating sphere nobody is looking at is pure battery drain. Stopping
        the timer takes the cost to zero rather than merely reducing it.
        """
        if self._timer is not None:
            self._timer.pause()

    def resume(self) -> None:
        if self._timer is not None:
            self._timer.resume()
            self._last = time.monotonic()  # don't jump the spin on return

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last, 0.25)  # clamp so a stall doesn't jump the spin
        self._last = now
        self._elapsed += dt

        params = STATE_PARAMS[self._state]
        self._yaw = (self._yaw + params.spin * dt) % (2 * math.pi)

        if params.pulse or self._pulse > 0.0:
            self._pulse += dt * 1.6
            if self._pulse > 1.0:
                self._pulse = 0.0 if not params.pulse else self._pulse - 1.0

        self.refresh()

    # ----- public API ------------------------------------------------------

    @property
    def state(self) -> SphereState:
        return self._state

    def set_state(self, state: SphereState) -> None:
        if state is self._state:
            return
        self._state = state
        if state is SphereState.ACTION:
            self._pulse = 0.001

    def set_accent(self, accent: str) -> None:
        self.accent = accent
        self._ramp_cache.clear()

    # ----- geometry --------------------------------------------------------

    def _ramp(self, color: str) -> list[str]:
        ramp = self._ramp_cache.get(color)
        if ramp is None:
            ramp = build_ramp(color)
            self._ramp_cache[color] = ramp
        return ramp

    # ----- render ----------------------------------------------------------

    def render(self) -> RenderResult:
        width, height = self.size.width, self.size.height
        if width < 4 or height < 3:
            return Text("")

        canvas = self._canvas
        rebuild = canvas is None or canvas.cw != width or canvas.ch != height
        if rebuild:
            canvas = BrailleCanvas(width, height)
            self._canvas = canvas
        else:
            canvas.clear()

        params = STATE_PARAMS[self._state]
        colour = params.color or self.accent

        base_radius = min(canvas.pw, canvas.ph) / 2 * 0.92
        radius = base_radius * params.scale
        cx = canvas.pw / 2
        cy = canvas.ph / 2

        if rebuild or not self._cloud[0]:
            self._cloud = build_cloud(base_radius)

        pitch = 0.42
        if params.wobble:
            pitch += math.sin(self._elapsed * 5.1) * params.wobble

        cos_y, sin_y = math.cos(self._yaw), math.sin(self._yaw)
        cos_p, sin_p = math.cos(pitch), math.sin(pitch)

        rasterize(
            canvas,
            self._cloud,
            cos_y=cos_y,
            sin_y=sin_y,
            cos_p=cos_p,
            sin_p=sin_p,
            cx=cx,
            cy=cy,
            radius=radius,
            jitter=params.jitter,
        )

        if self._pulse > 0.0:
            self._draw_pulse(canvas, cx, cy, radius, canvas.plot)

        return canvas.to_text(self._ramp(colour))

    def _draw_pulse(self, canvas, cx: float, cy: float, radius: float, plot) -> None:
        """An expanding ring that fires once per action, then fades."""
        t = self._pulse
        r = radius * (1.0 + t * 0.55)
        brightness = max(0.0, 1.0 - t)
        if brightness <= 0.02:
            return
        steps = max(40, int(r * 3))
        for i in range(steps):
            a = 2 * math.pi * i / steps
            plot(int(cx + math.cos(a) * r), int(cy + math.sin(a) * r * 0.98), brightness)
