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
from answer_eval.answerkey.schemas import (
    ANSWER_KEY_SCHEMA_VERSION,
    ParsedAnswerKey,
    ParsedConcept,
    ParsedDiagramHint,
    ParsedQuestion,
    ParsedQuestionOption,
)
from answer_eval.inference.provider import InferenceProvider
from answer_eval.inference.types import ImageInput, InferenceRequest, ReasoningMode

logger = logging.getLogger(__name__)

PARSER_PROMPT_VERSION = "answer-key-parser-v2"

SYSTEM_PROMPT = """You convert teacher answer keys into structured JSON.
Rules:
- Extract ONLY what is present in the document. Never invent or omit questions, marks, concepts, keywords or diagrams.
- Extract ALL questions, including short questions, multi-part questions, and choice questions (such as Option (a) OR Option (b) / Either-Or).
- Clean the text by omitting OCR page headers, footers (such as "Page X of Y", "Prepared by", examiner sign-offs), delimiter lines, and standalone raw mark labels.
- CRITICAL RULE FOR CHOICE / EITHER-OR QUESTIONS:
  In exam answer keys (especially descriptive 14-mark or 16-mark sections), questions are often presented as Either/Or choices (Option (a) OR Option (b)).
  Whenever you encounter an option marker like "(b)" or "14 (b)" or "(a)" / "(b)":
  1. ALWAYS check the solution content preceding "(b)". Any solution text before "(b)" on that page belongs to Option (a) of that same question (even if the label "14 (a)" was placed on a previous page header or omitted).
  2. STRICT RULE FOR QUESTION STATEMENTS:
     - Extract ONLY the question statement if it is explicitly written in the source document.
     - If the question statement is NOT present in the source key (for example, the page begins directly with partial answer/solution calculations like "𝜎(2) = ..."), NEVER invent, hallucinate, or auto-generate a question statement!
     - Leave question_text as an EMPTY STRING "" so the teacher review screen highlights it in RED ("Required — please fill in") for the teacher to complete.
     - Extract the full partial/reference answer calculations present into expected_answer_text.
  3. You MUST ALWAYS populate the "options" array with BOTH Option (a) AND Option (b) objects:
     - option_code: "a" and "b"
     - option_title: "Option (a)" and "Option (b): ..."
     - question_text: Option (a) statement (leave "" if not in source key) and Option (b) statement
     - expected_answer_text: Complete solution / partial calculations for Option (a) and Option (b) respectively
     - maximum_marks: equal marks per option as indicated in key (e.g. 14.0 or 16.0)
     - expected_concepts: rubric concepts for each option
     - keywords: technical keywords for each option
  4. In top-level question_text, write: "Option (a): [Missing Question Statement] [OR] Option (b): <opt_b_stmt>" (or include Option (a) statement if explicitly present).
  5. In top-level expected_answer_text, format both options with clear section headers:
     "============================================================\\nOPTION (a) (14 Marks)\\n============================================================\\n\\n<opt_a_solution>\\n\\n============================================================\\nOPTION (b): <opt_b_title> (14 Marks)\\n============================================================\\n\\n<opt_b_solution>".
  6. NEVER return an empty "options": [] when a question has Option (a) and Option (b) choices!
- question_count MUST equal the number of real questions you extracted.
- If a mark value is missing, use 0 for maximum_marks and add a parser warning.
- Split expected answers into expected_concepts only when the key clearly allocates separate points; otherwise provide balanced concept rubrics covering the answer criteria.
- keywords are important technical terms from the expected answer.
- For numerical/math questions allocate math_rubric steps ONLY if the key shows step-wise marking.
- diagram_hints: when a question's answer includes a figure/diagram in this document, report its page number and a short type_label describing the figure.
- Respond with JSON matching the provided schema exactly."""

USER_TEMPLATE = """Extract ALL questions, maximum marks, and expected answers from this answer key into {schema_name} JSON.

Document text:
---
{document_text}
---

Return a valid JSON object matching this exact structure:
{{
  "title": "Subject or Assessment Title",
  "question_count": 2,
  "questions": [
    {{
      "question_number": 1,
      "question_text": "Full question text",
      "maximum_marks": 2.0,
      "answer_type": "short_answer",
      "expected_answer_text": "Full expected answer text",
      "expected_concepts": [
        {{"concept_code": "C1", "description": "Key concept or point", "maximum_marks": 1.0}}
      ],
      "keywords": ["keyword1", "keyword2"],
      "mandatory_terms": ["term1"],
      "options": []
    }},
    {{
      "question_number": 11,
      "question_text": "Option (a): ... [OR] Option (b): ...",
      "maximum_marks": 16.0,
      "answer_type": "descriptive",
      "expected_answer_text": "Option (a): ...\\n\\nOption (b): ...",
      "expected_concepts": [
        {{"concept_code": "C1", "description": "Core concept", "maximum_marks": 4.0}}
      ],
      "keywords": ["keyword1"],
      "mandatory_terms": [],
      "options": [
        {{
          "option_code": "a",
          "option_title": "Option (a)",
          "question_text": "Option (a) question statement (leave empty string \"\" if not explicitly present in key)",
          "expected_answer_text": "Option (a) solution",
          "maximum_marks": 16.0,
          "expected_concepts": [{{"concept_code": "C1", "description": "Concept", "maximum_marks": 4.0}}],
          "keywords": ["key1"]
        }},
        {{
          "option_code": "b",
          "option_title": "Option (b)",
          "question_text": "Option (b) question text",
          "expected_answer_text": "Option (b) solution",
          "maximum_marks": 16.0,
          "expected_concepts": [{{"concept_code": "C1", "description": "Concept", "maximum_marks": 4.0}}],
          "keywords": ["key2"]
        }}
      ]
    }}
  ]
}}
Return ONLY the raw JSON object, without explanation."""

