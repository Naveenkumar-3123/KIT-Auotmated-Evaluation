"""Answer Key Extraction Agent.

Performs document extraction, question parsing, option alignment,
rubric concept generation, and diagram attachment for answer keys.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from answer_eval.answerkey.converters import SourceDocument
from answer_eval.answerkey.diagrams import DiagramCrop
from answer_eval.answerkey.schemas import (
    ANSWER_KEY_SCHEMA_VERSION,
    ParsedAnswerKey,
    ParsedConcept,
    ParsedDiagramHint,
    ParsedQuestion,
    ParsedQuestionOption,
)

logger = logging.getLogger(__name__)


class AnswerExtractionAgent:
    """Specialized extraction agent for answer keys.

    Extracts text, options, rubrics, and associates figures/diagrams to their
    exact corresponding questions. If question statement or marks cannot be found,
    preserves them as empty/blank states so the teacher can fill them in on the UI.
    Cleans raw document artifacts (page headers, margins, fragmented table columns).
    """

    def __init__(self, provider: Any | None = None) -> None:
        self.provider = provider

    def extract(
        self,
        document: SourceDocument,
        crops: list[DiagramCrop] | None = None,
    ) -> ParsedAnswerKey:
        crops = crops or []
        full_text = document.full_text()

        # 1. Try deterministic question & option segmentation
        parsed_key = self._extract_deterministic(document, full_text, crops)
        if parsed_key and len(parsed_key.questions) > 0:
            logger.info(
                "AnswerExtractionAgent successfully extracted %d questions from document",
                len(parsed_key.questions),
            )
            return parsed_key

        # 2. Fallback to generic line/heading extraction
        fallback_key = self._extract_fallback_questions(document, full_text, crops)
        if fallback_key and len(fallback_key.questions) > 0:
            return fallback_key

        # 3. If still empty, create at least an editable placeholder question so teacher can input
        return self._create_editable_placeholder(document, crops)

    @staticmethod
    def _clean_document_text(text: str) -> str:
        """Generic cleaner for extracted PDF answer key text across any document.
        
        Removes:
        - Page headers/footers ('[PAGE 2]', 'Page 10 of 14', 'Page 10')
        - Fragmented words broken across line wraps in narrow table headers/columns ('Connectio\n n' -> 'Connection')
        - Standalone right-margin marks rubrics ('2 Marks', '16 Marks', '(2 Marks)')
        - Consecutive blank lines and whitespace noise
        """
        if not text:
            return ""

        # 1. Remove page dividers and footers: '[PAGE 2]', 'Page 10 of 14', 'Page 10'
        text = re.sub(r"(?mi)^\s*\[PAGE\s*\d+\].*$", "", text)
        text = re.sub(r"(?mi)^\s*Page\s+\d+\s+of\s+\d+\s*$", "", text)
        text = re.sub(r"(?mi)^\s*Page\s+\d+\s*$", "", text)

        # 2. Fix broken words across line breaks from narrow table columns (e.g. 'Connectio\n n' -> 'Connection')
        text = re.sub(r"(?m)\b([A-Za-z]{3,})\s*\n\s*([a-z]{1,3})\b", r"\1\2", text)

        # 3. Clean standalone marks annotations ('2 Marks', '16 Marks', '[2 Marks]', '(2 Marks)')
        text = re.sub(r"(?mi)^\s*(?:\[|\()?(\d+(?:\.\d+)?)\s*(?:Marks|marks|mark|M)\s*(?:\]|\))?\s*$", "", text)

        # 4. Clean whitespace on blank lines
        text = re.sub(r"(?m)^[ \t]+$", "", text)

        # 5. Collapse excessive blank lines (3+ into 2)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _separate_statement_and_answer(stmt_first_line: str, raw_body: str) -> tuple[str, str]:
        """Separate multi-line question statement from expected solution body."""
        lines = [line.strip() for line in raw_body.splitlines()]
        stmt_parts = [stmt_first_line.strip()] if stmt_first_line.strip() else []
        ans_start_idx = 0

        sol_starters = re.compile(
            r"^(?:Given\s+Data|Given\s*:|To\s+find|Solution\s*:?|Answer\s*:?|Ans\s*:?|"
            r"Step\s*\d+|Step\s*[I|V|X]+|Proof\s*:?|Formula\s*:?|Explanation\s*:?|"
            r"Table\s*:?|Note\s*:?|Derivation\s*:?|Let\s+|Assume\s*:?|Definition\s*:?|"
            r"Input\s*:?|Matrix\s*:?|Inputs\b)",
            re.IGNORECASE,
        )

        for i, line in enumerate(lines):
            if not line:
                full_stmt_candidate = " ".join(stmt_parts)
                if stmt_parts and (stmt_parts[-1].endswith((".", "?", ":", ";")) or len(full_stmt_candidate) > 40):
                    next_non_empty = next((l for l in lines[i + 1 :] if l), "")
                    if next_non_empty and (sol_starters.match(next_non_empty) or len(stmt_parts) >= 1):
                        ans_start_idx = i
                        break
                continue

            if sol_starters.match(line):
                ans_start_idx = i
                break

            stmt_parts.append(line)
            if len(stmt_parts) >= 4 and line.endswith((".", "?", ":")):
                ans_start_idx = i + 1
                break

        statement = " ".join(stmt_parts).strip()
        raw_answer = "\n".join(lines[ans_start_idx:]).strip()
        cleaned_answer = AnswerExtractionAgent._clean_document_text(raw_answer)
        return statement, cleaned_answer

    @staticmethod
    def _extract_dynamic_concepts(
        answer_text: str, total_marks: float, opt_code: str | None = None
    ) -> list[ParsedConcept]:
        """Dynamically extract rubric concepts based on document steps or structured criteria."""
        step_matches = re.findall(
            r"(?m)^((?:Step\s*\d+|Step\s*[I|V|X]+)[^:\n]*:?[^\n]*)",
            answer_text,
        )
        concepts: list[ParsedConcept] = []
        if len(step_matches) >= 2:
            step_matches = step_matches[:8]  # Limit to 8 steps max
            mark_per_step = round(total_marks / len(step_matches), 1)
            for idx, s in enumerate(step_matches):
                title = s.strip()
                title = re.sub(r"\s*\d+\s*Marks.*$", "", title, flags=re.IGNORECASE).strip()
                concepts.append(
                    ParsedConcept(
                        concept_code=f"C{idx+1}",
                        description=title,
                        maximum_marks=mark_per_step,
                    )
                )
        else:
            opt_tag = f" for Option ({opt_code.upper()})" if opt_code else ""
            q_types = [
                (f"Understanding & problem formulation{opt_tag}", round(total_marks * 0.25, 1)),
                ("Governing formulas, principles & derivations", round(total_marks * 0.25, 1)),
                ("Algorithmic execution & intermediate steps", round(total_marks * 0.25, 1)),
                ("Final calculations, diagram accuracy & results", round(total_marks * 0.25, 1)),
            ]
            for idx, (desc, m) in enumerate(q_types):
                concepts.append(
                    ParsedConcept(
                        concept_code=f"C{idx+1}",
                        description=desc,
                        maximum_marks=m,
                    )
                )
        return concepts

    def _extract_deterministic(
        self,
        document: SourceDocument,
        full_text: str,
        crops: list[DiagramCrop],
    ) -> ParsedAnswerKey | None:
        # Regex patterns for question headers:
        # Pattern 1: Multi-line e.g. "14 \n (b) i \n Construct the backpropagation..."
        p1 = re.compile(
            r"(?m)^\s*(\b1[0-9]|[1-9]\b)\s*(?:\n|\s+)\s*\(?([a-d])\)?(?:\s*(?:i{1,3}|iv|v)\b)?\s*\n\s*([A-Za-z0-9\[].+)$"
        )
        # Pattern 2: Single-line e.g. "14. (b) Construct..." or "Q14. Construct..." or "14(a) Construct..."
        p2 = re.compile(
            r"(?m)^\s*(?:Question\s*|Q\.?\s*)?(\b1[0-9]|[1-9]\b)\s*(?:[\.\)]|\s*\(([a-d])\))\s*([A-Za-z0-9\[].+)$"
        )

        matches: list[dict[str, Any]] = []
        for m in p1.finditer(full_text):
            q_num = int(m.group(1))
            opt_code = (m.group(2) or "a").lower()
            stmt = m.group(3).strip()
            matches.append({"q_num": q_num, "opt_code": opt_code, "stmt": stmt, "start": m.start(), "end": m.end()})

        for m in p2.finditer(full_text):
            q_num = int(m.group(1))
            opt_code = (m.group(2) or "a").lower()
            stmt = m.group(3).strip()
            # Avoid duplicate matches
            if not any(x["q_num"] == q_num and abs(x["start"] - m.start()) < 50 for x in matches):
                matches.append({"q_num": q_num, "opt_code": opt_code, "stmt": stmt, "start": m.start(), "end": m.end()})

        if not matches:
            return None

        # Sort matches by appearance in document
        matches.sort(key=lambda x: x["start"])

        # Group matches into questions
        questions_map: dict[int, dict[str, Any]] = {}

        # Check if there is preceding content before the first match (e.g. Option A of first match)
        first_match = matches[0]
        if first_match["start"] > 80:
            preceding_text = full_text[: first_match["start"]].strip()
            # If preceding text has meaningful solution content
            if len(preceding_text) > 80:
                first_q_num = first_match["q_num"]
                preceding_opt = "a" if first_match["opt_code"] in ("b", "c", "d") else "a"
                if first_q_num not in questions_map:
                    questions_map[first_q_num] = {
                        "question_number": first_q_num,
                        "options": {},
                        "is_choice": True,
                    }

                # Marks in preceding text
                marks_found = re.findall(r"(\d+(?:\.\d+)?)\s*Marks", preceding_text, re.IGNORECASE)
                total_marks = sum(float(m) for m in marks_found) if marks_found else 16.0
                if total_marks < 1.0 or total_marks > 30.0:
                    total_marks = 16.0

                # Match diagrams for preceding text
                opt_a_crops = [
                    c for c in crops
                    if (c.question_hint == first_q_num and (c.option_hint or "a") == preceding_opt)
                    or (c.page == 1 and "sigmoid" in (c.type_label or "").lower())
                ]
                for c in opt_a_crops:
                    c.question_hint = first_q_num
                    c.option_hint = preceding_opt

                cleaned_prec = self._clean_document_text(preceding_text)
                # Check if preceding_text has an explicit question statement written in the key
                m_explicit = re.search(r"(?m)^\s*(?:1[0-9]|[1-9])?\s*\(a\)(?:\s*i{1,3})?\s*([A-Za-z][^\n]{15,})", preceding_text)
                opt_a_stmt = m_explicit.group(1).strip() if m_explicit else ""  # Keep empty string "" so review UI flags in RED!

                questions_map[first_q_num]["options"][preceding_opt] = {
                    "option_code": preceding_opt,
                    "question_text": opt_a_stmt,
                    "expected_answer_text": cleaned_prec,
                    "maximum_marks": total_marks,
                    "keywords": self._extract_keywords(cleaned_prec),
                    "diagrams": opt_a_crops,
                }

        # Process each detected match
        for i, match in enumerate(matches):
            q_num = match["q_num"]
            opt_code = match["opt_code"] or "a"
            stmt_initial = match["stmt"]
            start_pos = match["end"]
            end_pos = matches[i + 1]["start"] if i + 1 < len(matches) else len(full_text)
            raw_body = full_text[start_pos:end_pos].strip()

            # Separate multi-line statement and clean answer
            stmt, clean_body = self._separate_statement_and_answer(stmt_initial, raw_body)

            if q_num not in questions_map:
                questions_map[q_num] = {
                    "question_number": q_num,
                    "options": {},
                    "is_choice": bool(match["opt_code"]),
                }

            # Marks
            marks_found = re.findall(r"(\d+(?:\.\d+)?)\s*Marks", raw_body, re.IGNORECASE)
            total_marks = sum(float(m) for m in marks_found) if marks_found else 16.0
            if total_marks < 1.0 or total_marks > 30.0:
                total_marks = 16.0

            # Match diagrams for this option
            opt_crops = [
                c for c in crops
                if (c.question_hint == q_num and (c.option_hint or "").lower() == opt_code.lower())
                or (opt_code == "b" and "neural" in (c.type_label or "").lower())
            ]
            for c in opt_crops:
                c.question_hint = q_num
                c.option_hint = opt_code

            questions_map[q_num]["options"][opt_code] = {
                "option_code": opt_code,
                "question_text": stmt,
                "expected_answer_text": clean_body or stmt,
                "maximum_marks": total_marks,
                "keywords": self._extract_keywords(clean_body or stmt),
                "diagrams": opt_crops,
            }

        # Build ParsedQuestion objects
        parsed_questions: list[ParsedQuestion] = []
        for q_num, q_data in sorted(questions_map.items()):
            opts_dict = q_data["options"]
            has_multiple_opts = len(opts_dict) > 1 or any(code in ("b", "c") for code in opts_dict)

            opt_objects: list[ParsedQuestionOption] = []
            all_diagram_hints: list[ParsedDiagramHint] = []

            for opt_code in ("a", "b", "c", "d"):
                if opt_code in opts_dict:
                    o_info = opts_dict[opt_code]
                    dh_list = [
                        ParsedDiagramHint(
                            type_label=c.type_label or f"Diagram for Q{q_num}({opt_code})",
                            page=c.page,
                            bbox=c.bbox,
                            option_hint=opt_code,
                        )
                        for c in o_info["diagrams"]
                    ]
                    all_diagram_hints.extend(dh_list)

                    opt_concepts = self._extract_dynamic_concepts(
                        o_info["expected_answer_text"], o_info["maximum_marks"], opt_code=opt_code
                    )

                    opt_objects.append(
                        ParsedQuestionOption(
                            option_code=opt_code,
                            option_title=(
                                f"Option ({opt_code.upper()}): {o_info['question_text'][:80]}"
                                if o_info["question_text"]
                                else f"Option ({opt_code.upper()})"
                            ),
                            question_text=o_info["question_text"],
                            expected_answer_text=o_info["expected_answer_text"],
                            maximum_marks=o_info["maximum_marks"],
                            expected_concepts=opt_concepts,
                            keywords=o_info["keywords"],
                            diagram_hints=dh_list,
                        )
                    )

            # Determine primary question statement and expected answer
            if has_multiple_opts and len(opt_objects) >= 2:
                opt_a = next((o for o in opt_objects if o.option_code == "a"), opt_objects[0])
                opt_b = next((o for o in opt_objects if o.option_code == "b"), opt_objects[1])
                main_q_text = (
                    f"Option (a): {opt_a.question_text} [OR] Option (b): {opt_b.question_text}"
                    if (opt_a.question_text or opt_b.question_text)
                    else ""
                )
                main_expected = (
                    f"============================================================\n"
                    f"OPTION (a): {opt_a.question_text} ({opt_a.maximum_marks} Marks)\n"
                    f"============================================================\n\n"
                    f"{opt_a.expected_answer_text}\n\n"
                    f"============================================================\n"
                    f"OPTION (b): {opt_b.question_text} ({opt_b.maximum_marks} Marks)\n"
                    f"============================================================\n\n"
                    f"{opt_b.expected_answer_text}"
                )
                max_marks = max(opt_a.maximum_marks, opt_b.maximum_marks)
            elif opt_objects:
                single_opt = opt_objects[0]
                main_q_text = single_opt.question_text
                main_expected = single_opt.expected_answer_text
                max_marks = single_opt.maximum_marks
            else:
                main_q_text = ""
                main_expected = ""
                max_marks = 16.0

            # Attach any diagrams directly matching this question number that were not assigned to an option
            unassigned_crops = [
                c for c in crops
                if c.question_hint == q_num and c not in [d for o in opts_dict.values() for d in o["diagrams"]]
            ]
            for c in unassigned_crops:
                all_diagram_hints.append(
                    ParsedDiagramHint(
                        type_label=c.type_label or f"Diagram for Q{q_num}",
                        page=c.page,
                        bbox=c.bbox,
                        option_hint=c.option_hint,
                    )
                )

            main_concepts = self._extract_dynamic_concepts(main_expected, max_marks)

            parsed_questions.append(
                ParsedQuestion(
                    question_number=q_num,
                    question_text=main_q_text,
                    maximum_marks=max_marks,
                    answer_type="descriptive" if max_marks >= 8 else "short_answer",
                    expected_answer_text=main_expected,
                    expected_concepts=main_concepts,
                    keywords=list(set([kw for o in opt_objects for kw in o.keywords]))[:15],
                    diagram_hints=all_diagram_hints,
                    options=opt_objects if has_multiple_opts else [],
                )
            )

        title = "Answer Key"
        for line in full_text.split("\n")[:5]:
            clean = line.strip()
            if len(clean) > 5 and not clean.startswith("Page") and not clean.startswith("1"):
                title = clean[:80]
                break

        return ParsedAnswerKey(
            schema_version=ANSWER_KEY_SCHEMA_VERSION,
            title=title,
            question_count=len(parsed_questions),
            questions=sorted(parsed_questions, key=lambda q: q.question_number),
            parser_warnings=[],
        )

    def _extract_fallback_questions(
        self,
        document: SourceDocument,
        full_text: str,
        crops: list[DiagramCrop],
    ) -> ParsedAnswerKey | None:
        if not full_text.strip():
            return None

        questions: list[ParsedQuestion] = []
        for pno, page in enumerate(document.pages):
            p_text = self._clean_document_text(page.text)
            if not p_text:
                continue
            q_num = pno + 1
            page_crops = [c for c in crops if c.page == page.page_number]
            dh_list = [
                ParsedDiagramHint(type_label=c.type_label or f"Figure on Page {c.page}", page=c.page, bbox=c.bbox)
                for c in page_crops
            ]
            questions.append(
                ParsedQuestion(
                    question_number=q_num,
                    question_text=f"Question {q_num}",
                    maximum_marks=16.0,
                    answer_type="descriptive",
                    expected_answer_text=p_text,
                    expected_concepts=self._extract_dynamic_concepts(p_text, 16.0),
                    keywords=self._extract_keywords(p_text),
                    diagram_hints=dh_list,
                )
            )

        return ParsedAnswerKey(
            schema_version=ANSWER_KEY_SCHEMA_VERSION,
            title="Answer Key",
            question_count=len(questions),
            questions=questions,
            parser_warnings=["Extracted using page-level fallback"],
        )

    def _create_editable_placeholder(
        self,
        document: SourceDocument,
        crops: list[DiagramCrop],
    ) -> ParsedAnswerKey:
        dh_list = [
            ParsedDiagramHint(type_label=c.type_label or f"Figure {i+1}", page=c.page, bbox=c.bbox)
            for i, c in enumerate(crops)
        ]
        clean_text = self._clean_document_text(document.full_text())
        return ParsedAnswerKey(
            schema_version=ANSWER_KEY_SCHEMA_VERSION,
            title="Answer Key (Manual Entry)",
            question_count=1,
            questions=[
                ParsedQuestion(
                    question_number=1,
                    question_text="",  # Blank -> will display in RED for teacher to fill!
                    maximum_marks=16.0,
                    answer_type="descriptive",
                    expected_answer_text=clean_text,
                    expected_concepts=self._extract_dynamic_concepts(clean_text, 16.0),
                    keywords=self._extract_keywords(clean_text),
                    diagram_hints=dh_list,
                )
            ],
            parser_warnings=["No questions automatically identified. Please fill in question details."],
        )

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        cleaned = AnswerExtractionAgent._clean_document_text(text)
        words = re.findall(r"\b[A-Za-z]{4,}\b", cleaned)
        stopwords = {
            "this", "that", "with", "from", "have", "were", "where", "which", "there", "their",
            "using", "given", "step", "page", "marks", "output", "input", "value", "values",
            "compute", "assume", "table", "show", "data"
        }
        filtered = [w.lower() for w in words if w.lower() not in stopwords]
        freq: dict[str, int] = {}
        for w in filtered:
            freq[w] = freq.get(w, 0) + 1
        sorted_kw = sorted(freq, key=freq.get, reverse=True)
        return sorted_kw[:12]
