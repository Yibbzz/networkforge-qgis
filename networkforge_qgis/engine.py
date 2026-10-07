"""Installs, version-checks and runs the NetworkForge engine.

The engine lives in its own Python environment inside the QGIS profile
folder and is only ever run as a separate process through its command
line. It is never imported into QGIS's Python.
"""

import importlib.util
import io
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tarfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from qgis.core import QgsApplication, QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

# The engine's CLI flags, JSON events and exit codes are the contract, so
# the version is pinned here and nowhere else.
ENGINE_VERSION = "1.0.0"
ENGINE_REPO = "https://github.com/Yibbzz/networkforge"
# The tag's zip rather than "git+https://...", so users don't need git.
ENGINE_REQUIREMENT = (
    f"networkforge @ {ENGINE_REPO}/archive/refs/tags/v{ENGINE_VERSION}.zip"
)
ENGINE_PYTHON = "3.12"
# What `networkforge info --json` prints for the pinned version, saved so
# forms can be built without starting the engine (slow, and it may not be
# installed yet). Regenerate it whenever ENGINE_VERSION changes.
BUNDLED_INFO_PATH = Path(__file__).parent / "engine_info.json"
UV_INSTALL_GUIDE = "https://docs.astral.sh/uv/getting-started/installation/"
# uv's own builds, for a QGIS whose Python has no pip (the Flatpak one).
UV_DOWNLOADS = "https://github.com/astral-sh/uv/releases/latest/download"

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


def _engine_cmd():
    """The start of every engine command line (tests swap in a fake engine)."""
    return [str(engine_exe())]


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
    proc.stdout.close()
    return proc.wait()


def _own_uv_name():
    return "uv.exe" if _WINDOWS else "uv"


def _own_uv():
    """The plugin's own copy of uv, wherever it was put, or None."""
    return next((p for p in _uv_dir().rglob(_own_uv_name()) if p.is_file()), None)


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


def _uv_archive_name():
    """The file name of uv's own build for this computer, or None."""
    machine = {"x86_64": "x86_64", "amd64": "x86_64",
               "aarch64": "aarch64", "arm64": "aarch64"}.get(platform.machine().lower())
    if machine is None:
        return None
    if _WINDOWS:
        return f"uv-{machine}-pc-windows-msvc.zip"
    if sys.platform == "darwin":
        return f"uv-{machine}-apple-darwin.tar.gz"
    if sys.platform.startswith("linux"):
        # The musl build needs nothing from the system it runs on.
        return f"uv-{machine}-unknown-linux-musl.tar.gz"
    return None


def _unpack_uv(name, data):
    """Save the uv program out of a downloaded archive; False if it has none."""
    program = _own_uv_name()
    content = None
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.namelist():
                if Path(member).name == program:
                    content = archive.read(member)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive.getmembers():
                if member.isfile() and Path(member.name).name == program:
                    content = archive.extractfile(member).read()
    if content is None:
        return False
    _uv_dir().mkdir(parents=True, exist_ok=True)
    target = _uv_dir() / program
    target.write_bytes(content)
    target.chmod(0o755)
    return True


def _download_uv(feedback):
    """Fetch uv's own build into the plugin's folder; True if that worked.

    The download goes through QGIS, so it uses QGIS's proxy settings.
    """
    name = _uv_archive_name()
    if name is None:
        _log(f"no uv download for {sys.platform} {platform.machine()}")
        return False
    url = f"{UV_DOWNLOADS}/{name}"
    _log(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] downloading {url}")
    request = QgsBlockingNetworkRequest()
    request.get(QNetworkRequest(QUrl(url)), True, feedback)
    if feedback is not None and feedback.isCanceled():
        raise EngineCanceled()
    data = bytes(request.reply().content())
    if request.errorMessage() or not data:
        _log(f"download failed: {request.errorMessage() or 'empty reply'}")
        return False
    try:
        found = _unpack_uv(name, data)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as err:
        _log(f"could not unpack {name}: {err}")
        return False
    if not found:
        _log(f"{name} does not contain uv")
    return found


def _ensure_uv(feedback):
    """Return the path to uv, fetching it into the plugin's folder if needed.

    uv is a single program shipped inside a Python package. It goes into
    its own folder (pip's --target), so QGIS's Python is left untouched.
    Where QGIS's Python has no pip, uv's own build is downloaded instead.
    """
    uv = _find_uv()
    if uv is not None:
        return uv
    if feedback is not None:
        feedback.pushInfo("Fetching uv (the installer used for the engine)...")
    if importlib.util.find_spec("pip") is not None:
        _run_logged(
            [_qgis_python(), "-m", "pip", "install", "--upgrade",
             "--target", _uv_dir(), "uv"],
            feedback,
            dict(os.environ),
        )
        uv = _own_uv()
    if uv is None and _download_uv(feedback):
        uv = _own_uv()
    if uv is None:
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
            [*_engine_cmd(), "--version"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_clean_env(),
            creationflags=_NO_WINDOW,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        _log(f"the engine did not report its version: {err}")
        return None
    words = result.stdout.split()  # "networkforge 1.0.0"
    if result.returncode != 0 or not words:
        _log(f"the engine did not report its version (exit code "
             f"{result.returncode}):\n{result.stdout}{result.stderr}")
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
         # uv's own Python, never one found on the computer: the Flatpak
         # QGIS's Python mixes QGIS's packages (an older numpy) into the
         # engine's environment even with QGIS's settings removed.
         [uv, "venv", "--python", ENGINE_PYTHON,
          "--python-preference", "only-managed", venv_dir()]),
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
            [*_engine_cmd(), "info", "--json"],
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


def bundled_info():
    """What the pinned engine supports, read from the saved copy of `info`."""
    with open(BUNDLED_INFO_PATH, encoding="utf-8") as f:
        return json.load(f)


def guide_url(guide):
    """The web address of an engine guide, for the pinned version.

    `guide` is what an error event carries: an anchor in the tagging
    guide, or "<file>.md#anchor" for another document.
    """
    docs = f"{ENGINE_REPO}/blob/v{ENGINE_VERSION}/docs"
    if ".md" in guide:
        return f"{docs}/{guide}"
    return f"{docs}/tagging-guide.md#{guide}"


def run(args, feedback, on_event):
    """Run an engine command with --json, passing each event to on_event.

    Returns the engine's exit code. Raises EngineCanceled if the user
    cancels; the engine is stopped straight away, even mid-download.
    """
    cmd = [*_engine_cmd(), *[str(a) for a in args]]
    _log(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] $ {' '.join(cmd)}")
    with open(log_path(), "a", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=log,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_clean_env(),
                creationflags=_NO_WINDOW,
            )
        except OSError as err:
            raise EngineError(
                f"Could not start the engine: {err}. Details: {log_path()}"
            )
        # The engine can be silent for a long time (downloads), so its
        # output is read on a separate thread and this loop stays free to
        # notice the cancel button.
        lines = queue.Queue()

        def read():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=read, daemon=True).start()
        while True:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                line = ""
            if feedback is not None and feedback.isCanceled():
                proc.kill()
                proc.wait()
                proc.stdout.close()
                log.write("cancelled by the user\n")
                raise EngineCanceled()
            if line is None:
                break
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                log.write(line)
                continue
            on_event(event)
        proc.stdout.close()
        return proc.wait()