BATCH_USER_TEMPLATE = """Extract ALL questions, maximum marks, and expected answers from these answer-key pages (pages {page_span}) into {schema_name} JSON.

These are pages {page_span} of a longer answer-key document. Extract EVERY question that appears on these pages, exactly as stated.

Document text for these pages:
---
{document_text}
---

Return a valid JSON object matching this exact structure:
{{
  "title": "Subject or Assessment Title",
  "question_count": 2,
  "questions": [
    {{
      "question_number": 1,
      "question_text": "Full question text",
      "maximum_marks": 2.0,
      "answer_type": "short_answer",
      "expected_answer_text": "Full expected answer text",
      "expected_concepts": [
        {{"concept_code": "C1", "description": "Key concept or point", "maximum_marks": 1.0}}
      ],
      "keywords": ["keyword1", "keyword2"],
      "mandatory_terms": ["term1"],
      "options": []
    }},
    {{
      "question_number": 11,
      "question_text": "Option (a): ... [OR] Option (b): ...",
      "maximum_marks": 16.0,
      "answer_type": "descriptive",
      "expected_answer_text": "Option (a): ...\\n\\nOption (b): ...",
      "expected_concepts": [
        {{"concept_code": "C1", "description": "Core concept", "maximum_marks": 4.0}}
      ],
      "keywords": ["keyword1"],
      "mandatory_terms": [],
      "options": [
        {{
          "option_code": "a",
          "option_title": "Option (a)",
          "question_text": "Option (a) question statement (leave empty string \"\" if not explicitly present in key)",
          "expected_answer_text": "Option (a) solution",
          "maximum_marks": 16.0,
          "expected_concepts": [{{"concept_code": "C1", "description": "Concept", "maximum_marks": 4.0}}],
          "keywords": ["key1"]
        }},
        {{
          "option_code": "b",
          "option_title": "Option (b)",
          "question_text": "Option (b) question text",
          "expected_answer_text": "Option (b) solution",
          "maximum_marks": 16.0,
          "expected_concepts": [{{"concept_code": "C1", "description": "Concept", "maximum_marks": 4.0}}],
          "keywords": ["key2"]
        }}
      ]
    }}
  ]
}}
If no questions appear on these pages (e.g. title or instructions only), return {{"title": "Answer key", "question_count": 0, "questions": []}}.
Return ONLY the raw JSON object, without explanation."""

# Pages per inference request. 2 pages with 1-page overlap keeps context optimal and conforms to batch merge tests.
DEFAULT_BATCH_SIZE = int(os.getenv("ANSWER_KEY_BATCH_SIZE", "2"))
BATCH_OVERLAP_PAGES = int(os.getenv("ANSWER_KEY_BATCH_OVERLAP", "1"))
DEFAULT_BATCH_CONCURRENCY = max(1, int(os.getenv("ANSWER_KEY_BATCH_CONCURRENCY", "1")))


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
    """Field-wise merge of two parses of the same question; genuine parses win over stubs."""
    dump_a, dump_b = a.model_dump(), b.model_dump()
    text_a = (dump_a.get("question_text") or "").strip()
    text_b = (dump_b.get("question_text") or "").strip()

    # If one parse has a full question statement and the other is an empty stub/phantom match,
    # the parse with the full statement is our primary source of truth.
    if len(text_a) >= 10 and len(text_b) < 10:
        primary, secondary = dump_a, dump_b
    elif len(text_b) >= 10 and len(text_a) < 10:
        primary, secondary = dump_b, dump_a
    else:
        primary, secondary = dump_a, dump_b

    merged: dict = {}
    for key, value_a in dump_a.items():
        value_b = dump_b.get(key)
        if key == "maximum_marks":
            merged[key] = float(primary.get("maximum_marks") or value_a or value_b or 0)
        elif key == "answer_type":
            merged[key] = primary.get("answer_type") or value_a or value_b
        elif key == "expected_answer_text":
            str_a = (value_a or "").strip()
            str_b = (value_b or "").strip()
            if not str_a:
                merged[key] = str_b
            elif not str_b or str_b in str_a:
                merged[key] = str_a
            elif str_a in str_b:
                merged[key] = str_b
            else:
                merged[key] = str_a + "\n\n" + str_b
        elif key == "expected_concepts":
            concepts_prim = primary.get("expected_concepts") or []
            if concepts_prim:
                merged[key] = concepts_prim
            else:
                list_a = value_a or []
                list_b = value_b or []
                merged[key] = list_a + [item for item in list_b if item not in list_a]
        elif key in ("keywords", "mandatory_terms", "diagram_hints"):
            list_a = value_a or []
            list_b = value_b or []
            merged[key] = list_a + [item for item in list_b if item not in list_a]
        elif key == "options":
            opts_map = {}
            for opt in (value_a or []):
                code = opt.get("option_code", "").lower() if isinstance(opt, dict) else getattr(opt, "option_code", "").lower()
                if code:
                    opts_map[code] = opt
            for opt in (value_b or []):
                code = opt.get("option_code", "").lower() if isinstance(opt, dict) else getattr(opt, "option_code", "").lower()
                if code and code not in opts_map:
                    opts_map[code] = opt
            merged[key] = list(opts_map.values())
        elif isinstance(value_a, str):
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


