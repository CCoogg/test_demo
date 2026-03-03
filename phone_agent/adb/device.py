"""Device control utilities for Android automation."""

import os
import subprocess
import time
import re
from typing import List, Optional, Tuple

from phone_agent.config.apps import APP_PACKAGES
from phone_agent.config.timing import TIMING_CONFIG

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


def get_current_app(device_id: str | None = None) -> str:
    """
    Get the currently focused app name.

    Args:
        device_id: Optional ADB device ID for multi-device setups.

    Returns:
        The app name if recognized, otherwise package name or "System Home".
    """
    result = _run_adb(["shell", "dumpsys", "window"], device_id)
    output = result.stdout
    if not output:
        raise ValueError("No output from dumpsys window")

    # Parse window focus info
    for line in output.split("\n"):
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            for app_name, package in APP_PACKAGES.items():
                if package in line:
                    return app_name

    # Fallback: extract raw package from focus line if not mapped
    for line in output.split("\n"):
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            m = re.search(r"([A-Za-z0-9_\.]+)/([A-Za-z0-9_\.]+)", line)
            if m:
                return m.group(1)

    return "System Home"


def tap(
    x: int, y: int, device_id: str | None = None, delay: float | None = None
) -> None:
    """
    Tap at the specified coordinates.

    Args:
        x: X coordinate.
        y: Y coordinate.
        device_id: Optional ADB device ID.
        delay: Delay in seconds after tap. If None, uses configured default.
    """
    if delay is None:
        delay = TIMING_CONFIG.device.default_tap_delay

    _run_adb(["shell", "input", "tap", str(x), str(y)], device_id)
    time.sleep(delay)


def double_tap(
    x: int, y: int, device_id: str | None = None, delay: float | None = None
) -> None:
    """
    Double tap at the specified coordinates.

    Args:
        x: X coordinate.
        y: Y coordinate.
        device_id: Optional ADB device ID.
        delay: Delay in seconds after double tap. If None, uses configured default.
    """
    if delay is None:
        delay = TIMING_CONFIG.device.default_double_tap_delay

    _run_adb(["shell", "input", "tap", str(x), str(y)], device_id)
    time.sleep(TIMING_CONFIG.device.double_tap_interval)
    _run_adb(["shell", "input", "tap", str(x), str(y)], device_id)
    time.sleep(delay)


def long_press(
    x: int,
    y: int,
    duration_ms: int = 3000,
    device_id: str | None = None,
    delay: float | None = None,
) -> None:
    """
    Long press at the specified coordinates.

    Args:
        x: X coordinate.
        y: Y coordinate.
        duration_ms: Duration of press in milliseconds.
        device_id: Optional ADB device ID.
        delay: Delay in seconds after long press. If None, uses configured default.
    """
    if delay is None:
        delay = TIMING_CONFIG.device.default_long_press_delay

    _run_adb(
        ["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms)],
        device_id,
    )
    time.sleep(delay)


def swipe(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration_ms: int | None = None,
    device_id: str | None = None,
    delay: float | None = None,
) -> None:
    """
    Swipe from start to end coordinates.

    Args:
        start_x: Starting X coordinate.
        start_y: Starting Y coordinate.
        end_x: Ending X coordinate.
        end_y: Ending Y coordinate.
        duration_ms: Duration of swipe in milliseconds (auto-calculated if None).
        device_id: Optional ADB device ID.
        delay: Delay in seconds after swipe. If None, uses configured default.
    """
    if delay is None:
        delay = TIMING_CONFIG.device.default_swipe_delay

    if duration_ms is None:
        # Calculate duration based on distance
        dist_sq = (start_x - end_x) ** 2 + (start_y - end_y) ** 2
        duration_ms = int(dist_sq / 1000)
        duration_ms = max(1000, min(duration_ms, 2000))  # Clamp between 1000-2000ms

    _run_adb(
        [
            "shell",
            "input",
            "swipe",
            str(start_x),
            str(start_y),
            str(end_x),
            str(end_y),
            str(duration_ms),
        ],
        device_id,
    )
    time.sleep(delay)


def back(device_id: str | None = None, delay: float | None = None) -> None:
    """
    Press the back button.

    Args:
        device_id: Optional ADB device ID.
        delay: Delay in seconds after pressing back. If None, uses configured default.
    """
    if delay is None:
        delay = TIMING_CONFIG.device.default_back_delay

    _run_adb(["shell", "input", "keyevent", "4"], device_id)
    time.sleep(delay)


def home(device_id: str | None = None, delay: float | None = None) -> None:
    """
    Press the home button.

    Args:
        device_id: Optional ADB device ID.
        delay: Delay in seconds after pressing home. If None, uses configured default.
    """
    if delay is None:
        delay = TIMING_CONFIG.device.default_home_delay

    _run_adb(["shell", "input", "keyevent", "KEYCODE_HOME"], device_id)
    time.sleep(delay)


def launch_app(
    app_name: str, device_id: str | None = None, delay: float | None = None
) -> bool:
    """
    Launch an app by name.

    Args:
        app_name: The app name (must be in APP_PACKAGES).
        device_id: Optional ADB device ID.
        delay: Delay in seconds after launching. If None, uses configured default.

    Returns:
        True if app was launched, False if app not found.
    """
    if delay is None:
        delay = TIMING_CONFIG.device.default_launch_delay

    if app_name not in APP_PACKAGES:
        return False

    package = APP_PACKAGES[app_name]
    _run_adb(
        [
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        device_id,
    )
    time.sleep(delay)
    return True


def _get_adb_prefix(device_id: str | None) -> list:
    """Get ADB command prefix with optional device specifier."""
    if device_id:
        return ["adb", "-s", device_id]
    return ["adb"]
