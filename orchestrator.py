"""
orchestrator.py
───────────────
The Orchestrator manages the full manuscript pipeline.

It sequences agents, checks gate conditions between phases, handles failures,
and produces a final status report. It is also the entry point for revision rounds.

Pipeline phases:
  Phase 1 (Extraction)  — Cartographer → ResultsExtractor → MethodsFormaliser
                         → JournalProfiler        [parallel-safe but run in series]
  Phase 2 (Writing)     — MethodsWriter → ResultsWriter → IntroductionWriter
                         → DiscussionWriter  [in this order: methods must precede results]
  Phase 3 (Auditing)    — StatsAuditor → DomainConsistencyChecker → ReproducibilityChecker
  Phase 4 (Review)      — MockReviewer × 3  →  MockEditor  →  RevisionCoordinator
  Phase 5 (Abstract)    — AbstractWriter   [always last]
"""

from __future__ import annotations
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import print as rprint

from knowledge_base import KnowledgeBase
from agents.layer1 import (
    RepoCartographer, ResultsExtractor, MethodsFormaliser, JournalProfiler
)
from agents.layer2 import (
    IntroductionWriter, MethodsWriter, ResultsWriter,
    DiscussionWriter, AbstractWriter,
    StatsAuditor, DomainConsistencyChecker, ReproducibilityChecker,
    MockReviewer, MockEditor, RevisionCoordinator
)

console = Console()


# ── Gate conditions between phases ───────────────────────────────────────────

def gate_extraction_complete(kb: KnowledgeBase) -> tuple[bool, str]:
    """Layer 1 must be complete before writing begins."""
    issues = []
    if not kb.repo_registry.all_pipeline_steps():
        issues.append("No repo maps have pipeline steps")
    if not kb.results_store.entries:
        issues.append("Results store is empty")
    if not kb.methods_spec.notation_registry:
        issues.append("Notation registry is empty")
    if not kb.journal_spec.journal_name:
        issues.append("Journal spec not populated")
    return (len(issues) == 0, "; ".join(issues) if issues else "OK")


def gate_writing_complete(kb: KnowledgeBase) -> tuple[bool, str]:
    """Core sections must exist before auditing."""
    missing = [s for s in ['methods', 'results', 'introduction', 'discussion']
               if not getattr(kb.draft, s)]
    return (len(missing) == 0,
            f"Missing sections: {missing}" if missing else "OK")


def gate_audit_passed(kb: KnowledgeBase) -> tuple[bool, str]:
    """Audit must pass (zero fatal issues) before review."""
    n_fatal = kb.audit.n_fatal()
    return (n_fatal == 0,
            f"{n_fatal} fatal audit issues remain" if n_fatal > 0 else "OK")


# ── Orchestrator ──────────────────────────────────────────────────────────────

