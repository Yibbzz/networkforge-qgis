"""Installs, version-checks and runs the NetworkForge engine.

The engine lives in its own Python environment inside the QGIS profile
folder and is only ever run as a separate process through its command
line. It is never imported into QGIS's Python.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from qgis.core import QgsApplication

# The engine's CLI flags, JSON events and exit codes are the contract, so
# the version is pinned here and nowhere else.
ENGINE_VERSION = "0.4.0"
ENGINE_REPO = "https://github.com/Yibbzz/networkforge"
# The tag's zip rather than "git+https://...", so users don't need git.
ENGINE_REQUIREMENT = (
    f"networkforge @ {ENGINE_REPO}/archive/refs/tags/v{ENGINE_VERSION}.zip"
)
ENGINE_PYTHON = "3.12"
UV_INSTALL_GUIDE = "https://docs.astral.sh/uv/getting-started/installation/"

_WINDOWS = os.name == "nt"
# Stops a console window flashing up on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# QGIS points these at its own Python and its own GDAL/PROJ data, which
# would break the engine's separate environment. Every PYTHON* variable
# is removed as well (see _clean_env).
_QGIS_ONLY_ENV = (
    "__PYVENV_LAUNCHER__",
    "VIRTUAL_ENV",
    "GDAL_DATA",
    "GDAL_DRIVER_PATH",
    "PROJ_LIB",
    "PROJ_DATA",
)
# QGIS on Windows can point these at a folder it doesn't ship; uv then
# trusts no certificates at all.
_CERT_PATH_ENV = ("SSL_CERT_DIR", "SSL_CERT_FILE")


class EngineError(Exception):
    """The engine could not be installed or run; the message is for the user."""


class EngineCanceled(Exception):
    """The user cancelled while the engine was being installed."""


def base_dir():
    return Path(QgsApplication.qgisSettingsDirPath()) / "networkforge"


def venv_dir():
    return base_dir() / "engine-venv"


def log_path():
    return base_dir() / "engine.log"


def engine_exe():
    if _WINDOWS:
        return venv_dir() / "Scripts" / "networkforge.exe"
    return venv_dir() / "bin" / "networkforge"


def _venv_python():
    if _WINDOWS:
        return venv_dir() / "Scripts" / "python.exe"
    return venv_dir() / "bin" / "python"


def _uv_dir():
    return base_dir() / "uv"


def _clean_env():
    """The environment for uv and the engine: QGIS's, minus its Python setup."""
    env = {}
    for key, value in os.environ.items():
        name = key.upper()
        # PYTHONEXECUTABLE in particular makes the engine's Python think it
        # is QGIS's: uv then installs into the wrong place and refuses.
        if name.startswith("PYTHON") or name in _QGIS_ONLY_ENV:
            continue
        if name in _CERT_PATH_ENV and not os.path.exists(value):
            continue
        env[key] = value
    env["PYTHONUTF8"] = "1"
    # Let uv replace a half-removed environment instead of stopping to ask.
    env["UV_VENV_CLEAR"] = "1"
    return env


def _log(text):
    base_dir().mkdir(parents=True, exist_ok=True)
    with open(log_path(), "a", encoding="utf-8") as log:
        log.write(text if text.endswith("\n") else text + "\n")


def _run_logged(cmd, feedback, env):
    """Run a command, copying its output to the Processing log and engine.log.

    Returns the exit code. Raises EngineCanceled if the user cancels.
    """
    cmd = [str(c) for c in cmd]
    _log(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] $ {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=_NO_WINDOW,
        )
    except OSError as err:
        _log(f"could not start: {err}")
        return 127
    for line in proc.stdout:
        _log(line)
        if feedback is not None:
            if feedback.isCanceled():
                proc.kill()
                proc.wait()
                raise EngineCanceled()
            feedback.pushConsoleInfo(line.rstrip())
    return proc.wait()


def _own_uv():
    """The plugin's own copy of uv, wherever pip put it, or None."""
    name = "uv.exe" if _WINDOWS else "uv"
    return next((p for p in _uv_dir().rglob(name) if p.is_file()), None)


def _find_uv():
    own = _own_uv()
    if own is not None:
        return own
    found = shutil.which("uv")
    return Path(found) if found else None


