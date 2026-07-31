# Demo recording script for charmbracelet/vhs.
#
#   brew install vhs
#   vhs demo.tape        ->  docs/demo.gif
#
# vhs drives a real terminal and records it, which is the only way to get a
# smooth, honest recording of a TUI — screen-capture tools drop frames on the
# braille sphere and the result looks broken when it is not.
#
# Keep this under ~25s. A README GIF that loops before the reader finishes it
# reads as fast; one that runs a minute reads as slow.

Output docs/demo.gif

Set Shell "zsh"
Set FontFamily "JetBrainsMono Nerd Font Mono"
Set FontSize 15
Set Width 1500
Set Height 900
Set Padding 20
Set Theme { "name": "lattice", "background": "#0a0b0c", "foreground": "#b6bec7", "cursor": "#e0873c", "selection": "#e0873c" }
Set Framerate 30
Set PlaybackSpeed 1.0

Hide
Type "cd ~/hud && clear" Enter
Sleep 500ms
Show

# --- boot -------------------------------------------------------------------
Type "hud" Enter
Sleep 4s

# --- projects: composite state per workspace --------------------------------
Down 2
Sleep 1500ms
Down 1
Sleep 2s

# --- the command palette is the primary interface ---------------------------
Ctrl+p
Sleep 800ms
Type "engage"
Sleep 2s
Escape
Sleep 500ms

# --- per-app inspection -----------------------------------------------------
Ctrl+p
Sleep 500ms
Type "docker"
Sleep 1500ms
Escape
Sleep 500ms

# --- themes -----------------------------------------------------------------
Type "t"
Sleep 1500ms
Type "t"
Sleep 1500ms

Sleep 1s
Ctrl+q
