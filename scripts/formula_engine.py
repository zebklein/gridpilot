"""
Formula injection for formula-driven line items.

Some line items display Sheets formulas rather than static values — their
low/mid/high cells are calculated from INPUTS tab values. This module maps
item IDs to their formula generators.

To add a new formula-driven item:
  1. Add "formula": true, "low": null, "mid": null, "high": null to the JSON
  2. Optionally add "formula_expr": {"low": "{key} * {key}", ...} for push.py to
     write and restore the formula automatically on every push.
  3. Or add a branch in get_formula() below for complex multi-cell formulas.

formula_expr placeholders use input_map keys wrapped in {}: e.g.
  "{construction.sqft_phase1} * {construction.rate_framing_low}"
resolves to "=BUDGET!B66*BUDGET!B72" via the input_map.
"""
import re


def cell_ref(inp_tab, input_map, key):
    """Return a fully-qualified cell reference like 'BUDGET!B32', or None if key missing."""
    addr = input_map.get(key)
    if not addr:
        return None
    return f"{inp_tab}!{addr}"


def get_formula(item_id, input_map, inp_tab, mid_const):
    """
    Returns (low_formula, mid_formula, high_formula) strings for formula-driven items,
    or None if item_id is not handled here.

    mid_const: a Sheets expression like "(BUDGET!B17*BUDGET!B19)" representing
               sqft * cost_per_sqft_mid — used to compute percentage-based soft costs.
    """
    def c(key):
        return cell_ref(inp_tab, input_map, key)

    if item_id == "soft_architect":
        ref = c("soft_costs.architect_pct")
        if ref:
            return (
                f"={mid_const}*{ref}*0.6",
                f"={mid_const}*{ref}",
                f"={mid_const}*{ref}*1.4",
            )

    elif item_id == "soft_engineering":
        ref = c("soft_costs.engineering_pct")
        if ref:
            return (
                f"={mid_const}*{ref}*0.6",
                f"={mid_const}*{ref}",
                f"={mid_const}*{ref}*1.4",
            )

    elif item_id == "soft_permits":
        ref = c("soft_costs.permits_fees_flat")
        if ref:
            return (f"={ref}", f"={ref}", f"={ref}")

    elif item_id == "soft_survey_geotech":
        ref = c("soft_costs.survey_geotech_flat")
        if ref:
            return (f"={ref}", f"={ref}", f"={ref}")

    elif item_id == "soft_legal":
        ref = c("soft_costs.legal_misc_flat")
        if ref:
            return (f"={ref}", f"={ref}", f"={ref}")

    elif item_id in ("soft_loan_fees", "soft_loan_fees_p2"):
        ltv = c("financing.construction_loan_ltv")
        if ltv:
            return (
                f"={mid_const}*{ltv}*0.015*0.5",
                f"={mid_const}*{ltv}*0.015",
                f"={mid_const}*{ltv}*0.015*1.5",
            )

    return None


def resolve_formula_expr(expr, input_map, inp_tab):
    """
    Replace {key} placeholders with fully-qualified cell refs from input_map.
    Returns a Sheets formula string starting with '=', or None if any key is missing.

    Example:
      "{construction.sqft_phase1} * {construction.rate_framing_low}"
      → "=BUDGET!B66*BUDGET!B72"
    """
    keys = re.findall(r'\{([^}]+)\}', expr)
    result = expr
    for key in keys:
        addr = input_map.get(key)
        if not addr:
            return None
        qualified = addr if "!" in addr else f"{inp_tab}!{addr}"
        result = result.replace(f"{{{key}}}", qualified)
    return f"={result}"


def get_formula_expr_updates(item, row_1idx, tab_name, input_map, inp_tab):
    """
    Build a list of {range, values} dicts for an item's formula_expr entries.
    Write these with USER_ENTERED so Sheets interprets the '=' as a formula.

    formula_expr key → column:
      low/mid/high     → C/D/E  (Phase 1 or single-phase)
      p2_low/mid/high  → F/G/H  (Phase 2)
    """
    expr_map = item.get("formula_expr", {})
    if not expr_map:
        return []

    col_map = {
        "low": "C", "mid": "D", "high": "E",
        "p2_low": "F", "p2_mid": "G", "p2_high": "H",
    }
    updates = []
    for key, col in col_map.items():
        if key not in expr_map:
            continue
        formula = resolve_formula_expr(expr_map[key], input_map, inp_tab)
        if formula:
            updates.append({"range": f"{tab_name}!{col}{row_1idx}", "values": [[formula]]})
        else:
            print(f"  WARNING: formula_expr '{key}' for {item['id']} has unresolvable placeholder")
    return updates


def is_formula_item(item):
    """True if item should be skipped by push (formula-driven or all-null values)."""
    if item.get("formula"):
        return True
    return item.get("low") is None and item.get("mid") is None and item.get("high") is None
