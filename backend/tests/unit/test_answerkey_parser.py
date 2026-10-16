"""Regression tests for AnswerKeyParserAgent (live-parser async contract).

Root cause of the production "Parser crashed; see server logs" bug:
`infer_structured` is `async` on every real InferenceProvider, but the parser
used to call it without `await`, yielding a coroutine object that crashed with
AttributeError on `.model_id`. These tests drive the REAL agent against an
async scripted provider — the exact path no earlier test covered.
"""

from __future__ import annotations

import asyncio

from answer_eval.answerkey.converters import convert_source
from answer_eval.answerkey.parser import AnswerKeyParserAgent, _default_fixture
from answer_eval.answerkey.schemas import ANSWER_KEY_SCHEMA_VERSION, ParsedAnswerKey
from answer_eval.inference.types import InferenceResponse


class AsyncScriptedProvider:
    """Mimics OllamaProvider's async surface: async initialize + infer_structured."""

    def __init__(self, data: dict) -> None:
        self.data = data
        self.initialize_calls = 0
        self.parse_calls = 0

    async def initialize(self, model, config, hardware=None) -> None:
        self.initialize_calls += 1

    async def infer_structured(self, request, schema, max_retries: int = 2):
        self.parse_calls += 1
        return InferenceResponse(
            request_id=request.request_id,
            provider="fake-async",
            model_id="fake-4b",
            text="structured",
            structured_data=self.data,
        )


def _pdf_bytes(text: str) -> bytes:
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_parse_awaits_async_provider_and_returns_validated_key() -> None:
    payload = _default_fixture().model_dump(mode="json")
    provider = AsyncScriptedProvider(payload)
    agent = AnswerKeyParserAgent(provider)
    document = convert_source("key.pdf", _pdf_bytes("Q1. Define TCP.\nAnswer: protocol"))

    parsed = asyncio.run(agent.parse(document))

    assert provider.parse_calls == 1
    assert isinstance(parsed, ParsedAnswerKey)
    # .model_id access proves we got a real InferenceResponse, not a coroutine.
    assert agent.last_model_id == "fake-4b"
    assert parsed.schema_version == ANSWER_KEY_SCHEMA_VERSION
    assert parsed.question_count == len(parsed.questions)


def test_parse_wraps_schema_validation_failure_in_value_error() -> None:
    provider = AsyncScriptedProvider({"unexpected": True})  # missing required `questions`
    agent = AnswerKeyParserAgent(provider)
    document = convert_source("key.pdf", _pdf_bytes("fixture"))

    try:
        asyncio.run(agent.parse(document))
    except ValueError as exc:
        assert "schema validation" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid parser payload")


# ---------------------------------------------------------------------------
# Batched parsing (real failure: 14-page scanned key = ~59k image tokens vs a
# 16k context -> Ollama HTTP 400 "request exceeds the available context size")
# ---------------------------------------------------------------------------


def _multipage_pdf_bytes() -> bytes:
    import fitz

    doc = fitz.open()
    for number in range(1, 8):  # 7 pages -> 3 overlapping batches at size 3
        doc.new_page().insert_text((72, 72), f"Q{number}. Define topic {number}.")
    data = doc.tobytes()
    doc.close()
    return data


def _numbered_payload(numbers: list[int]) -> dict:
    base = _default_fixture().model_dump(mode="json")
    questions = []
    for number in numbers:
        question = dict(base["questions"][0])
        question["question_number"] = number
        question["question_text"] = f"Define topic {number}."
        questions.append(question)
    base["questions"] = questions
    base["question_count"] = len(questions)
    return base


