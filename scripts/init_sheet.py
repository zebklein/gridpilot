"""
Creates and fully formats a Gridpilot budget spreadsheet in Google Sheets.
Run once per project. If spreadsheet_id is already set in config.json, the script
refuses to overwrite — clear it and delete the old sheet first.

Usage:
    python scripts/init_sheet.py --project <name>
    python scripts/init_sheet.py --project myproject --template new-construction
"""
import os
import sys
import json
import argparse
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from sheets_client import get_service, batch_write, batch_format, create_spreadsheet, get_sheet_id
from project_config import (
    get_project_dir, load_project, get_scenario_row_map_key, GRIDPILOT_ROOT
)
from formula_engine import get_formula

KANBAN_HEADERS = ["ID", "Title", "Status", "Owner", "Priority", "Blocked By", "Notes", "Resources"]


# ── Colour palette ─────────────────────────────────────────────────────────────

def rgb(r, g, b):
    return {"red": r / 255, "green": g / 255, "blue": b / 255}

C_HEADER_DARK   = rgb(30, 41, 59)    # slate-900  — sheet title bar
C_HEADER_MID    = rgb(51, 65, 85)    # slate-700  — section headers
C_HEADER_TEXT   = rgb(255, 255, 255)
C_INPUT         = rgb(255, 251, 235)  # amber-50   — editable cells
C_FORMULA       = rgb(241, 245, 249)  # slate-100  — calculated cells
C_SUBTOTAL      = rgb(226, 232, 240)  # slate-200  — subtotal rows
C_TOTAL_BG      = rgb(15, 23, 42)    # slate-950  — grand total row
C_TOTAL_TEXT    = rgb(255, 255, 255)
C_LOW_HEADER    = rgb(220, 252, 231)  # green-100  — Low column header
C_MID_HEADER    = rgb(219, 234, 254)  # blue-100   — Mid column header
C_HIGH_HEADER   = rgb(254, 226, 226)  # red-100    — High column header
C_P1_HEADER     = rgb(219, 234, 254)  # blue-100
C_P2_HEADER     = rgb(243, 232, 255)  # purple-100
C_WHITE         = rgb(255, 255, 255)


# ── Formatting helpers ─────────────────────────────────────────────────────────

def cell_range(sheet_id, r1, c1, r2, c2):
    return {
        "sheetId": sheet_id,
        "startRowIndex": r1, "endRowIndex": r2,
        "startColumnIndex": c1, "endColumnIndex": c2,
    }


def fmt_request(sheet_id, r1, c1, r2, c2, **fmt):
    return {
        "repeatCell": {
            "range": cell_range(sheet_id, r1, c1, r2, c2),
            "cell": {"userEnteredFormat": fmt},
            "fields": "userEnteredFormat(" + ",".join(fmt.keys()) + ")",
        }
    }


def bg_request(sheet_id, r1, c1, r2, c2, color):
    return fmt_request(sheet_id, r1, c1, r2, c2, backgroundColor=color)


def bold_request(sheet_id, r1, c1, r2, c2, bold=True):
    return fmt_request(sheet_id, r1, c1, r2, c2,
                       textFormat={"bold": bold, "fontSize": 10})


def header_request(sheet_id, r1, c1, r2, c2, bg, fg=None, size=10):
    fg = fg or C_HEADER_TEXT
    return fmt_request(sheet_id, r1, c1, r2, c2,
                       backgroundColor=bg,
                       textFormat={"bold": True, "fontSize": size, "foregroundColor": fg})


def currency_request(sheet_id, r1, c1, r2, c2):
    return fmt_request(sheet_id, r1, c1, r2, c2,
                       numberFormat={"type": "CURRENCY", "pattern": '"$"#,##0'})


def percent_request(sheet_id, r1, c1, r2, c2):
    return fmt_request(sheet_id, r1, c1, r2, c2,
                       numberFormat={"type": "PERCENT", "pattern": "0.0%"})


def merge_request(sheet_id, r1, c1, r2, c2):
    return {
        "mergeCells": {
            "range": cell_range(sheet_id, r1, c1, r2, c2),
            "mergeType": "MERGE_ALL",
        }
    }


def col_width_request(sheet_id, col, width_px):
    return {
        "updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": col, "endIndex": col + 1},
            "properties": {"pixelSize": width_px},
            "fields": "pixelSize",
        }
    }


def row_height_request(sheet_id, row, height_px):
    return {
        "updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS",
                      "startIndex": row, "endIndex": row + 1},
            "properties": {"pixelSize": height_px},
            "fields": "pixelSize",
        }
    }


def freeze_request(sheet_id, rows=0, cols=0):
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": rows, "frozenColumnCount": cols},
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }
    }


def tab_color_request(sheet_id, color):
    return {
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "tabColor": color},
            "fields": "tabColor",
        }
    }


def border_request(sheet_id, r1, c1, r2, c2, style="SOLID", width=1):
    border = {"style": style, "width": width, "color": rgb(100, 116, 139)}
    return {
        "updateBorders": {
            "range": cell_range(sheet_id, r1, c1, r2, c2),
            "top": border, "bottom": border, "left": border, "right": border,
            "innerHorizontal": border, "innerVertical": border,
        }
    }


def add_sheet_request(title, tab_color, index):
    return {
        "addSheet": {
            "properties": {"title": title, "index": index, "tabColor": tab_color}
        }
    }


# ── BUDGET (inputs) tab ────────────────────────────────────────────────────────

