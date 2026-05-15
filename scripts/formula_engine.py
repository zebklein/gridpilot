"""
Formula injection for formula-driven line items.

Some line items display Sheets formulas rather than static values — their
low/mid/high cells are calculated from INPUTS tab values. This module maps
item IDs to their formula generators.

To add a new formula-driven item:
  1. Add "formula": true, "low": null, "mid": null, "high": null to the JSON
  2. Add a branch below mapping its ID to a formula tuple

The formulas reference input cells via input_map (e.g. input_map["soft_costs.architect_pct"]
returns the cell address like "B32", which is then qualified as "{inp_tab}!B32").
"""


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


def is_formula_item(item):
    """True if item should be skipped by push (formula-driven or all-null values)."""
    if item.get("formula"):
        return True
    return item.get("low") is None and item.get("mid") is None and item.get("high") is None
