# Manuscript Agent Team

A multi-agent pipeline that turns a computational genetics GitHub repository
into a journal-ready manuscript draft, complete with statistical audit and
mock peer review.

Runs on a **Claude Max subscription** via the Claude Agent SDK — no
pay-per-token API billing required.

---

## How it works

You point the pipeline at a repo and name a target journal. A team of
specialised agents runs in sequence:

```
Your repo  ──►  Extract  ──►  Write  ──►  Audit  ──►  Review  ──►  Abstract
               (4 agents)   (4 agents)  (3 agents)  (5 agents)   (1 agent)
```

Every agent reads from and writes to a shared **KnowledgeBase** — a typed
Python object that flows through the entire pipeline. No agent passes prose
directly to another. Every number in the manuscript is traceable to a locked
entry in the `ResultsStore`, populated before any writing begins.

---

## Quick start

### Prerequisites

```bash
# Node.js v18+ (required by Claude Code CLI)
node --version

# Install Claude Code and log in with your Max subscription
npm install -g @anthropic-ai/claude-code
claude login              # use your claude.ai account — not an API key

# Install Python dependencies
pip install -r requirements.txt

# Critical: ensure no API key is set (it overrides subscription billing)
unset ANTHROPIC_API_KEY
```

### Run

```bash
# Dry run — see the plan without spending any subscription
python run.py \
  --repo /path/to/your/genetics/repo \
  --journal "PLOS Genetics" \
  --dry-run

# Phase 1 only — extract the KB and inspect it before committing to full run
python run.py \
  --repo /path/to/your/genetics/repo \
  --journal "PLOS Genetics" \
  --context "Local ancestry analysis identifying Neanderthal introgressed regions" \
  --phases 1

# Full pipeline
python run.py \
  --repo /path/to/your/genetics/repo \
  --journal "PLOS Genetics" \
  --context "Local ancestry analysis identifying Neanderthal introgressed regions"
```

---

## Telling the agents what you want: `PAPER_VISION.md`

Place a file called `PAPER_VISION.md` in the root of your **analysis repo**
(not this repo). The pipeline reads it before anything else. It lets you
communicate your scientific vision, narrative angle, and constraints directly
to the agents — without them having to guess.

```markdown
# Paper Vision

## The one-sentence claim
This paper presents a significance framework for ancestry tract lengths
that identifies genomic regions deviating from the exponential null,
demonstrated on Neanderthal introgression in sub-Saharan African genomes.

## The narrative angle
Methods-forward. The statistical framework is the contribution.
The biological application is the demonstration, not the headline.

## Key findings to foreground
1. The probability matrix as a unified framework connecting segment
   calling to significance testing
2. The Fisher joint test detects regions where both ancestry classes
   show simultaneous anomalous tract lengths
3. [your empirical finding here]

## Key findings to background
- Specific parameter choices are illustrative; do not present as
  calibrated biological estimates

## Connections to previous work
- Builds on Pool & Nielsen 2009 tract-length model
- Distinct from HAPMIX/RFMix (callers vs significance framework)
- Relevant to Platt et al. 2026 (IBDmix in sub-Saharan Africa)

## Things the paper must NOT claim
- That the exponential null is the only valid model
- That the method detects selection (it detects unusual tract lengths)

## Preferred journals (in order)
1. PLOS Genetics
2. Genome Research
3. Molecular Biology and Evolution

## Tone
Precise and technical. Write for readers who will implement the method.
```

---

## Pipeline phases

| Phase | What runs | Gate |
|-------|-----------|------|
| 1 — Extraction | RepoCartographer, ResultsExtractor, MethodsFormaliser, JournalProfiler | All KB fields must be populated |
| 2 — Writing | MethodsWriter, ResultsWriter, IntroductionWriter, DiscussionWriter | All four sections must exist |
| 3 — Auditing | StatsAuditor, DomainConsistencyChecker, ReproducibilityChecker | Zero fatal issues |
| 4 — Peer Review | MockReviewer ×3, MockEditor, RevisionCoordinator | — |
| 5 — Abstract | AbstractWriter | — |

The KB is saved as JSON after each phase (`kb_phase1.json` etc.), so a
failed or interrupted run can always be resumed.

---

## Where you intervene

The pipeline is designed for you to direct, not just receive. Key points:

**After Phase 1** — inspect `kb_phase1.json`. Check that the pipeline
steps, results, and notation registry are accurate. Edit them directly in
the JSON before running Phase 2 if anything is wrong.

**Before Phase 2** — if you have a strong view on narrative angle or
journal, set `kb.journal_name` and review `kb.extra_context` in the
saved JSON before loading it for the writing phase.