def setup_inputs(service, spreadsheet_id, sheet_id, project, project_dir):
    """
    Builds the BUDGET tab from project.json["inputs_sections"].
    Returns input_map: dict of dotted_key -> "B{row_1idx}".
    """
    tab_name = project["tabs"]["inputs"]
    title = project["spreadsheet_title"]

    rows = []      # (row_0idx, [A, B, C])
    input_map = {}
    section_rows = set()
    percent_rows = set()
    currency_rows = set()
    input_value_rows = set()

    # Load current values from inputs.json
    inputs_path = os.path.join(project_dir, "inputs.json")
    inputs_data = {}
    if os.path.exists(inputs_path):
        with open(inputs_path) as f:
            inputs_data = json.load(f)

    def get_val(dotted_key):
        parts = dotted_key.split(".")
        node = inputs_data
        try:
            for p in parts:
                node = node[p]
            return node if node is not None else ""
        except (KeyError, TypeError):
            return ""

    # Row 0: title (merged)
    rows.append((0, [f"{title} — BUDGET INPUTS", "", ""]))
    current_row = 2  # next row to use (0-indexed); row 2 is blank before first section

    for section in project["inputs_sections"]:
        current_row += 1  # blank separator row
        sec_row = current_row
        section_rows.add(sec_row)
        rows.append((sec_row, [section["label"], "", ""]))
        current_row += 1

        for field in section["fields"]:
            row_0idx = current_row
            row_1idx = row_0idx + 1
            cell_addr = f"B{row_1idx}"

            hint = field.get("hint", "")
            val = get_val(field["key"])
            rows.append((row_0idx, [field["label"], val, hint]))
            input_map[field["key"]] = cell_addr

            ftype = field.get("type", "text")
            if ftype == "percent":
                percent_rows.add(row_0idx)
            elif ftype == "currency":
                currency_rows.add(row_0idx)

            input_value_rows.add(row_0idx)
            current_row += 1

    max_row = current_row + 2
    grid = [["", "", ""] for _ in range(max_row)]
    for idx, vals in rows:
        grid[idx] = [str(v) if v not in (None, "") else "" for v in vals]

    batch_write(service, spreadsheet_id, [{
        "range": f"{tab_name}!A1:C{max_row}",
        "values": grid,
    }])

    requests = []
    for col, w in [(0, 240), (1, 220), (2, 340)]:
        requests.append(col_width_request(sheet_id, col, w))

    requests += [
        merge_request(sheet_id, 0, 0, 1, 3),
        header_request(sheet_id, 0, 0, 1, 3, C_HEADER_DARK, size=13),
        row_height_request(sheet_id, 0, 42),
    ]
    for r in section_rows:
        requests += [
            merge_request(sheet_id, r, 0, r + 1, 3),
            header_request(sheet_id, r, 0, r + 1, 3, C_HEADER_MID),
            row_height_request(sheet_id, r, 26),
        ]
    for r in input_value_rows:
        requests.append(bg_request(sheet_id, r, 1, r + 1, 2, C_INPUT))
        requests.append(bold_request(sheet_id, r, 0, r + 1, 1))
    for r in percent_rows:
        requests.append(percent_request(sheet_id, r, 1, r + 1, 2))
    for r in currency_rows:
        requests.append(currency_request(sheet_id, r, 1, r + 1, 2))
    requests.append(freeze_request(sheet_id, rows=1))

    batch_format(service, spreadsheet_id, requests)
    return input_map, current_row  # current_row = first row after all inputs (for comparison append)


# ── Single-phase scenario tab (e.g. ONE_SHOT) ─────────────────────────────────

def setup_single_phase_tab(service, spreadsheet_id, sheet_id, scenario, project_dir, input_map):
    """
    Builds a scenario tab with columns: A=Category, B=Label, C=Low, D=Mid, E=High, F=Notes.
    Returns (item_rows dict, gt_all_in_row_1idx).
    """
    inp = project_dir  # unused; we use input_map directly
    json_path = os.path.join(project_dir, scenario["json_file"])
    with open(json_path) as f:
        data = json.load(f)

    tab_name = scenario["tab"]
    tab_title = scenario.get("label", scenario["id"])
    inp_tab = project_dir  # placeholder — we look up via input_map
    # Resolve the inputs tab name from the scenario's project (passed in separately)
    # We need it for formula strings; it's embedded in input_map cell refs already
    # So we just need the tab name for cross-sheet formulas.
    # The calling code will pass inp_tab_name.
    raise RuntimeError("Use setup_single_phase_tab_named() which takes inp_tab_name")


