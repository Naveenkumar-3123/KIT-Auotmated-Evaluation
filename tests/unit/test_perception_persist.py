"""Regression tests for the perception-evidence persistence bridge."""

from __future__ import annotations

from answer_eval.jobs.perception_persist import _region_type


def test_region_type_maps_to_db_enum() -> None:
    """Segmenter types map onto the question_regions DB check constraint."""
    assert _region_type("answer_text") == "answer_text"
    assert _region_type("diagram") == "diagram"
    assert _region_type("mixed") == "mixed"
    # Segmenter's 'unknown' has no DB row type -> 'blank' (the closest allowed).
    assert _region_type("unknown") == "blank"
    # Unknown/garbage values are never allowed to crash the insert.
    assert _region_type(None) == "answer_text"
    assert _region_type("MARGIN") in {"answer_text", "blank", "diagram", "mixed"}


def test_persist_perception_failure_is_swallowed() -> None:
    """Evidence persistence must never raise into the worker's completion path."""
    from answer_eval.jobs import PostgresJobStore
    from answer_eval.jobs.perception_persist import persist_perception

    class _DudStore(PostgresJobStore):
        def __init__(self) -> None:  # noqa: D107 - bypass real connection
            self._pool = None  # type: ignore[assignment]

        def run_coro(self, coro):  # type: ignore[override]
            import asyncio

            coro.close()  # real bridge would submit it to the loop; here discard
            raise RuntimeError("no loop")

    store = _DudStore()
    result = persist_perception(
        "00000000-0000-0000-0000-000000000000",
        {"page_records": [{"page_number": 1}], "region_records": []},
        storage=None,  # type: ignore[arg-type]
        run_coro=store.run_coro,
        pool=None,  # type: ignore[arg-type]
    )
    assert result is None  # failure is logged, never propagated