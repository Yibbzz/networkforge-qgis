"""What the plugin installs is pinned, checked and agreed to.

Every version comes from the lists in networkforge_qgis/locks, every
file is checked against a checksum, and nothing is downloaded before the
user has been shown the list and said yes.
"""

import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
import time

import pytest
from qgis import processing
from qgis.core import QgsProcessingException

from networkforge_qgis import consent, engine

# Before conftest's nobody_to_ask fixture swaps it out for each test.
REAL_CAN_ASK = consent._can_ask
# The Python the stand-in engines run with (see conftest.FAKE_PYTHON): on
# macOS QGIS's own can't start without the settings the plugin clears.
PYTHON = os.environ.get("NF_TEST_FAKE_PYTHON") or sys.executable


# ---------------------------------------------------------------- the lists

def test_the_lists_are_for_the_pinned_versions():
    assert dict(engine.locked_packages(engine.ENGINE_LOCK))["networkforge"] == engine.ENGINE_VERSION
    assert dict(engine.locked_packages(engine.TRAFFIC_LOCK))["networkforge"] == engine.ENGINE_VERSION
    assert engine.locked_packages(engine.UV_LOCK) == [("uv", engine.UV_VERSION)]
    assert engine.UV_VERSION in engine.UV_DOWNLOADS_LOCK.read_text(encoding="utf-8")


@pytest.mark.parametrize("lock", [engine.ENGINE_LOCK, engine.TRAFFIC_LOCK, engine.UV_LOCK])
def test_every_package_has_an_exact_version_and_checksums(lock):
    text = lock.read_text(encoding="utf-8")
    # One block per package: "name==version \", then its --hash lines.
    blocks = re.split(r"\n(?=\S)", text.strip())
    assert len(blocks) == len(engine.locked_packages(lock)) > 0
    for block in blocks:
        assert re.match(r"[A-Za-z0-9_.-]+==\S+", block), block[:60]
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", block), block[:60]
    assert ">=" not in text and "git+" not in text and "http" not in text


def test_traffic_adds_valhalla_and_changes_nothing_else():
    plain = engine.locked_packages(engine.ENGINE_LOCK)
    traffic = engine.locked_packages(engine.TRAFFIC_LOCK)
    assert [p for p in traffic if p not in plain] == [
        ("pyvalhalla", dict(traffic)["pyvalhalla"])]
    assert all(p in traffic for p in plain)


def test_there_is_a_checksum_for_uv_on_every_system(monkeypatch):
    checksums = engine._uv_checksums()
    for windows, system in ((True, "win32"), (False, "darwin"), (False, "linux")):
        for machine in ("x86_64", "AMD64", "arm64", "aarch64"):
            monkeypatch.setattr(engine, "_WINDOWS", windows)
            monkeypatch.setattr(engine.sys, "platform", system)
            monkeypatch.setattr(engine.platform, "machine", lambda machine=machine: machine)
            assert re.fullmatch(r"[0-9a-f]{64}", checksums[engine._uv_archive_name()])


# ---------------------------------------------------------------- installing

def test_the_engine_is_installed_from_the_list_with_checksums_required(
        monkeypatch, tmp_path, feedback):
    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(engine, "_ensure_uv", lambda feedback: "uv")
    monkeypatch.setattr(engine, "reported_version", lambda: engine.ENGINE_VERSION)
    commands = []
    monkeypatch.setattr(engine, "_run_logged",
                        lambda cmd, feedback, env: commands.append([str(c) for c in cmd]) or 0)

    engine.install(feedback)
    monkeypatch.setattr(engine, "has_traffic", lambda: False if len(commands) < 3 else True)
    engine.ensure_traffic(feedback)

    installs = [cmd for cmd in commands if cmd[1:3] == ["pip", "install"]]
    assert [cmd[-1] for cmd in installs] == [str(engine.ENGINE_LOCK), str(engine.TRAFFIC_LOCK)]
    for cmd in installs:
        assert "--require-hashes" in cmd and cmd[-2] == "-r"
        assert not any("github.com" in part or "networkforge" == part for part in cmd)
    # The log names every version before anything is fetched.
    assert any(f"networkforge {engine.ENGINE_VERSION}" in line for line in feedback.infos)


