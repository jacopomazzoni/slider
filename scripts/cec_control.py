#!/usr/bin/env python3
from __future__ import annotations

import os
import fcntl
import math
from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Iterable
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / '.env')


class CECControlError(RuntimeError):
    """Raised when a CEC command cannot be delivered successfully."""


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise CECControlError(f"{name} must be an integer, got {raw_value!r}.") from exc


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
        if not math.isfinite(value) or value < 0 or value > 60:
            raise ValueError('must be finite and between 0 and 60')
        return value
    except ValueError as exc:
        raise CECControlError(f"{name} must be a number, got {raw_value!r}.") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, "").strip().lower()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise CECControlError(f"{name} must be a boolean-like value, got {raw_value!r}.")


def _cec_client_bin() -> str:
    configured = os.getenv("CEC_CLIENT_BIN", "").strip()
    if configured:
        return configured

    detected = shutil.which("cec-client")
    if detected:
        return detected

    raise CECControlError(
        "cec-client was not found in PATH. Install libcec/cec-client on the Raspberry Pi "
        "or set CEC_CLIENT_BIN to its full path."
    )


def _target() -> str:
    target = os.getenv('CEC_TV_ADDRESS', '0').strip().lower() or '0'
    if not re.fullmatch(r'[0-9a-e]', target):
        raise CECControlError('CEC_TV_ADDRESS must be one hexadecimal logical address (0-e), normally 0 for the TV.')
    return target


def list_adapters() -> tuple[list[str], str]:
    result = subprocess.run([_cec_client_bin(), '-l'], capture_output=True, text=True, timeout=20)
    output = result.stdout + '\n' + result.stderr
    if result.returncode:
        raise CECControlError(output.strip() or 'CEC adapter discovery failed.')
    return list(dict.fromkeys(re.findall(r'com port:\s*(\S+)', output, re.I))), output.strip()


def select_adapter() -> str:
    adapter = os.getenv('CEC_ADAPTER', '').strip()
    if not adapter:
        adapters, output = list_adapters()
        if not adapters:
            raise CECControlError('No CEC adapter detected. Check HDMI connection, cec-utils and /dev/cec*.\n' + output)
        if len(adapters) != 1:
            raise CECControlError('Multiple CEC adapters found: ' + ', '.join(adapters)
                                  + '. Set CEC_ADAPTER in .env to the connected HDMI adapter.')
        adapter = adapters[0]
    if adapter.startswith('-') or any(c.isspace() for c in adapter):
        raise CECControlError('Invalid CEC_ADAPTER.')
    if adapter.startswith('/dev/') and not os.access(adapter, os.R_OK | os.W_OK):
        raise CECControlError(f'Cannot read/write {adapter}. Check its owner/group and grant the runtime user access; log in again after group changes.')
    return adapter


