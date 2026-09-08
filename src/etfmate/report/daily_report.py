from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

def render_html(
    date: str, recommendations: list[dict], grid_advices: list[dict],
    trade_review: dict, data_completeness: dict | None = None,
) -> str:
    from etfmate.analysis.account_strategy import account_overview, TARGETS
    from etfmate.analysis.action_plan import describe_action_plan
    from etfmate.analysis.execution_review import build_execution_review
    from etfmate.analysis.decision_review import build_decision_review
    data = data_completeness or {}
    overview = account_overview(recommendations, data.get("account_summary"))
    grids = {item["code"]: item for item in grid_advices}
    plans = {r["code"]: describe_action_plan(r, grids.get(r["code"], {})) for r in recommendations}
    review = build_execution_review(recommendations, grid_advices, data.get("conditions"),
                                    data.get("funding_plan"), data.get("submitted_orders"))
    decision_review = data.get("decision_review") or build_decision_review(
        recommendations, grid_advices, data.get("account_summary"), data.get("funding_plan"))
    targets = sorted([r for r in recommendations if r.get("code") in TARGETS],
                     key=lambda r: list(TARGETS).index(r["code"]))
    exits = [r for r in recommendations if r.get("code") not in TARGETS]
    priority = {"LIQUIDATION_REVIEW": 0, "CURRENT_PARTIAL_REVIEW": 1, "REVIEW_PATH": 2}
    exits.sort(key=lambda r: (priority.get(plans[r["code"]]["sell_status"], 3), -(r.get("market_value") or 0)))
    return _template_env().get_template("account_report.html").render(
        date=date, overview=overview, targets=targets, exits=exits, grids=grids,
        data=data, trade_review=trade_review, execution_review=review,
        action_plans=plans, decision_review=decision_review,
    )


def write_report(
    path: Path,
    date: str,
    recommendations: list[dict],
    grid_advices: list[dict],
    trade_review: dict,
    data_completeness: dict | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(date, recommendations, grid_advices, trade_review, data_completeness), encoding="utf-8")
    return path


def _template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).with_name("templates")),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
