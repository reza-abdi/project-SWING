from pathlib import Path

import pytest

from modules.config import PROJECT_ROOT, resolve_project_path, runtime_paths


def test_default_paths_use_repository_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    paths = runtime_paths({})
    assert paths.root == PROJECT_ROOT
    assert paths.data == PROJECT_ROOT / "data"
    assert paths.models == PROJECT_ROOT / "models"
    assert paths.event_db == PROJECT_ROOT / "data" / "event_log.db"
    assert paths.twin_ui == PROJECT_ROOT / "Digital_Twin_UI"
    assert paths.agent_ui == PROJECT_ROOT / "Agent_Dashboard_UI"


def test_relative_overrides_are_root_relative(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    paths = runtime_paths({"SWING_DATA_DIR": "sample/data", "SWING_MODEL_DIR": "sample/models"})
    assert paths.data == PROJECT_ROOT / "sample" / "data"
    assert paths.models == PROJECT_ROOT / "sample" / "models"
    assert paths.faiss == paths.data / "knowledge_base" / "faiss_index"
    assert paths.event_db == paths.data / "event_log.db"


def test_absolute_override_is_kept(tmp_path):
    paths = runtime_paths({"SWING_EVENT_DB_PATH": str(tmp_path / "events.db")})
    assert paths.event_db == tmp_path / "events.db"
    assert resolve_project_path(Path("reports")) == PROJECT_ROOT / "reports"


def test_bad_setting_exception_does_not_echo_environment(monkeypatch):
    marker = "secret-marker-value"
    monkeypatch.setenv("GOOGLE_API_KEY", marker)
    monkeypatch.setenv("SWING_MODEL_DIR", "   ")
    with pytest.raises(ValueError) as error:
        runtime_paths()
    assert "SWING_MODEL_DIR" in str(error.value)
    assert marker not in str(error.value)
    assert "GOOGLE_API_KEY" not in str(error.value)
