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


# ── Author vision ────────────────────────────────────────────────────────────

@dataclass
class RepoRole:
    """Per-repo metadata from PAPER_VISION.md."""
    repo_id: str = ""              # e.g. "munch-group/analysis"
    role: str = ""                 # free-text role description
    focus: list[str] = field(default_factory=list)    # paths/areas to focus on
    ignore: list[str] = field(default_factory=list)   # paths/areas to skip
    relationships: list[str] = field(default_factory=list)  # how it connects to other repos


@dataclass
class AuthorVision:
    """
    Structured author intent loaded from PAPER_VISION.md in the primary repo.

    Guides all agents: RepoCartographer uses repo_roles to focus exploration,
    writing agents use narrative fields to align framing.
    """
    one_sentence_claim: str = ""
    primary_audience: str = ""
    narrative_angle: str = ""       # "methods-forward" | "biology-forward" | "tools-forward"
    key_findings_foreground: list[str] = field(default_factory=list)
    key_findings_background: list[str] = field(default_factory=list)
    connections_to_previous_work: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)
    preferred_journals: list[str] = field(default_factory=list)
    tone: str = ""
    repo_roles: dict[str, RepoRole] = field(default_factory=dict)
    # repo_id (account/repo) → RepoRole
    raw_markdown: str = ""          # the full PAPER_VISION.md text for reference


# ── Typed sub-stores ──────────────────────────────────────────────────────────

@dataclass
class RepoMap:
    """Output of the Repo Cartographer — one per repository."""
    repo_label: str = ""                # short label, e.g. "analysis", "simulation"
    repo_path: str = ""                 # absolute path to this repository
    file_tree: str = ""
    pipeline_steps: list[dict] = field(default_factory=list)
    # Each step: {name, script, inputs, outputs, description}
    software_stack: list[dict] = field(default_factory=list)
    # Each: {name, version, purpose}
    parameters: dict[str, Any] = field(default_factory=dict)
    doc_vs_code_mismatches: list[str] = field(default_factory=list)
    key_algorithms: list[str] = field(default_factory=list)


@dataclass
class RepoRegistry:
    """
    Registry of all input repositories and their maps.

    For single-repo projects this holds one entry. For multi-repo projects
    each repository gets its own RepoMap, keyed by label.
    """
    repos: dict[str, RepoMap] = field(default_factory=dict)
    # label → RepoMap

    def add(self, label: str, path: str) -> RepoMap:
        """Register a repo and return its (empty) RepoMap."""
        rm = RepoMap(repo_label=label, repo_path=path)
        self.repos[label] = rm
        return rm

    def get(self, label: str) -> RepoMap | None:
        return self.repos.get(label)

    @property
    def labels(self) -> list[str]:
        return list(self.repos.keys())

    @property
    def primary(self) -> RepoMap:
        """Return the first repo map (convenience for single-repo projects)."""
        if not self.repos:
            return RepoMap()
        return next(iter(self.repos.values()))

    def all_pipeline_steps(self) -> list[dict]:
        """Merged pipeline steps across all repos, tagged with repo_label."""
        steps = []
        for label, rm in self.repos.items():
            for step in rm.pipeline_steps:
                tagged = {**step, "repo": label}
                steps.append(tagged)
        return steps

    def all_software(self) -> list[dict]:
        """Merged software stack across all repos, deduplicated by name."""
        seen = {}
        for label, rm in self.repos.items():
            for sw in rm.software_stack:
                key = sw.get("name", "")
                if key not in seen:
                    seen[key] = {**sw, "repo": label}
        return list(seen.values())

    def all_parameters(self) -> dict[str, Any]:
        """Merged parameters across all repos, prefixed with repo label."""
        merged = {}
        for label, rm in self.repos.items():
            for k, v in rm.parameters.items():
                merged[f"{label}.{k}"] = v
        return merged

    def summary(self) -> str:
        lines = []
        for label, rm in self.repos.items():
            lines.append(f"  [{label}] {rm.repo_path}")
            lines.append(f"    files: {len(rm.file_tree.splitlines()) if rm.file_tree else 0}")
            lines.append(f"    pipeline steps: {len(rm.pipeline_steps)}")
            lines.append(f"    software: {len(rm.software_stack)}")
        return "\n".join(lines) if lines else "  (no repos registered)"


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
    repo_paths: list[dict] = field(default_factory=list)
    # Each entry: {"path": str, "label": str}
    journal_name: str = ""
    extra_context: str = ""       # anything the user wants to inject
    target_audience: str = ""

    # Author vision (loaded from PAPER_VISION.md in primary repo)
    author_vision: AuthorVision = field(default_factory=AuthorVision)

    # Layer 1 outputs
    repo_registry: RepoRegistry = field(default_factory=RepoRegistry)
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

    # ── Backward compatibility ─────────────────────────────────────────────────

    @property
    def repo_path(self) -> str:
        """Return the first repo path (backward compat for single-repo usage)."""
        if self.repo_paths:
            return self.repo_paths[0]["path"]
        return ""

    @repo_path.setter
    def repo_path(self, value: str):
        """Set a single repo path (backward compat)."""
        if self.repo_paths:
            self.repo_paths[0]["path"] = value
        else:
            self.repo_paths = [{"path": value, "label": "main"}]

    @property
    def repo_map(self) -> RepoMap:
        """Return the primary repo map (backward compat for single-repo usage)."""
        return self.repo_registry.primary

    @repo_map.setter
    def repo_map(self, value: RepoMap):
        """Set the primary repo map (backward compat)."""
        label = value.repo_label or "main"
        self.repo_registry.repos[label] = value

    def _tool_read_kb(self, field: str, subfield: str = "") -> str:
        """Read a KB field as a formatted string (used in task prompts)."""
        obj = getattr(self, field, None)
        if obj is None:
            return f"KB field '{field}' not found."
        if subfield:
            obj = getattr(obj, subfield, None) or (
                obj.get(subfield) if isinstance(obj, dict) else None
            )
            if obj is None:
                return f"KB subfield '{field}.{subfield}' not found."
        if hasattr(obj, "__dict__"):
            return json.dumps(obj.__dict__, indent=2, default=str)
        return json.dumps(obj, indent=2, default=str)

    # ── Core methods ───────────────────────────────────────────────────────────

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
        repo_lines = []
        for rp in self.repo_paths:
            repo_lines.append(f"    [{rp['label']}] {rp['path']}")
        repo_str = "\n".join(repo_lines) if repo_lines else "    (not set)"
        total_steps = len(self.repo_registry.all_pipeline_steps())
        vision_str = (f"loaded ({self.author_vision.narrative_angle or 'no angle'})"
                      if self.author_vision.one_sentence_claim else "not loaded")
        lines = [
            "── Knowledge Base Status ──────────────────────────────",
            f"  Repos         :",
            repo_str,
            f"  Author vision : {vision_str}",
            f"  Journal       : {self.journal_name or '(not set)'}",
            f"  Pipeline steps: {total_steps}",
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