def setup_single_phase_tab_named(service, spreadsheet_id, sheet_id, scenario, project_dir,
                                  input_map, inp_tab_name):
    """
    Builds a single-phase scenario tab.
    Returns (item_rows: {item_id: row_1idx}, gt_all_in_row_1idx).
    """
    json_path = os.path.join(project_dir, scenario["json_file"])
    with open(json_path) as f:
        data = json.load(f)

    tab_name = scenario["tab"]
    tab_title = scenario.get("label", scenario["id"])

    sqft_addr = input_map.get("construction.target_sqft", "B17")
    mid_cost_addr = input_map.get("construction.cost_per_sqft_mid", "B19")
    mid_const = f"({inp_tab_name}!{sqft_addr}*{inp_tab_name}!{mid_cost_addr})"

    layout = []
    item_rows = {}

    layout.append((0, [f"{tab_title.upper()} — SCENARIO", "", "", "", "", ""]))
    layout.append((1, ["Category", "Line Item", "Low Estimate", "Mid Estimate", "High Estimate", "Notes"]))

    # Land section (formula rows referencing INPUTS)
    land_price = input_map.get("land.purchase_price", "B12")
    closing_pct = input_map.get("land.closing_costs_pct", "B13")
    layout.append((3, ["LAND & ACQUISITION", "", "", "", "", ""]))
    layout.append((4, ["Land & Acq.", "Land Purchase Price",
                        f"={inp_tab_name}!{land_price}",
                        f"={inp_tab_name}!{land_price}",
                        f"={inp_tab_name}!{land_price}",
                        "From BUDGET tab"]))
    layout.append((5, ["Land & Acq.", "Closing Costs",
                        f"={inp_tab_name}!{land_price}*{inp_tab_name}!{closing_pct}",
                        f"={inp_tab_name}!{land_price}*{inp_tab_name}!{closing_pct}",
                        f"={inp_tab_name}!{land_price}*{inp_tab_name}!{closing_pct}",
                        "Purchase Price x Closing %"]))
    layout.append((6, ["", "SUBTOTAL — Land & Acquisition",
                        "=SUM(C5:C6)", "=SUM(D5:D6)", "=SUM(E5:E6)", ""]))
    land_sub_row = 7  # 1-indexed

    # Group items by section, preserving order from JSON
    sections_ordered = []
    seen = set()
    for item in data["line_items"]:
        s = item["section"]
        if s not in seen:
            sections_ordered.append(s)
            seen.add(s)

    current_row = 8  # 0-indexed; row 9 in spreadsheet (due diligence section header)
    section_subtotals = {}  # section_name -> sub_row_0idx

    for sec_name in sections_ordered:
        sec_items = [i for i in data["line_items"] if i["section"] == sec_name]
        if not sec_items:
            continue

        sec_row = current_row
        layout.append((sec_row, [sec_name.upper(), "", "", "", "", ""]))
        current_row += 1
        start = current_row

        for item in sec_items:
            formulas = get_formula(item["id"], input_map, inp_tab_name, mid_const)
            if formulas:
                low_v, mid_v, high_v = formulas
            else:
                low_v = item.get("low", "") if item.get("low") is not None else ""
                mid_v = item.get("mid", "") if item.get("mid") is not None else ""
                high_v = item.get("high", "") if item.get("high") is not None else ""
            layout.append((current_row, [sec_name, item["label"],
                                          low_v, mid_v, high_v, item.get("notes", "")]))
            item_rows[item["id"]] = current_row + 1  # 1-indexed
            current_row += 1

        end = current_row
        r1 = start + 1; r2 = end
        layout.append((end, ["", f"SUBTOTAL — {sec_name}",
                              f"=SUM(C{r1}:C{r2})", f"=SUM(D{r1}:D{r2})", f"=SUM(E{r1}:E{r2})", ""]))
        section_subtotals[sec_name] = end
        current_row = end + 2  # blank after subtotal

    # Hard cost subtotal
    hard_sections = ["Site Work", "Foundation", "Structure", "MEP", "Interior", "Specialty"]
    hard_refs = [section_subtotals[s] + 1 for s in hard_sections if s in section_subtotals]
    if not hard_refs:
        hard_refs = [section_subtotals[s] + 1 for s in sections_ordered
                     if s in section_subtotals and s not in ("Due Diligence", "Soft Costs")]
    hard_row = current_row
    hc = "+".join([f"C{r}" for r in hard_refs])
    hd = "+".join([f"D{r}" for r in hard_refs])
    he = "+".join([f"E{r}" for r in hard_refs])
    layout.append((hard_row, ["", "HARD COST SUBTOTAL (Excl. Land, Due Dil., Soft)",
                               f"={hc}", f"={hd}", f"={he}", ""]))

    soft_ref = (section_subtotals.get("Soft Costs", 0) + 1)
    dd_ref = (section_subtotals.get("Due Diligence", 0) + 1)
    hard_ref_1 = hard_row + 1

    # Contingency
    cont_sec = hard_row + 1
    cont_start = cont_sec + 1
    layout.append((cont_sec, ["CONTINGENCY (AUTO-CALCULATED)", "", "", "", "", ""]))

    sw_ref_1 = (section_subtotals.get("Site Work", hard_row) + 1)
    sw_cont = input_map.get("contingency.sitework_pct", "B39")
    cn_cont = input_map.get("contingency.construction_pct", "B40")
    oc_cont = input_map.get("contingency.owner_change_pct", "B41")
    ds_cont = input_map.get("contingency.design_pct", "B42")

    cont_items = [
        ("Sitework Contingency",
         f"=C{sw_ref_1}*{inp_tab_name}!{sw_cont}",
         f"=D{sw_ref_1}*{inp_tab_name}!{sw_cont}",
         f"=E{sw_ref_1}*{inp_tab_name}!{sw_cont}"),
        ("Construction Contingency",
         f"=C{hard_ref_1}*{inp_tab_name}!{cn_cont}",
         f"=D{hard_ref_1}*{inp_tab_name}!{cn_cont}",
         f"=E{hard_ref_1}*{inp_tab_name}!{cn_cont}"),
        ("Owner Change Reserve",
         f"=C{hard_ref_1}*{inp_tab_name}!{oc_cont}",
         f"=D{hard_ref_1}*{inp_tab_name}!{oc_cont}",
         f"=E{hard_ref_1}*{inp_tab_name}!{oc_cont}"),
        ("Design Contingency",
         f"=C{soft_ref}*{inp_tab_name}!{ds_cont}",
         f"=D{soft_ref}*{inp_tab_name}!{ds_cont}",
         f"=E{soft_ref}*{inp_tab_name}!{ds_cont}"),
    ]
    for i, (label, l, m, h) in enumerate(cont_items):
        layout.append((cont_start + i, ["Contingency", label, l, m, h, "From BUDGET rates"]))
    cont_end = cont_start + len(cont_items)
    layout.append((cont_end, ["", "SUBTOTAL — Contingency",
                               f"=SUM(C{cont_start+1}:C{cont_end})",
                               f"=SUM(D{cont_start+1}:D{cont_end})",
                               f"=SUM(E{cont_start+1}:E{cont_end})", ""]))

    # Financing
    fin_sec = cont_end + 1
    fin_start = fin_sec + 1
    layout.append((fin_sec, ["FINANCING COSTS (AUTO-CALCULATED)", "", "", "", "", ""]))
    cont_sub_1 = cont_end + 1
    rate = f"{inp_tab_name}!{input_map.get('financing.construction_loan_rate', 'B24')}"
    ltv  = f"{inp_tab_name}!{input_map.get('financing.construction_loan_ltv', 'B25')}"
    dur  = f"{inp_tab_name}!{input_map.get('financing.construction_duration_months', 'B28')}"
    base_l = f"(C{hard_ref_1}+C{soft_ref}+C{cont_sub_1})"
    base_m = f"(D{hard_ref_1}+D{soft_ref}+D{cont_sub_1})"
    base_h = f"(E{hard_ref_1}+E{soft_ref}+E{cont_sub_1})"
    layout.append((fin_start, ["Financing", "Construction Loan Interest",
                                f"={base_l}*{ltv}*{rate}*({dur}/12)",
                                f"={base_m}*{ltv}*{rate}*({dur}/12)",
                                f"={base_h}*{ltv}*{rate}*({dur}/12)",
                                "Simplified: base x LTV x rate x term"]))
    layout.append((fin_start + 1, ["Financing", "Loan Origination Fees (~1.5%)",
                                    f"={base_l}*{ltv}*0.015",
                                    f"={base_m}*{ltv}*0.015",
                                    f"={base_h}*{ltv}*0.015", ""]))
    fin_end = fin_start + 2
    layout.append((fin_end, ["", "SUBTOTAL — Financing",
                              f"=SUM(C{fin_start+1}:C{fin_end})",
                              f"=SUM(D{fin_start+1}:D{fin_end})",
                              f"=SUM(E{fin_start+1}:E{fin_end})", ""]))

    # Grand total
    gt_row = fin_end + 1
    fin_sub_1 = fin_end + 1
    layout.append((gt_row, ["", "GRAND TOTAL (Excl. Land)",
                             f"=C{dd_ref}+C{soft_ref}+C{hard_ref_1}+C{cont_sub_1}+C{fin_sub_1}",
                             f"=D{dd_ref}+D{soft_ref}+D{hard_ref_1}+D{cont_sub_1}+D{fin_sub_1}",
                             f"=E{dd_ref}+E{soft_ref}+E{hard_ref_1}+E{cont_sub_1}+E{fin_sub_1}",
                             ""]))
    layout.append((gt_row + 1, ["", "LAND + ALL-IN TOTAL",
                                 f"=C{land_sub_row}+C{gt_row+1}",
                                 f"=D{land_sub_row}+D{gt_row+1}",
                                 f"=E{land_sub_row}+E{gt_row+1}",
                                 "Land purchase price + all project costs"]))

    total_rows = gt_row + 2
    grid = [[""] * 6 for _ in range(total_rows)]
    for idx, vals in layout:
        if idx < total_rows:
            grid[idx] = [str(v) if v not in (None, "") else "" for v in vals]

    batch_write(service, spreadsheet_id, [{
        "range": f"{tab_name}!A1:F{total_rows}",
        "values": grid,
    }])

    # Formatting
    requests = []
    for col, w in [(0, 140), (1, 280), (2, 130), (3, 130), (4, 130), (5, 320)]:
        requests.append(col_width_request(sheet_id, col, w))
    requests += [
        merge_request(sheet_id, 0, 0, 1, 6),
        header_request(sheet_id, 0, 0, 1, 6, C_HEADER_DARK, size=12),
        row_height_request(sheet_id, 0, 40),
        bold_request(sheet_id, 1, 0, 2, 6),
    ]
    for col, color in [(2, C_LOW_HEADER), (3, C_MID_HEADER), (4, C_HIGH_HEADER)]:
        requests.append(bg_request(sheet_id, 1, col, 2, col + 1, color))
    for idx, vals in layout:
        if vals and vals[0].upper() == vals[0] and len(vals[0]) > 3 and vals[1] == "":
            requests += [merge_request(sheet_id, idx, 0, idx + 1, 6),
                         header_request(sheet_id, idx, 0, idx + 1, 6, C_HEADER_MID)]
        if len(vals) > 1 and str(vals[1]).startswith("SUBTOTAL"):
            requests += [bg_request(sheet_id, idx, 0, idx + 1, 6, C_SUBTOTAL),
                         bold_request(sheet_id, idx, 0, idx + 1, 6),
                         currency_request(sheet_id, idx, 2, idx + 1, 5)]
    requests += [
        bg_request(sheet_id, hard_row, 0, hard_row + 1, 6, rgb(186, 230, 253)),
        bold_request(sheet_id, hard_row, 0, hard_row + 1, 6),
        currency_request(sheet_id, hard_row, 2, hard_row + 1, 5),
    ]
    for r in [gt_row, gt_row + 1]:
        requests += [
            bg_request(sheet_id, r, 0, r + 1, 6, C_TOTAL_BG),
            fmt_request(sheet_id, r, 0, r + 1, 6,
                        backgroundColor=C_TOTAL_BG,
                        textFormat={"bold": True, "fontSize": 11, "foregroundColor": C_TOTAL_TEXT}),
            currency_request(sheet_id, r, 2, r + 1, 5),
        ]
    data_rows_idx = {idx for idx, vals in layout
                     if vals and vals[0] not in ("", "Category")
                     and not (vals[0].upper() == vals[0] and vals[1] == "")}
    for r in data_rows_idx:
        requests.append(currency_request(sheet_id, r, 2, r + 1, 5))
    requests.append(freeze_request(sheet_id, rows=2))
    batch_format(service, spreadsheet_id, requests)

    return item_rows, gt_row + 2  # 1-indexed all-in total row


