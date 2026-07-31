#!/usr/bin/env bash
# Wires up the terminal + hotkey layer on macOS.
#
# Safe to re-run. Never overwrites an existing ~/.hammerspoon/init.lua — it
# appends a single require line instead, so your own config survives.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GHOSTTY_DIR="$HOME/.config/ghostty"
HS_DIR="$HOME/.hammerspoon"

say() { printf '\033[36m==>\033[0m %s\n' "$1"; }

# ---------------------------------------------------------------- packages --

say "Installing Ghostty, Hammerspoon, and JetBrains Mono Nerd Font"
brew install --cask ghostty hammerspoon font-jetbrains-mono-nerd-font

# ----------------------------------------------------------------- ghostty --

say "Writing HUD-only Ghostty profile to $GHOSTTY_DIR/hud"
mkdir -p "$GHOSTTY_DIR"
cp "$REPO/config/ghostty-hud" "$GHOSTTY_DIR/hud"

# ------------------------------------------------------------- hammerspoon --

say "Installing Hammerspoon chord config"
mkdir -p "$HS_DIR"
cp "$REPO/config/hammerspoon-hud.lua" "$HS_DIR/hud.lua"

if [ -f "$HS_DIR/init.lua" ]; then
  if grep -q 'require("hud")' "$HS_DIR/init.lua"; then
    say "init.lua already requires hud — leaving it alone"
  else
    say "Appending require to your existing init.lua"
    printf '\nrequire("hud")\n' >> "$HS_DIR/init.lua"
  fi
else
  printf 'require("hud")\n' > "$HS_DIR/init.lua"
fi

# ------------------------------------------------------------------- done --

cat <<EOF

$(say "Done. Two manual steps remain:")

  1. Launch Hammerspoon and grant it Accessibility permission
     (System Settings > Privacy & Security > Accessibility).
     The event tap CANNOT read the Ctrl+F+U chord without it.

  2. Reload the Hammerspoon config (menu bar icon > Reload Config).

Then press Ctrl+F+U from anywhere.

No shader is installed. The look is meant to be modern — crisp text, flat
panels, one accent — and a CRT treatment works against that on dense tables.
EOF
