"""Diagram extraction agent data structures."""

from typing import Any

from pydantic import BaseModel, Field

from answer_eval.core.provenance import Provenance


class DiagramLabel(BaseModel):
    """Text label identified within a diagram."""

    text: str = Field(description="Visible label text verbatim")
    uncertain: bool = Field(default=False, description="Whether the label is partially illegible")
    location_hint: str | None = Field(default=None, description="Location description inside diagram")


class DiagramComponent(BaseModel):
    """Visual structural component in a diagram (box, circle, block, etc.)."""

    type: str = Field(default="box", description="box, circle, arrow, cylinder, shape, icon, other")
    label: str | None = Field(default=None, description="Associated label on or inside the component")
    description: str = Field(default="", description="Visual description of the component")


class DiagramRelationship(BaseModel):
    """Directed or undirected connection between diagram components."""

    from_component: str = Field(description="Source component label or identifier")
    to_component: str = Field(description="Target component label or identifier")
    relationship_type: str = Field(default="arrow", description="arrow, line, double_arrow, grouping")
    label: str | None = Field(default=None, description="Label on the connector line if any")


class DiagramVisualQuality(BaseModel):
    """Visual clarity and legibility assessment of the diagram."""

    legibility: str = Field(default="good", description="good, medium, poor")
    label_clarity: str = Field(default="good", description="good, medium, poor")
    completeness_appearance: str = Field(default="complete", description="complete, partial, fragment")


class DiagramResult(BaseModel):
    """Complete observation output of DiagramAgent."""

    diagram_present: bool = Field(
        description="True when a visual diagram is present in the region; False means only handwriting/text was found"
    )
    diagram_type_guess: str = Field(
        default="unknown",
        description="flowchart, block_diagram, network, circuit, graph, table, other — only meaningful when diagram_present=true",
    )
    labels: list[DiagramLabel] = Field(default_factory=list, description="All observed text labels")
    components: list[DiagramComponent] = Field(default_factory=list, description="All drawn structural blocks")
    relationships: list[DiagramRelationship] = Field(default_factory=list, description="All observed connections")
    visual_quality: DiagramVisualQuality = Field(default_factory=DiagramVisualQuality, description="Visual assessment")
    uncertain_elements: list[dict[str, str]] = Field(
        default_factory=list, description="Unclear or ambiguous diagram elements"
    )
    fallback_ocr_text: str | None = Field(
        default=None,
        description="OCR text extracted as fallback when diagram_present=False or structured extraction failed",
    )
    provenance: Provenance = Field(description="Full traceability metadata")
    model_metadata: dict[str, Any] = Field(default_factory=dict, description="Inference timing and token usage")
