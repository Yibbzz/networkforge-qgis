"""Installs, version-checks and runs the NetworkForge engine.

The engine lives in its own Python environment inside the QGIS profile
folder and is only ever run as a separate process through its command
line. It is never imported into QGIS's Python.
"""

import hashlib
import importlib.util
import io
import json
import os
import platform
import queue
import re
import shutil
import signal
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
ENGINE_VERSION = "1.4.1"
ENGINE_REPO = "https://github.com/Yibbzz/networkforge"
# uv, the installer used for the engine: pinned too.
UV_VERSION = "0.13.8"
# Exactly what gets installed: every package with its version and the
# checksums of its files (scripts/lock_engine.sh writes them). The
# installers are told to refuse anything else (--require-hashes), so a
# user gets the versions that were tested, and a changed or swapped file
# is not installed at all.
LOCKS = Path(__file__).parent / "locks"
ENGINE_LOCK = LOCKS / "engine.txt"      # the engine (from PyPI) and what it needs
# The same plus Valhalla (pyvalhalla, ~100 MB), for "Add traffic": installed
# the first time that tool runs, not for everyone.
TRAFFIC_LOCK = LOCKS / "traffic.txt"
UV_LOCK = LOCKS / "uv.txt"              # uv as a Python package (for pip)
UV_DOWNLOADS_LOCK = LOCKS / "uv-downloads.txt"   # uv's own builds: name, SHA-256
ENGINE_PYTHON = "3.12"
# What `networkforge info --json` prints for the pinned version, saved so
# forms can be built without starting the engine (slow, and it may not be
# installed yet). Regenerate it whenever ENGINE_VERSION changes.
BUNDLED_INFO_PATH = Path(__file__).parent / "engine_info.json"
UV_INSTALL_GUIDE = "https://docs.astral.sh/uv/getting-started/installation/"
# uv's own builds, for a QGIS whose Python has no pip (the Flatpak one).
UV_DOWNLOADS = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}"

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


def locked_packages(lock):
    """[(name, version), ...] of a lock file, in its order."""
    found = re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)",
                       Path(lock).read_text(encoding="utf-8"), flags=re.MULTILINE)
    return [(name, version) for name, version in found]


def _uv_checksums():
    """{file name: SHA-256} of uv's own builds for the pinned version."""
    lines = UV_DOWNLOADS_LOCK.read_text(encoding="utf-8").splitlines()
    return dict(line.split() for line in lines if line.strip() and not line.startswith("#"))


def _site_packages():
    """The folders of the engine's environment that hold its packages."""
    return [p for pattern in ("lib/python*/site-packages", "Lib/site-packages")
            for p in venv_dir().glob(pattern)]


def installed_packages():
    """{name: version} of what is in the engine's environment, read from its files."""
    packages = {}
    for folder in _site_packages():
        for info in folder.glob("*.dist-info"):
            name, _, version = info.name[:-len(".dist-info")].rpartition("-")
            packages[_normal(name)] = version
    return packages


