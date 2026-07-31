"""Sub-cell drawing surface built on Braille Patterns (U+2800-U+28FF).

Each cell encodes 8 dots in a 2x4 grid, and because a character cell is roughly
1:2, those dots come out very close to square — so circles look like circles.
That gives 8x the point density of plain text with no image protocol, no
dependencies, and no terminal-specific support required.

Dot bit layout inside a cell:

    1 4      0x01 0x08
    2 5      0x02 0x10
    3 6      0x04 0x20
    7 8      0x40 0x80
"""

from __future__ import annotations

from rich.text import Text

BRAILLE_BASE = 0x2800

# [row within cell][column within cell] -> bit value
DOT_BITS = (
    (0x01, 0x08),
    (0x02, 0x10),
    (0x04, 0x20),
    (0x40, 0x80),
)

DEPTH_STEPS = 12
"""Depth is quantised before colouring so that runs of equal colour can be
merged into a single span. Without this, a 54x24 canvas emits ~1300 spans per
frame and the compositor becomes the bottleneck at 30fps."""


class BrailleCanvas:
    """A cell grid addressed in dots.

    Callers plot in dot coordinates (0..width*2, 0..height*4) and optionally
    pass a depth in 0..1. Depth is averaged per cell and drives brightness,
    which is what reads as three-dimensionality once rendered.
    """

    __slots__ = ("cw", "ch", "pw", "ph", "_bits", "_depth", "_count")

    def __init__(self, cell_w: int, cell_h: int) -> None:
        self.cw = max(1, cell_w)
        self.ch = max(1, cell_h)
        self.pw = self.cw * 2
        self.ph = self.ch * 4
        size = self.cw * self.ch
        self._bits = bytearray(size)
        self._depth = [0.0] * size
        self._count = [0] * size

    def clear(self) -> None:
        size = self.cw * self.ch
        self._bits = bytearray(size)
        self._depth = [0.0] * size
        self._count = [0] * size

    def plot(self, px: int, py: int, depth: float = 1.0) -> None:
        if px < 0 or py < 0 or px >= self.pw or py >= self.ph:
            return
        idx = (py >> 2) * self.cw + (px >> 1)
        self._bits[idx] |= DOT_BITS[py & 3][px & 1]
        self._depth[idx] += depth
        self._count[idx] += 1

    def to_text(self, ramp: list[str]) -> Text:
        """Render to a Rich Text using `ramp` as a dim->bright colour ladder.

        Adjacent cells sharing a quantised depth are merged into one span.
        """
        steps = len(ramp)
        text = Text(no_wrap=True, end="")
        bits = self._bits
        depth = self._depth
        count = self._count
        cw = self.cw

        for row in range(self.ch):
            base = row * cw
            run: list[str] = []
            run_style: str | None = None

            for col in range(cw):
                idx = base + col
                bit = bits[idx]
                if bit == 0:
                    style = None
                    char = " "
                else:
                    avg = depth[idx] / count[idx]
                    step = int(avg * (steps - 1))
                    step = 0 if step < 0 else (steps - 1 if step >= steps else step)
                    style = ramp[step]
                    char = chr(BRAILLE_BASE + bit)

                if style != run_style and run:
                    text.append("".join(run), style=run_style)
                    run = []
                run_style = style
                run.append(char)

            if run:
                text.append("".join(run), style=run_style)
            if row != self.ch - 1:
                text.append("\n")

        return text


def build_ramp(
    color: str,
    steps: int = DEPTH_STEPS,
    floor: float = 0.22,
    gamma: float = 0.65,
) -> list[str]:
    """A dim->bright ladder of one hue, as Rich colour strings.

    `floor` keeps the far side of a wireframe visible rather than black, which
    is what stops a rotating sphere from looking like a flat disc.

    `gamma` below 1 lifts the middle of the ramp. On a sphere most points sit
    near the silhouette, where depth clusters around 0.5 — a linear ramp puts
    the bulk of the wireframe at half brightness and the whole thing reads as
    murky. The curve pushes those mid values up so the form stays legible.
    """
    color = color.lstrip("#")
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)

    ramp: list[str] = []
    for i in range(steps):
        t = (i / max(1, steps - 1)) ** gamma
        t = floor + (1.0 - floor) * t
        ramp.append(f"#{int(r * t):02x}{int(g * t):02x}{int(b * t):02x}")
    return ramp
