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
    assert {"init", "replan", "state", "start", "import_file", "export_drawing", "export_plan"} <= public
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


def test_cancelled_dialogs(api):
    api.attach(FakeWindow(None, None, None))
    assert api.import_file() == {"cancelled": True}
    assert api.export_drawing([SQUARE]) == {"cancelled": True}
    assert api.export_plan([SQUARE], api.init()["params"]) == {"cancelled": True}


def test_export_drawing_adds_a_default_suffix_and_imports_back(api, tmp_path):
    window = FakeWindow(str(tmp_path / "drawing"))
    api.attach(window)
    assert api.export_drawing([SQUARE])["name"] == "drawing.svg"
    window.answers.append([str(tmp_path / "drawing.svg")])
    result = api.import_file()
    assert len(result["shapes"]) == 1 and "message" in result


def test_import_file_hands_images_to_the_tracer(api, tmp_path):
    from PIL import Image

    Image.new("L", (40, 30), 255).save(tmp_path / "a.png")
    api.attach(FakeWindow([str(tmp_path / "a.png")]))
    result = api.import_file()
    assert result["bitmap"]["w"] == 40 and result["bitmap"]["png"].startswith("data:image/png")


def test_dialogs_start_where_the_last_file_was(api, tmp_path):
    window = FakeWindow(str(tmp_path / "x.svg"), None)
    api.attach(window)
    api.export_drawing([SQUARE])
    api.import_file()
    assert window.dialogs[1][1]["directory"] == str(tmp_path)


def test_export_plan_adds_a_default_suffix(api, tmp_path):
    api.attach(FakeWindow(str(tmp_path / "path")))
    assert api.export_plan([SQUARE], api.init()["params"]) == {"name": "path.csv"}
    assert (tmp_path / "path.csv").read_text().strip()


def test_export_of_an_empty_drawing_is_an_error(api):
    assert "error" in api.export_plan([], api.init()["params"])
    assert "error" in api.export_drawing([])


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

    for group in (api_module.IMPORT_TYPES, api_module.DRAWING_TYPES, api_module.PATH_TYPES):
        for filter_ in group:
            parse_file_type(filter_)