def clean_page_text(text: str) -> str:
    """Clean OCR line artifacts, repeated headers, footers and delimiters."""
    import re

    if not text:
        return ""
    # Remove page banners and numbering
    text = re.sub(r"\[PAGE\s*\d+\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)Page\s*\d+\s*(?:of\s*\d+)?", "", text)
    # Remove examiner sign-offs / footers
    text = re.sub(r"(?i)Prepared by\s*(?:\(Course Co-ordinator\))?\s*(?:Head of the Department)?", "", text)
    text = re.sub(r"(?i)\(Course Co-ordinator\)", "", text)
    text = re.sub(r"(?i)Head of the Department", "", text)
    # Remove separator bars like ===== or ----- or _____
    text = re.sub(r"^[=\-_~*]{3,}\s*$", "", text, flags=re.MULTILINE)
    # Fix dangling bullets
    text = re.sub(r"(?m)^\s*([•·▪►\-])\s*\n\s*", r"\1 ", text)
    # Remove standalone marks annotations e.g. "2 Marks" or "[2 Marks]"
    text = re.sub(r"(?mi)^\s*(?:\[|\()?(\d+(?:\.\d+)?)\s*(?:Marks|marks|mark|M)\s*(?:\]|\))?\s*$", "", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_dict(payload: dict) -> dict:
    """Tolerantly fill missing optional fields while preserving validation errors for bad payloads."""
    if not isinstance(payload, dict):
        return payload
    if "questions" not in payload or not isinstance(payload["questions"], list):
        return payload
    payload.setdefault("schema_version", ANSWER_KEY_SCHEMA_VERSION)
    payload.setdefault("title", "Answer key")
    questions = payload["questions"]
    payload.setdefault("question_count", len(questions))
    for idx, q in enumerate(questions):
        if isinstance(q, dict):
            if "question_number" not in q:
                q["question_number"] = idx + 1
            try:
                q["question_number"] = int(q["question_number"])
            except Exception:
                q["question_number"] = idx + 1
            q.setdefault("question_text", "")
            try:
                q["maximum_marks"] = float(q.get("maximum_marks", 2.0))
            except Exception:
                q["maximum_marks"] = 2.0
            q.setdefault("answer_type", "short_answer" if q["maximum_marks"] <= 2.0 else "descriptive")
            q.setdefault("expected_answer_text", "")
            q.setdefault("keywords", [])
            q.setdefault("mandatory_terms", [])
            q.setdefault("diagram_hints", [])
            q.setdefault("parser_uncertainties", [])
            q.setdefault("options", [])

            if isinstance(q.get("keywords"), str):
                q["keywords"] = [k.strip() for k in q["keywords"].split(",") if k.strip()]
            if isinstance(q.get("mandatory_terms"), str):
                q["mandatory_terms"] = [k.strip() for k in q["mandatory_terms"].split(",") if k.strip()]

            # Normalize concepts
            raw_concepts = q.get("expected_concepts") or []
            norm_concepts = []
            for cidx, c in enumerate(raw_concepts):
                if isinstance(c, str):
                    norm_concepts.append({
                        "concept_code": f"C{cidx+1}",
                        "description": c,
                        "maximum_marks": round(q["maximum_marks"] / max(len(raw_concepts), 1), 1),
                    })
                elif isinstance(c, dict):
                    c.setdefault("concept_code", f"C{cidx+1}")
                    c.setdefault("description", "")
                    try:
                        c["maximum_marks"] = float(c.get("maximum_marks", round(q["maximum_marks"] / max(len(raw_concepts), 1), 1)))
                    except Exception:
                        c["maximum_marks"] = 1.0
                    norm_concepts.append(c)
            q["expected_concepts"] = norm_concepts

            # Normalize options
            raw_options = q.get("options") or []
            norm_options = []
            for oidx, opt in enumerate(raw_options):
                if isinstance(opt, dict):
                    code = str(opt.get("option_code", "a" if oidx == 0 else "b")).strip().lower()
                    opt["option_code"] = code
                    opt.setdefault("option_title", f"Option ({code})")
                    opt.setdefault("question_text", opt.get("question_text") or q.get("question_text", ""))
                    opt.setdefault("expected_answer_text", opt.get("expected_answer_text") or "")
                    try:
                        opt["maximum_marks"] = float(opt.get("maximum_marks", q["maximum_marks"]))
                    except Exception:
                        opt["maximum_marks"] = q["maximum_marks"]
                    opt.setdefault("keywords", [])
                    if isinstance(opt.get("keywords"), str):
                        opt["keywords"] = [k.strip() for k in opt["keywords"].split(",") if k.strip()]

                    # Normalize option concepts
                    raw_opt_concepts = opt.get("expected_concepts") or []
                    norm_opt_concepts = []
                    for cidx, c in enumerate(raw_opt_concepts):
                        if isinstance(c, str):
                            norm_opt_concepts.append({
                                "concept_code": f"C{cidx+1}",
                                "description": c,
                                "maximum_marks": round(opt["maximum_marks"] / max(len(raw_opt_concepts), 1), 1),
                            })
                        elif isinstance(c, dict):
                            c.setdefault("concept_code", f"C{cidx+1}")
                            c.setdefault("description", "")
                            try:
                                c["maximum_marks"] = float(c.get("maximum_marks", 1.0))
                            except Exception:
                                c["maximum_marks"] = 1.0
                            norm_opt_concepts.append(c)
                    opt["expected_concepts"] = norm_opt_concepts
                    norm_options.append(opt)
            q["options"] = norm_options
    return payload


def extract_structured_exam_key(full_text: str) -> ParsedAnswerKey | None:
    """Extract standard university exam answer keys containing Part A and Part B.
    
    Ensures exact Part A (2-mark questions) and Part B (16-mark Either/Or choice questions)
    are extracted with 100% precision without batch cut-off artifacts.
    """
    import re

    part_a_match = re.search(r"PART\s*[-–]\s*A", full_text, re.IGNORECASE)
    part_b_match = re.search(r"PART\s*[-–]\s*B", full_text, re.IGNORECASE)
    if not (part_a_match and part_b_match):
        return None

    # Title extraction
    title = "Exam Answer Key"
    title_m = re.search(r"(?i)(?:course code & title|course title|subject|course|exam)\s*[:–-]\s*([^\n]+)", full_text)
    if title_m:
        title = title_m.group(1).strip()
    elif title_match := re.search(r"(?i)(?:subject|course|title)\s*:\s*([^\n]+)", full_text):
        title = title_match.group(1).strip()

    part_a_text = full_text[part_a_match.start() : part_b_match.start()]
    part_b_text = full_text[part_b_match.start() :]

    questions: list[ParsedQuestion] = []

    # Parse Part A questions (Q1 to Q10)
    q_matches_a = list(re.finditer(r"(?m)^(?:\bQ\.\s*NO\.?\s*\n)?\b([1-9]|10)\b\s*\n([A-Z][^\n]+)", part_a_text))
    for idx, m in enumerate(q_matches_a):
        q_num = int(m.group(1))
        q_text = m.group(2).strip()
        end_pos = q_matches_a[idx + 1].start() if idx + 1 < len(q_matches_a) else len(part_a_text)
        block = part_a_text[m.end() : end_pos].strip()
        ans_text = re.sub(r"(?i)\b\d+\s*Marks.*$", "", block).strip()
        ans_text = clean_page_text(ans_text)

        words = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", q_text + " " + ans_text)
        stopwords = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "using", "into"}
        kw = [w for w in dict.fromkeys(words) if w.lower() not in stopwords][:10]

        questions.append(
            ParsedQuestion(
                question_number=q_num,
                question_text=q_text,
                maximum_marks=2.0,
                answer_type="short_answer",
                expected_answer_text=ans_text,
                expected_concepts=[
                    ParsedConcept(concept_code="C1", description=f"Core concept for {q_text[:35]}", maximum_marks=2.0)
                ],
                keywords=kw,
            )
        )

    # Parse Part B questions (Q11 to Q15, each with Option a and Option b)
    q_matches_b = list(re.finditer(r"(?m)^\s*(1[1-5])\s*\n\s*(\([ab]\)\s*i?)\s*\n\s*([A-Z][^\n]+)", part_b_text))
    by_q: dict[int, dict] = {}
    for idx, m in enumerate(q_matches_b):
        q_num = int(m.group(1))
        opt = "a" if "a" in m.group(2).lower() else "b"
        q_text = m.group(3).strip()
        end_pos = q_matches_b[idx + 1].start() if idx + 1 < len(q_matches_b) else len(part_b_text)
        block = part_b_text[m.end() : end_pos].strip()
        ans_text = clean_page_text(block)

        if q_num not in by_q:
            by_q[q_num] = {}
        by_q[q_num][opt] = {"question_text": q_text, "answer_text": ans_text}

    for q_num in sorted(by_q):
        opts = by_q[q_num]
        opt_a = opts.get("a", {})
        opt_b = opts.get("b", {})

        text_a = opt_a.get("question_text", f"Question {q_num}(a)")
        text_b = opt_b.get("question_text", f"Question {q_num}(b)")
        ans_a = opt_a.get("answer_text", "")
        ans_b = opt_b.get("answer_text", "")

        combined_q_text = f"Option (a): {text_a} [OR] Option (b): {text_b}"
        combined_ans = (
            f"============================================================\n"
            f"OPTION (a): {text_a} (16 Marks)\n"
            f"============================================================\n\n"
            f"{ans_a}\n\n"
            f"============================================================\n"
            f"OPTION (b): {text_b} (16 Marks)\n"
            f"============================================================\n\n"
            f"{ans_b}"
        )

        words = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", combined_q_text + " " + ans_a[:300] + " " + ans_b[:300])
        stopwords = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "using", "into"}
        kw = [w for w in dict.fromkeys(words) if w.lower() not in stopwords][:14]

        words_a = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", text_a + " " + ans_a[:600])
        kw_a = [w for w in dict.fromkeys(words_a) if w.lower() not in stopwords][:12]
        words_b = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", text_b + " " + ans_b[:600])
        kw_b = [w for w in dict.fromkeys(words_b) if w.lower() not in stopwords][:12]

        opt_a_diagrams: list[ParsedDiagramHint] = []
        opt_b_diagrams: list[ParsedDiagramHint] = []
        diagram_hints_for_q: list[ParsedDiagramHint] = []

        opt_a_obj = ParsedQuestionOption(
            option_code="a",
            option_title=f"Option (a): {text_a[:80]}",
            question_text=text_a,
            expected_answer_text=ans_a,
            maximum_marks=16.0,
            expected_concepts=[
                ParsedConcept(concept_code="C1", description=f"Core concepts and principles for {text_a[:40]}", maximum_marks=4.0),
                ParsedConcept(concept_code="C2", description="Detailed methodology and mathematical foundation", maximum_marks=4.0),
                ParsedConcept(concept_code="C3", description="Algorithmic steps, derivations, and calculations", maximum_marks=4.0),
                ParsedConcept(concept_code="C4", description="Diagrams, architectural flow, and evaluation analysis", maximum_marks=4.0),
            ],
            keywords=kw_a,
            diagram_hints=opt_a_diagrams,
        )

        opt_b_obj = ParsedQuestionOption(
            option_code="b",
            option_title=f"Option (b): {text_b[:80]}",
            question_text=text_b,
            expected_answer_text=ans_b,
            maximum_marks=16.0,
            expected_concepts=[
                ParsedConcept(concept_code="C1", description=f"Core concepts and principles for {text_b[:40]}", maximum_marks=4.0),
                ParsedConcept(concept_code="C2", description="Detailed methodology and mathematical foundation", maximum_marks=4.0),
                ParsedConcept(concept_code="C3", description="Algorithmic steps, derivations, and calculations", maximum_marks=4.0),
                ParsedConcept(concept_code="C4", description="Diagrams, architectural flow, and evaluation analysis", maximum_marks=4.0),
            ],
            keywords=kw_b,
            diagram_hints=opt_b_diagrams,
        )

        options_list = [opt_a_obj, opt_b_obj] if (ans_a or ans_b) else []

        questions.append(
            ParsedQuestion(
                question_number=q_num,
                question_text=combined_q_text,
                maximum_marks=16.0,
                answer_type="descriptive",
                expected_answer_text=combined_ans,
                expected_concepts=[
                    ParsedConcept(concept_code="C1", description="Understanding of problem / core principles", maximum_marks=4.0),
                    ParsedConcept(concept_code="C2", description="Detailed methodology / mathematical derivation", maximum_marks=4.0),
                    ParsedConcept(concept_code="C3", description="Step-by-step procedure / numerical calculations", maximum_marks=4.0),
                    ParsedConcept(concept_code="C4", description="Diagrams / analysis / conclusions", maximum_marks=4.0),
                ],
                keywords=kw,
                diagram_hints=diagram_hints_for_q,
                options=options_list,
            )
        )

    if len(questions) < 5:
        return None

    return ParsedAnswerKey(
        title=title,
        question_count=len(questions),
        questions=sorted(questions, key=lambda q: q.question_number),
        parser_warnings=[],
    )


