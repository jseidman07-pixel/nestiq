from typing import Any, Dict, List

from tools.mongodb_client import get_database


def _format_saved_deal(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a MongoDB underwriting document into a clean JSON-safe summary.
    """

    analysis = document.get("analysis_result", {})
    property_input = document.get("property_input", {})
    created_at = document.get("created_at")

    return {
        "mongodb_id": str(document.get("_id")),
        "property_name": analysis.get("property_name") or document.get("property_name"),
        "verdict": analysis.get("verdict"),
        "purchase_price": analysis.get("purchase_price") or property_input.get("purchase_price"),
        "monthly_rent": analysis.get("monthly_rent") or property_input.get("monthly_rent"),
        "noi": analysis.get("noi"),
        "cap_rate": analysis.get("cap_rate"),
        "monthly_cash_flow": analysis.get("monthly_cash_flow"),
        "annual_cash_flow": analysis.get("annual_cash_flow"),
        "cash_on_cash_return": analysis.get("cash_on_cash_return"),
        "dscr": analysis.get("dscr"),
        "total_cash_invested": analysis.get("total_cash_invested"),
        "created_at": created_at.isoformat() if created_at else None,
    }


def list_recent_saved_deals(limit: int = 5) -> Dict[str, Any]:
    """
    List the most recent saved underwriting deals from MongoDB.

    Args:
        limit: Maximum number of saved deals to return.

    Returns:
        A dictionary containing recent saved deal summaries.
    """

    db = get_database()
    collection = db["underwriting_results"]

    limit = max(1, min(int(limit), 20))

    documents = (
        collection.find({})
        .sort("created_at", -1)
        .limit(limit)
    )

    deals = [_format_saved_deal(doc) for doc in documents]

    return {
        "status": "success",
        "count": len(deals),
        "deals": deals,
    }


def find_saved_deals_by_verdict(verdict: str, limit: int = 10) -> Dict[str, Any]:
    """
    Find saved underwriting deals by verdict.

    Args:
        verdict: Deal verdict to search for. Use BUY, NEGOTIATE, or WALK AWAY.
        limit: Maximum number of matching deals to return.

    Returns:
        A dictionary containing matching saved deals.
    """

    db = get_database()
    collection = db["underwriting_results"]

    normalized_verdict = verdict.strip().upper()
    limit = max(1, min(int(limit), 20))

    documents = (
        collection.find({"analysis_result.verdict": normalized_verdict})
        .sort("created_at", -1)
        .limit(limit)
    )

    deals = [_format_saved_deal(doc) for doc in documents]

    return {
        "status": "success",
        "searched_verdict": normalized_verdict,
        "count": len(deals),
        "deals": deals,
    }


def get_best_saved_deal(metric: str = "cash_on_cash_return") -> Dict[str, Any]:
    """
    Get the strongest saved deal by a chosen metric.

    Args:
        metric: Metric to rank by. Options: cash_on_cash_return, cap_rate, monthly_cash_flow, dscr, noi.

    Returns:
        A dictionary containing the best saved deal by that metric.
    """

    allowed_metrics = {
        "cash_on_cash_return",
        "cap_rate",
        "monthly_cash_flow",
        "dscr",
        "noi",
    }

    metric = metric.strip().lower()

    if metric not in allowed_metrics:
        return {
            "status": "error",
            "message": f"Unsupported metric: {metric}. Use one of: {sorted(allowed_metrics)}",
        }

    db = get_database()
    collection = db["underwriting_results"]

    document = collection.find_one(
        {"analysis_result." + metric: {"$ne": None}},
        sort=[("analysis_result." + metric, -1)],
    )

    if not document:
        return {
            "status": "success",
            "message": "No saved deals found.",
            "deal": None,
        }

    return {
        "status": "success",
        "ranked_by": metric,
        "deal": _format_saved_deal(document),
    }
