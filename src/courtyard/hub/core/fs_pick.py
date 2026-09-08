"""The native directory picker (item: professional dir choosing, 2026-09-07).

The hub runs on the operator's own machine in their GUI session — the same premise the
shift uses to open Terminal windows — so it can show the real macOS folder dialog via
`osascript` and return the chosen POSIX path. Browser-side pickers cannot do this job:
web APIs never reveal an absolute path to the page, by security design.

Where the native dialog is unavailable (not macOS, no GUI, disabled by env
COURTYARD_NATIVE_PICKER=0, or osascript failing), the API answers with the code
`native_picker_unavailable` and the WebUI falls back to its own browse dialog.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from courtyard.hub.core.errors import DomainError


class NativePickerUnavailable(DomainError):
    code = "native_picker_unavailable"
    http_status = 409


class PickerBusy(DomainError):
    """A dialog is already on screen; a second one would stack invisibly behind it."""

    code = "picker_busy"


_lock = threading.Lock()

# choose folder returns the alias; activating first brings the dialog in front of the
# browser. The prompt is passed as argv (never spliced into the script) — no escaping.
_SCRIPT = (
    "on run argv\n"
    '  tell application id "com.apple.systemevents" to activate\n'
    "  POSIX path of (choose folder with prompt (item 1 of argv))\n"
    "end run"
)


def pick_directory(prompt: str, timeout: float = 300) -> str | None:
    """Show the native folder dialog; the chosen path, or None when cancelled."""
    if sys.platform != "darwin" or os.environ.get("COURTYARD_NATIVE_PICKER") == "0":
        raise NativePickerUnavailable("no native folder dialog on this hub")
    if not _lock.acquire(blocking=False):
        raise PickerBusy("a folder dialog is already open on the hub's screen")
    try:
        result = subprocess.run(
            ["osascript", "-e", _SCRIPT, prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,  # a nonzero exit is data: cancel vs failure, judged below
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise NativePickerUnavailable(f"the folder dialog did not answer: {exc}") from exc
    finally:
        _lock.release()
    if result.returncode == 0:
        return result.stdout.strip()
    if "-128" in result.stderr:  # AppleScript's "User canceled"
        return None
    raise NativePickerUnavailable(f"osascript failed: {result.stderr.strip()}")