def test_uv_is_fetched_at_its_pinned_version_with_checksums_required(
        monkeypatch, tmp_path, feedback):
    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    commands = []

    def pip(cmd, feedback, env):
        commands.append([str(c) for c in cmd])
        (tmp_path / "uv" / "bin").mkdir(parents=True)
        (tmp_path / "uv" / "bin" / engine._own_uv_name()).write_bytes(b"uv")
        return 0

    monkeypatch.setattr(engine, "_run_logged", pip)

    uv = engine._ensure_uv(feedback)

    assert uv == engine._own_uv()
    (cmd,) = commands
    assert "--require-hashes" in cmd and cmd[-2:] == ["-r", str(engine.UV_LOCK)]
    assert "uv" not in cmd[cmd.index("install"):]  # no bare, unpinned name
    assert engine._uv_marker().read_text(encoding="utf-8") == engine.UV_VERSION


def test_an_older_copy_of_uv_is_replaced(monkeypatch, tmp_path, feedback):
    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    (tmp_path / "uv").mkdir()
    (tmp_path / "uv" / engine._own_uv_name()).write_bytes(b"old")
    engine._uv_marker().write_text("0.0.1", encoding="utf-8")

    assert engine._find_uv() is None  # not the pinned version: not used


class _Reply:
    def __init__(self, data):
        self._data = data

    def content(self):
        return self._data


def _downloads(monkeypatch, data):
    class Request:
        def get(self, request, force, feedback):
            self.url = request.url().toString()

        def reply(self):
            return _Reply(data)

        def errorMessage(self):
            return ""

    monkeypatch.setattr(engine, "QgsBlockingNetworkRequest", Request)


def test_a_download_of_uv_with_another_checksum_is_refused(monkeypatch, tmp_path, feedback):
    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    _downloads(monkeypatch, b"not the uv that was pinned")

    assert engine._download_uv(feedback) is False

    assert engine._own_uv() is None
    assert "refused" in engine.log_path().read_text(encoding="utf-8")


def test_a_download_of_uv_with_the_pinned_checksum_is_used(monkeypatch, tmp_path, feedback):
    import io
    import tarfile

    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(engine, "_WINDOWS", False)
    monkeypatch.setattr(engine.sys, "platform", "linux")
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        member = tarfile.TarInfo("uv-x/uv")
        member.size = 2
        archive.addfile(member, io.BytesIO(b"uv"))
    data = data.getvalue()
    monkeypatch.setattr(engine, "_uv_checksums",
                        lambda: {engine._uv_archive_name(): hashlib.sha256(data).hexdigest()})
    _downloads(monkeypatch, data)

    assert engine._download_uv(feedback) is True
    assert engine._own_uv().read_bytes() == b"uv"


# ---------------------------------------------------------------- what is installed

def _pretend_installed(folder, packages):
    site = folder / "engine-venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    for name, version in packages:
        (site / f"{name.replace('-', '_')}-{version}.dist-info").mkdir()
    exe = engine.engine_exe()
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("")


def test_installed_version_is_read_from_the_files_without_starting_the_engine(
        monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: pytest.fail("ran a program"))
    _pretend_installed(tmp_path, engine.locked_packages(engine.ENGINE_LOCK))

    assert engine.installed_version() == engine.ENGINE_VERSION
    assert engine.pending_install() is None
    assert not engine.has_traffic()
    assert engine.unexpected_packages() == []


