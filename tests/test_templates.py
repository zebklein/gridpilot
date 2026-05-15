"""
Template integrity tests.

These run against the actual files in templates/ and catch regressions like
missing required keys, broken JSON, or invalid line item structure before a
user ever runs init_sheet.py.
"""
import json
import os
import pytest

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
TEMPLATES = ["new-construction", "home-renovation"]

REQUIRED_PROJECT_KEYS = {"spreadsheet_title", "tabs", "scenarios", "inputs_sections", "kanban_meta"}
REQUIRED_TAB_KEYS = {"inputs", "kanban"}
REQUIRED_SCENARIO_KEYS = {"id", "label", "tab", "json_file"}
REQUIRED_LINE_ITEM_KEYS = {"section", "id", "label"}
REQUIRED_INPUTS_KEYS = {"_meta"}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def get_template_path(template, filename):
    return os.path.join(TEMPLATES_DIR, template, filename)


@pytest.mark.parametrize("template", TEMPLATES)
class TestTemplateFiles:
    def test_required_files_exist(self, template):
        base = os.path.join(TEMPLATES_DIR, template)
        for fname in ("project.json", "inputs.json", "kanban.json"):
            assert os.path.exists(os.path.join(base, fname)), f"{template}/{fname} missing"

    def test_all_json_files_are_valid(self, template):
        base = os.path.join(TEMPLATES_DIR, template)
        for fname in os.listdir(base):
            if fname.endswith(".json"):
                path = os.path.join(base, fname)
                try:
                    load_json(path)
                except json.JSONDecodeError as e:
                    pytest.fail(f"{template}/{fname} is invalid JSON: {e}")

    def test_project_json_required_keys(self, template):
        data = load_json(get_template_path(template, "project.json"))
        missing = REQUIRED_PROJECT_KEYS - set(data.keys())
        assert not missing, f"{template}/project.json missing keys: {missing}"

    def test_project_json_has_inputs_and_kanban_tabs(self, template):
        data = load_json(get_template_path(template, "project.json"))
        missing = REQUIRED_TAB_KEYS - set(data.get("tabs", {}).keys())
        assert not missing, f"{template}/project.json tabs missing: {missing}"

    def test_project_json_scenarios_are_valid(self, template):
        data = load_json(get_template_path(template, "project.json"))
        scenarios = data.get("scenarios", [])
        assert len(scenarios) > 0, f"{template} has no scenarios"
        for s in scenarios:
            missing = REQUIRED_SCENARIO_KEYS - set(s.keys())
            assert not missing, f"{template} scenario '{s.get('id')}' missing keys: {missing}"

    def test_scenario_json_files_exist(self, template):
        project = load_json(get_template_path(template, "project.json"))
        base = os.path.join(TEMPLATES_DIR, template)
        for s in project.get("scenarios", []):
            path = os.path.join(base, s["json_file"])
            assert os.path.exists(path), f"{template}/{s['json_file']} referenced but not found"

    def test_scenario_json_has_line_items(self, template):
        project = load_json(get_template_path(template, "project.json"))
        base = os.path.join(TEMPLATES_DIR, template)
        for s in project.get("scenarios", []):
            data = load_json(os.path.join(base, s["json_file"]))
            if s.get("phases"):
                for phase in s["phases"]:
                    assert phase in data, f"{template}/{s['json_file']} missing phase '{phase}'"
                    assert "line_items" in data[phase], \
                        f"{template}/{s['json_file']}['{phase}'] missing 'line_items'"
                    assert len(data[phase]["line_items"]) > 0
            else:
                assert "line_items" in data, f"{template}/{s['json_file']} missing 'line_items'"
                assert len(data["line_items"]) > 0

    def test_line_items_have_required_fields(self, template):
        project = load_json(get_template_path(template, "project.json"))
        base = os.path.join(TEMPLATES_DIR, template)
        for s in project.get("scenarios", []):
            data = load_json(os.path.join(base, s["json_file"]))
            if s.get("phases"):
                all_items = [item for phase in s["phases"] for item in data[phase]["line_items"]]
            else:
                all_items = data["line_items"]
            for item in all_items:
                missing = REQUIRED_LINE_ITEM_KEYS - set(item.keys())
                assert not missing, \
                    f"{template}/{s['json_file']} item '{item.get('id')}' missing: {missing}"

    def test_formula_items_have_null_values(self, template):
        project = load_json(get_template_path(template, "project.json"))
        base = os.path.join(TEMPLATES_DIR, template)
        for s in project.get("scenarios", []):
            data = load_json(os.path.join(base, s["json_file"]))
            if s.get("phases"):
                all_items = [item for phase in s["phases"] for item in data[phase]["line_items"]]
            else:
                all_items = data["line_items"]
            for item in all_items:
                if item.get("formula"):
                    for field in ("low", "mid", "high"):
                        assert item.get(field) is None, \
                            f"{template} formula item '{item['id']}' has non-null {field}"

    def test_line_item_ids_are_unique_per_scenario(self, template):
        project = load_json(get_template_path(template, "project.json"))
        base = os.path.join(TEMPLATES_DIR, template)
        for s in project.get("scenarios", []):
            data = load_json(os.path.join(base, s["json_file"]))
            if s.get("phases"):
                for phase in s["phases"]:
                    ids = [i["id"] for i in data[phase]["line_items"]]
                    assert len(ids) == len(set(ids)), \
                        f"{template}/{s['json_file']}['{phase}'] has duplicate item IDs: {ids}"
            else:
                ids = [i["id"] for i in data["line_items"]]
                assert len(ids) == len(set(ids)), \
                    f"{template}/{s['json_file']} has duplicate item IDs"

    def test_inputs_json_has_meta(self, template):
        data = load_json(get_template_path(template, "inputs.json"))
        assert "_meta" in data, f"{template}/inputs.json missing '_meta'"

    def test_kanban_json_has_tasks_list(self, template):
        data = load_json(get_template_path(template, "kanban.json"))
        assert "tasks" in data, f"{template}/kanban.json missing 'tasks'"
        assert isinstance(data["tasks"], list)

    def test_inputs_sections_have_fields(self, template):
        project = load_json(get_template_path(template, "project.json"))
        for section in project.get("inputs_sections", []):
            assert "fields" in section, f"Section '{section.get('id')}' missing 'fields'"
            assert len(section["fields"]) > 0, f"Section '{section.get('id')}' has no fields"
            for field in section["fields"]:
                for key in ("key", "label", "type"):
                    assert key in field, \
                        f"Field in section '{section.get('id')}' missing '{key}'"
