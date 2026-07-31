-- HUD global hotkey: Ctrl+F+U as a genuine simultaneous chord.
--
-- Why this is an eventtap rather than hs.hotkey.bind: Ctrl is a modifier but F
-- and U are both ordinary keys, and every hotkey API binds modifiers plus
-- exactly ONE key. A three-key chord has to watch the raw event stream.
--
-- The complication is that both halves collide with readline: Ctrl+F is
-- forward-char and Ctrl+U is kill-line, and you use both constantly in a
-- shell. Swallowing them outright would break your terminal.
--
-- So: Ctrl+F is captured and held for CHORD_WINDOW seconds. If U arrives in
-- that window the HUD toggles and both keys are consumed. If the window
-- expires, the held Ctrl+F is replayed into whatever app has focus. Net
-- effect — the chord works, Ctrl+F still works with a small lag, and Ctrl+U is
-- only ever intercepted mid-chord.
--
-- If the lag turns out to annoy you, set USE_SIMPLE_BINDING = true below for a
-- conflict-free Ctrl+Alt+U instead. One line, no event tap, no lag.

local M = {}

local CHORD_WINDOW = 0.40
local USE_SIMPLE_BINDING = false

local HUD_BIN = os.getenv("HOME") .. "/hud/.venv/bin/hud"
local HUD_GHOSTTY_CONFIG = os.getenv("HOME") .. "/.config/ghostty/hud"
local WINDOW_TITLE_MATCH = "HUD"

-- ---------------------------------------------------------------- toggling --

local function findHudWindow()
  local app = hs.application.get("Ghostty")
  if not app then return nil, nil end
  for _, w in ipairs(app:allWindows()) do
    if w:title() and w:title():find(WINDOW_TITLE_MATCH) then
      return w, app
    end
  end
  return nil, app
end

local function launchHud()
  -- A dedicated Ghostty instance with the HUD-only config, so the shader stack
  -- never touches your everyday terminal.
  local cmd = string.format(
    'open -na Ghostty --args --config-file=%q -e %q',
    HUD_GHOSTTY_CONFIG, HUD_BIN
  )
  hs.execute(cmd)
end

function M.toggle()
  local win, app = findHudWindow()
  if not win then
    launchHud()
    return
  end
  -- Already running: focus it, or hide it if it is already frontmost. Keeping
  -- the process alive is the whole point — Textual's ~0.5-1s cold start gets
  -- paid once at login instead of on every summon.
  if app:isFrontmost() and win:isVisible() then
    app:hide()
  else
    win:raise()
    win:focus()
  end
end

-- ------------------------------------------------------------------ chord --

local pendingTimer = nil
local replaying = false

local function replayCtrlF()
  replaying = true
  hs.eventtap.keyStroke({ "ctrl" }, "f", 0)
  -- Cleared on a timer rather than inline: keyStroke posts asynchronously, so
  -- clearing immediately can let our own synthetic event back into the tap.
  hs.timer.doAfter(0.05, function() replaying = false end)
end

local function cancelPending(replay)
  if pendingTimer then
    pendingTimer:stop()
    pendingTimer = nil
    if replay then replayCtrlF() end
  end
end

local chordTap = hs.eventtap.new({ hs.eventtap.event.types.keyDown }, function(e)
  if replaying then return false end

  local flags = e:getFlags()
  local key = hs.keycodes.map[e:getKeyCode()]

  if pendingTimer then
    if key == "u" then
      cancelPending(false)
      M.toggle()
      return true -- consume the U
    end
    -- Any other key means this was not the chord. Flush the held Ctrl+F first
    -- so ordering is preserved, then let this key through untouched.
    cancelPending(true)
    return false
  end

  local onlyCtrl = flags.ctrl and not flags.cmd and not flags.alt and not flags.shift
  if onlyCtrl and key == "f" then
    pendingTimer = hs.timer.doAfter(CHORD_WINDOW, function()
      pendingTimer = nil
      replayCtrlF()
    end)
    return true -- hold it; we decide in CHORD_WINDOW seconds
  end

  return false
end)

-- ------------------------------------------------------------------ start --

if USE_SIMPLE_BINDING then
  hs.hotkey.bind({ "ctrl", "alt" }, "u", M.toggle)
else
  chordTap:start()
end

hs.alert.show("HUD hotkey armed: " ..
  (USE_SIMPLE_BINDING and "Ctrl+Alt+U" or "Ctrl+F+U"))

return M
