"""Tests for the Python API the web page calls (no window needed: dialogs are faked)."""

import pytest

pytest.importorskip("webview")
pytest.importorskip("shapely")

from laserscan import api as api_module
from laserscan.api import Api, with_suffix
from laserscan.session import SESSION

SQUARE = {"type": "path", "path": "M0,0L400,0L400,300L0,300Z", "op": "add"}


class FakeWindow:
    """Stands in for ``webview.Window``: answers file dialogs with queued paths and records titles."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.titles = []
        self.dialogs = []

    def create_file_dialog(self, kind, **kwargs):
        self.dialogs.append((kind, kwargs))
        return self.answers.pop(0)

    def set_title(self, title):
        self.titles.append(title)


@pytest.fixture
def api():
    a = Api(simulate=True)
    yield a
    SESSION.shutdown("test")


def test_public_methods_only_expose_the_page_contract(api):
    """pywebview exposes every public attribute, so state must stay private."""
    public = {n for n in dir(api) if not n.startswith("_")}
    assert {"init", "replan", "state", "start", "open_project", "save_project", "export_plan"} <= public
    assert all(callable(getattr(api, n)) for n in public)


def test_init_and_replan_return_json_friendly_values(api):
    import json

    info = api.init()
    json.dumps(info)
    plan = api.replan([SQUARE], info["params"])
    json.dumps(plan)
    assert plan["plan"] and not plan["problems"] and plan["region"]


def test_replan_reports_planning_errors(api):
    bad = {"pattern": "serpentine", "step": 0, "angle": 0, "speed": 20, "margin": 0, "passes": 1}
    assert api.replan([SQUARE], bad)["problems"]


def test_state_after_ready_in_simulation(api):
    api.ready()
    state = api.state()
    assert state["connected"] and state["simulated"] and not state["running"]
    assert state["profile"]["x_range_um"]


def test_start_needs_a_connection(api):
    assert "error" in api.start([SQUARE], api.init()["params"], "design")


def test_save_and_open_project_round_trip(api, tmp_path):
    target = tmp_path / "job"
    window = FakeWindow(str(target))
    api.attach(window)
    saved = api.save_project([SQUARE], api.init()["params"], True)
    assert saved == {"name": "job.laserscan.json"}
    assert window.titles[-1] == "job.laserscan.json — LaserScan"

    window.answers.append([str(tmp_path / "job.laserscan.json")])
    opened = api.open_project()
    assert opened["shapes"][0]["path"] == SQUARE["path"]
    assert opened["params"]["pattern"] == "serpentine"

    again = api.save_project([SQUARE], api.init()["params"], False)  # saves to the same file without asking
    assert again == {"name": "job.laserscan.json"} and not window.answers


def test_cancelled_dialogs(api):
    api.attach(FakeWindow(None, None, None))
    assert api.open_project() == {"cancelled": True}
    assert api.save_project([SQUARE], api.init()["params"], True) == {"cancelled": True}
    assert api.export_plan([SQUARE], api.init()["params"]) == {"cancelled": True}


def test_export_adds_a_default_suffix(api, tmp_path):
    api.attach(FakeWindow(str(tmp_path / "path")))
    assert api.export_plan([SQUARE], api.init()["params"]) == {"name": "path.csv"}
    assert (tmp_path / "path.csv").read_text().strip()


def test_export_of_an_empty_drawing_is_an_error(api):
    assert "error" in api.export_plan([], api.init()["params"])


def test_merge_through_the_api(api):
    a = {"type": "path", "path": "M0,0L100,0L100,100L0,100Z", "op": "add"}
    b = {"type": "path", "path": "M50,0L150,0L150,100L50,100Z", "op": "add"}
    result = api.merge_selected([a, b], [0, 1])
    assert result["merged"] and len(result["shapes"]) == 1


def test_with_suffix():
    assert with_suffix("a", (".csv", ".npz"), ".csv") == "a.csv"
    assert with_suffix("a.NPZ", (".csv", ".npz"), ".csv") == "a.NPZ"


def test_file_filters_are_valid_for_pywebview():
    from webview.util import parse_file_type

    for group in (api_module.PROJECT_TYPES, api_module.IMPORT_TYPES, api_module.BITMAP_TYPES, api_module.EXPORT_TYPES):
        for filter_ in group:
            parse_file_type(filter_)
