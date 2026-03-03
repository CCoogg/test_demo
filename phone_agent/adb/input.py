"""Input utilities for Android device text input."""

import base64
import os
import subprocess
from typing import Optional

ADB_VERBOSE = os.getenv("PHONE_AGENT_ADB_VERBOSE", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


def _run_adb(args: list[str], device_id: str | None = None) -> subprocess.CompletedProcess:
    adb_prefix = _get_adb_prefix(device_id)
    cmd = adb_prefix + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if ADB_VERBOSE:
        print(f"[adb] {' '.join(cmd)}")
        if result.stdout:
            print(f"[adb][stdout] {result.stdout.strip()}")
        if result.stderr:
            print(f"[adb][stderr] {result.stderr.strip()}")
    if result.returncode != 0:
        raise RuntimeError(
            f"ADB command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr}"
        )
    return result


def type_text(text: str, device_id: str | None = None) -> None:
    """
    Type text into the currently focused input field using ADB Keyboard.

    Args:
        text: The text to type.
        device_id: Optional ADB device ID for multi-device setups.

    Note:
        Requires ADB Keyboard to be installed on the device.
        See: https://github.com/nicnocquee/AdbKeyboard
    """
    encoded_text = base64.b64encode(text.encode("utf-8")).decode("utf-8")
    _run_adb(
        [
            "shell",
            "am",
            "broadcast",
            "-a",
            "ADB_INPUT_B64",
            "--es",
            "msg",
            encoded_text,
        ],
        device_id,
    )


def clear_text(device_id: str | None = None) -> None:
    """
    Clear text in the currently focused input field.

    Args:
        device_id: Optional ADB device ID for multi-device setups.
    """
    _run_adb(["shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT"], device_id)


def detect_and_set_adb_keyboard(device_id: str | None = None) -> str:
    """
    Detect current keyboard and switch to ADB Keyboard if needed.

    Args:
        device_id: Optional ADB device ID for multi-device setups.

    Returns:
        The original keyboard IME identifier for later restoration.
    """
    # Get current IME
    result = _run_adb(
        ["shell", "settings", "get", "secure", "default_input_method"], device_id
    )
    current_ime = (result.stdout + result.stderr).strip()

    # Switch to ADB Keyboard if not already set
    if "com.android.adbkeyboard/.AdbIME" not in current_ime:
        _run_adb(["shell", "ime", "set", "com.android.adbkeyboard/.AdbIME"], device_id)

    # Warm up the keyboard
    type_text("", device_id)

    return current_ime


def restore_keyboard(ime: str, device_id: str | None = None) -> None:
    """
    Restore the original keyboard IME.

    Args:
        ime: The IME identifier to restore.
        device_id: Optional ADB device ID for multi-device setups.
    """
    _run_adb(["shell", "ime", "set", ime], device_id)


def _get_adb_prefix(device_id: str | None) -> list:
    """Get ADB command prefix with optional device specifier."""
    if device_id:
        return ["adb", "-s", device_id]
    return ["adb"]