class NumberedBatchProvider:
    """Returns the question numbers each request's prompt page-span covers."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def initialize(self, model, config, hardware=None) -> None: ...

    async def infer_structured(self, request, schema, max_retries: int = 2):
        import json
        import re

        self.prompts.append(request.prompt)
        span = re.search(r"pages (\d+)-(\d+)", request.prompt)
        if span is None:
            data = _default_fixture().model_dump(mode="json")
            return InferenceResponse(
                request_id=request.request_id,
                provider="fake-async",
                model_id="fake-4b",
                text="structured",
                structured_data=data,
            )
        numbers = list(range(int(span.group(1)), int(span.group(2)) + 1))
        return InferenceResponse(
            request_id=request.request_id,
            provider="fake-async",
            model_id="fake-4b",
            text="structured",
            structured_data=json.loads(json.dumps(_numbered_payload(numbers))),
        )


def test_multipage_key_parses_in_batches_and_merges() -> None:
    provider = NumberedBatchProvider()
    agent = AnswerKeyParserAgent(provider)
    document = convert_source("key.pdf", _multipage_pdf_bytes())

    parsed = asyncio.run(agent.parse(document))

    # 7 pages at batch size 2 with 1-page overlap -> windows 1-2 .. 6-7.
    assert len(provider.prompts) == 6
    assert "pages 1-2" in provider.prompts[0]
    assert "pages 6-7" in provider.prompts[-1]
    # Overlap duplicates merge by question number -> exactly 7 questions.
    assert parsed.question_count == 7
    assert [q.question_number for q in parsed.questions] == [1, 2, 3, 4, 5, 6, 7]
    assert parsed.questions[0].question_text == "Define topic 1."


def test_single_page_key_uses_single_request() -> None:
    provider = NumberedBatchProvider()
    agent = AnswerKeyParserAgent(provider)
    document = convert_source("key.pdf", _pdf_bytes("Q1. Define TCP."))

    parsed = asyncio.run(agent.parse(document))

    assert len(provider.prompts) == 1
    assert "pages 1-1" not in provider.prompts[0]  # original whole-document template
    assert parsed.question_count >= 1


def test_batch_survives_one_failing_batch() -> None:
    class FlakyBatchProvider(NumberedBatchProvider):
        async def infer_structured(self, request, schema, max_retries: int = 2):
            # Skip two consecutive windows (3-4, 4-5) so Q4 has no complete parse.
            if "pages 3-4" in request.prompt or "pages 4-5" in request.prompt:
                raise RuntimeError("inference offline for this batch")
            return await super().infer_structured(request, schema, max_retries)

    provider = FlakyBatchProvider()
    agent = AnswerKeyParserAgent(provider)
    document = convert_source("key.pdf", _multipage_pdf_bytes())

    parsed = asyncio.run(agent.parse(document))

    # The remaining windows still parsed; the gap is reported, not fatal.
    assert [q.question_number for q in parsed.questions] == [1, 2, 3, 5, 6, 7]


# ---------------------------------------------------------------------------
# Tolerant JSON extraction (real log failures: schema-echo concatenation ->
# "Extra data"; truncated output -> "Unterminated string")
# ---------------------------------------------------------------------------


def test_extract_json_handles_schema_echo_concatenation() -> None:
    import json

    payload = json.dumps(_numbered_payload([1, 2]))
    schema_echo = json.dumps(
        {
            "$defs": {"ParsedQuestion": {"type": "object"}},
            "properties": {"questions": {"type": "array"}},
        }
    )
    parsed = AnswerKeyParserAgent._extract_json(schema_echo + "\n" + payload)
    assert parsed["question_count"] == 2
    assert [q["question_number"] for q in parsed["questions"]] == [1, 2]


def test_extract_json_salvages_complete_questions_from_truncated_output() -> None:
    import json

    payload = json.dumps(_numbered_payload([1, 2, 3]))
    truncated = payload[: -90]  # cut inside the last question object
    parsed = AnswerKeyParserAgent._extract_json(truncated)
    assert parsed["question_count"] == 2  # Q3 was incomplete -> dropped
    assert [q["question_number"] for q in parsed["questions"]] == [1, 2]


def test_extract_json_still_rejects_empty_garbage() -> None:
    try:
        AnswerKeyParserAgent._extract_json("no json here at all")
    except ValueError as exc:
        assert "no JSON" in str(exc)
    else:
        raise AssertionError("expected ValueError for garbage output")