def test_packages_that_are_not_pinned_are_named(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    packages = [(name, "0.0.1" if name == "numpy" else version)
                for name, version in engine.locked_packages(engine.ENGINE_LOCK)]
    _pretend_installed(tmp_path, [*packages, ("left-pad", "1.0")])

    unexpected = engine.unexpected_packages()

    assert len(unexpected) == 2
    assert any(line.startswith("left-pad 1.0") for line in unexpected)
    assert any(line.startswith("numpy 0.0.1 (pinned: ") for line in unexpected)


# ---------------------------------------------------------------- asking first

def test_what_will_be_installed_is_spelt_out(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)

    summary, details = engine.pending_install(traffic=True)

    assert f"uv {engine.UV_VERSION}" in summary
    assert f"NetworkForge engine {engine.ENGINE_VERSION}" in summary
    assert "pyvalhalla" in summary and str(tmp_path) in summary
    assert "checksum" in summary
    assert details.splitlines() == [
        f"{name} {version}" for name, version in engine.locked_packages(engine.TRAFFIC_LOCK)]


def test_only_valhalla_is_listed_when_the_engine_is_there(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    _pretend_installed(tmp_path, engine.locked_packages(engine.ENGINE_LOCK))

    summary, details = engine.pending_install(traffic=True)

    assert "pyvalhalla" in summary and "NetworkForge engine" not in summary
    assert details.startswith("pyvalhalla ") and len(details.splitlines()) == 1


def test_nothing_is_installed_when_the_user_says_no(provider, fake_engine, feedback, monkeypatch):
    asked = []
    monkeypatch.setattr(consent, "_can_ask", lambda: True)
    monkeypatch.setattr(consent, "ask", lambda summary, details: asked.append(details) and False)
    monkeypatch.setattr(engine, "ensure_installed", lambda feedback=None: pytest.fail("installed"))

    with pytest.raises(QgsProcessingException):
        processing.run("networkforge:engine_info", {}, feedback=feedback)

    assert any("Nothing was installed" in error for error in feedback.errors)
    assert len(asked) == 1 and f"networkforge {engine.ENGINE_VERSION}" in asked[0]


def test_the_tool_goes_ahead_when_the_user_says_install(
        provider, fake_engine, feedback, monkeypatch):
    monkeypatch.setattr(consent, "_can_ask", lambda: True)
    monkeypatch.setattr(consent, "ask", lambda summary, details: True)
    fake_engine.play([engine.bundled_info()])

    results = processing.run("networkforge:engine_info", {}, feedback=feedback)

    assert results["ENGINE_VERSION"] == engine.ENGINE_VERSION
    assert any("This will be downloaded" in line for line in feedback.infos)


def test_nobody_is_asked_when_everything_is_installed(
        provider, fake_engine, feedback, monkeypatch, tmp_path):
    _pretend_installed(engine.base_dir(), engine.locked_packages(engine.ENGINE_LOCK))
    monkeypatch.setattr(consent, "_can_ask", lambda: True)
    monkeypatch.setattr(consent, "ask", lambda summary, details: pytest.fail("asked"))
    fake_engine.play([engine.bundled_info()])

    processing.run("networkforge:engine_info", {}, feedback=feedback)

    assert any("exactly a version this plugin pins" in line for line in feedback.infos)


def test_nobody_is_asked_without_qgis_desktop(monkeypatch):
    # qgis_process has no main window. On Windows the box opened there
    # anyway, unseen, and the tool waited for ever.
    from qgis import utils

    monkeypatch.setattr(utils, "iface", None)
    assert REAL_CAN_ASK() is False


def test_reinstalling_asks_even_with_an_engine_there(
        provider, fake_engine, feedback, monkeypatch):
    _pretend_installed(engine.base_dir(), engine.locked_packages(engine.ENGINE_LOCK))
    monkeypatch.setattr(consent, "_can_ask", lambda: True)
    monkeypatch.setattr(consent, "ask", lambda summary, details: False)
    monkeypatch.setattr(engine, "install", lambda feedback=None: pytest.fail("installed"))

    with pytest.raises(QgsProcessingException):
        processing.run("networkforge:engine_info", {"REINSTALL": True}, feedback=feedback)

    assert any("Nothing was installed" in error for error in feedback.errors)


# ---------------------------------------------------------------- stopping

@pytest.mark.skipif(os.name == "nt", reason="looks for the child by its POSIX process id")
def test_cancelling_also_stops_the_programs_the_engine_started(
        fake_engine, feedback, monkeypatch):
    # As "Add traffic" does: the engine starts Valhalla's programs.
    script = (
        "import subprocess, sys, json, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "print(json.dumps({'event': 'progress', 'step': 1, 'total': 2, 'message': str(child.pid)}),"
        " flush=True)\n"
        "time.sleep(120)\n"
    )
    monkeypatch.setattr(engine, "_engine_cmd", lambda: [PYTHON, "-c", script])
    children = []

    def on_event(event):
        children.append(int(event["message"]))
        threading.Timer(0.2, feedback.cancel).start()

    with pytest.raises(engine.EngineCanceled):
        engine.run([], feedback, on_event)

    (child,) = children
    for _ in range(50):  # give the system a moment to clear it away
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        # Still listed: a finished child nobody has collected counts as gone.
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(child)],
                               capture_output=True, text=True, check=False).stdout.strip()
        if not state or state.startswith("Z"):
            break
        time.sleep(0.1)
    else:
        os.kill(child, signal.SIGKILL)
        pytest.fail("the engine's child program was left running")


def test_the_engine_is_stopped_when_a_tool_fails_on_one_of_its_events(
        fake_engine, feedback):
    fake_engine.play([{"event": "progress"}], sleep=60)
    started = time.monotonic()

    def broken(event):
        raise KeyError("step")

    with pytest.raises(KeyError):
        engine.run(["build"], feedback, broken)

    assert time.monotonic() - started < 10
