"""Multi-agent Excel upload-processing pipeline.

Extracts structural/visual metadata, builds a semantic schema, and enriches
it with domain-aware context. Runs once per data source on upload.

Architecture:
- Visual Metadata Extractor: colors, merged cells, structural info
- Semantic Mapper: JSON schema of workbook structure
- Semantic Enricher: domain, metrics, context header for Q&A
- Orchestrator: coordinates the pipeline

NOTE: Natural-language Q&A is NOT handled by this module. It is handled
by core.rosetta.coordinator.answer() via ExcelAgentService.ask_question().
"""

from core.agents.base import BaseAgent
from core.agents.extractor import VisualMetadataExtractor
from core.agents.mapper import SemanticMapper
from core.agents.orchestrator import ExcelAgentOrchestrator
from core.agents.semantic_enricher import SemanticEnricher

__all__ = [
    "BaseAgent",
    "VisualMetadataExtractor",
    "SemanticMapper",
    "SemanticEnricher",
    "ExcelAgentOrchestrator",
]