# ── Multi-phase scenario tab (e.g. MODULAR) ────────────────────────────────────

def setup_multiphase_tab(service, spreadsheet_id, sheet_id, scenario, project_dir,
                          input_map, inp_tab_name):
    """
    Builds a multi-phase scenario tab.
    Columns: A=Category, B=Label, C-E=Phase1 Low/Mid/High, F-H=Phase2 Low/Mid/High, I=Notes.
    Returns (phase_rows: {key: {item_id: row_1idx}}, gt_all_in_row_1idx).
    """
    json_path = os.path.join(project_dir, scenario["json_file"])
    with open(json_path) as f:
        data = json.load(f)

    tab_name = scenario["tab"]
    tab_title = scenario.get("label", scenario["id"])
    phases = scenario["phases"]  # e.g. ["phase1", "phase2"]
    num_cols = 9

    sqft_addr = input_map.get("construction.target_sqft", "B17")
    mid_cost_addr = input_map.get("construction.cost_per_sqft_mid", "B19")
    mid_const = f"({inp_tab_name}!{sqft_addr}*{inp_tab_name}!{mid_cost_addr})"

    layout = []
    phase1_rows = {}
    phase2_rows = {}

    layout.append((0, [f"{tab_title.upper()} — PHASED SCENARIO"] + [""] * (num_cols - 1)))
    p1_label = phases[0].replace("_", " ").title()
    p2_label = phases[1].replace("_", " ").title() if len(phases) > 1 else "Phase 2"
    layout.append((1, ["Category", "Line Item",
                        f"{p1_label} Low", f"{p1_label} Mid", f"{p1_label} High",
                        f"{p2_label} Low", f"{p2_label} Mid", f"{p2_label} High", "Notes"]))

    p1_items_by_id = {i["id"]: i for i in data[phases[0]]["line_items"]}
    p2_items_by_id = {i["id"]: i for i in data[phases[1]]["line_items"]} if len(phases) > 1 else {}

    sections_ordered = []
    seen = set()
    for item in data[phases[0]]["line_items"]:
        s = item["section"]
        if s not in seen:
            sections_ordered.append(s)
            seen.add(s)

    current_row = 2
    section_subtotals = {}

    for sec_name in sections_ordered:
        sec_p1 = [i for i in data[phases[0]]["line_items"] if i["section"] == sec_name]
        if not sec_p1:
            continue

        sec_row = current_row
        layout.append((sec_row, [sec_name.upper()] + [""] * (num_cols - 1)))
        current_row += 1
        start = current_row

        for p1_item in sec_p1:
            p2_id = p1_item["id"] + "_p2"
            p2_item = p2_items_by_id.get(p2_id, {})

            p1_formulas = get_formula(p1_item["id"], input_map, inp_tab_name, mid_const)
            if p1_formulas:
                p1_low, p1_mid, p1_high = p1_formulas
            else:
                p1_low  = p1_item.get("low", "") if p1_item.get("low") is not None else ""
                p1_mid  = p1_item.get("mid", "") if p1_item.get("mid") is not None else ""
                p1_high = p1_item.get("high", "") if p1_item.get("high") is not None else ""

            p2_formulas = get_formula(p2_id, input_map, inp_tab_name, mid_const)
            if p2_formulas:
                p2_low, p2_mid, p2_high = p2_formulas
            else:
                p2_low  = p2_item.get("low", "") if p2_item.get("low") is not None else ""
                p2_mid  = p2_item.get("mid", "") if p2_item.get("mid") is not None else ""
                p2_high = p2_item.get("high", "") if p2_item.get("high") is not None else ""

            layout.append((current_row, [
                sec_name, p1_item["label"],
                p1_low, p1_mid, p1_high,
                p2_low, p2_mid, p2_high,
                p1_item.get("notes", ""),
            ]))
            phase1_rows[p1_item["id"]] = current_row + 1
            if p2_id in p2_items_by_id:
                phase2_rows[p2_id] = current_row + 1
            current_row += 1

        end = current_row
        r1 = start + 1; r2 = end
        layout.append((end, ["", f"SUBTOTAL — {sec_name}",
                              f"=SUM(C{r1}:C{r2})", f"=SUM(D{r1}:D{r2})", f"=SUM(E{r1}:E{r2})",
                              f"=SUM(F{r1}:F{r2})", f"=SUM(G{r1}:G{r2})", f"=SUM(H{r1}:H{r2})",
                              ""]))
        section_subtotals[sec_name] = end
        current_row = end + 2

    # Remobilization section
    remob_sec = current_row
    layout.append((remob_sec, ["REMOBILIZATION"] + [""] * (num_cols - 1)))
    current_row += 1
    remob_start = current_row

    hard_sections = ["Site Work", "Foundation", "Structure", "MEP", "Interior", "Specialty"]
    p2_hard_subs = [section_subtotals[s] + 1 for s in hard_sections if s in section_subtotals]
    prem_pct = data.get("_meta", {}).get("remobilization_premium_pct", 0.10)
    if p2_hard_subs:
        p2_f = "+".join([f"F{r}" for r in p2_hard_subs])
        p2_g = "+".join([f"G{r}" for r in p2_hard_subs])
        p2_h = "+".join([f"H{r}" for r in p2_hard_subs])
        layout.append((current_row, ["Remobilization", "Contractor Remobilization Premium",
                                      "", "", "",
                                      f"=({p2_f})*{prem_pct}",
                                      f"=({p2_g})*{prem_pct}",
                                      f"=({p2_h})*{prem_pct}",
                                      f"~{int(prem_pct*100)}% of Phase 2 hard costs"]))
    current_row += 1
    layout.append((current_row, ["Remobilization", "Phase 1 Protection & Temporary Works",
                                  "", "", "", 5000, 12000, 25000,
                                  "Protecting Phase 1 finishes during Phase 2 construction"]))
    current_row += 1
    remob_end = current_row
    r1 = remob_start + 1; r2 = remob_end
    layout.append((remob_end, ["", "SUBTOTAL — Remobilization", "", "", "",
                                f"=SUM(F{r1}:F{r2})", f"=SUM(G{r1}:G{r2})", f"=SUM(H{r1}:H{r2})", ""]))
    remob_sub_row = remob_end
    current_row += 2

    # Phase gap carrying costs
    gap_row = current_row
    gap_months = f"{inp_tab_name}!{input_map.get('financing.phase_gap_months', 'B29')}"
    sw_sub_ref = section_subtotals.get("Site Work", 0) + 1
    phase_gap_notes = data.get("_meta", {}).get("phase_gap_notes", "months between phases")
    layout.append((gap_row, ["Gap Costs", "Phase 1 Carrying Costs During Gap",
                              "", "", "",
                              f"=D{sw_sub_ref}*0.005*{gap_months}",
                              f"=D{sw_sub_ref}*0.008*{gap_months}",
                              f"=D{sw_sub_ref}*0.012*{gap_months}",
                              f"Property tax + insurance during gap ({phase_gap_notes})"]))
    current_row += 2

    # Totals
    tot_row = current_row
    all_sub = {k: v + 1 for k, v in section_subtotals.items()}
    p1c = "+".join([f"C{all_sub[s]}" for s in sections_ordered if s in all_sub])
    p1d = "+".join([f"D{all_sub[s]}" for s in sections_ordered if s in all_sub])
    p1e = "+".join([f"E{all_sub[s]}" for s in sections_ordered if s in all_sub])
    p2f = "+".join([f"F{all_sub[s]}" for s in sections_ordered if s in all_sub])
    p2g = "+".join([f"G{all_sub[s]}" for s in sections_ordered if s in all_sub])
    p2h = "+".join([f"H{all_sub[s]}" for s in sections_ordered if s in all_sub])

    layout.append((tot_row, ["", "TOTAL PHASE 1",
                              f"={p1c}", f"={p1d}", f"={p1e}", "", "", "", ""]))
    layout.append((tot_row + 1, ["", f"TOTAL {p2_label.upper()} (incl. Remobilization)",
                                  "", "", "",
                                  f"={p2f}+F{remob_sub_row+1}",
                                  f"={p2g}+G{remob_sub_row+1}",
                                  f"={p2h}+H{remob_sub_row+1}", ""]))
    layout.append((tot_row + 2, ["", "GRAND TOTAL — ALL-IN",
                                  f"=C{tot_row+1}+F{tot_row+2}",
                                  f"=D{tot_row+1}+G{tot_row+2}",
                                  f"=E{tot_row+1}+H{tot_row+2}",
                                  "", "", "", ""]))

    total_rows = tot_row + 3
    grid = [[""] * num_cols for _ in range(total_rows)]
    for idx, vals in layout:
        if idx < total_rows:
            grid[idx] = [str(v) if v not in (None, "") else "" for v in vals]

    batch_write(service, spreadsheet_id, [{
        "range": f"{tab_name}!A1:{chr(ord('A')+num_cols-1)}{total_rows}",
        "values": grid,
    }])

    # Formatting
    requests = []
    for col, w in [(0, 140), (1, 280), (2, 115), (3, 115), (4, 115),
                   (5, 115), (6, 115), (7, 115), (8, 310)]:
        requests.append(col_width_request(sheet_id, col, w))
    requests += [
        merge_request(sheet_id, 0, 0, 1, num_cols),
        header_request(sheet_id, 0, 0, 1, num_cols, C_HEADER_DARK, size=12),
        row_height_request(sheet_id, 0, 40),
        bold_request(sheet_id, 1, 0, 2, num_cols),
    ]
    for col in range(2, 5):
        requests.append(bg_request(sheet_id, 1, col, 2, col + 1, C_P1_HEADER))
    for col in range(5, 8):
        requests.append(bg_request(sheet_id, 1, col, 2, col + 1, C_P2_HEADER))
    for idx, vals in layout:
        if vals and vals[0].upper() == vals[0] and len(vals[0]) > 3 and vals[1] == "":
            requests += [merge_request(sheet_id, idx, 0, idx + 1, num_cols),
                         header_request(sheet_id, idx, 0, idx + 1, num_cols, C_HEADER_MID)]
        if len(vals) > 1 and str(vals[1]).startswith("SUBTOTAL"):
            requests += [bg_request(sheet_id, idx, 0, idx + 1, num_cols, C_SUBTOTAL),
                         bold_request(sheet_id, idx, 0, idx + 1, num_cols),
                         currency_request(sheet_id, idx, 2, idx + 1, 8)]
    for r in [tot_row, tot_row + 1, tot_row + 2]:
        requests += [
            bg_request(sheet_id, r, 0, r + 1, num_cols, C_TOTAL_BG),
            fmt_request(sheet_id, r, 0, r + 1, num_cols,
                        backgroundColor=C_TOTAL_BG,
                        textFormat={"bold": True, "fontSize": 11, "foregroundColor": C_TOTAL_TEXT}),
            currency_request(sheet_id, r, 2, r + 1, 8),
        ]
    requests.append(freeze_request(sheet_id, rows=2))
    batch_format(service, spreadsheet_id, requests)

    phase_key_0 = get_scenario_row_map_key(scenario, phases[0])
    phase_key_1 = get_scenario_row_map_key(scenario, phases[1]) if len(phases) > 1 else None
    result = {phase_key_0: phase1_rows}
    if phase_key_1:
        result[phase_key_1] = phase2_rows
    return result, tot_row + 3  # 1-indexed grand total (all-in) row


