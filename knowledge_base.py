"""
knowledge_base.py
─────────────────
The single shared state object that flows through the entire agent pipeline.
All agents read from and write to this; no agent passes raw prose directly
to another. Every factual claim in the manuscript is traceable to an entry here.
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Typed sub-stores ──────────────────────────────────────────────────────────

@dataclass
class RepoMap:
    """Output of the Repo Cartographer."""
    file_tree: str = ""
    pipeline_steps: list[dict] = field(default_factory=list)
    # Each step: {name, script, inputs, outputs, description}
    software_stack: list[dict] = field(default_factory=list)
    # Each: {name, version, purpose}
    parameters: dict[str, Any] = field(default_factory=dict)
    doc_vs_code_mismatches: list[str] = field(default_factory=list)
    key_algorithms: list[str] = field(default_factory=list)


@dataclass
class ResultsStore:
    """
    Locked store of every result that will appear in the manuscript.
    Writers may only cite entries here — they cannot invent numbers.
    """
    entries: dict[str, dict] = field(default_factory=dict)
    # key: result_id  value: {value, source_file, figure, claim, units}

    def add(self, result_id: str, value: Any, source_file: str,
            figure: str = "", claim: str = "", units: str = ""):
        self.entries[result_id] = dict(
            value=value, source_file=source_file,
            figure=figure, claim=claim, units=units,
            locked_at=time.time()
        )

    def get(self, result_id: str) -> dict:
        return self.entries.get(result_id, {})

    def summary(self) -> str:
        lines = []
        for rid, r in self.entries.items():
            lines.append(f"  {rid}: {r['value']} {r['units']}  [{r['source_file']}]"
                         + (f"  → {r['claim']}" if r['claim'] else ""))
        return "\n".join(lines) if lines else "  (empty)"


@dataclass
class MethodsSpec:
    """Output of the Methods Formaliser."""
    notation_registry: dict[str, str] = field(default_factory=dict)
    # symbol → definition, e.g. {"f": "ancestry frequency", "t": "generations since admixture"}
    model_definitions: list[str] = field(default_factory=list)
    statistical_tests: list[dict] = field(default_factory=list)
    # Each: {name, null_hypothesis, statistic, null_distribution, correction}
    pipeline_prose: str = ""           # formal prose description of the pipeline
    parameter_table: list[dict] = field(default_factory=list)


@dataclass
class JournalSpec:
    """Output of the Journal Profiler."""
    journal_name: str = ""
    scope: str = ""
    section_structure: list[str] = field(default_factory=list)
    word_limits: dict[str, int] = field(default_factory=dict)
    figure_limit: int = 0
    citation_style: str = ""
    statistical_conventions: str = ""
    tone_notes: str = ""
    recent_paper_styles: list[str] = field(default_factory=list)


@dataclass
class ManuscriptDraft:
    """The evolving manuscript. Each section is stored separately."""
    title: str = ""
    abstract: str = ""
    introduction: str = ""
    methods: str = ""
    results: str = ""
    discussion: str = ""
    figure_legends: str = ""
    references: str = ""
    # Metadata per section
    section_word_counts: dict[str, int] = field(default_factory=dict)
    section_versions: dict[str, int] = field(default_factory=dict)

    def word_count(self, section: str) -> int:
        text = getattr(self, section, "")
        return len(text.split()) if text else 0

    def full_text(self) -> str:
        parts = []
        for sec in ['title','abstract','introduction','methods',
                    'results','discussion','figure_legends']:
            txt = getattr(self, sec, "")
            if txt:
                parts.append(f"## {sec.upper()}\n\n{txt}")
        return "\n\n---\n\n".join(parts)


@dataclass
class AuditReport:
    """Structured audit from the Stats Auditor and Domain Checker."""
    stats_issues: list[dict] = field(default_factory=list)
    # Each: {section, location, issue, severity}  severity: fatal/major/minor
    domain_issues: list[dict] = field(default_factory=list)
    reproducibility_gaps: list[str] = field(default_factory=list)
    all_passed: bool = False

    def n_fatal(self) -> int:
        return sum(1 for i in self.stats_issues + self.domain_issues
                   if i.get('severity') == 'fatal')

    def summary(self) -> str:
        lines = [f"Stats issues: {len(self.stats_issues)}",
                 f"Domain issues: {len(self.domain_issues)}",
                 f"Reproducibility gaps: {len(self.reproducibility_gaps)}",
                 f"Fatal issues: {self.n_fatal()}",
                 f"Overall: {'PASS' if self.all_passed else 'FAIL'}"]
        return "\n".join(lines)


@dataclass
class ReviewPackage:
    """Outputs of the mock review round."""
    reviewer_reports: list[dict] = field(default_factory=list)
    # Each: {reviewer_profile, major_concerns, minor_concerns, recommendation}
    editor_decision: str = ""          # accept/major_revision/minor_revision/reject
    editor_letter: str = ""
    ranked_action_list: list[str] = field(default_factory=list)
    response_to_reviewers: str = ""


# ── Master knowledge base ─────────────────────────────────────────────────────

@dataclass
class KnowledgeBase:
    """
    The single shared state object. Passed between all agents.
    Layer 1 agents populate it; Layer 2 agents read from it.
    """
    # Inputs (set before pipeline starts)
    repo_path: str = ""
    journal_name: str = ""
    extra_context: str = ""       # anything the user wants to inject
    target_audience: str = ""

    # Layer 1 outputs
    repo_map: RepoMap = field(default_factory=RepoMap)
    results_store: ResultsStore = field(default_factory=ResultsStore)
    methods_spec: MethodsSpec = field(default_factory=MethodsSpec)
    journal_spec: JournalSpec = field(default_factory=JournalSpec)

    # Layer 2 outputs
    draft: ManuscriptDraft = field(default_factory=ManuscriptDraft)
    audit: AuditReport = field(default_factory=AuditReport)
    review: ReviewPackage = field(default_factory=ReviewPackage)

    # Pipeline provenance
    agent_log: list[dict] = field(default_factory=list)
    # Each entry: {agent, timestamp, action, summary}

    def log(self, agent: str, action: str, summary: str):
        self.agent_log.append(dict(
            agent=agent, timestamp=time.time(),
            action=action, summary=summary
        ))
        print(f"  [{agent}] {action}: {summary[:80]}")

    def save(self, path: str):
        """Serialise to JSON for inspection / resumption."""
        def default(o):
            if hasattr(o, '__dict__'): return o.__dict__
            return str(o)
        with open(path, 'w') as f:
            json.dump(self.__dict__, f, indent=2, default=default)

    def status(self) -> str:
        lines = [
            "── Knowledge Base Status ──────────────────────────────",
            f"  Repo          : {self.repo_path or '(not set)'}",
            f"  Journal       : {self.journal_name or '(not set)'}",
            f"  Pipeline steps: {len(self.repo_map.pipeline_steps)}",
            f"  Results locked: {len(self.results_store.entries)}",
            f"  Notation syms : {len(self.methods_spec.notation_registry)}",
            f"  Draft sections: "
            + ", ".join(s for s in ['abstract','introduction','methods',
                                    'results','discussion']
                        if getattr(self.draft, s)),
            f"  Audit passed  : {self.audit.all_passed}",
            f"  Review round  : {len(self.review.reviewer_reports)} reports",
            "────────────────────────────────────────────────────────",
        ]
        return "\n".join(lines)