def _normal(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def unexpected_packages():
    """How the engine's environment differs from what the plugin pins.

    Returns lines such as "numpy 2.0.0 (pinned: 2.5.3)" or "leftpad 1.0
    (not in the pinned list)"; empty when everything installed is exactly
    a pinned version. Packages pinned for another system only (tzdata is
    for Windows) may be absent.
    """
    installed = installed_packages()
    lock = TRAFFIC_LOCK if "pyvalhalla" in installed else ENGINE_LOCK
    pinned = {_normal(name): version for name, version in locked_packages(lock)}
    lines = []
    for name, version in sorted(installed.items()):
        if name not in pinned:
            lines.append(f"{name} {version} (not in the pinned list)")
        elif pinned[name] != version:
            lines.append(f"{name} {version} (pinned: {pinned[name]})")
    return lines


def pending_install(traffic=False, reinstall=False):
    """What a tool is about to download, or None if everything is there.

    Returns (summary, details): a few lines for a person to read, and
    the full list of packages with their versions. `reinstall`: as if
    there were no engine yet.
    """
    engine_missing = reinstall or installed_version() != ENGINE_VERSION
    traffic_missing = traffic and (engine_missing or not has_traffic())
    if not engine_missing and not traffic_missing:
        return None
    lock = TRAFFIC_LOCK if traffic_missing else ENGINE_LOCK
    packages = locked_packages(lock)
    if not engine_missing:  # only Valhalla is new
        packages = [(n, v) for n, v in packages if _normal(n) == "pyvalhalla"]
    lines = []
    if engine_missing:
        if _find_uv() is None:
            lines.append(f"uv {UV_VERSION}, the installer (from pypi.org, or github.com "
                         "where QGIS has no pip)")
        lines.append(f"Python {ENGINE_PYTHON}, for the engine only (uv downloads it from "
                     "github.com/astral-sh/python-build-standalone)")
        lines.append(f"the NetworkForge engine {ENGINE_VERSION} and the "
                     f"{len(packages) - 1} Python packages it needs (from pypi.org), "
                     "about 600 MB in all")
    if traffic_missing:
        valhalla = dict(packages).get("pyvalhalla", "")
        lines.append(f"Valhalla for traffic: pyvalhalla {valhalla} (from pypi.org), "
                     "about 100 MB")
    summary = (
        "This will be downloaded, once:\n"
        + "\n".join(f"  - {line}" for line in lines)
        + f"\n\nIt goes into {base_dir()}"
        + (" (Python itself into uv's own data folder)" if engine_missing else "")
        + ". Nothing is added to QGIS's own Python.\n\n"
        "Every version is fixed by this plugin, and every file is checked "
        "against a checksum that ships with it: anything else is refused."
    )
    details = "\n".join(f"{name} {version}" for name, version in packages)
    return summary, details


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


def _own_group():
    """Popen settings that put a program and what it starts in a group of
    their own, so _stop() can end all of them."""
    return {} if _WINDOWS else {"start_new_session": True}


def _stop(proc):
    """End a program started with _own_group(), and the programs it started.

    The engine runs Valhalla's programs for "Add traffic", and uv runs
    installers: killing only the parent left those running.
    """
    try:
        if _WINDOWS:
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            subprocess.run(
                [str(taskkill), "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, stdin=subprocess.DEVNULL,
                creationflags=_NO_WINDOW, timeout=30, check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass
    proc.wait()


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
            **_own_group(),
        )
    except OSError as err:
        _log(f"could not start: {err}")
        return 127
    try:
        for line in proc.stdout:
            _log(line)
            if feedback is not None:
                if feedback.isCanceled():
                    raise EngineCanceled()
                feedback.pushConsoleInfo(line.rstrip())
    except BaseException:
        _stop(proc)
        raise
    finally:
        proc.stdout.close()
    return proc.wait()


def _own_uv_name():
    return "uv.exe" if _WINDOWS else "uv"


def _own_uv():
    """The plugin's own copy of uv, wherever it was put, or None."""
    return next((p for p in _uv_dir().rglob(_own_uv_name()) if p.is_file()), None)


def _uv_marker():
    """Says which version the plugin's own copy of uv is."""
    return _uv_dir() / "version.txt"


def _find_uv():
    """The plugin's own uv if it is the pinned version, else the user's own."""
    own = _own_uv()
    try:
        current = _uv_marker().read_text(encoding="utf-8").strip() == UV_VERSION
    except OSError:
        current = False
    if own is not None and current:
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
    target.chmod(0o700)   # only the user who installed it runs it
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
    expected = _uv_checksums().get(name)
    found = hashlib.sha256(data).hexdigest()
    if found != expected:
        _log(f"refused {name}: its SHA-256 is {found}, not the pinned {expected}")
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
        feedback.pushInfo(f"Fetching uv {UV_VERSION} (the installer used for the engine)...")
    shutil.rmtree(_uv_dir(), ignore_errors=True)  # an older version, or half of one
    uv = None
    if importlib.util.find_spec("pip") is not None:
        # The pinned version only, and only files with the pinned checksums.
        _run_logged(
            [_qgis_python(), "-m", "pip", "install", "--require-hashes",
             "--only-binary", ":all:", "--no-deps",
             "--target", _uv_dir(), "-r", UV_LOCK],
            feedback,
            dict(os.environ),
        )
        uv = _own_uv()
    if uv is None and _download_uv(feedback):
        uv = _own_uv()
    if uv is not None:
        _uv_marker().write_text(UV_VERSION, encoding="utf-8")
    if uv is None:
        raise EngineError(
            "Could not fetch uv, the installer used for the NetworkForge "
            "engine. Check your internet connection and try again. If it "
            f"keeps failing, install uv yourself ({UV_INSTALL_GUIDE}), "
            f"restart QGIS and try again. Details: {log_path()}"
        )
    return uv


def installed_version():
    """The installed engine's version, or None if there is none.

    Read from the environment's files: asking the engine itself takes
    seconds (it loads all its libraries), before every run of every tool.
    """
    if not engine_exe().exists():
        return None
    return installed_packages().get("networkforge")


def reported_version():
    """The version the engine itself reports, or None if it doesn't run."""
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
    words = result.stdout.split()  # "networkforge 1.3.0"
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
        (f"Installing NetworkForge engine {ENGINE_VERSION} "
         f"({len(locked_packages(ENGINE_LOCK))} packages, each checked against "
         "its pinned checksum)...",
         [uv, "pip", "install", "--python", _venv_python(),
          "--require-hashes", "-r", ENGINE_LOCK]),
    )
    if feedback is not None:
        feedback.pushInfo("Installing exactly these versions: " + ", ".join(
            f"{name} {version}" for name, version in locked_packages(ENGINE_LOCK)))
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
    found = reported_version()
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


def has_traffic():
    """Whether the engine's environment has Valhalla (pyvalhalla) for traffic."""
    pinned = dict(locked_packages(TRAFFIC_LOCK))["pyvalhalla"]
    return installed_packages().get("pyvalhalla") == pinned


def ensure_traffic(feedback=None):
    """Add Valhalla to the engine's environment, unless it is there already."""
    if has_traffic():
        return
    if feedback is not None:
        feedback.pushInfo(
            "Installing Valhalla for traffic (once only, about 100 MB)...")
    uv = _ensure_uv(feedback)
    cmd = [uv, "pip", "install", "--python", _venv_python(),
           "--require-hashes", "-r", TRAFFIC_LOCK]
    if _run_logged(cmd, feedback, _clean_env()) != 0 or not has_traffic():
        raise EngineError(
            "Could not install Valhalla, which traffic needs. It is "
            "downloaded once, so it needs an internet connection: check it "
            "and try again. If your connection is fine, the reason is at the "
            f"end of the log file: {log_path()}"
        )


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

    `guide` is what an error event carries: "<file>.md#anchor"
    ("network-rules.md#presets"), or, from engines up to v1.0.1, a bare
    anchor in what was then the tagging guide.
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
                **_own_group(),
            )
        except OSError as err:
            raise EngineError(
                f"Could not start the engine: {err}. If this keeps happening, "
                "run the \"Engine information\" tool with \"Reinstall the "
                f"engine\" ticked. Details: {log_path()}"
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
        try:
            while True:
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    line = ""
                if feedback is not None and feedback.isCanceled():
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
        except BaseException:
            # Cancelled, or the tool failed on an event: the engine (and
            # the programs it started) must not be left running.
            _stop(proc)
            raise
        finally:
            proc.stdout.close()
        return proc.wait()
