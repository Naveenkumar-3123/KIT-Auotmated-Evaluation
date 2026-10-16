"""LangGraph workflow assembly (Module 17).

Controlled state machine — NOT an autonomous agent swarm:

    validate_submission -> process_pdf -> preprocess_segment -> ocr_diagram
      -> reconstruct -> grade_answers -> [human_review_gate] -> finalize

Checkpoints persist after every expensive stage. The default checkpointer is
in-memory (development only); set WORKFLOW_CHECKPOINT_DB to a SQLite path for
durable local checkpoints, or DATABASE_URL to a PostgreSQL DSN for production
(requires the `langgraph-checkpoint-postgres` package).
"""

import os
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from answer_eval.core.logging import get_logger
from answer_eval.inference.provider import InferenceProvider
from answer_eval.workflow import nodes, routing

logger = get_logger("workflow.graph")


def create_checkpointer(checkpointer: BaseCheckpointSaver | None = None) -> BaseCheckpointSaver:
    """Production-compatible checkpoint factory.

    Priority: explicit argument > PostgreSQL (DATABASE_URL) > SQLite
    (WORKFLOW_CHECKPOINT_DB) > in-memory development fallback.
    """
    if checkpointer is not None:
        return checkpointer

    # Prefer DIRECT_URL (session pooling) — the checkpointer uses prepared
    # statements, which pgbouncer transaction pooling (the pooled DATABASE_URL)
    # silently breaks with "prepared statement does not exist".
    database_url = os.getenv("DIRECT_URL", "") or os.getenv("DATABASE_URL", "")
    if database_url.startswith(("postgres://", "postgresql://")):
        try:
            import psycopg
            from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore

            logger.info("Using PostgreSQL LangGraph checkpointer")
            conn = psycopg.connect(database_url, autocommit=True, prepare_threshold=0, connect_timeout=5)
            try:
                saver = PostgresSaver(conn)  # type: ignore[call-arg]
                saver.setup()  # create checkpoint tables on first use
                return saver  # type: ignore[return-value]
            except Exception as exc:
                logger.warning(
                    "PostgresSaver.setup() failed; falling back to a local checkpointer",
                    error=str(exc),
                )
                conn.close()
        except ImportError:
            logger.warning(
                "DATABASE_URL is set but 'langgraph-checkpoint-postgres' is not installed; "
                "falling back to SQLite/in-memory checkpoints."
            )
        except Exception as exc:
            logger.warning(
                "PostgreSQL checkpointer connection failed (%s); falling back to SQLite/in-memory checkpoints.",
                exc,
            )

    sqlite_path = os.getenv("WORKFLOW_CHECKPOINT_DB", "")
    if sqlite_path:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = sqlite3.connect(sqlite_path, check_same_thread=False)
        logger.info("Using SQLite LangGraph checkpointer", path=sqlite_path)
        return SqliteSaver(conn)

    logger.debug("Using in-memory LangGraph checkpointer (development fallback)")
    return InMemorySaver()


def build_evaluation_graph(
    provider: InferenceProvider,
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """Compile the full evaluation workflow graph."""
    from answer_eval.workflow.state import EvaluationWorkflowState

    builder = StateGraph(EvaluationWorkflowState)

    builder.add_node("validate_submission", nodes.validate_submission)
    builder.add_node("process_pdf", nodes.process_pdf)
    builder.add_node("preprocess_segment", nodes.preprocess_and_segment)
    builder.add_node("map_questions", lambda state: nodes.map_questions(state, provider))
    builder.add_node("ocr_diagram", lambda state: nodes.run_ocr_diagram(state, provider))
    builder.add_node("reconstruct", nodes.reconstruct_answers)
    builder.add_node("grade_answers", lambda state: nodes.grade_answers(state, provider))
    builder.add_node("human_review_gate", nodes.human_review_gate)
    builder.add_node("finalize", nodes.finalize)

    builder.set_entry_point("validate_submission")
    builder.add_conditional_edges(
        "validate_submission",
        routing.route_after_validation,
        {"process_pdf": "process_pdf", "end_failed": END},
    )
    builder.add_edge("process_pdf", "preprocess_segment")
    builder.add_conditional_edges(
        "preprocess_segment",
        routing.route_after_perception,
        {"continue": "map_questions", "end_retry": END, "end_failed": END},
    )
    builder.add_conditional_edges(
        "map_questions",
        routing.route_after_perception,
        {"continue": "ocr_diagram", "end_retry": END, "end_failed": END},
    )
    builder.add_conditional_edges(
        "ocr_diagram",
        routing.route_after_perception,
        {"continue": "reconstruct", "end_retry": END, "end_failed": END},
    )
    builder.add_edge("reconstruct", "grade_answers")
    builder.add_conditional_edges(
        "grade_answers",
        routing.route_after_grading,
        {"human_review": "human_review_gate", "finalize": "finalize", "end_retry": END, "end_failed": END},
    )
    # interrupt() inside human_review_gate pauses execution transparently;
    # after Command(resume=...) the node completes and flows to finalize.
    builder.add_edge("human_review_gate", "finalize")
    builder.add_edge("finalize", END)

    app = builder.compile(checkpointer=create_checkpointer(checkpointer))
    logger.info("Evaluation workflow graph compiled")
    return app


def initial_state(
    job_id: str,
    submission_id: str,
    pdf_path: str,
    rubrics: dict[str, Any],
    teacher_rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "submission_id": submission_id,
        "pdf_path": pdf_path,
        "rubrics": rubrics,
        "teacher_rules": teacher_rules or {},
        "status": "running",
        "current_stage": "queued",
        "progress_total": nodes.TOTAL_STAGES,
        "progress_completed": 0,
        "errors": [],
        "rubrics_version": "rubric-v1",
    }