# ── Comparison section appended to BUDGET tab ─────────────────────────────────

def setup_comparison(service, spreadsheet_id, inputs_sheet_id, project, scenarios_info, input_map,
                      inputs_start_row):
    """
    Appends a scenario comparison section below the inputs in the BUDGET tab.
    scenarios_info: list of {id, tab, gt_row_1idx, phases}
    """
    inp_tab = project["tabs"]["inputs"]
    title = project["spreadsheet_title"]

    if len(scenarios_info) < 1:
        return

    # Use first two scenarios for comparison
    s1 = scenarios_info[0]
    s2 = scenarios_info[1] if len(scenarios_info) > 1 else None

    sqft_addr = input_map.get("construction.target_sqft", "B17")
    land_addr  = input_map.get("land.purchase_price", "B12")
    rate_addr  = input_map.get("financing.construction_loan_rate", "B24")
    gap_addr   = input_map.get("financing.phase_gap_months", "B29")

    # Start the comparison section below the inputs with a gap
    start_0idx = inputs_start_row + 3  # leave 3 blank rows
    rows = []

    def r(idx, vals):
        rows.append((idx, vals))

    r(start_0idx,     [f"{title} — SCENARIO COMPARISON", "", "", "", ""])
    r(start_0idx + 1, ["", "Metric", s1["tab"], s2["tab"] if s2 else "", "Delta (B − A)" if s2 else ""])

    cmp = start_0idx + 2  # offset for section rows
    r(cmp + 1, ["COST SUMMARY", "", "", "", ""])
    s1r = s1["gt_row_1idx"]; s2r = s2["gt_row_1idx"] if s2 else None
    for i, col in enumerate(["C", "D", "E"]):
        label = ["Low", "Mid", "High"][i]
        v1 = f"='{s1['tab']}'!{col}{s1r}"
        v2 = f"='{s2['tab']}'!{col}{s2r}" if s2 else ""
        delta = f"=D{cmp+3+i}-C{cmp+3+i}" if s2 else ""
        r(cmp + 2 + i, ["", f"Total Cost — {label}", v1, v2, delta])

    r(cmp + 6, ["COST PER SQ FT", "", "", "", ""])
    r(cmp + 7, ["", "Cost / Sq Ft (Mid, All-In)",
                f"='{s1['tab']}'!D{s1r}/{inp_tab}!{sqft_addr}",
                f"='{s2['tab']}'!D{s2r}/{inp_tab}!{sqft_addr}" if s2 else "", ""])

    r(cmp + 9, ["KEY INPUTS (SNAPSHOT)", "", "", "", ""])
    r(cmp + 10, ["", "Land Purchase Price",    f"={inp_tab}!{land_addr}", "", ""])
    r(cmp + 11, ["", "Target Sq Ft",           f"={inp_tab}!{sqft_addr}", "", ""])
    r(cmp + 12, ["", "Construction Loan Rate", f"={inp_tab}!{rate_addr}", "", ""])
    r(cmp + 13, ["", "Phase Gap (months)",     f"={inp_tab}!{gap_addr}", "", ""])

    total_rows = cmp + 15
    grid = [[""] * 5 for _ in range(total_rows - start_0idx)]
    for idx, vals in rows:
        g_idx = idx - start_0idx
        if 0 <= g_idx < len(grid):
            grid[g_idx] = [str(v) if v not in (None, "") else "" for v in vals]

    batch_write(service, spreadsheet_id, [{
        "range": f"{inp_tab}!A{start_0idx+1}:E{total_rows}",
        "values": grid,
    }])

    requests = []
    requests += [
        merge_request(inputs_sheet_id, start_0idx, 0, start_0idx + 1, 5),
        header_request(inputs_sheet_id, start_0idx, 0, start_0idx + 1, 5, C_HEADER_DARK, size=12),
        row_height_request(inputs_sheet_id, start_0idx, 40),
        bold_request(inputs_sheet_id, start_0idx + 1, 0, start_0idx + 2, 5),
    ]
    for sec_offset in [cmp + 1, cmp + 6, cmp + 9]:
        requests += [
            merge_request(inputs_sheet_id, sec_offset, 0, sec_offset + 1, 5),
            header_request(inputs_sheet_id, sec_offset, 0, sec_offset + 1, 5, C_HEADER_MID),
        ]
    for i in range(3):
        requests.append(currency_request(inputs_sheet_id, cmp + 2 + i, 2, cmp + 3 + i, 5))
    requests.append(currency_request(inputs_sheet_id, cmp + 7, 2, cmp + 8, 4))
    requests.append(bg_request(inputs_sheet_id, cmp + 3, 0, cmp + 4, 5, rgb(219, 234, 254)))
    requests.append(bold_request(inputs_sheet_id, cmp + 3, 0, cmp + 4, 5))
    batch_format(service, spreadsheet_id, requests)


