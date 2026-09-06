# FILE: cognitive-harness/exceptions.py
"""Exceptions for cognitive harness.

v0.6.4: IncompleteEnumerationError — raised when a FULL_REQUIRED analysis
cannot proceed because the storage backend cannot guarantee complete
enumeration of all KnowledgeObjects.
"""


class IncompleteEnumerationError(Exception):
    """Raised when list_all_kos() cannot guarantee complete enumeration.

    FULL_REQUIRED analyses (detect_all_anti_patterns, list_review_required,
    global cycle detection) must see every KO in the selected scope.
    A backend that uses search-based enumeration, partial pagination, or
    best-effort retrieval cannot satisfy this requirement.

    The backend MUST either:
    1. Implement provably complete enumeration (type-list + paginated query), or
    2. Set enumeration_complete = False, causing this exception to be raised.

    LOCAL_COMPLETE_ADJACENCY_REQUIRED operations (compute_warrant,
    get_justification_path, compute_impact_set, evaluate_gates) are NOT
    affected — they traverse from a known KO and only need local adjacency.
    """
    pass
