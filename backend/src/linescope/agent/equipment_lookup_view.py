"""Observed equipment lookup facts for the model, separate from API results."""

from ..domain.canonical import canonical_json
from .equipment_reference import reference_key

# The original Tool results remain complete; this bounds only duplicated labels.
CANDIDATE_SAMPLE_SIZE = 20


def equipment_lookup_view(observations, failures=()):
    groups = {}

    def group(arguments):
        filters = arguments.get("filter", {})
        if (
            isinstance(filters, dict)
            and len(filters) == 1
            and next(iter(filters)) in {"name", "equipment_code", "reference"}
            and isinstance(next(iter(filters.values())), str)
        ):
            key = ("LITERAL", reference_key(next(iter(filters.values()))))
        else:
            # An explicit conjunction stays a conjunction, never an OR lookup.
            key = ("FILTER", canonical_json(filters))
        return groups.setdefault(key, {"queries": {}, "matches": {}}), filters

    for observation in observations:
        if observation.tool != "search_equipment" or observation.arguments is None:
            continue
        arguments, data = observation.arguments, observation.result.data
        current, filters = group(arguments)
        query = current["queries"].setdefault(
            canonical_json(filters), {"filter": filters, "pages": [], "errors": []}
        )
        query["pages"].append(
            {
                "cursor": arguments.get("cursor"),
                "next_cursor": data.get("next_cursor"),
                "ids": [row["equipment_id"] for row in data.get("items", [])],
            }
        )
        for row in data.get("items", []):
            identifier = row["equipment_id"]
            attributes = {
                key: row[key]
                for key in ("equipment_code", "equipment_name", "version")
                if key in row
            }
            variants = current["matches"].setdefault(identifier, [])
            if attributes not in variants:
                variants.append(attributes)
    for arguments, code in failures:
        current, filters = group(arguments)
        query = current["queries"].setdefault(
            canonical_json(filters), {"filter": filters, "pages": [], "errors": []}
        )
        query["errors"].append(code)

    result = []
    for current in groups.values():
        complete = True
        queries = []
        for query in current["queries"].values():
            pages = query["pages"]
            consumed = {page["cursor"] for page in pages}
            remaining = {page["next_cursor"] for page in pages} - consumed - {None}
            query_complete = None in consumed and not remaining and not query["errors"]
            complete = complete and query_complete
            identifiers = sorted({identifier for page in pages for identifier in page["ids"]})
            queries.append(
                {
                    "filter": query["filter"],
                    "complete": query_complete,
                    "errors": query["errors"],
                    "returned_equipment_count": len(identifiers),
                    "returned_equipment_ids": identifiers[:CANDIDATE_SAMPLE_SIZE],
                    "returned_equipment_sample_truncated": len(identifiers) > CANDIDATE_SAMPLE_SIZE,
                }
            )
        count = len(current["matches"])
        status = (
            "INCOMPLETE"
            if not complete
            else "NO_MATCH"
            if count == 0
            else "FOUND"
            if count == 1
            else "MULTIPLE_MATCHES"
        )
        result.append(
            {
                "queries": queries,
                "equipment_found": count > 0,
                "candidate_count": count,
                "status": status,
                "complete": complete,
                "candidates": [
                    {"equipment_id": identifier, "observed_attributes": attributes}
                    for identifier, attributes in list(current["matches"].items())[
                        :CANDIDATE_SAMPLE_SIZE
                    ]
                ],
                "candidate_sample_truncated": count > CANDIDATE_SAMPLE_SIZE,
                "scope": "OBSERVED_EQUIPMENT_LOOKUPS_ONLY",
                "consistency": "LATEST_PER_CALL",
            }
        )
    return result
