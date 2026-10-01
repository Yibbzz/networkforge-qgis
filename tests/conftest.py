import json
import sys
from pathlib import Path

import pytest
from qgis.core import QgsApplication, QgsProcessingFeedback

from networkforge_qgis import engine
from networkforge_qgis.provider import NetworkForgeProvider

FAKE_ENGINE = Path(__file__).parent / "fake_engine.py"


class FakeEngine:
    """Controls the stand-in engine and shows what it was asked to do."""

    def __init__(self, folder):
        self._args = folder / "args.json"
        self._play = folder / "play.json"
        self.play()

    def play(self, lines=(), exit_code=0, sleep=0):
        """Set what the engine will print and how it will exit."""
        self._play.write_text(
            json.dumps({"lines": list(lines), "exit": exit_code, "sleep": sleep}),
            encoding="utf-8",
        )

    @property
    def args(self):
        """The arguments of the last run."""
        return json.loads(self._args.read_text(encoding="utf-8"))

    def value(self, flag):
        """The value given after a flag such as --custom."""
        args = self.args
        return args[args.index(flag) + 1]

    def values(self, flag):
        args = self.args
        return [args[i + 1] for i, arg in enumerate(args) if arg == flag]


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    """Replace the engine with the stand-in; nothing is installed or downloaded."""
    folder = tmp_path / "networkforge"
    folder.mkdir()
    fake = FakeEngine(folder)
    monkeypatch.setattr(engine, "base_dir", lambda: folder)
    monkeypatch.setattr(engine, "_engine_cmd", lambda: [sys.executable, str(FAKE_ENGINE)])
    monkeypatch.setattr(engine, "ensure_installed", lambda feedback=None: None)
    monkeypatch.setenv("NF_FAKE_ARGS", str(fake._args))
    monkeypatch.setenv("NF_FAKE_PLAY", str(fake._play))
    return fake


@pytest.fixture
def provider(qgis_processing):
    """The NetworkForge tools, registered with Processing."""
    registry = QgsApplication.processingRegistry()
    provider = NetworkForgeProvider()
    registry.addProvider(provider)
    yield provider
    registry.removeProvider(provider)


class Feedback(QgsProcessingFeedback):
    """Remembers what a tool told the user."""

    def __init__(self):
        super().__init__()
        self.infos, self.warnings, self.errors = [], [], []
        self.progress, self.progress_texts = [], []

    def pushInfo(self, info):
        self.infos.append(info)

    def pushWarning(self, warning):
        self.warnings.append(warning)

    def reportError(self, error, fatalError=False):
        self.errors.append(error)

    def setProgress(self, progress):
        self.progress.append(progress)
        super().setProgress(progress)

    def setProgressText(self, text):
        self.progress_texts.append(text)


@pytest.fixture
def feedback():
    return Feedback()


@pytest.fixture(scope="session")
def real_engine():
    """The real engine, installed once and kept between test runs.

    It goes into NF_TEST_ENGINE_DIR, or .pytest_cache/networkforge-engine
    in the repository. Installing needs an internet connection.
    """
    import os

    folder = Path(os.environ.get(
        "NF_TEST_ENGINE_DIR",
        Path(__file__).parent.parent / ".pytest_cache" / "networkforge-engine",
    ))
    patch = pytest.MonkeyPatch()
    patch.setattr(engine, "base_dir", lambda: folder)
    engine.ensure_installed()
    yield engine
    patch.undo()