# ── KANBAN tab ─────────────────────────────────────────────────────────────────

def setup_kanban(service, spreadsheet_id, sheet_id, project, project_dir):
    tab_name = project["tabs"]["kanban"]
    meta = project.get("kanban_meta", {})
    valid_statuses  = meta.get("valid_statuses",  ["New", "Active", "Complete", "Stopped"])
    valid_priorities = meta.get("valid_priorities", ["Critical", "High", "Medium", "Low"])

    # Load tasks from kanban.json
    kanban_path = os.path.join(project_dir, "kanban.json")
    tasks = []
    if os.path.exists(kanban_path):
        with open(kanban_path) as f:
            kdata = json.load(f)
        tasks = kdata.get("tasks", [])

    num_cols = len(KANBAN_HEADERS)

    # Write header + tasks
    rows = [KANBAN_HEADERS]
    for task in tasks:
        rows.append([
            task.get("id", ""),
            task.get("title", ""),
            task.get("status", "New"),
            task.get("owner", ""),
            task.get("priority", "Medium"),
            task.get("blocked_by", ""),
            task.get("notes", ""),
            task.get("resources", ""),
        ])

    batch_write(service, spreadsheet_id, [{
        "range": f"{tab_name}!A1:{chr(ord('A')+num_cols-1)}{len(rows)}",
        "values": rows,
    }])

    requests = []
    for col, w in [(0, 80), (1, 260), (2, 90), (3, 90), (4, 90), (5, 120), (6, 300), (7, 250)]:
        requests.append(col_width_request(sheet_id, col, w))
    requests += [
        header_request(sheet_id, 0, 0, 1, num_cols, C_HEADER_DARK),
        freeze_request(sheet_id, rows=1),
        bg_request(sheet_id, 0, 0, 1, 1, rgb(51, 65, 85)),  # ID col slightly dimmer
    ]

    # Status dropdown (column C = index 2)
    requests.append({
        "setDataValidation": {
            "range": cell_range(sheet_id, 1, 2, 1000, 3),
            "rule": {
                "condition": {"type": "ONE_OF_LIST",
                              "values": [{"userEnteredValue": s} for s in valid_statuses]},
                "showCustomUi": True, "strict": True,
            }
        }
    })
    # Priority dropdown (column E = index 4)
    requests.append({
        "setDataValidation": {
            "range": cell_range(sheet_id, 1, 4, 1000, 5),
            "rule": {
                "condition": {"type": "ONE_OF_LIST",
                              "values": [{"userEnteredValue": p} for p in valid_priorities]},
                "showCustomUi": True, "strict": True,
            }
        }
    })

    # Status conditional formatting
    status_colors = {
        "New":      rgb(226, 232, 240),  # slate-200
        "Active":   rgb(191, 219, 254),  # blue-200
        "Complete": rgb(187, 247, 208),  # green-200
        "Stopped":  rgb(254, 202, 202),  # red-200
    }
    for status, color in status_colors.items():
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [cell_range(sheet_id, 1, 2, 1000, 3)],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": status}]},
                        "format": {"backgroundColor": color},
                    },
                },
                "index": 0,
            }
        })

    # Priority conditional formatting
    priority_colors = {
        "Critical": rgb(254, 202, 202),  # red-200
        "High":     rgb(254, 215, 170),  # orange-200
        "Medium":   rgb(254, 249, 195),  # yellow-200
        "Low":      rgb(226, 232, 240),  # slate-200
    }
    for priority, color in priority_colors.items():
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [cell_range(sheet_id, 1, 4, 1000, 5)],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": priority}]},
                        "format": {"backgroundColor": color},
                    },
                },
                "index": 0,
            }
        })

    batch_format(service, spreadsheet_id, requests)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Initialize a Gridpilot spreadsheet")
    parser.add_argument("--project", required=True, help="Project name (subdirectory of projects/)")
    parser.add_argument("--template", default=None,
                        help="Template to copy if project dir doesn't exist yet")
    args = parser.parse_args()

    # If project dir doesn't exist and a template was specified, copy it
    project_path = os.path.join(GRIDPILOT_ROOT, "projects", args.project)
    if not os.path.isdir(project_path):
        if args.template:
            template_path = os.path.join(GRIDPILOT_ROOT, "templates", args.template)
            if not os.path.isdir(template_path):
                print(f"ERROR: Template '{args.template}' not found in templates/")
                sys.exit(1)
            shutil.copytree(template_path, project_path)
            print(f"  Copied template '{args.template}' to projects/{args.project}/")
            # Initialize a git repo in the project dir
            import subprocess
            subprocess.run(["git", "-C", project_path, "init"], check=True, capture_output=True)
            print(f"  Initialized git repo in projects/{args.project}/")
        else:
            print(f"ERROR: projects/{args.project}/ not found.")
            print(f"  Use --template <name> to create from a template, e.g.:")
            print(f"    --template new-construction")
            sys.exit(1)

    project_dir = project_path
    project = load_project(project_dir)

    config_path = os.path.join(project_dir, "config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    if config.get("spreadsheet_id"):
        print("ERROR: spreadsheet_id already set in config.json.")
        print("  Clear it and delete the existing sheet before re-initializing.")
        sys.exit(1)

    print("Authenticating with Google...")
    service = get_service()

    print(f"Creating spreadsheet: {project['spreadsheet_title']}...")
    spreadsheet_id, first_sheet_id = create_spreadsheet(service, project["spreadsheet_title"])
    print(f"  Created: {spreadsheet_id}")

    inp_tab = project["tabs"]["inputs"]
    kanban_tab = project["tabs"]["kanban"]

    # Rename first sheet to inputs tab name; add scenario and kanban tabs
    add_requests = [
        {"updateSheetProperties": {
            "properties": {"sheetId": first_sheet_id, "title": inp_tab,
                           "index": 0, "tabColor": rgb(100, 116, 139)},
            "fields": "title,index,tabColor",
        }},
    ]
    tab_colors = [
        rgb(34, 197, 94),   # green
        rgb(139, 92, 246),  # purple
        rgb(249, 115, 22),  # orange
        rgb(20, 184, 166),  # teal
    ]
    for i, scenario in enumerate(project["scenarios"]):
        color = tab_colors[i % len(tab_colors)]
        add_requests.append(add_sheet_request(scenario["tab"], color, i + 1))
    add_requests.append(add_sheet_request(kanban_tab, rgb(59, 130, 246), len(project["scenarios"]) + 1))

    batch_format(service, spreadsheet_id, add_requests)

    # Build BUDGET (inputs) tab — also generates input_map
    print(f"Building {inp_tab} tab...")
    input_map, inputs_last_row = setup_inputs(service, spreadsheet_id, first_sheet_id,
                                               project, project_dir)

    # Build scenario tabs
    row_map = {}
    scenarios_info = []

    for scenario in project["scenarios"]:
        tab_id = get_sheet_id(service, spreadsheet_id, scenario["tab"])

        if not scenario.get("phases"):
            print(f"Building {scenario['tab']} tab (single-phase)...")
            item_rows, gt_row = setup_single_phase_tab_named(
                service, spreadsheet_id, tab_id, scenario, project_dir, input_map, inp_tab)
            row_map[scenario["id"]] = {str(v): k for k, v in item_rows.items()}
            scenarios_info.append({"id": scenario["id"], "tab": scenario["tab"],
                                    "gt_row_1idx": gt_row, "phases": None})
        else:
            print(f"Building {scenario['tab']} tab (multi-phase)...")
            phase_rows, gt_row = setup_multiphase_tab(
                service, spreadsheet_id, tab_id, scenario, project_dir, input_map, inp_tab)
            for key, rows_dict in phase_rows.items():
                row_map[key] = {str(v): k for k, v in rows_dict.items()}
            scenarios_info.append({"id": scenario["id"], "tab": scenario["tab"],
                                    "gt_row_1idx": gt_row, "phases": scenario["phases"]})

    # Comparison section in BUDGET tab
    print(f"Appending comparison to {inp_tab} tab...")
    setup_comparison(service, spreadsheet_id, first_sheet_id, project, scenarios_info,
                     input_map, inputs_last_row)

    # KANBAN tab
    print(f"Building {kanban_tab} tab...")
    kanban_id = get_sheet_id(service, spreadsheet_id, kanban_tab)
    setup_kanban(service, spreadsheet_id, kanban_id, project, project_dir)

    # Write row_map.json and input_map.json
    row_map_path = os.path.join(project_dir, "row_map.json")
    with open(row_map_path, "w") as f:
        json.dump(row_map, f, indent=2)
    print(f"  row_map.json written.")

    input_map_path = os.path.join(project_dir, "input_map.json")
    with open(input_map_path, "w") as f:
        json.dump(input_map, f, indent=2)
    print(f"  input_map.json written.")

    # Save config.json
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    config["spreadsheet_id"] = spreadsheet_id
    config["spreadsheet_url"] = url
    config["initialized_at"] = datetime.now().isoformat()
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    # Initial git commit of the project data
    import subprocess
    try:
        subprocess.run(["git", "-C", project_dir, "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", project_dir, "commit", "-m", "init: spreadsheet created"],
                       check=True, capture_output=True)
        print(f"  git: committed initial state in projects/{args.project}/")
    except subprocess.CalledProcessError:
        pass  # git may not be initialized; that's OK

    print(f"\nDone. Spreadsheet URL:\n  {url}")


if __name__ == "__main__":
    main()