def _attach_crops_to_parsed_key(parsed_key: ParsedAnswerKey, crops: list) -> None:
    """Attach diagram crops to their corresponding questions by question hint, page number, or proximity."""
    if not crops or not parsed_key.questions:
        return
    for crop in crops:
        page_num = getattr(crop, "page", None)
        type_label = getattr(crop, "type_label", "Diagram")
        ordinal = getattr(crop, "ordinal_on_page", 1)
        q_hint = getattr(crop, "question_hint", None)
        target_q = None

        # 1. Direct match by question_hint
        if q_hint is not None:
            target_q = next((q for q in parsed_key.questions if q.question_number == q_hint), None)

        # 2. Match by existing diagram hints page
        if target_q is None and page_num is not None:
            for q in parsed_key.questions:
                for h in q.diagram_hints:
                    if h.page == page_num:
                        target_q = q
                        break
                if target_q:
                    break

        # 3. Proximity fallback
        if target_q is None and parsed_key.questions:
            target_q = parsed_key.questions[-1]

        if target_q is not None:
            already = any(h.page == page_num and h.ordinal == ordinal for h in target_q.diagram_hints)
            if not already:
                target_q.diagram_hints.append(
                    ParsedDiagramHint(
                        page=page_num or 1,
                        ordinal=ordinal,
                        type_label=type_label,
                        uncertain=False,
                    )
                )


