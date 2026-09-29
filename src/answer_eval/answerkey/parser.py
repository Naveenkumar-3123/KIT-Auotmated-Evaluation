"""AnswerKeyParserAgent — turns the converted source document into
`answer-key-v1` structured JSON using the configured VLM provider.

Contract (per architecture §12): extract what the teacher supplied WITHOUT
inventing rubric information. Missing marks/concepts stay empty; doubts are
reported as warnings so the teacher review step resolves them.
"""

from __future__ import annotations

import asyncio
import logging
import os

from pydantic import ValidationError

from answer_eval.answerkey.converters import SourceDocument
from answer_eval.answerkey.schemas import ANSWER_KEY_SCHEMA_VERSION, ParsedAnswerKey
from answer_eval.inference.provider import InferenceProvider
from answer_eval.inference.types import ImageInput, InferenceRequest, ReasoningMode

logger = logging.getLogger(__name__)

PARSER_PROMPT_VERSION = "answer-key-parser-v1"

SYSTEM_PROMPT = """You convert teacher answer keys into structured JSON.
Rules:
- Extract ONLY what is present in the document. Never invent marks, concepts, keywords or diagrams.
- question_count MUST equal the number of real questions you extracted.
- If a mark value is missing, use 0 for maximum_marks and add a parser warning.
- Split expected answers into expected_concepts only when the key clearly allocates separate points;
  otherwise leave expected_concepts empty.
- keywords are important technical terms from the expected answer; mandatory_terms only when the key
  explicitly demands them.
- For numerical/math questions allocate math_rubric steps ONLY if the key shows step-wise marking.
- diagram_hints: when a question's answer includes a figure/diagram in this document, report its page
  number and, if you can locate it, a normalized bbox [x_min,y_min,x_max,y_max] on that page.
- Respond with JSON matching the provided schema exactly."""

USER_TEMPLATE = """Convert this answer key into {schema_name} JSON.

Document text:
---
{document_text}
---

Return only the JSON object."""

BATCH_USER_TEMPLATE = """Convert the questions on these answer-key pages into {schema_name} JSON.

These are pages {page_span} of a longer answer-key document; one question may
continue from an earlier page. Extract ONLY the questions that start or continue
on these pages, exactly as the document states them.

Document text for these pages:
---
{document_text}
---

Return only the JSON object."""

# Pages per inference request. A page image costs ~4k vision tokens, so a
# 14-page key sent whole was ~59k tokens against a 16k context -> HTTP 400.
# 2 pages keeps model OUTPUT short too: dense batches were truncated mid-JSON
# (stop_reason=length -> "Unterminated string").
DEFAULT_BATCH_SIZE = 2
# One-page overlap between consecutive batches so questions spanning a batch
# boundary are fully seen by at least one request; duplicates merge by number.
BATCH_OVERLAP_PAGES = 1
# Concurrent in-flight batches. The VLM (local Ollama on one GPU) effectively
# serializes requests, so each in-flight batch queues behind the others and its
# wall-clock time grows with concurrency — too high and batches die at the
# request timeout, losing whole sections. 2 overlaps enough to hide gaps
# without starving; tune with ANSWER_KEY_BATCH_CONCURRENCY.
DEFAULT_BATCH_CONCURRENCY = max(1, int(os.getenv("ANSWER_KEY_BATCH_CONCURRENCY", "2")))


def _build_batches(pages: list, batch_size: int, overlap: int = BATCH_OVERLAP_PAGES) -> list[list]:
    """Split pages into overlapping windows of at most ``batch_size`` pages."""
    if len(pages) <= batch_size:
        return [pages]
    step = max(1, batch_size - overlap)
    batches: list[list] = []
    index = 0
    while index < len(pages):
        batch = pages[index : index + batch_size]
        batches.append(batch)
        if index + batch_size >= len(pages):
            break
        index += step
    return batches


def _merge_question(a, b):
    """Field-wise merge of two parses of the same question; non-empty wins."""
    merged: dict = {}
    dump_a, dump_b = a.model_dump(), b.model_dump()
    for key, value_a in dump_a.items():
        value_b = dump_b.get(key)
        if isinstance(value_a, (str, list)):
            merged[key] = value_a or value_b
        elif isinstance(value_a, (int, float)) and not isinstance(value_a, bool):
            merged[key] = value_a if value_a else value_b
        else:
            merged[key] = value_a if value_a is not None else value_b
    return type(a).model_validate(merged)


def _merge_parsed_keys(keys: list):
    """Union of batch parses; questions deduplicate by question number."""
    title = next((k.title for k in keys if k.title and k.title != "Answer key"), "Answer key")
    by_number: dict = {}
    warnings: list[str] = []
    by_number: dict = {}
    for key in keys:
        warnings.extend(key.parser_warnings)
        for question in key.questions:
            existing = by_number.get(question.question_number)
            by_number[question.question_number] = (
                _merge_question(existing, question) if existing is not None else question
            )
    questions = [by_number[number] for number in sorted(by_number)]
    return ParsedAnswerKey(
        schema_version=ANSWER_KEY_SCHEMA_VERSION,
        title=title,
        question_count=len(questions),
        questions=questions,
        parser_warnings=sorted(set(warnings)),
    )


