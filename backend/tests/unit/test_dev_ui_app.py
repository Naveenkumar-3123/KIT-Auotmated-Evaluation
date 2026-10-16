"""Boot-level smoke test for the dev UI (Streamlit AppTest).

Executes the real app.py script in-process: perception workspace default view,
then switches to the Grading & Workflow workspace and verifies the Module
12-18 tabs render without exceptions.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "tools" / "test_ui" / "app.py"


@pytest.fixture()
def ui_jobs_db(tmp_path, monkeypatch):
    db = tmp_path / "ui_jobs.db"
    monkeypatch.setenv("DEV_UI_JOBS_DB", str(db))
    return db


def test_app_boots_perception_workspace(ui_jobs_db):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    radio = at.radio(key="workspace_selector")
    assert radio.value.startswith("🔍")


def test_grading_workspace_tabs_render(ui_jobs_db):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    at.radio(key="workspace_selector").set_value("🎯 Grading & Workflow (M12–18)").run()
    assert not at.exception
    # Both M12-16 and M17-18 tabs are present
    labels = [t.label for t in at.tabs]
    assert any("Direct Grading" in lbl for lbl in labels)
    assert any("Jobs" in lbl for lbl in labels)


def test_direct_grading_mock_run_end_to_end(ui_jobs_db):
    """Click 'Grade Answer' in mock mode inside the real app and check output."""
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    at.radio(key="workspace_selector").set_value("🎯 Grading & Workflow (M12–18)").run()

    at.radio(key="grading_model_radio").set_value("Mock (instant, deterministic)").run()
    buttons = [b for b in at.button if "Grade Answer" in b.label]
    assert buttons, "Grade button missing"
    buttons[0].click().run()

    assert not at.exception
    try:
        error = at.session_state["grading_error"]  # SafeSessionState has no .get()
    except KeyError:
        error = "n/a"
    assert "graded" in at.session_state, f"no graded result; error={error}"
    graded = at.session_state["graded"]
    assert graded["marks"]["final_proposed_marks"] == 10.0
    assert graded["risk"]["auto_approve"] is True
