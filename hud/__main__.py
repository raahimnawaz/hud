from __future__ import annotations

from hud.app import HudApp
from hud.core.config import Config


def main() -> None:
    HudApp(Config.load()).run()


if __name__ == "__main__":
    main()
