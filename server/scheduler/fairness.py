"""Invigilator fairness / workload balance engine.

Fairness Score = 100 * (1 - SD / max(Average, 1)), clamped to 0..100.
This is a project-defined workload balance indicator (not an industry standard):
read it together with availability, eligibility and per-person duty caps. It never
overrides a hard constraint.
"""
from collections import defaultdict

from .constraints import Problem, to_minutes  # noqa: F401  (to_minutes kept for API symmetry)


def _consecutive_duties(problem, duties_by_inv):
    pairs = 0
    for inv_id, slots in duties_by_inv.items():
        by_date = defaultdict(list)
        for slot in slots:
            by_date[slot["examination_date"]].append(slot)
        for date, items in by_date.items():
            items.sort(key=lambda s: s["start_time"])
            for a, b in zip(items, items[1:]):
                if to_minutes(b["start_time"]) - to_minutes(a["end_time"]) <= 150:
                    pairs += 1
    return pairs


def evaluate(problem, assignments: list) -> dict:
    invs = [i for i in problem.invigilators if i.get("status") == "Active"]
    counts = {i["id"]: 0 for i in invs}
    duties_by_inv = defaultdict(list)
    duty_dates = defaultdict(set)

    for a in assignments:
        slot = problem.slot_by_id.get(a.get("time_slot_id"))
        for inv_id in a.get("invigilator_ids") or []:
            if inv_id not in counts:
                continue
            counts[inv_id] += 1
            duty_dates[inv_id].add(a.get("examination_date"))
            if slot:
                duties_by_inv[inv_id].append(slot)

    values = list(counts.values())
    n = len(values) or 1
    total = sum(values)
    average = total / n
    maximum = max(values) if values else 0
    minimum = min(values) if values else 0
    variance = sum((v - average) ** 2 for v in values) / n if values else 0
    sd = variance ** 0.5
    fairness_score = 100 * (1 - sd / max(average, 1)) if values else 0.0
    fairness_score = max(0.0, min(100.0, fairness_score))

    violations = []
    for a in assignments:
        a0 = to_minutes(a.get("start_time"))
        a1 = to_minutes(a.get("end_time"))
        for inv_id in a.get("invigilator_ids") or []:
            for record in problem.config.get("availability_by_inv", {}).get(inv_id, []):
                if record["date"] != a.get("examination_date"):
                    continue
                if record["availability_status"] not in ("Unavailable", "Leave"):
                    continue
                r0 = to_minutes(record.get("start_time")) if record.get("start_time") else 0
                r1 = to_minutes(record.get("end_time")) if record.get("end_time") else 24 * 60
                if a0 < r1 and r0 < a1:
                    violations.append(inv_id)
    compliance = 100.0 if not assignments else max(0.0, 100.0 * (1 - len(violations) / max(1, total)))

    per_invigilator = []
    for inv in invs:
        c = counts.get(inv["id"], 0)
        per_invigilator.append({
            "invigilator_id": inv["id"], "name": inv["name"], "school_id": inv["school_id"],
            "duties": c, "maximum_total_duties": inv.get("maximum_total_duties"),
            "maximum_daily_duties": inv.get("maximum_daily_duties"),
            "preferred_duties": inv.get("preferred_duties"),
            "distinct_dates": len(duty_dates[inv["id"]]),
            "utilisation_percent": round(100 * c / max(1, int(inv.get("maximum_total_duties") or 1)), 1),
            "status": ("Overloaded" if c > average * 1.3 and c > 0
                       else "Underutilised" if c < average * 0.7 else "Balanced"),
        })
    per_invigilator.sort(key=lambda x: -x["duties"])

    overloaded = [p for p in per_invigilator if p["status"] == "Overloaded"]
    underutilised = [p for p in per_invigilator if p["status"] == "Underutilised"]
    suggestions = []
    if overloaded:
        suggestions.append("Shift duties from " + ", ".join(p["name"] for p in overloaded[:3]) +
                           " to available faculty with spare capacity.")
    if underutilised:
        suggestions.append("Invigilators with spare capacity: " + ", ".join(p["name"] for p in underutilised[:4]) +
                           ". Re-run with balanced allocation enabled to use them.")
    if violations:
        suggestions.append("Resolve availability conflicts before publication: " +
                           f"{len(set(violations))} invigilator(s) received duties on unavailable windows.")
    if not suggestions:
        suggestions.append("Workload is evenly distributed; no rebalancing is required.")

    metrics = [
        ("total_assigned_duties", total, "Sum of all invigilation duties in this run."),
        ("eligible_invigilators", len(invs), "Active invigilators considered for allocation."),
        ("average_workload", round(average, 2), "Total duties / number of eligible invigilators."),
        ("maximum_workload", maximum, "Highest duty count for a single invigilator."),
        ("minimum_workload", minimum, "Lowest duty count for a single invigilator."),
        ("workload_range", maximum - minimum, "Maximum workload - minimum workload."),
        ("standard_deviation", round(sd, 3), "sqrt(sum((individual - average)^2) / N) over eligible invigilators."),
        ("fairness_score", round(fairness_score, 1),
         "100 * (1 - SD / max(Average,1)), clamped to 0-100. Project-defined balance indicator."),
        ("consecutive_duties", _consecutive_duties(problem, duties_by_inv),
         "Duty pairs scheduled back-to-back on the same day (gap <= 2.5 hours)."),
        ("availability_compliance", round(compliance, 1),
         "Percentage of duties that avoid declared unavailable/leave windows."),
    ]
    for p in per_invigilator:
        metrics.append((f"duties::{p['name']}", p["duties"], f"Duties assigned to {p['name']}."))
    for school_id in {i["school_id"] for i in invs}:
        school_total = sum(p["duties"] for p in per_invigilator if p["school_id"] == school_id)
        metrics.append((f"school_duties::{school_id}", school_total,
                        "Duty distribution for this school (school id in the metric name)."))

    return {
        "metrics": [{"metric_name": m, "metric_value": float(v), "metric_description": d}
                    for m, v, d in metrics],
        "summary": {
            "total_assigned_duties": total, "eligible_invigilators": len(invs),
            "average_workload": round(average, 2), "maximum_workload": maximum,
            "minimum_workload": minimum, "workload_range": maximum - minimum,
            "standard_deviation": round(sd, 3), "fairness_score": round(fairness_score, 1),
            "consecutive_duties": metrics[8][1], "availability_compliance": round(compliance, 1),
        },
        "per_invigilator": per_invigilator,
        "overloaded": [{"name": p["name"], "duties": p["duties"]} for p in overloaded],
        "underutilised": [{"name": p["name"], "duties": p["duties"]} for p in underutilised],
        "suggestions": suggestions,
    }
