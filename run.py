#!/usr/bin/env python3
"""
run.py
──────
Command-line entry point for the Manuscript Agent Team.

Usage examples:

  # Full pipeline
  python run.py --repo /path/to/repo --journal "PLOS Genetics" \
      --context "Study of Neanderthal introgression patterns in sub-Saharan Africa"

  # Extraction only (useful to inspect KB before writing)
  python run.py --repo /path/to/repo --journal "PLOS Genetics" --phases 1

  # Resume from writing (if extraction KB already saved)
  python run.py --repo /path/to/repo --journal "PLOS Genetics" \
      --load kb_phase1.json --phases 2 3 4 5

  # Run a revision cycle after manually editing the draft
  python run.py --repo /path/to/repo --journal "PLOS Genetics" \
      --load kb_phase2.json --revision

  # Dry run (print plan without calling API)
  python run.py --repo /path/to/repo --journal "PLOS Genetics" --dry-run
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()


def load_kb_from_json(path: str):
    """Partially restore a KnowledgeBase from a saved JSON snapshot."""
    from knowledge_base import (
        KnowledgeBase, RepoMap, ResultsStore, MethodsSpec,
        JournalSpec, ManuscriptDraft, AuditReport, ReviewPackage
    )
    with open(path) as f:
        data = json.load(f)

    kb = KnowledgeBase()
    # Restore scalar fields
    for field in ['repo_path', 'journal_name', 'extra_context', 'target_audience']:
        setattr(kb, field, data.get(field, ''))

    # Restore structured sub-objects (best-effort)
    def restore(cls, d):
        obj = cls()
        if isinstance(d, dict):
            for k, v in d.items():
                if hasattr(obj, k):
                    try:
                        setattr(obj, k, v)
                    except Exception:
                        pass
        return obj

    kb.repo_map    = restore(RepoMap,    data.get('repo_map', {}))
    kb.methods_spec = restore(MethodsSpec, data.get('methods_spec', {}))
    kb.journal_spec = restore(JournalSpec, data.get('journal_spec', {}))
    kb.draft       = restore(ManuscriptDraft, data.get('draft', {}))
    kb.audit       = restore(AuditReport, data.get('audit', {}))
    kb.review      = restore(ReviewPackage, data.get('review', {}))

    # Results store entries
    rs_data = data.get('results_store', {})
    if isinstance(rs_data, dict) and 'entries' in rs_data:
        kb.results_store.entries = rs_data['entries']

    kb.agent_log = data.get('agent_log', [])
    return kb


def dry_run(args):
    """Print the planned pipeline without making any API calls."""
    console.print(Panel(
        f"[bold]DRY RUN — Manuscript Agent Team[/bold]\n\n"
        f"Repo        : {args.repo}\n"
        f"Journal     : {args.journal}\n"
        f"Phases      : {args.phases or [1,2,3,4,5]}\n"
        f"Context     : {args.context or '(none)'}\n"
        f"Load KB from: {args.load or '(none)'}",
        style="blue"
    ))

    phase_agents = {
        1: ["RepoCartographer", "ResultsExtractor", "MethodsFormaliser", "JournalProfiler"],
        2: ["MethodsWriter", "ResultsWriter", "IntroductionWriter", "DiscussionWriter"],
        3: ["StatsAuditor", "DomainConsistencyChecker", "ReproducibilityChecker"],
        4: ["MockReviewer×3", "MockEditor", "RevisionCoordinator"],
        5: ["AbstractWriter"],
    }
    phase_names = {
        1: "Extraction",
        2: "Writing",
        3: "Auditing",
        4: "Peer Review",
        5: "Abstract",
    }

    phases = args.phases or [1, 2, 3, 4, 5]
    total_agents = 0
    for p in phases:
        agents = phase_agents.get(p, [])
        total_agents += len(agents)
        console.print(f"\n  Phase {p} — {phase_names.get(p, '')}")
        for a in agents:
            console.print(f"    → {a}")

    console.print(f"\n  Total agents: {total_agents}")
    console.print(f"  Estimated API calls: {total_agents * 8}–{total_agents * 15}")
    console.print(f"\n  Remove --dry-run to execute.")


def main():
    parser = argparse.ArgumentParser(
        description="Manuscript Agent Team — generate a manuscript from a GitHub repo"
    )
    parser.add_argument("--repo", required=True,
                        help="Path to the local repository")
    parser.add_argument("--journal", required=True,
                        help="Target journal name (e.g. 'PLOS Genetics')")
    parser.add_argument("--context", default="",
                        help="Free-text description of the project for agent context")
    parser.add_argument("--audience", default="computational geneticists",
                        help="Target audience description")
    parser.add_argument("--phases", type=int, nargs="+",
                        help="Which phases to run (1-5). Default: all.")
    parser.add_argument("--load", default="",
                        help="Path to a saved KB JSON to resume from")
    parser.add_argument("--save", default="kb_final.json",
                        help="Path to save the final KB JSON")
    parser.add_argument("--revision", action="store_true",
                        help="Run a revision cycle (re-audit + re-review)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-agent verbose output")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the planned pipeline without running")

    args = parser.parse_args()

    # Warn if ANTHROPIC_API_KEY is set — it overrides subscription auth
    if os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[yellow]Warning: ANTHROPIC_API_KEY is set. Claude Code will use "
            "API pay-per-token billing instead of your Max subscription.\n"
            "Run: unset ANTHROPIC_API_KEY   to use your subscription.[/yellow]"
        )

    # Check repo exists
    if not Path(args.repo).exists():
        console.print(f"[red]Error: Repo path does not exist: {args.repo}[/red]")
        sys.exit(1)

    if args.dry_run:
        dry_run(args)
        return

    # Build or restore KB
    from knowledge_base import KnowledgeBase
    from orchestrator import ManuscriptOrchestrator

    if args.load:
        console.print(f"Loading KB from {args.load}...")
        kb = load_kb_from_json(args.load)
        kb.repo_path = args.repo      # override in case path changed
        kb.journal_name = args.journal
    else:
        kb = KnowledgeBase(
            repo_path=str(Path(args.repo).resolve()),
            journal_name=args.journal,
            extra_context=args.context,
            target_audience=args.audience,
        )

    orch = ManuscriptOrchestrator(kb, verbose=not args.quiet)

    if args.revision:
        kb = orch.run_revision()
    else:
        kb = orch.run(phases=args.phases)

    # Save final KB
    kb.save(args.save)
    console.print(f"\n[green]Final KB saved → {args.save}[/green]")

    # Print the draft if available
    draft_text = kb.draft.full_text()
    if draft_text:
        draft_path = args.save.replace('.json', '_draft.txt')
        with open(draft_path, 'w') as f:
            f.write(draft_text)
        console.print(f"[green]Draft text saved → {draft_path}[/green]")


if __name__ == "__main__":
    main()