class ManuscriptOrchestrator:
    """
    Runs the full agent pipeline for manuscript generation.

    Usage:
        kb = KnowledgeBase(
            repo_path="/path/to/repo",
            journal_name="PLOS Genetics",
            extra_context="Study of Neanderthal introgression in African populations"
        )
        orch = ManuscriptOrchestrator(kb)
        orch.run()
    """

    def __init__(self, kb: KnowledgeBase, verbose: bool = True,
                 skip_phases: Optional[list[int]] = None):
        self.kb = kb
        self.verbose = verbose
        self.skip_phases = skip_phases or []
        self.phase_results: dict[int, bool] = {}

    def _run_agent(self, agent_class, **kwargs) -> bool:
        """Instantiate and run one agent, with timing and error handling."""
        try:
            agent = agent_class(kb=self.kb, repo_root=self.kb.repo_path, **kwargs)
            t0 = time.time()
            success = agent.run(verbose=self.verbose)
            elapsed = time.time() - t0
            status = "✓" if success else "✗"
            console.print(f"  {status} {agent.name}  ({elapsed:.1f}s)",
                          style="green" if success else "red")
            return success
        except Exception as e:
            console.print(f"  ✗ {agent_class.__name__} FAILED: {e}", style="red bold")
            self.kb.log(agent_class.__name__, "error", str(e))
            return False

    def _check_gate(self, gate_fn, phase_name: str) -> bool:
        passed, msg = gate_fn(self.kb)
        if passed:
            console.print(f"\n  ✓ Gate [{phase_name}]: {msg}", style="green")
        else:
            console.print(f"\n  ✗ Gate [{phase_name}] FAILED: {msg}", style="red bold")
        return passed

    def _phase_header(self, n: int, title: str):
        console.print(Panel(f"[bold white]PHASE {n}: {title}[/bold white]",
                            style="blue", expand=False))

    # ── Phase runners ─────────────────────────────────────────────────────────

    def run_phase_1(self) -> bool:
        """Layer 1: Extraction agents."""
        self._phase_header(1, "EXTRACTION")
        results = [
            self._run_agent(RepoCartographer),
            self._run_agent(ResultsExtractor),
            self._run_agent(MethodsFormaliser),
            self._run_agent(JournalProfiler),
        ]
        ok = all(results)
        if ok:
            ok = self._check_gate(gate_extraction_complete, "extraction complete")
        return ok

    def run_phase_2(self) -> bool:
        """Layer 2a: Writing agents (order matters)."""
        self._phase_header(2, "WRITING")
        # Methods must come first (auditors check it against the spec)
        # Results after Methods (results cite methods)
        # Introduction and Discussion after Results
        results = [
            self._run_agent(MethodsWriter),
            self._run_agent(ResultsWriter),
            self._run_agent(IntroductionWriter),
            self._run_agent(DiscussionWriter),
        ]
        ok = all(results)
        if ok:
            ok = self._check_gate(gate_writing_complete, "writing complete")
        return ok

    def run_phase_3(self) -> bool:
        """Layer 2b: Auditing agents."""
        self._phase_header(3, "AUDITING")
        results = [
            self._run_agent(StatsAuditor),
            self._run_agent(DomainConsistencyChecker),
            self._run_agent(ReproducibilityChecker),
        ]
        # Consolidate audit pass/fail
        all_issues = (self.kb.audit.stats_issues
                      + self.kb.audit.domain_issues)
        n_fatal = sum(1 for i in all_issues if i.get('severity') == 'fatal')
        self.kb.audit.all_passed = (n_fatal == 0)

        console.print(f"\n  Audit summary:", style="bold")
        console.print(self.kb.audit.summary())

        ok = self._check_gate(gate_audit_passed, "audit passed")
        return ok

    def run_phase_4(self) -> bool:
        """Layer 2c: Mock review panel."""
        self._phase_header(4, "PEER REVIEW")
        results = [
            self._run_agent(MockReviewer, profile="methodological"),
            self._run_agent(MockReviewer, profile="biological"),
            self._run_agent(MockReviewer, profile="breadth"),
            self._run_agent(MockEditor),
            self._run_agent(RevisionCoordinator),
        ]
        return all(results)

    def run_phase_5(self) -> bool:
        """Abstract — always last."""
        self._phase_header(5, "ABSTRACT")
        return self._run_agent(AbstractWriter)

    # ── Full pipeline ─────────────────────────────────────────────────────────

    def run(self, phases: Optional[list[int]] = None) -> KnowledgeBase:
        """
        Run the complete pipeline.

        Parameters
        ----------
        phases : list of int, optional
            Which phases to run (1-5). Default is all phases.
            Useful for resuming a partial run:
              orch.run(phases=[3, 4, 5])  # skip extraction and writing
        """
        phases_to_run = phases or [1, 2, 3, 4, 5]

        repo_lines = "\n".join(
            f"  [{rp['label']}] {rp['path']}" for rp in self.kb.repo_paths
        )
        console.print(Panel(
            f"[bold]MANUSCRIPT AGENT TEAM[/bold]\n"
            f"Repos:\n{repo_lines}\n"
            f"Journal: {self.kb.journal_name}\n"
            f"Phases: {phases_to_run}",
            style="bold blue"
        ))

        phase_fns = {
            1: self.run_phase_1,
            2: self.run_phase_2,
            3: self.run_phase_3,
            4: self.run_phase_4,
            5: self.run_phase_5,
        }

        for n in phases_to_run:
            fn = phase_fns.get(n)
            if fn is None:
                console.print(f"Unknown phase {n}, skipping.", style="yellow")
                continue
            success = fn()
            self.phase_results[n] = success
            if not success and n in [1, 2]:  # Extraction and writing are blockers
                console.print(
                    f"\n[red bold]Phase {n} failed — cannot continue.[/red bold]"
                )
                break
            # Auto-save after each phase
            save_path = f"kb_phase{n}.json"
            self.kb.save(save_path)
            console.print(f"\n  KB saved → {save_path}", style="dim")

        self._print_final_report()
        return self.kb

    def run_revision(self) -> KnowledgeBase:
        """
        Run a revision cycle: re-audit → re-review.
        Call this after manually addressing issues flagged in the review.
        """
        console.print(Panel("[bold]REVISION CYCLE[/bold]", style="yellow"))
        # Clear previous audit and review
        from knowledge_base import AuditReport, ReviewPackage
        self.kb.audit = AuditReport()
        self.kb.review = ReviewPackage()
        self.run(phases=[3, 4, 5])
        return self.kb

    # ── Reporting ─────────────────────────────────────────────────────────────

    def _print_final_report(self):
        console.print("\n")
        console.print(Panel("[bold white]PIPELINE COMPLETE — FINAL REPORT[/bold white]",
                            style="bold blue"))

        # Phase results table
        table = Table(title="Phase Results")
        table.add_column("Phase", style="cyan")
        table.add_column("Description")
        table.add_column("Status", style="bold")

        phase_names = {
            1: "Extraction",
            2: "Writing",
            3: "Auditing",
            4: "Peer Review",
            5: "Abstract",
        }
        for n, name in phase_names.items():
            status = self.phase_results.get(n)
            if status is None:
                s, style = "SKIPPED", "yellow"
            elif status:
                s, style = "✓ PASS", "green"
            else:
                s, style = "✗ FAIL", "red"
            table.add_row(str(n), name, f"[{style}]{s}[/{style}]")
        console.print(table)

        # Draft word counts
        wc_table = Table(title="Draft Word Counts")
        wc_table.add_column("Section")
        wc_table.add_column("Words", justify="right")
        wc_table.add_column("Limit", justify="right")
        for sec in ['abstract','introduction','methods','results','discussion']:
            wc = self.kb.draft.word_count(sec)
            limit = self.kb.journal_spec.word_limits.get(sec, 0)
            over = wc > limit > 0
            style = "red" if over else "green"
            wc_table.add_row(
                sec.capitalize(),
                f"[{style}]{wc}[/{style}]",
                str(limit) if limit else "—"
            )
        console.print(wc_table)

        # Audit summary
        console.print(f"\n[bold]Audit:[/bold] {self.kb.audit.summary()}")

        # Review summary
        if self.kb.review.editor_decision:
            style = {"Accept": "green", "Minor Revision": "yellow",
                     "Major Revision": "orange3", "Reject": "red"}.get(
                self.kb.review.editor_decision, "white")
            console.print(
                f"\n[bold]Editor decision:[/bold] "
                f"[{style}]{self.kb.review.editor_decision}[/{style}]"
            )

        console.print(f"\n[bold]Agent log:[/bold] {len(self.kb.agent_log)} entries")
        console.print(self.kb.status())
