"""Courtyard in the menu bar: the buttons for the hub's make targets, and the shift.

    uv run --extra tray courtyard-tray      # by hand
    make install                            # as its own LaunchAgent, beside the hub's

One icon in the top bar. Beside it: nothing while all is quiet, the number of messages
waiting at the gate when something needs you, a hollow dot when the hub is down. The
menu: the state line, Open WebUI, Start hub / Stop hub / Restart hub (what `make
hub-start|stop|restart` run), Start shift / End shift (the hub's API), Show log, Quit
Courtyard Admin. A menu bar app only: no Dock tile, no entry in the task switcher; its
alerts carry the courtyard's icon, not the Python launcher's rocket. Quit unloads its
LaunchAgent (a plain exit would be restarted); the Courtyard Admin app in ~/Applications,
`make hub-start` or the next login bring it back.

This is deliberately a separate small app: the hub's WebUI cannot start a hub that is
down, and a stop button inside the hub would tie it to this machine's supervisor. The
hub stays the same here or, later, on a remote machine; only this app is macOS-shaped.
"""

from __future__ import annotations

import sys
import threading

try:
    import rumps
    from AppKit import NSApplication, NSImage
except ImportError:  # pragma: no cover - the tray extra is optional
    rumps = None

from pathlib import Path

from courtyard.traycore import HubControl, HubState

POLL_SECONDS = 5
# NSApplicationActivationPolicyAccessory: a process with a menu bar item and windows on
# demand, but no Dock tile and no place in the task switcher (Cmd-Tab, Force Quit)
ACCESSORY = 1


def keep_out_of_the_dock(nsapp, icon: Path | None, load_image) -> None:
    """Without a .app bundle the process runs as Python's framework launcher: a Dock tile
    with the Python rocket, listed in Force Quit, restarted by launchd when killed there.
    The activation policy makes it a menu bar app; the icon is what its alerts and
    notifications show."""
    nsapp.setActivationPolicy_(ACCESSORY)
    if icon is not None and icon.exists():
        image = load_image(str(icon))
        if image is not None:
            nsapp.setApplicationIconImage_(image)


def main() -> None:
    if rumps is None:
        sys.exit("the menu bar app needs the `tray` extra: uv sync --extra tray")
    control = HubControl()
    keep_out_of_the_dock(
        NSApplication.sharedApplication(),
        control.root / "webui" / "icons" / "icon-512.png",
        lambda path: NSImage.alloc().initWithContentsOfFile_(path),
    )
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
        rumps.MenuItem("Quit Courtyard Admin", callback=lambda _: quit_admin()),
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

    def quit_admin() -> None:
        if not control.quit_admin():  # not under launchd: a plain exit is final
            rumps.quit_application()

    rumps.Timer(refresh, POLL_SECONDS).start()
    refresh()
    app.run()


if __name__ == "__main__":
    main()
