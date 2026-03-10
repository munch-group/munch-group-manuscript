#!/usr/bin/env python3
"""
run.py
──────
Command-line entry point for the Manuscript Agent Team.

Usage examples:

  # Full pipeline (single repo)
  python run.py --repo /path/to/repo --journal "PLOS Genetics" \
      --context "Study of Neanderthal introgression patterns in sub-Saharan Africa"

  # Multi-repo pipeline (use account/repo labels matching PAPER_VISION.md)
  python run.py \
      --repo munch-group/analysis=/path/to/analysis \
      --repo munch-group/sim-toolkit=/path/to/sim \
      --journal "PLOS Genetics"

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
        KnowledgeBase, RepoMap, RepoRegistry, ResultsStore, MethodsSpec,
        JournalSpec, ManuscriptDraft, AuditReport, ReviewPackage,
        AuthorVision, RepoRole
    )
    with open(path) as f:
        data = json.load(f)

    kb = KnowledgeBase()
    # Restore scalar fields
    for fld in ['journal_name', 'extra_context', 'target_audience']:
        setattr(kb, fld, data.get(fld, ''))

    # Restore repo_paths (new format: list of dicts)
    if 'repo_paths' in data and isinstance(data['repo_paths'], list):
        kb.repo_paths = data['repo_paths']
    elif 'repo_path' in data and isinstance(data['repo_path'], str):
        # Backward compat: old single-repo format
        kb.repo_paths = [{"path": data['repo_path'], "label": "main"}]

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

    # Restore repo_registry (new) or fall back to repo_map (old)
    reg_data = data.get('repo_registry', {})
    if isinstance(reg_data, dict) and 'repos' in reg_data:
        registry = RepoRegistry()
        for label, rm_dict in reg_data['repos'].items():
            rm = restore(RepoMap, rm_dict)
            rm.repo_label = label
            registry.repos[label] = rm
        kb.repo_registry = registry
    elif 'repo_map' in data:
        # Backward compat: old single repo_map
        rm = restore(RepoMap, data['repo_map'])
        rm.repo_label = "main"
        rm.repo_path = kb.repo_path
        kb.repo_registry = RepoRegistry(repos={"main": rm})

    # Restore author_vision
    av_data = data.get('author_vision', {})
    if isinstance(av_data, dict):
        av = restore(AuthorVision, av_data)
        # Restore nested RepoRole objects
        rr_data = av_data.get('repo_roles', {})
        if isinstance(rr_data, dict):
            av.repo_roles = {
                rid: restore(RepoRole, rd) if isinstance(rd, dict) else rd
                for rid, rd in rr_data.items()
            }
        kb.author_vision = av

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


def _parse_repos(raw_repos: list[str]) -> list[dict]:
    """
    Parse --repo arguments into [{path, label}] dicts.

    Accepts three formats:
      --repo /path/to/repo                          → label = directory name
      --repo munch-group/analysis=/path/to/repo      → label = account/repo
      --repo analysis=/path/to/repo                  → label = analysis

    The account/repo format is preferred for multi-repo projects because
    PAPER_VISION.md uses it to reference repos.
    """
    result = []
    for r in raw_repos:
        if "=" in r:
            label, path = r.split("=", 1)
        else:
            path = r
            label = Path(path).name
        result.append({"path": str(Path(path).resolve()), "label": label})
    # Ensure labels are unique
    seen = set()
    for entry in result:
        base = entry["label"]
        i = 2
        while entry["label"] in seen:
            entry["label"] = f"{base}_{i}"
            i += 1
        seen.add(entry["label"])
    return result


def dry_run(args, repo_entries: list[dict]):
    """Print the planned pipeline without making any API calls."""
    repo_lines = "\n".join(f"  [{r['label']}] {r['path']}" for r in repo_entries)
    console.print(Panel(
        f"[bold]DRY RUN — Manuscript Agent Team[/bold]\n\n"
        f"Repos       :\n{repo_lines}\n"
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
    parser.add_argument("--repo", required=True, action="append",
                        help="Path to a local repository. May be repeated for multi-repo "
                             "projects. Use account/repo=path format to match "
                             "PAPER_VISION.md identifiers "
                             "(e.g. --repo munch-group/analysis=/path/to/repo).")
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

    # Parse and validate repo paths
    repo_entries = _parse_repos(args.repo)
    for entry in repo_entries:
        if not Path(entry["path"]).exists():
            console.print(f"[red]Error: Repo path does not exist: {entry['path']}[/red]")
            sys.exit(1)

    if args.dry_run:
        dry_run(args, repo_entries)
        return

    # Build or restore KB
    from knowledge_base import KnowledgeBase, RepoRegistry
    from orchestrator import ManuscriptOrchestrator

    if args.load:
        console.print(f"Loading KB from {args.load}...")
        kb = load_kb_from_json(args.load)
        kb.repo_paths = repo_entries  # override in case paths changed
        kb.journal_name = args.journal
    else:
        kb = KnowledgeBase(
            repo_paths=repo_entries,
            journal_name=args.journal,
            extra_context=args.context,
            target_audience=args.audience,
        )
        # Pre-register repos in the registry
        for entry in repo_entries:
            kb.repo_registry.add(entry["label"], entry["path"])

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