def _scan_top_level_objects(text: str) -> list[tuple[int, int, bool]]:
    """(start, end, complete) for each top-level ``{...}`` object in *text*.

    ``complete`` is False when the object never closes (truncated output).
    String literals (with escapes) are respected so braces inside quotes do
    not affect depth.
    """
    spans: list[tuple[int, int, bool]] = []
    depth = 0
    in_string = False
    escaped = False
    start: int | None = None
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, i, True))
                start = None
    if start is not None:
        spans.append((start, len(text) - 1, False))
    return spans


class AnswerKeyParserAgent:
    def __init__(
        self,
        provider: InferenceProvider,
        *,
        prompt_version: str = PARSER_PROMPT_VERSION,
        max_tokens: int | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._provider = provider
        self._prompt_version = prompt_version
        # Typical batch JSON is 500-2,500 tokens; 4,096 covers dense batches
        # while halving worst-case generation time (8,192-token runaway outputs
        # were the slowest batches by far). Truncated tails are recovered by
        # the per-question salvage parser.
        self._max_tokens = max_tokens or int(os.getenv("ANSWER_KEY_MAX_TOKENS", "4096"))
        self._batch_size = max(1, batch_size)
        self.last_model_id: str | None = None

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    async def parse(self, document: SourceDocument, *, on_progress=None) -> ParsedAnswerKey:
        """Parse the answer key, batched so page images fit the VLM context.

        A page image costs several thousand vision tokens; whole-document
        requests for multi-page scanned keys exceed the model context (real
        failure: 14 pages = ~59k tokens vs a 16k window -> HTTP 400). Pages are
        parsed in overlapping batches and the results merged by question
        number. Single-batch documents take the original single-request path.

        ``on_progress(done, total)`` fires as each batch finishes so callers can
        surface parsing progress for long documents.
        """
        batches = _build_batches(document.pages, self._batch_size)

        def report(done: int) -> None:
            if on_progress is not None:
                try:
                    on_progress(done, len(batches))
                except Exception:  # noqa: BLE001 - progress must never break parsing
                    logger.debug("answer-key progress callback failed", exc_info=True)

        if len(batches) == 1:
            result = await self._parse_request(
                USER_TEMPLATE.format(schema_name="answer-key-v1", document_text=document.full_text()),
                self._images_for(batches[0]),
            )
            report(1)
            return result

        semaphore = asyncio.Semaphore(DEFAULT_BATCH_CONCURRENCY)
        done = 0

        async def run_batch(batch: list) -> ParsedAnswerKey | None:
            nonlocal done
            span = f"{batch[0].page_number}-{batch[-1].page_number}"
            text = "\n\n".join(
                f"[PAGE {page.page_number}]\n{page.text.strip() or '(no extractable text)'}" for page in batch
            )
            async with semaphore:
                try:
                    parsed = await self._parse_request(
                        BATCH_USER_TEMPLATE.format(
                            schema_name="answer-key-v1", page_span=span, document_text=text
                        ),
                        self._images_for(batch),
                    )
                except Exception as exc:  # noqa: BLE001 - one bad batch must not kill the key
                    logger.warning("Answer-key batch %s failed to parse: %s", span, exc)
                    return None
            done += 1
            report(done)
            return parsed

        results = [r for r in await asyncio.gather(*(run_batch(b) for b in batches)) if r is not None]
        if not results:
            raise ValueError("All answer-key page batches failed to parse")
        merged = _merge_parsed_keys(results)
        return merged.validated()

    def _images_for(self, pages: list) -> list[ImageInput]:
        return [
            ImageInput(image_bytes=page.image_bytes, mime_type="image/png")
            for page in pages
            if page.image_bytes
        ]

    async def _parse_request(self, prompt: str, images: list[ImageInput]) -> ParsedAnswerKey:
        request = InferenceRequest(
            request_id=f"answer-key-parse-{abs(hash(prompt)) % 10_000_000}",
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            images=images,
            max_tokens=self._max_tokens,
            temperature=0.0,
            reasoning_mode=ReasoningMode.DIRECT,
        )
        # `infer_structured` is async on every InferenceProvider — it MUST be
        # awaited, otherwise we get a coroutine object instead of a response
        # and crash with AttributeError on `.model_id`.
        # max_retries=1: each provider "repair retry" is a full extra vision
        # inference (40-130s). One repair is enough; after that, our local
        # salvage below recovers truncated/concatenated output for free.
        try:
            response = await self._provider.infer_structured(
                request, ParsedAnswerKey.model_json_schema(), max_retries=1
            )
        except Exception as exc:
            raw = ""
            details = getattr(exc, "details", None) or {}
            if isinstance(details, dict):
                raw = details.get("raw_response") or ""
            if not raw:
                raise
            logger.warning(
                "Answer-key batch output failed provider validation — recovering with local salvage",
                request_id=request.request_id,
                raw_length=len(raw),
            )
            payload = self._extract_json(raw)
            parsed = ParsedAnswerKey.model_validate(payload)
            parsed.schema_version = ANSWER_KEY_SCHEMA_VERSION
            return parsed.validated()
        self.last_model_id = response.model_id
        payload = response.structured_data if response.structured_data else self._extract_json(response.text or "")
        try:
            parsed = ParsedAnswerKey.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"Parser output failed schema validation: {exc}") from exc
        parsed.schema_version = ANSWER_KEY_SCHEMA_VERSION
        return parsed.validated()

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Parse model output tolerantly.

        Handles, in order: fenced/bare JSON, concatenated objects (the model
        sometimes echoes the JSON schema before the payload -> "Extra data"),
        and truncated output (stop_reason=length cutting mid-string ->
        "Unterminated string") by salvaging every complete question object.
        """
        import json

        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]

        spans = _scan_top_level_objects(cleaned)

        def _usable(parsed: object) -> bool:
            return isinstance(parsed, dict) and isinstance(parsed.get("questions"), list)

        # 1. Whole-text parse (fast path).
        try:
            parsed = json.loads(cleaned)
            if _usable(parsed):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

        # 2. Complete top-level objects in order — picks the payload when the
        # model concatenated a schema echo with the real data.
        for start, end, complete in spans:
            if not complete:
                continue
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                continue
            if _usable(parsed):
                return parsed

        # 3. Truncated output: salvage complete question objects from the
        # questions array, drop the incomplete tail.
        salvaged = AnswerKeyParserAgent._salvage_questions(cleaned, spans)
        if salvaged is not None:
            return salvaged
        raise ValueError("Parser returned no JSON object")

    @staticmethod
    def _salvage_questions(text: str, spans: list[tuple[int, int, bool]]) -> dict | None:
        """Best-effort recovery of complete question objects from truncated JSON."""
        import json

        # Only truncated (never-closed) spans can be salvaged; complete spans
        # that simply lack a questions list are rejected upstream.
        incomplete = [text[s : e + 1] for s, e, complete in spans if not complete]
        if not incomplete:
            return None
        for fragment in reversed(incomplete):
            marker = fragment.find('"questions"')
            if marker == -1:
                continue
            array_start = fragment.find("[", marker)
            if array_start == -1:
                continue
            questions: list[dict] = []
            depth = 0
            in_string = False
            escaped = False
            obj_start: int | None = None
            for i in range(array_start + 1, len(fragment)):
                ch = fragment[i]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    if depth == 0:
                        obj_start = i
                    depth += 1
                elif ch == "[":
                    if depth == 0:
                        break  # a sibling array, not part of this question object
                    depth += 1
                elif ch == "}":
                    if depth == 0:
                        break
                    depth -= 1
                    if depth == 0 and obj_start is not None:
                        candidate = fragment[obj_start : i + 1]
                        try:
                            parsed_question = json.loads(candidate)
                        except (json.JSONDecodeError, ValueError):
                            break  # truncated tail — keep only what completed
                        if isinstance(parsed_question, dict) and "question_number" in parsed_question:
                            questions.append(parsed_question)
                        else:
                            break
                        obj_start = None
                elif ch == "]":
                    if depth == 0:
                        break  # end of the questions array
                    depth -= 1
            if questions:
                return {
                    "schema_version": "answer-key-v1",
                    "title": "Answer key",
                    "question_count": len(questions),
                    "questions": questions,
                }
        return None


class FakeAnswerKeyParserAgent:
    """Deterministic stand-in for tests/plumbing without a live VLM."""

    def __init__(self, result: ParsedAnswerKey | None = None) -> None:
        self.result = result or _default_fixture()
        self.calls = 0
        self.last_model_id = "fake-parser"
        self.prompt_version = "fake-v1"

    async def parse(self, document: SourceDocument) -> ParsedAnswerKey:
        self.calls += 1
        return self.result


def _default_fixture() -> ParsedAnswerKey:
    from answer_eval.answerkey.schemas import ParsedConcept, ParsedDiagramHint, ParsedQuestion

    return ParsedAnswerKey(
        title="Fixture key",
        question_count=2,
        questions=[
            ParsedQuestion(
                question_number=1,
                question_text="Explain flow control.",
                maximum_marks=4,
                answer_type="explain",
                expected_answer_text="Receiver regulates sender via acknowledgements and windowing.",
                expected_concepts=[ParsedConcept(concept_code="C1", description="Acknowledgements", maximum_marks=2)],
                keywords=["acknowledgement", "window"],
                mandatory_terms=["acknowledgement"],
            ),
            ParsedQuestion(
                question_number=2,
                question_text="Draw the three-way handshake.",
                maximum_marks=6,
                answer_type="diagram",
                expected_answer_text="SYN, SYN-ACK, ACK exchange between client and server.",
                diagram_hints=[ParsedDiagramHint(page=1, ordinal=1, type_label="TCP handshake", uncertain=True)],
                parser_uncertainties=["diagram location uncertain"],
            ),
        ],
        parser_warnings=["Fixture data — replace with a real model run"],
    )
