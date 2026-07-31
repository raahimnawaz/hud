"""Executes Actions. The single choke point every side effect passes through.

Confirmation is *not* decided here — the app layer gates on Action.danger before
calling run(). Keeping that split means a plugin cannot accidentally bypass a
confirm by constructing its own subprocess.
"""

from __future__ import annotations

from hud.core.action import Action, Completed, Danger, PowerOp
from hud.core.target import Target


class PowerDenied(Exception):
    """Raised when a remote host has not been opted into power control."""


async def run_action(action: Action, target: Target) -> Completed:
    """The single choke point. The allow_power check lives here rather than in
    the power plugin so that no caller holding a power Action can route around
    it by constructing the Action itself.
    """
    if action.is_power and not target.allows_power:
        raise PowerDenied(
            f"{target.label} has allow_power = false. Enable it in hosts.toml "
            f"before this host can be powered off from the HUD."
        )

    if not target.online:
        return Completed(returncode=1, stderr=f"{target.label} is offline")

    if action.detach:
        await target.host.spawn(action.argv)
        return Completed(returncode=0)

    result = await target.host.run(action.argv, timeout=20.0)

    # A shutdown or restart issued over SSH kills the connection under us. That
    # is the expected outcome of success, not a failure worth surfacing.
    if action.is_power and not target.host.is_local:
        target.mark_offline("powered down from HUD")

    return result


def power_action(op: PowerOp, target: Target) -> Action:
    """Build a power Action bound to its target, so every confirmation dialog
    can name the machine it is about to act on."""
    base = target.platform.power(op)
    return Action(
        title=base.title,
        argv=base.argv,
        danger=base.danger,
        target=target,
        is_power=True,
    )


def gate_for(danger: Danger, target: Target) -> tuple[str, str]:
    """Which confirmation a danger level requires, and the phrase to type.

    Returns (gate, phrase) where gate is none | keypress | type.

    Remote destructive actions demand the host *alias* specifically, because
    "shut down the wrong machine" is the mistake no timing gesture catches —
    typing the name forces you to look at which host you selected.
    """
    if danger is Danger.SAFE:
        return "none", ""
    if danger is Danger.CAUTION:
        return "keypress", ""
    if target.host.is_local:
        return "type", "CONFIRM"
    return "type", target.host.alias