def _qgis_python():
    """QGIS's Python interpreter (on Windows sys.executable is QGIS itself)."""
    if _WINDOWS:
        for name in ("python.exe", "python3.exe"):
            candidate = Path(sys.exec_prefix) / name
            if candidate.exists():
                return candidate
    return Path(sys.executable)


def _ensure_uv(feedback):
    """Return the path to uv, fetching it into the plugin's folder if needed.

    uv is a single program shipped inside a Python package. It goes into
    its own folder (pip's --target), so QGIS's Python is left untouched.
    """
    uv = _find_uv()
    if uv is not None:
        return uv
    if feedback is not None:
        feedback.pushInfo("Fetching uv (the installer used for the engine)...")
    code = _run_logged(
        [_qgis_python(), "-m", "pip", "install", "--upgrade",
         "--target", _uv_dir(), "uv"],
        feedback,
        dict(os.environ),
    )
    uv = _own_uv()
    if code != 0 or uv is None:
        raise EngineError(
            "Could not fetch uv, the installer used for the NetworkForge "
            "engine. Check your internet connection and try again. If it "
            f"keeps failing, install uv yourself ({UV_INSTALL_GUIDE}), "
            f"restart QGIS and try again. Details: {log_path()}"
        )
    return uv


def installed_version():
    """The installed engine's version, or None if there is no working engine."""
    if not engine_exe().exists():
        return None
    try:
        result = subprocess.run(
            [str(engine_exe()), "--version"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_clean_env(),
            creationflags=_NO_WINDOW,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    words = result.stdout.split()  # "networkforge 0.4.0"
    if result.returncode != 0 or not words:
        return None
    return words[-1]


def install(feedback=None):
    """(Re)create the engine's environment and install the pinned engine."""
    uv = _ensure_uv(feedback)
    env = _clean_env()
    if venv_dir().exists():
        shutil.rmtree(venv_dir(), ignore_errors=True)
    steps = (
        ("Creating the engine's Python environment...",
         [uv, "venv", "--python", ENGINE_PYTHON, venv_dir()]),
        (f"Installing NetworkForge engine {ENGINE_VERSION}...",
         [uv, "pip", "install", "--python", _venv_python(), ENGINE_REQUIREMENT]),
    )
    for message, cmd in steps:
        if feedback is not None:
            feedback.pushInfo(message)
        if _run_logged(cmd, feedback, env) != 0:
            raise EngineError(
                "Could not install the NetworkForge engine. The first "
                "install downloads Python and the engine, so it needs an "
                "internet connection: check it and try again. If your "
                "connection is fine, the reason is at the end of the log "
                f"file: {log_path()}"
            )
    found = installed_version()
    if found != ENGINE_VERSION:
        raise EngineError(
            f"The engine was installed but reports version {found!r} "
            f"instead of {ENGINE_VERSION}. Details: {log_path()}"
        )


def ensure_installed(feedback=None):
    """Install the pinned engine unless it is already there."""
    found = installed_version()
    if found == ENGINE_VERSION:
        return
    if feedback is not None:
        if found is None:
            feedback.pushInfo(
                "The NetworkForge engine is not installed yet. Installing "
                "it now (once only, this can take a few minutes)."
            )
        else:
            feedback.pushInfo(
                f"Found engine {found}; this plugin needs {ENGINE_VERSION}. "
                "Replacing it."
            )
    install(feedback)


def info():
    """What the installed engine supports: `networkforge info --json`."""
    _log(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] $ networkforge info --json")
    with open(log_path(), "a", encoding="utf-8") as log:
        result = subprocess.run(
            [str(engine_exe()), "info", "--json"],
            stdout=subprocess.PIPE,
            stderr=log,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=_clean_env(),
            creationflags=_NO_WINDOW,
        )
    if result.returncode != 0:
        raise EngineError(
            f"The engine stopped with exit code {result.returncode}. "
            f"Details: {log_path()}"
        )
    try:
        return json.loads(result.stdout)
    except ValueError:
        _log(result.stdout)
        raise EngineError(
            f"The engine's reply could not be read. Details: {log_path()}"
        )
