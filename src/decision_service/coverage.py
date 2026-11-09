from collections import defaultdict
from datetime import datetime


def merge_execution_refs(refs):
    merged = None
    for ref in refs:
        if ref is None:
            continue
        if merged is None:
            merged = {"source": ref["source"], "ids": dict(ref["ids"])}
        elif merged["source"] != ref["source"] or any(
            merged["ids"][key] != ref["ids"][key] for key in merged["ids"].keys() & ref["ids"].keys()
        ):
            return None, False
        else:
            merged["ids"].update(ref["ids"])
    return merged, True


def coverage_for(expects_application, feedback):
    current = [
        event for event in feedback
        if event["is_current"] and event["kind"] in ("application", "result")
    ]
    expected = int(expects_application)
    received = int(bool(expected and any(e["kind"] == "application" for e in current)))
    counts = {
        "application": {"expected": expected, "received": received, "rate": received / expected if expected else None},
        "result": {"expected_ended": None, "received": None, "rate": None},
        "pending": None, "missing": None, "unknown": None, "quality_pending": None,
        "scope_complete": False, "observed_at": None,
    }
    observations = [e["coverage_observation"] for e in current if e.get("coverage_observation")]
    if not observations:
        return counts
    timestamp = max((o["observed_at"] for o in observations),
                    key=lambda value: (datetime.fromisoformat(value), value))
    latest_at = datetime.fromisoformat(timestamp)
    counts["observed_at"] = timestamp
    # An observation's unit IDs are only comparable within its own source scope.
    if len({o["scope_ref"] for o in observations}) != 1:
        return counts

    snapshots = defaultdict(list)
    latest_scope = [o for o in observations if datetime.fromisoformat(o["observed_at"]) == latest_at]
    for observation in observations:
        timestamp = datetime.fromisoformat(observation["observed_at"])
        for unit in observation["units"]:
            snapshots[unit["unit_id"]].append((timestamp, unit))

    units = {}
    for unit_id, observations_of_unit in snapshots.items():
        timestamp = max(t for t, _ in observations_of_unit)
        newest = [u for t, u in observations_of_unit if t == timestamp]
        state_and_expectation = {(u["state"], u["expects_result"]) for u in newest}
        ref, compatible = merge_execution_refs(u.get("execution_ref") for u in newest)
        if len(state_and_expectation) > 1 or not compatible:
            units[unit_id] = {"state": "unknown", "expects_result": any(u["expects_result"] for u in newest)}
        else:
            units[unit_id] = {**newest[0], "execution_ref": ref}

    full_unit_ids = {frozenset(u["unit_id"] for u in o["units"]) for o in latest_scope}
    scope_complete = (all(o["scope_complete"] for o in latest_scope)
                      and full_unit_ids == {frozenset(units)})
    if not units and not scope_complete:
        return counts

    result_events = defaultdict(list)
    for event in current:
        if event["kind"] == "result":
            result_events[event["subject_ref"].get("unit_id")].append(event)

    expected_ended = received_ended = quality_pending = pending = missing = unknown = 0
    for unit_id, unit in units.items():
        if unit["state"] == "unknown":
            unknown += 1
        elif unit["expects_result"] and unit["state"] == "pending":
            pending += 1
        elif unit["expects_result"] and unit["state"] == "ended":
            expected_ended += 1
            matching = [
                e for e in result_events[unit_id]
                if merge_execution_refs((unit.get("execution_ref"), e.get("execution_ref")))[1]
            ]
            if matching:
                received_ended += 1
                qualities = {e["payload"]["quality_status"] for e in matching}
                quality_pending += int(len(qualities) != 1 or bool(qualities & {"pending", "unknown"}))
            else:
                missing += 1

    counts.update(
        result={"expected_ended": expected_ended, "received": received_ended,
                "rate": received_ended / expected_ended if expected_ended else None},
        pending=pending, missing=missing, unknown=unknown, quality_pending=quality_pending,
        scope_complete=scope_complete,
    )
    return counts
