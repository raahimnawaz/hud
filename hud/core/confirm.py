"""Confirmation gates for dangerous actions.

Design note — a deviation from the original plan, for a real reason: terminals
do not report key *release*, only key press (and OS-level repeat). A literal
"hold Enter for two seconds" gesture is therefore not implementable in a TUI
without depending on the user's key-repeat settings, which is exactly the kind
of fragility you do not want guarding a shutdown.

So DESTRUCTIVE actions require *typing* a confirmation word instead. This is
strictly stronger than a hold: it cannot be triggered by a stuck key, it cannot
be muscle-memoried past, and it is the same pattern GitHub uses for repository
deletion. Remote hosts require the host alias specifically, because
"shut down the wrong machine" is the failure a timing gesture never catches.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from hud.core.action import Action, Danger


class ConfirmScreen(ModalScreen[bool]):
    """Returns True if the user confirmed, False otherwise."""

    BINDINGS = [
        Binding("escape", "dismiss_no", "Cancel", show=True),
    ]

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen > Vertical {
        width: 62;
        height: auto;
        border: heavy $error;
        background: $surface;
        padding: 1 2;
    }
    ConfirmScreen.-caution > Vertical {
        border: heavy $warning;
    }
    ConfirmScreen .title {
        text-style: bold;
        color: $error;
        width: 100%;
    }
    ConfirmScreen.-caution .title {
        color: $warning;
    }
    ConfirmScreen .target {
        color: $foreground;
        text-style: bold;
        margin: 1 0 0 0;
    }
    ConfirmScreen .hint {
        color: $foreground 60%;
        margin: 1 0;
    }
    ConfirmScreen Horizontal {
        height: auto;
        margin: 1 0 0 0;
    }
    ConfirmScreen Button {
        margin: 0 1 0 0;
    }
    """

    def __init__(self, action: Action, gate: str, *, phrase: str = "") -> None:
        super().__init__()
        self.action = action
        self.gate = gate
        self.phrase = phrase

    def compose(self) -> ComposeResult:
        caution = self.action.danger is Danger.CAUTION
        self.set_class(caution, "-caution")

        with Vertical():
            verb = "CONFIRM" if caution else "⚠  DESTRUCTIVE ACTION"
            yield Label(verb, classes="title")
            yield Static(self.action.title, classes="target")
            yield Static(f"Target: {self.action.describe_target()}", classes="target")

            if self.gate == "keypress":
                yield Static("Press [b]y[/b] to confirm, [b]esc[/b] to cancel", classes="hint")
            else:
                yield Static(
                    f"Type [b]{self.phrase}[/b] to confirm. This cannot be undone.",
                    classes="hint",
                )
                yield Input(placeholder=self.phrase, id="phrase")
                with Horizontal():
                    yield Button("Confirm", variant="error", id="ok", disabled=True)
                    yield Button("Cancel", variant="primary", id="cancel")

    def on_mount(self) -> None:
        if self.gate != "keypress":
            self.query_one("#phrase", Input).focus()

    def on_key(self, event) -> None:
        if self.gate == "keypress" and event.key == "y":
            event.stop()
            self.dismiss(True)

    @on(Input.Changed, "#phrase")
    def _check_phrase(self, event: Input.Changed) -> None:
        self.query_one("#ok", Button).disabled = event.value.strip() != self.phrase

    @on(Input.Submitted, "#phrase")
    def _submit_phrase(self, event: Input.Submitted) -> None:
        if event.value.strip() == self.phrase:
            self.dismiss(True)

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(False)

    def action_dismiss_no(self) -> None:
        self.dismiss(False)
