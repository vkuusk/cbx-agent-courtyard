"""Courtyard in the menu bar: the buttons for the hub's make targets, and the shift.

    uv run --extra tray courtyard-tray      # by hand
    make install                            # as its own LaunchAgent, beside the hub's

One icon in the top bar. Beside it: nothing while all is quiet, the number of messages
waiting at the gate when something needs you, a hollow dot when the hub is down. The
menu: the state line, Open WebUI, Start hub / Stop hub / Restart hub (what `make
hub-start|stop|restart` run), Start shift / End shift (the hub's API), Show log, Quit.

This is deliberately a separate small app: the hub's WebUI cannot start a hub that is
down, and a stop button inside the hub would tie it to this machine's supervisor. The
hub stays the same here or, later, on a remote machine; only this app is macOS-shaped.
"""

from __future__ import annotations

import sys
import threading

try:
    import rumps
except ImportError:  # pragma: no cover - the tray extra is optional
    rumps = None

from courtyard.traycore import HubControl, HubState

POLL_SECONDS = 5


def main() -> None:
    if rumps is None:
        sys.exit("the menu bar app needs the `tray` extra: uv sync --extra tray")
    control = HubControl()
    icon = control.root / "webui" / "icons" / "menubar.png"
    app = rumps.App(
        "Courtyard", icon=str(icon) if icon.exists() else None, template=True, quit_button=None
    )
    status = rumps.MenuItem("hub: checking…")
    status.set_callback(None)
    start_hub = rumps.MenuItem("Start hub")
    stop_hub = rumps.MenuItem("Stop hub")
    restart_hub = rumps.MenuItem("Restart hub")
    start_shift = rumps.MenuItem("Start shift")
    end_shift = rumps.MenuItem("End shift")
    app.menu = [
        status,
        None,
        rumps.MenuItem("Open WebUI", callback=lambda _: control.open_webui()),
        None,
        start_hub,
        stop_hub,
        restart_hub,
        None,
        start_shift,
        end_shift,
        None,
        rumps.MenuItem("Show hub log", callback=lambda _: control.open_log()),
        rumps.MenuItem("Quit Courtyard menu", callback=lambda _: rumps.quit_application()),
    ]

    def apply(state: HubState) -> None:
        status.title = state.line()
        app.title = state.glyph()
        start_hub.set_callback(None if state.up else run("start"))
        stop_hub.set_callback(run("stop") if state.up else None)
        restart_hub.set_callback(run("restart") if state.up else None)
        shift_on = state.up and state.shift not in (None, "off")
        start_shift.set_callback(None if (not state.up or shift_on) else do_start_shift)
        end_shift.set_callback(do_end_shift if shift_on else None)

    def refresh(_=None) -> None:
        apply(control.state())

    def run(action: str):
        def _go(_):
            status.title = f"hub: {action}ing…"

            def work() -> None:
                result = control.run(action)
                if result.returncode != 0:
                    rumps.notification(
                        "Courtyard",
                        f"{action} failed",
                        (result.stderr or result.stdout).strip()[-200:],
                    )
                refresh()

            threading.Thread(target=work, daemon=True).start()

        return _go

    def do_start_shift(_) -> None:
        try:
            control.start_shift()
        except Exception as exc:  # noqa: BLE001 - shown to the operator
            rumps.notification("Courtyard", "Start shift failed", str(exc)[-200:])
        refresh()

    def do_end_shift(_) -> None:
        try:
            answer = control.end_shift(force=False)
            if answer == "shift_busy":
                ok = rumps.alert(
                    "End the shift anyway?",
                    "Some conversations are mid-work. Ending the shift expires them "
                    "(kept in history) and closes the agents' terminals.",
                    ok="End shift",
                    cancel="Not now",
                )
                if ok == 1:
                    control.end_shift(force=True)
        except Exception as exc:  # noqa: BLE001 - shown to the operator
            rumps.notification("Courtyard", "End shift failed", str(exc)[-200:])
        refresh()

    rumps.Timer(refresh, POLL_SECONDS).start()
    refresh()
    app.run()


if __name__ == "__main__":
    main()