**After Phase 2** — read the Discussion section. This is where
overclaiming and underclaiming happen. Edit `kb.draft.discussion` in the
JSON before auditing.

**After Phase 4** — read `kb.review.editor_letter` and
`kb.review.ranked_action_list`. The `RevisionCoordinator` maps concerns
to agents; you decide which to address and how.

```bash
# Resume from a checkpoint and re-run from Phase 3
python run.py \
  --repo /path/to/repo \
  --journal "PLOS Genetics" \
  --load kb_phase2.json \
  --phases 3 4 5

# Revision cycle after editing the draft
python run.py \
  --repo /path/to/repo \
  --journal "PLOS Genetics" \
  --load kb_phase2.json \
  --revision
```

---

## Programmatic use

```python
from knowledge_base import KnowledgeBase
from orchestrator import ManuscriptOrchestrator

kb = KnowledgeBase(
    repo_path="/path/to/repo",
    journal_name="Genome Research",
    extra_context="Population genomics of admixture using tract-length statistics",
    target_audience="computational geneticists and evolutionary biologists"
)

orch = ManuscriptOrchestrator(kb, verbose=True)
kb = orch.run()

# Access outputs
print(kb.draft.full_text())
print(kb.review.editor_letter)
print(kb.audit.summary())
```

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    SHARED KNOWLEDGE BASE                        │
│  repo_map │ results_store │ methods_spec │ journal_spec │ draft │
│  audit    │ review        │ agent_log                           │
└────────────────────────────┬────────────────────────────────────┘
                             │  read/write via MCP tools
         ┌───────────────────┴──────────────────────┐
         │ LAYER 1 — EXTRACTION                     │
         │  RepoCartographer  → repo_map             │
         │  ResultsExtractor  → results_store (locked)│
         │  MethodsFormaliser → methods_spec         │
         │  JournalProfiler   → journal_spec         │
         └───────────────────┬──────────────────────┘
                             │ gate: KB fully populated
         ┌───────────────────┴──────────────────────┐
         │ LAYER 2a — WRITING                       │
         │  MethodsWriter   → draft.methods          │
         │  ResultsWriter   → draft.results          │
         │  IntroductionWriter → draft.introduction  │
         │  DiscussionWriter → draft.discussion      │
         └───────────────────┬──────────────────────┘
                             │ gate: all sections present
         ┌───────────────────┴──────────────────────┐
         │ LAYER 2b — AUDITING                      │
         │  StatsAuditor → audit.stats_issues        │
         │  DomainChecker → audit.domain_issues      │
         │  ReproducibilityChecker → audit.repro     │
         └───────────────────┬──────────────────────┘
                             │ gate: zero fatal issues
         ┌───────────────────┴──────────────────────┐
         │ LAYER 2c — PEER REVIEW                   │
         │  MockReviewer ×3 → review.reviewer_reports│
         │  MockEditor → review.editor_decision      │
         │  RevisionCoordinator → response template  │
         └───────────────────┬──────────────────────┘
                             │
         ┌───────────────────┴──────────────────────┐
         │ PHASE 5 — ABSTRACT (always last)          │
         └───────────────────────────────────────────┘
```

Each agent communicates with the shared KB through five MCP tools:
`read_file`, `list_directory`, `read_kb`, `write_kb`, and `finish`.
The agentic tool-use loop is managed internally by Claude Code.

---

## Adding agents

Subclass `BaseAgent` and implement `name`, `system_prompt`, and
`task_prompt`. See `CLAUDE.md` for the full pattern and rules.

The most important rule: **Layer 1 agents may read the repo and write
to the KB. Layer 2 agents may only read the KB** — never the repo directly.

---

## Subscription usage

A full single pipeline run uses ~14 Claude Code sessions. This is comfortably
within a Max plan's daily allocation for typical usage. Running many revision
cycles on the same day may approach limits; use `--phases` to run only what
changed.

If you hit a rolling window limit mid-run, wait for it to reset and resume
with `--load kb_phaseN.json --phases N+1 ...`.

See `SETUP.md` for the full setup guide, billing explanation, and
troubleshooting.

---

## Planned features

- **`PAPER_VISION.md` integration** — the `RepoCartographer` reads a vision
  file from the target repo and loads it into the KB before any other agent
  runs, giving all writers access to the author's framing intent
- **Journal Selector (Phase 1.5)** — two agents score candidate journals
  and explain the framing trade-offs before a human chooses
- **Human gate system** — the orchestrator pauses at six defined points for
  author input on the KB, argument skeleton, and Discussion before finalising
- **`NarrativeSpec` KB field** — stores the chosen narrative angle and
  forbidden claims; propagated to all writing and auditing agents

---

## License

MIT