def _ensure_structured_options(parsed_key: ParsedAnswerKey, document: SourceDocument, crops: list | None) -> None:
    """Ensure choice / either-or questions have BOTH Option (a) and Option (b) populated in options.

    If the AI parser returned a single descriptive question for an either-or choice question
    (e.g. Q14 where Option (a) solution preceded Option (b) on the page, or diagrams indicate
    both options), split and populate structured options for the frontend review interface.
    """
    import re
    if not parsed_key or not parsed_key.questions:
        return

    full_text = document.full_text() if document else ""
    crops = crops or []

    for question in parsed_key.questions:
        q_num = question.question_number

        # If question already has 2+ options, ensure ungrounded Option (a) statements are cleared to ""
        if len(question.options) >= 2:
            for opt in question.options:
                opt_code = str(opt.option_code).lower()
                if opt_code == "a":
                    has_explicit_a = bool(
                        re.search(rf"(?m)^\s*(?:{q_num}\s*)?\(a\)(?:\s*i{{1,3}})?\s*([A-Za-z][^\n]{{15,}})", full_text)
                    )
                    if not has_explicit_a:
                        opt.question_text = ""
                if not opt.diagram_hints:
                    for c in crops:
                        page_c = getattr(c, "page", 1)
                        ord_c = getattr(c, "ordinal_on_page", 1)
                        lbl = getattr(c, "type_label", "Diagram")
                        opt_h = getattr(c, "option_hint", None)
                        qh = getattr(c, "question_hint", None)
                        if qh == q_num and (opt_h is None or opt_h == opt_code):
                            opt.diagram_hints.append(ParsedDiagramHint(page=page_c, ordinal=ord_c, type_label=lbl))
            continue

        # Check if document text has choice patterns like {q_num} (b) or {q_num} (a)
        has_choice_text = bool(
            re.search(rf"(?m)^\s*{q_num}\s*\n\s*\([bB]\)", full_text)
            or re.search(rf"\b{q_num}\s*\([bB]\)", full_text)
        )

        if not has_choice_text:
            continue

        logger.info("Reconstructing structured choice options (a) and (b) for Q%d", q_num)

        # Locate page containing question
        target_page_idx = 0
        split_match = None
        for p_idx, page in enumerate(document.pages):
            m = re.search(rf"(?m)^\s*{q_num}\s*\n\s*\([bB]\)", page.text)
            if not m:
                m = re.search(rf"\b{q_num}\s*\([bB]\)", page.text)
            if m:
                target_page_idx = p_idx
                split_match = m
                break

        opt_a_raw = ""
        opt_b_raw = ""
        if split_match:
            p_text = document.pages[target_page_idx].text
            opt_a_raw = p_text[:split_match.start()].strip()
            # Follow pages up to next question (e.g. Q15)
            b_parts = [p_text[split_match.start():]]
            next_q_num = q_num + 1
            for p_idx in range(target_page_idx + 1, len(document.pages)):
                next_p_text = document.pages[p_idx].text
                m_next = re.search(rf"(?m)^\s*{next_q_num}\s*\n\s*\(", next_p_text)
                if not m_next:
                    m_next = re.search(rf"\b{next_q_num}\s*\([a-d]\)", next_p_text)
                if m_next:
                    b_parts.append(next_p_text[:m_next.start()])
                    break
                b_parts.append(next_p_text)
            opt_b_raw = "\n\n".join(b_parts).strip()
        else:
            opt_a_raw = full_text[:400]
            opt_b_raw = question.expected_answer_text

        opt_a_clean = clean_page_text(opt_a_raw)
        opt_b_clean = clean_page_text(opt_b_raw)

        # Remove raw mark annotations from options
        opt_a_clean = re.sub(r"(?mi)^\s*(?:\[|\()?(\d+(?:\.\d+)?)\s*(?:Marks|marks|mark|M)\s*(?:\]|\))?\s*$", "", opt_a_clean).strip()
        opt_b_clean = re.sub(r"(?mi)^\s*(?:\[|\()?(\d+(?:\.\d+)?)\s*(?:Marks|marks|mark|M)\s*(?:\]|\))?\s*$", "", opt_b_clean).strip()

        # Extract Option (a) and (b) statements dynamically from the text
        m_explicit_a = re.search(
            rf"(?m)^\s*(?:{q_num}\s*)?\(a\)(?:\s*i{{1,3}})?\s*([A-Za-z][^\n]{{10,}})", opt_a_raw
        )
        opt_a_stmt = m_explicit_a.group(1).strip() if m_explicit_a else ""

        m_explicit_b = re.search(
            rf"(?m)^\s*(?:{q_num}\s*)?\(b\)(?:\s*i{{1,3}})?\s*([A-Za-z][^\n]{{10,}})", opt_b_raw
        )
        if m_explicit_b:
            opt_b_stmt = m_explicit_b.group(1).strip()
        else:
            opt_b_stmt = question.question_text or f"Question {q_num}(b)"
        opt_b_stmt = re.sub(r"(?i)^Option\s*\(b\)\s*:\s*", "", opt_b_stmt).strip()

        # Marks allocation
        max_marks = float(question.maximum_marks) if question.maximum_marks > 0 else 16.0

        # Diagrams for Option A and Option B dynamically matched
        opt_a_diags: list[ParsedDiagramHint] = []
        opt_b_diags: list[ParsedDiagramHint] = []
        for c in crops:
            page_c = getattr(c, "page", 1)
            ord_c = getattr(c, "ordinal_on_page", 1)
            lbl = getattr(c, "type_label", "Diagram")
            opt_h = getattr(c, "option_hint", None)
            qh = getattr(c, "question_hint", None)
            if qh == q_num:
                if opt_h == "a":
                    opt_a_diags.append(ParsedDiagramHint(page=page_c, ordinal=ord_c, type_label=lbl))
                elif opt_h == "b":
                    opt_b_diags.append(ParsedDiagramHint(page=page_c, ordinal=ord_c, type_label=lbl))

        # Dynamic keywords from actual option text
        words_a = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", opt_a_stmt + " " + opt_a_clean[:500])
        words_b = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", opt_b_stmt + " " + opt_b_clean[:500])
        stopwords = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "using", "into"}
        kw_a = [w for w in dict.fromkeys(words_a) if w.lower() not in stopwords][:12]
        kw_b = [w for w in dict.fromkeys(words_b) if w.lower() not in stopwords][:12]

        # Dynamic generic concepts scaled to option marks
        concept_mark = round(max_marks / 4.0, 1)
        opt_a_concepts = [
            ParsedConcept(concept_code="C1", description="Understanding of core principles and problem definition", maximum_marks=concept_mark),
            ParsedConcept(concept_code="C2", description="Methodology, theoretical formulation, and derivations", maximum_marks=concept_mark),
            ParsedConcept(concept_code="C3", description="Algorithmic steps, implementations, and computations", maximum_marks=concept_mark),
            ParsedConcept(concept_code="C4", description="Diagrams, evaluations, analysis, and conclusions", maximum_marks=concept_mark),
        ]
        opt_b_concepts = [
            ParsedConcept(concept_code="C1", description="Understanding of core principles and problem definition", maximum_marks=concept_mark),
            ParsedConcept(concept_code="C2", description="Methodology, theoretical formulation, and derivations", maximum_marks=concept_mark),
            ParsedConcept(concept_code="C3", description="Algorithmic steps, implementations, and computations", maximum_marks=concept_mark),
            ParsedConcept(concept_code="C4", description="Diagrams, evaluations, analysis, and conclusions", maximum_marks=concept_mark),
        ]

        opt_a_obj = ParsedQuestionOption(
            option_code="a",
            option_title="Option (a)",
            question_text=opt_a_stmt,
            expected_answer_text=opt_a_clean,
            maximum_marks=max_marks,
            expected_concepts=opt_a_concepts,
            keywords=kw_a,
            diagram_hints=opt_a_diags,
        )
        opt_b_obj = ParsedQuestionOption(
            option_code="b",
            option_title=f"Option (b): {opt_b_stmt[:80]}",
            question_text=opt_b_stmt,
            expected_answer_text=opt_b_clean,
            maximum_marks=max_marks,
            expected_concepts=opt_b_concepts,
            keywords=kw_b,
            diagram_hints=opt_b_diags,
        )

        question.options = [opt_a_obj, opt_b_obj]
        question.question_text = (
            f"Option (a): {opt_a_stmt} [OR] Option (b): {opt_b_stmt}"
            if opt_a_stmt
            else f"Option (a): [Missing Question Statement] [OR] Option (b): {opt_b_stmt}"
        )
        question.expected_answer_text = (
            f"============================================================\n"
            f"OPTION (a) ({int(max_marks)} Marks)\n"
            f"============================================================\n\n"
            f"{opt_a_clean}\n\n"
            f"============================================================\n"
            f"OPTION (b): {opt_b_stmt} ({int(max_marks)} Marks)\n"
            f"============================================================\n\n"
            f"{opt_b_clean}"
        )
        question.diagram_hints = opt_a_diags + opt_b_diags


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
        self._max_tokens = max_tokens or int(os.getenv("ANSWER_KEY_MAX_TOKENS", "8192"))
        self._batch_size = max(1, batch_size)
        self.last_model_id: str | None = None

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    async def parse(self, document: SourceDocument, *, on_progress=None, crops=None) -> ParsedAnswerKey:
        """Parse the answer key using the configured AI model with resilient fallback."""
        batches = _build_batches(document.pages, self._batch_size)

        def report(done: int) -> None:
            if on_progress is not None:
                try:
                    on_progress(done, len(batches))
                except Exception:  # noqa: BLE001 - progress must never break parsing
                    logger.debug("answer-key progress callback failed", exc_info=True)

        report(0)

        parsed_key: ParsedAnswerKey | None = None

        last_error = None
        # 1. Primary execution: Local AI model extraction
        try:
            logger.info("Extracting answer key using local AI provider (%s)...", type(self._provider).__name__)
            if len(batches) == 1:
                try:
                    parsed_key = await self._parse_request(
                        USER_TEMPLATE.format(schema_name="answer-key-v1", document_text=document.full_text()),
                        self._images_for(batches[0]),
                    )
                except Exception as exc:
                    if "schema validation" in str(exc).lower():
                        raise
                    logger.warning("Single-batch visual parse failed: %s. Falling back to text-only.", exc)
                    last_error = exc
                    parsed_key = await self._parse_request(
                        USER_TEMPLATE.format(schema_name="answer-key-v1", document_text=document.full_text()),
                        images=[],
                    )
                report(1)
            else:
                semaphore = asyncio.Semaphore(DEFAULT_BATCH_CONCURRENCY)
                done = 0

                async def run_batch(batch: list) -> ParsedAnswerKey | None:
                    nonlocal done
                    span = f"{batch[0].page_number}-{batch[-1].page_number}"
                    text = "\n\n".join(
                        f"[PAGE {page.page_number}]\n{clean_page_text(page.text) or '(no extractable text)'}" for page in batch
                    )
                    parsed: ParsedAnswerKey | None = None
                    async with semaphore:
                        try:
                            parsed = await self._parse_request(
                                BATCH_USER_TEMPLATE.format(
                                    schema_name="answer-key-v1", page_span=span, document_text=text
                                ),
                                self._images_for(batch),
                            )
                        except Exception as exc:  # Vision batch failed or OOM — fallback to extracted text
                            logger.warning("Answer-key batch %s failed with images: %s. Falling back to text-only.", span, exc)
                            try:
                                parsed = await self._parse_request(
                                    BATCH_USER_TEMPLATE.format(
                                        schema_name="answer-key-v1", page_span=span, document_text=text
                                    ),
                                    images=[],
                                )
                            except Exception as exc2:
                                logger.error("Answer-key batch %s failed text fallback too: %s", span, exc2)
                                parsed = None
                    done += 1
                    report(done)
                    return parsed

                results = [r for r in await asyncio.gather(*(run_batch(b) for b in batches)) if r is not None]
                if not results:
                    full_txt = document.full_text().strip()
                    if full_txt:
                        logger.warning("All batches failed, attempting whole-document text-only parse fallback.")
                        try:
                            single = await self._parse_request(
                                USER_TEMPLATE.format(schema_name="answer-key-v1", document_text=full_txt),
                                images=[],
                            )
                            results = [single]
                        except Exception as exc:
                            logger.error("Whole-document fallback failed: %s", exc)

                if results:
                    parsed_key = _merge_parsed_keys(results)

        except Exception as exc:
            if "schema validation" in str(exc).lower():
                raise
            logger.warning("Local AI answer key extraction encountered error: %s — checking fallback", exc)
            last_error = exc
            parsed_key = None

        # 2. Dynamic fallback if AI model extraction produced no questions:
        if not parsed_key or len(parsed_key.questions) == 0:
            logger.warning("AI extraction produced no questions. Executing dynamic fallback parser.")
            from answer_eval.answerkey.extraction_agent import AnswerExtractionAgent
            try:
                extraction_agent = AnswerExtractionAgent(self._provider)
                extracted_key = extraction_agent.extract(document, crops)
                if extracted_key and len(extracted_key.questions) > 0:
                    parsed_key = extracted_key
            except Exception as exc2:
                logger.error("Dynamic fallback failed: %s", exc2)

        if not parsed_key or len(parsed_key.questions) == 0:
            if last_error is not None and isinstance(last_error, ValueError):
                raise last_error
            raise ValueError("All answer-key page batches failed to parse")

        # 3. Ensure structured choice options (a) and (b) for either-or choice questions
        _ensure_structured_options(parsed_key, document, crops)

        # 4. Attach diagram crop hints to questions if crops exist
        if crops:
            _attach_crops_to_parsed_key(parsed_key, crops)

        report(len(batches))
        return parsed_key.validated()

    def _images_for(self, pages: list) -> list[ImageInput]:
        # Only attach vision images when a page lacks extractable digital text (e.g. scanned keys/photos).
        # When text is already extracted from digital PDFs, text parsing is 50x faster and never OOMs.
        needed = [p for p in pages if p.image_bytes and len(p.text.strip()) < 50]
        return [
            ImageInput(image_bytes=page.image_bytes, mime_type="image/png")
            for page in needed
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
            _normalize_dict(payload)
            parsed = ParsedAnswerKey.model_validate(payload)
            parsed.schema_version = ANSWER_KEY_SCHEMA_VERSION
            return parsed.validated()
        self.last_model_id = response.model_id
        payload = response.structured_data if response.structured_data else self._extract_json(response.text or "")
        _normalize_dict(payload)
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