@contextmanager
def adapter_lock():
    # Shared by direct CLI calls and all workers on this Pi.
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    from sliderCMS.runtime import DATA_DIR
    path = DATA_DIR / 'logs' / 'cec.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CECControlError('Another CEC operation is running; try again shortly.') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _run_cec_commands(commands: Iterable[str], *, adapter: str, timeout_seconds: int | None = None) -> subprocess.CompletedProcess[str]:
    command_list = [command.strip() for command in commands if command and command.strip()]
    if len(command_list) != 1 or '\n' in command_list[0] or '\r' in command_list[0]:
        raise CECControlError('cec-client single-command mode requires exactly one command.')

    timeout_seconds = timeout_seconds or _env_int("CEC_TIMEOUT_SECONDS", 20)
    if not 1 <= timeout_seconds <= 60:
        raise CECControlError('CEC_TIMEOUT_SECONDS must be between 1 and 60.')
    debug_level = str(_env_int("CEC_DEBUG_LEVEL", 1))
    cec_bin = _cec_client_bin()
    args = [cec_bin, '-s', '-d', debug_level, '-t', 'p', '-o', 'sliderCMS']
    port = os.getenv('CEC_HDMI_PORT', '').strip()
    if port:
        if not port.isdigit() or not 1 <= int(port) <= 15:
            raise CECControlError('CEC_HDMI_PORT must be between 1 and 15 (the TV input, not the Pi connector number).')
        args.extend(['-p', port])
    args.append(adapter)
    process = subprocess.run(
        args,
        input="\n".join(command_list) + "\n",
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    # libCEC command handlers can print errors but still return exit status zero.
    output = process.stdout + '\n' + process.stderr
    if process.returncode != 0 or re.search(r'ERROR:|failed to|unable to|invalid destination', output, re.I):
        details = "\n".join(
            part for part in (process.stdout.strip(), process.stderr.strip()) if part
        )
        raise CECControlError(
            f"CEC command failed (exit status {process.returncode}) while running {command_list!r}."
            + (f"\n{details}" if details else "")
        )

    return process


def power_status(adapter: str) -> str:
    result = _run_cec_commands([f'pow {_target()}'], adapter=adapter)
    match = re.search(r'power status:\s*([^\r\n]+)', result.stdout, re.I)
    if not match:
        raise CECControlError('TV did not report its power status. Check CEC is enabled on the TV and the HDMI cable supports CEC.')
    return match.group(1).strip().lower()


def _verify(expected: str, adapter: str) -> None:
    state = power_status(adapter)
    if state != expected:
        raise CECControlError(f'TV reported {state!r}, expected {expected!r}; power change is not confirmed.')


def _retry(action: str, callback) -> None:
    retries = _env_int("CEC_RETRIES", 3)
    if not 1 <= retries <= 5:
        raise CECControlError('CEC_RETRIES must be between 1 and 5.')
    retry_delay = _env_float("CEC_RETRY_DELAY_SECONDS", 2.0)
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            callback()
            return
        except Exception as exc:  # noqa: BLE001 - intentional task-level retry wrapper
            last_error = exc
            if attempt >= retries:
                break
            print(
                f"{action} attempt {attempt}/{retries} failed: {exc}. Retrying in {retry_delay:.1f}s...",
                file=sys.stderr,
            )
            time.sleep(retry_delay)

    raise CECControlError(f"{action} failed after {retries} attempts: {last_error}") from last_error


def power_on() -> None:
    target = _target()
    settle_delay = _env_float("CEC_POWER_ON_SETTLE_SECONDS", 4.0)
    active_source_enabled = _env_bool("CEC_SEND_ACTIVE_SOURCE", True)
    active_source_command = os.getenv("CEC_ACTIVE_SOURCE_COMMAND", "as").strip() or "as"

    def _send() -> None:
        _run_cec_commands([f"on {target}"], adapter=adapter)
        if settle_delay > 0:
            time.sleep(settle_delay)
        if active_source_enabled:
            _run_cec_commands([active_source_command], adapter=adapter)
        _verify('on', adapter)

    with adapter_lock():
        adapter = select_adapter()
        _retry("CEC power on", _send)
    print(
        f"TV power ON confirmed at address {target} via {adapter}."
        + (" Active source requested." if active_source_enabled else "")
    )


def power_off() -> None:
    target = _target()
    settle_delay = _env_float('CEC_POWER_OFF_SETTLE_SECONDS', 2.0)

    def _send() -> None:
        _run_cec_commands([f"standby {target}"], adapter=adapter)
        if settle_delay:
            time.sleep(settle_delay)
        _verify('standby', adapter)

    with adapter_lock():
        adapter = select_adapter()
        _retry("CEC power off", _send)
    print(f"TV STANDBY confirmed at address {target} via {adapter}.")


def power_cycle() -> None:
    onoff_delay = _env_float("CEC_ONOFF_TEST_DELAY_SECONDS", 5.0)
    power_on()
    if onoff_delay > 0:
        time.sleep(onoff_delay)
    power_off()
    print(f"CEC power-cycle completed with a {onoff_delay:.1f}s pause.")
