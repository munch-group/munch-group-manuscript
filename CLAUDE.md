# CLAUDE.md — Manuscript Agent Team

This file is the authoritative technical reference for Claude Code working on
this project. Read it fully before making any changes. It describes the
architecture, all design decisions and their rationale, the complete data model,
how to extend the system, and what planned features are not yet implemented.

---

## What this project is

A multi-agent pipeline that turns a computational genetics GitHub repository
into a journal-ready manuscript. The user points it at a repo, names a target
journal, and the pipeline runs a structured sequence of specialised Claude
agents that extract, write, audit, and review the paper.

The system is designed to run on a **Claude Max subscription** via the
`claude-agent-sdk`, not via direct Anthropic API calls. Authentication flows
through `claude login`; no `ANTHROPIC_API_KEY` should be set.

---

## Repository layout

```
munch-group-manuscript/
├── CLAUDE.md              ← this file
├── README.md              ← user-facing documentation
├── SETUP.md               ← step-by-step setup for Claude Code / Max billing
├── requirements.txt       ← Python dependencies
├── run.py                 ← CLI entry point
├── knowledge_base.py      ← shared state object (all dataclasses)
├── base_agent.py          ← abstract base class + MCP server factory
├── orchestrator.py        ← sequences agents, enforces gate conditions
├── __init__.py
└── agents/
    ├── __init__.py
    ├── layer1.py           ← extraction agents (populate KB from repo)
    └── layer2.py           ← production agents (write, audit, review)
```

**Convention**: every file starts with a docstring explaining its purpose.
Maintain this. Do not add files without docstrings.

---

## Core design principles — do not violate these

### 1. Two-layer strict separation
Layer 1 agents (extraction) read the repository and populate the
KnowledgeBase. Layer 2 agents (production) read ONLY from the KB —
they never touch the repo directly. This prevents hallucination and
makes every manuscript claim traceable to a specific KB entry.

### 2. The ResultsStore is locked
`ResultsStore.entries` is populated exclusively by `ResultsExtractor`.
Writing agents may call `read_kb(field="results_store")` to cite values,
but they must never add to it. The `write_kb` tool writes to the store
only during Phase 1. If a number is not in the store, a writer must
emit `[MISSING RESULT: description]` — never invent a value.

### 3. One notation registry, used by all writers
`MethodsSpec.notation_registry` (symbol → definition) is the single
authoritative source for all mathematical notation. Inconsistency in
notation is a major manuscript error. The `MethodsFormaliser` builds
it; all writers read it. Never let two agents define the same symbol
differently.

### 4. Abstract always last
`AbstractWriter` runs in Phase 5, after all sections are written and
audited. It distils from the final text. Never move it earlier.

### 5. Gate conditions are hard stops
Gates between phases are not advisory — a failed gate aborts the
pipeline (for phases 1 and 2; later phases warn but continue). Do not
weaken gates when extending the system. If a gate is wrong, fix the
gate condition, not the enforcement.

### 6. KB is the only inter-agent communication channel
Agents do not call each other. They communicate exclusively through
the shared `KnowledgeBase` object. Adding direct agent-to-agent calls
would break the traceability model.

---

## KnowledgeBase data model (`knowledge_base.py`)

The `KnowledgeBase` dataclass is passed to every agent. It has these
top-level fields:

### Input fields (set by the user before pipeline starts)
```python
repo_paths: list[dict]  # [{"path": str, "label": str}, ...]
                         # supports single or multiple repos
journal_name: str        # e.g. "PLOS Genetics"
extra_context: str       # free-text description of the project
target_audience: str     # e.g. "computational population geneticists"
```

**Backward compatibility**: `kb.repo_path` (str property) still works —
it reads/writes the first entry in `repo_paths`. This allows existing
code and old KB JSON snapshots (with a single `repo_path` string) to
work without changes.

### Author vision (loaded from PAPER_VISION.md)
```python
author_vision: AuthorVision
    .one_sentence_claim: str
    .primary_audience: str
    .narrative_angle: str           # "methods-forward" | "biology-forward" | "tools-forward"
    .key_findings_foreground: list[str]
    .key_findings_background: list[str]
    .connections_to_previous_work: list[str]
    .forbidden_claims: list[str]
    .preferred_journals: list[str]
    .tone: str
    .repo_roles: dict[str, RepoRole]  # repo_id (account/repo) → RepoRole
    .raw_markdown: str                # full PAPER_VISION.md text

RepoRole:
    .repo_id: str                   # e.g. "munch-group/analysis"
    .role: str                      # free-text role description
    .focus: list[str]               # paths/areas to focus on
    .ignore: list[str]              # paths/areas to skip
    .relationships: list[str]       # how this repo connects to others
```

`RepoCartographer` reads `PAPER_VISION.md` from the primary repo before
exploring any repository. If it exists, the agent parses it and writes
all fields to `kb.author_vision`. The `repo_roles` section guides which
parts of each repo to focus on or ignore.

All writing agents receive the author vision in their task prompts via
the `_vision_context()` helper in `layer2.py`. The `DomainConsistencyChecker`
also checks the manuscript against `forbidden_claims`.

### Layer 1 outputs
```python
repo_registry: RepoRegistry
    .repos: dict[str, RepoMap]       # label → RepoMap
    .labels: list[str]               # property: all registered labels
    .primary: RepoMap                # property: first repo map
    .all_pipeline_steps() → list     # merged steps tagged with "repo" key
    .all_software() → list           # deduplicated software across repos
    .all_parameters() → dict         # merged params prefixed "label.param"
    .summary() → str                 # formatted overview of all repos

repo_map: RepoMap                    # property alias → repo_registry.primary
    .repo_label: str                 # label for this repo
    .repo_path: str                  # absolute path to this repo
    .file_tree: str                  # formatted directory listing
    .pipeline_steps: list[dict]      # {name, script, inputs, outputs, description}
    .software_stack: list[dict]      # {name, version, purpose}
    .parameters: dict[str, Any]      # param_name → value
    .doc_vs_code_mismatches: list[str]
    .key_algorithms: list[str]

results_store: ResultsStore
    .entries: dict[str, dict]         # result_id → {value, source_file, figure, claim, units, locked_at}
    # Methods: .add(), .get(), .summary()

methods_spec: MethodsSpec
    .notation_registry: dict[str, str]  # symbol → definition
    .model_definitions: list[str]
    .statistical_tests: list[dict]      # {name, null_hypothesis, statistic, null_distribution, correction}
    .pipeline_prose: str
    .parameter_table: list[dict]

journal_spec: JournalSpec
    .journal_name: str
    .scope: str
    .section_structure: list[str]
    .word_limits: dict[str, int]        # section → word count
    .figure_limit: int
    .citation_style: str
    .statistical_conventions: str
    .tone_notes: str
    .recent_paper_styles: list[str]
```

### Layer 2 outputs
```python
draft: ManuscriptDraft
    .title: str
    .abstract: str
    .introduction: str
    .methods: str
    .results: str
    .discussion: str
    .figure_legends: str
    .references: str
    # Methods: .word_count(section), .full_text()

audit: AuditReport
    .stats_issues: list[dict]           # {section, location, issue, severity}
    .domain_issues: list[dict]          # {section, location, issue, severity}
    .reproducibility_gaps: list[str]
    .all_passed: bool
    # severity values: "fatal" | "major" | "minor"
    # Methods: .n_fatal(), .summary()

review: ReviewPackage
    .reviewer_reports: list[dict]       # {reviewer_profile, summary, major_concerns, minor_concerns, recommendation}
    .editor_decision: str               # "Accept" | "Minor Revision" | "Major Revision" | "Reject"
    .editor_letter: str
    .ranked_action_list: list[str]
    .response_to_reviewers: str
```

### Provenance
```python
agent_log: list[dict]   # {agent, timestamp, action, summary} — append-only
```

### KB methods
- `kb.log(agent, action, summary)` — all agents must call this
- `kb.save(path)` — serialises to JSON; called by orchestrator after each phase
- `kb.status()` — returns a formatted status string for display

### Serialisation notes
`kb.save()` uses `json.dumps` with a `default` that serialises dataclasses
via `__dict__`. The `run.py` loader (`load_kb_from_json`) reconstructs the
KB best-effort. This is not a perfect round-trip for nested dataclasses —
if you add new nested types, update `load_kb_from_json` in `run.py`.

---

## BaseAgent (`base_agent.py`)

All agents inherit from `BaseAgent`. Subclasses must implement:

```python
name: str                    # class attribute, snake_case, unique
system_prompt: str           # @property — the agent's specialised instructions
task_prompt(self) -> str     # method — user turn constructed from KB state
```

### MCP tool protocol
Each agent builds an in-process MCP server via `_build_mcp_server()`.
The server exposes five tools to Claude Code:

| Tool | Purpose |
|------|---------|
| `read_file` | Read a file from a repo (path relative to repo root; optional `repo` label for multi-repo) |
| `list_directory` | List files/dirs within a repo (optional `repo` label for multi-repo) |
| `read_kb` | Read any KB field (optionally a subfield) |
| `write_kb` | Write a value to a KB field or subfield |
| `finish` | Signal task completion, record summary in agent_log |

The MCP server name is `{agent.name}_kb`. Allowed tool names follow the
pattern `mcp__{server_name}__{tool_name}`, e.g.
`mcp__repo_cartographer_kb__read_file`.

**Important**: `write_kb` receives values as strings from the MCP protocol.
The implementation in `_write_kb` attempts `json.loads()` first — so agents
should pass structured data as JSON strings.

### The `_tool_read_kb` method
Layer 1 task prompts call `self.kb._tool_read_kb(field, subfield)` directly
(Python call, not via MCP). This is intentional — task prompts are Python
strings constructed before the agent runs. Do not confuse this with the
`read_kb` MCP tool that the agent calls during its run.

### Agent SDK execution
`BaseAgent.run(verbose)` calls `anyio.run(self._run_async, verbose)`.
`_run_async` creates the MCP server, wraps it in `ClaudeAgentOptions`,
opens a `ClaudeSDKClient`, sends the task prompt, and streams the response.

The agentic loop is entirely internal to Claude Code — `base_agent.py` does
not manage tool-use iterations. Claude Code calls the MCP tools as needed
and stops when it calls `finish` or reaches its own internal limit.

---

## Orchestrator (`orchestrator.py`)

`ManuscriptOrchestrator` sequences agents in five phases:

| Phase | Agents | Gate after |
|-------|--------|------------|
| 1 — Extraction | RepoCartographer, ResultsExtractor, MethodsFormaliser, JournalProfiler | `gate_extraction_complete` |
| 2 — Writing | MethodsWriter, ResultsWriter, IntroductionWriter, DiscussionWriter | `gate_writing_complete` |
| 3 — Auditing | StatsAuditor, DomainConsistencyChecker, ReproducibilityChecker | `gate_audit_passed` |
| 4 — Peer Review | MockReviewer×3, MockEditor, RevisionCoordinator | (none) |
| 5 — Abstract | AbstractWriter | (none) |

### Gate functions
```python
gate_extraction_complete(kb) → (bool, str)
    # Fails if: no repo maps have pipeline_steps, results_store empty,
    # notation_registry empty, journal_spec not populated

gate_writing_complete(kb) → (bool, str)
    # Fails if any of: methods, results, introduction, discussion missing

gate_audit_passed(kb) → (bool, str)
    # Fails if: audit.n_fatal() > 0
```

Phases 1 and 2 are **hard blockers** — a failure aborts the run.
Phases 3–5 log the failure but continue.

### KB auto-save
After each phase the orchestrator calls `kb.save(f"kb_phase{n}.json")`.
This enables resumption: `run.py --load kb_phase2.json --phases 3 4 5`.

### `run_revision()`
Clears `kb.audit` and `kb.review`, then re-runs phases 3, 4, 5.
Call after manually editing draft sections in the KB JSON.

---

## Layer 1 agents (`agents/layer1.py`)

### RepoCartographer
**Writes to**: `repo_registry.*` (one `RepoMap` per repo label)
**Behaviour**: Explores each repo with `list_directory` and `read_file`
(using the `repo` parameter to switch between repos in multi-repo projects).
Reads README, Snakefile/workflow, config files, main scripts.
Records the pipeline as ordered steps. Flags doc/code mismatches.
For multi-repo projects, also identifies cross-repo dependencies.
**Critical**: This agent's output is the only source of repo truth for
all downstream agents. It must be exhaustive.

### ResultsExtractor
**Writes to**: `results_store.entries`
**Behaviour**: Reads result files (CSVs, logs, notebook outputs), figure
scripts, and tables. Records every quantitative finding with a
`result_id`. Flags cross-file inconsistencies as `INCONSISTENCY_*` entries.
**Critical**: Writers cannot add to the results store. If this agent misses
a result, it cannot appear in the manuscript.

### MethodsFormaliser
**Writes to**: `methods_spec.*`
**Behaviour**: Reads analysis scripts and translates the implementation
into formal mathematical language. Builds the notation registry that all
writers use. Uses LaTeX-style notation in definitions.

### JournalProfiler
**Writes to**: `journal_spec.*`
**Behaviour**: Uses Claude's training knowledge of the target journal.
Does not search the web. Records word limits, figure limits, citation
style, section structure, and statistical conventions.
**Note**: JournalProfiler knowledge may be stale for very new journals
or recent guideline changes. Flag uncertain values clearly.

---

## Layer 2 agents (`agents/layer2.py`)

### Writers (run in this order — order is enforced by orchestrator)

**MethodsWriter** — writes `draft.methods`
- Primary source: `methods_spec` (must not deviate)
- Uses `[MISSING: ...]` for anything not in KB
- Covers: data, pipeline, statistical analysis, software availability

**ResultsWriter** — writes `draft.results`
- Reads `results_store` before writing any number
- Uses `[MISSING RESULT: ...]` for uncited values
- Narrates figures in order; no interpretation

**IntroductionWriter** — writes `draft.introduction`
- Uses `[CITE: topic]` placeholders for all citations
- Does not present results
- Argument structure: gap → approach → headline finding

**DiscussionWriter** — writes `draft.discussion`
- May only interpret results in `results_store`
- Uses hedged language: "is consistent with", not "proves"
- Uses `[CITE: ...]` for literature comparisons

**AbstractWriter** — writes `draft.abstract` — always last
- Reads `draft.full_text()` to distil from the final manuscript
- All numbers must match `results_store` exactly

### Auditors

**StatsAuditor** — writes `audit.stats_issues`
- Checks: test stats without df, uncorrected p-values, overstated language,
  Results values not matching results_store, wrong null distributions
- Sets `audit.all_passed = True` only if zero fatal issues

**DomainConsistencyChecker** — writes `audit.domain_issues`
- Checks: terminology (admixture vs introgression), implausible parameters,
  overclaiming, notation inconsistency, missing assumption statements

**ReproducibilityChecker** — writes `audit.reproducibility_gaps`
- Cross-checks Methods prose against repo_map
- Flags: undocumented parameters, missing software versions, magic numbers

### Review panel

**MockReviewer** (three instances, different profiles):
- `"methodological"` — stats, methods validity, benchmarking
- `"biological"` — biological interpretation, claim support
- `"breadth"` — clarity, accessibility, jargon for non-specialists

All three append to `review.reviewer_reports`. They run independently —
no reviewer sees another's report.

**MockEditor** — adjudicates between reviewers
Writes: `review.editor_decision`, `review.editor_letter`,
`review.ranked_action_list`

**RevisionCoordinator** — maps editorial concerns to agents
Writes: `review.response_to_reviewers`
Also flags concerns that require new analyses (cannot be addressed by
writing agents alone).

---

## CLI (`run.py`)

```
python run.py --repo PATH [--repo PATH ...] --journal NAME [options]

Options:
  --repo PATH        Path to a local repository (repeatable for multi-repo).
                     Use label=path for explicit labels:
                       --repo analysis=/path/to/analysis
                       --repo simulation=/path/to/sim
                     Without a label, the directory name is used.
  --context TEXT     Free-text project description (injected into extra_context)
  --audience TEXT    Target audience (default: "computational geneticists")
  --phases N [N ...] Which phases to run (1-5); default: all
  --load PATH        Load a saved KB JSON to resume from
  --save PATH        Where to save the final KB (default: kb_final.json)
  --revision         Run revision cycle: clear audit+review, re-run phases 3-5
  --quiet            Suppress per-agent verbose output
  --dry-run          Print the plan without making any API calls
```

**Billing warning**: if `ANTHROPIC_API_KEY` is set, `run.py` prints a
warning. The correct setup is `claude login` with a Max account and
no API key in the environment.

---

## Authentication and billing

This system uses the `claude-agent-sdk` which wraps the Claude Code CLI.
The CLI handles Anthropic API calls. Authentication is determined by:

1. If `ANTHROPIC_API_KEY` is set → API pay-per-token billing (not wanted)
2. If authenticated via `claude login` with claude.ai account → Max subscription

Setup sequence:
```bash
npm install -g @anthropic-ai/claude-code
claude login                    # log in with claude.ai Max account
unset ANTHROPIC_API_KEY         # must not be set
pip install -r requirements.txt
```

See `SETUP.md` for full setup instructions and troubleshooting.

---

## `PAPER_VISION.md` — author vision file

A structured Markdown file placed in the root of the **primary target repo**
(not this codebase). `RepoCartographer` reads it first, before anything
else, and loads it into `kb.author_vision`.

Repos are referenced by their GitHub identifier (`account/repo-name`),
which must match the `--repo` label used on the CLI.

Suggested structure:
```markdown
# Paper Vision

## The one-sentence claim
Our new method detects adaptive introgression with 10x fewer false positives.

## The primary audience
Computational population geneticists

## The narrative angle
methods-forward

## Key findings to foreground
1. Detection power improvement over existing methods
2. Application to archaic introgression dataset

## Key findings to background
1. Runtime benchmarks (mention but don't foreground)

## Connections to previous work
- Extends the framework of [CITE: Racimo et al., 2017]
- Addresses false-positive issue raised by [CITE: Setter et al., 2020]

## Things the paper must NOT claim
- That this method proves adaptive introgression occurred
- That the method works for very recent admixture (<10 generations)

## Preferred journals (in order)
1. PLOS Genetics
2. Molecular Biology and Evolution

## Tone
Accessible but technically precise. Avoid jargon where possible.

## Repositories
- **munch-group/analysis** — Main analysis pipeline. Produces all figures.
  Focus on: `workflow/`, `results/`, `scripts/figures/`
  Ignore: `scratch/`, `old_versions/`
- **munch-group/sim-toolkit** — Forward-time simulations for power analysis.
  Focus on: `sim_pipeline.py`, `configs/`
  Ignore: `notebooks/exploration/`
  Relationship: produces simulated datasets consumed by analysis repo's `benchmark/` step
```

The `## Repositories` section uses `account/repo-name` identifiers that
must match the `--repo` labels on the CLI:
```bash
python run.py \
    --repo munch-group/analysis=/path/to/analysis \
    --repo munch-group/sim-toolkit=/path/to/sim \
    --journal "PLOS Genetics"
```

**Implementation status**: Fully implemented. The `AuthorVision` and
`RepoRole` dataclasses are in `knowledge_base.py`. `RepoCartographer`
reads `PAPER_VISION.md` from the primary repo. All writing agents
receive the vision via `_vision_context()` in `layer2.py`.
`DomainConsistencyChecker` checks `forbidden_claims`.

---

## Planned features not yet implemented

These were designed in conversation with the project author and should be
implemented as the next development priorities.

### 1. Journal Selector (Phase 1.5)

Runs after extraction, before writing. Two sub-agents:

**ScopeMatcher**: Reads `repo_map`, `results_store`, `methods_spec` and
scores a candidate list of journals on: novelty of method, breadth of
biological claim, expected audience size, technical depth required.
Produces a ranked shortlist with explicit reasoning per journal.

**ImpactFramer**: For the top 2-3 journals, explains how framing would
differ: methods paper vs biology paper vs tools paper.

A human gate follows — the user chooses the journal and this choice is
written into `kb.journal_name` and a new `NarrativeSpec` KB field before
Phase 2 begins.

Implementation:
- Add `NarrativeSpec` dataclass to `knowledge_base.py`:
  ```python
  @dataclass
  class NarrativeSpec:
      primary_claim: str = ""
      narrative_angle: str = ""   # "methods" | "biology" | "tools"
      foregrounded_findings: list[str] = field(default_factory=list)
      backgrounded_findings: list[str] = field(default_factory=list)
      forbidden_claims: list[str] = field(default_factory=list)
  ```
- Add `kb.narrative_spec: NarrativeSpec` to `KnowledgeBase`
- Add `ScopeMatcher` and `ImpactFramer` to a new `agents/layer1b.py`
- Add Phase 1.5 to `ManuscriptOrchestrator` with a human-gate pause

### 3. Human gate system

The orchestrator should pause at defined points and prompt the user
for input. Six gate points are planned:

| Gate | After | Purpose |
|------|-------|---------|
| 1 | Phase 1 | Verify repo map and results store correctness |
| 2 | Phase 1.5 | Choose journal and confirm NarrativeSpec |
| 3 | Argument skeleton | Approve Introduction argument before prose |
| 4 | Phase 2 Discussion | Review Discussion before finalisation |
| 5 | Phase 4 | Direct revision priorities |
| 6 | Phase 5 Abstract | Final author read |

Implementation: add `await_human_input(gate_number, prompt, kb)` to
`orchestrator.py`. In CLI mode this calls `input()`. A future interactive
mode could use a web interface. Gates 1 and 2 should be hard blockers
(pipeline pauses until user responds). Gates 3–6 can be skippable with
`--skip-gates`.

Gate 3 specifically requires a new `IntroductionWriter` mode: first run
with instructions to produce a bullet-point argument skeleton only (stored
in a new `kb.draft.introduction_skeleton` field), wait for human approval,
then run again in prose mode.

### 4. Prompt caching

The KB content (especially `repo_map`, `methods_spec`) is re-read by many
agents as large system/user payloads. Adding Anthropic prompt caching would
cut repeated input token costs by ~90% when running revision cycles.

This requires switching to direct API calls for those agents, or waiting
for the `claude-agent-sdk` to expose caching configuration.

### 5. `NarrativeSpec` propagation

Most of the originally planned `NarrativeSpec` functionality is now
covered by `AuthorVision` (loaded from `PAPER_VISION.md`). The remaining
piece is the `NarrativeSpec` that `ImpactFramer` would produce in
Phase 1.5, providing journal-specific framing adjustments on top of
the author's vision. Once Phase 1.5 is implemented, add:
```python
f"Journal-specific framing:\n{self.kb._tool_read_kb('narrative_spec')}\n"
```
to all writing agent task prompts (after the `_vision_context()` block).

---

## How to add a new agent

1. Choose the right file: `agents/layer1.py` if it reads the repo and
   populates the KB; `agents/layer2.py` if it reads the KB and produces
   manuscript content or quality checks.

2. Subclass `BaseAgent`:
```python
class MyAgent(BaseAgent):
    name = "my_agent"   # unique snake_case, used in MCP server name and logs

    @property
    def system_prompt(self) -> str:
        return "You are a specialist in X. Your job is..."

    def task_prompt(self) -> str:
        return f"""
Please do X.

Relevant KB context:
{self.kb._tool_read_kb('some_field')}

Write your output to:
  write_kb(field="some_field", subfield="some_subfield", value=<your output>)

Call finish when done.
"""
```

3. Add the agent class to the appropriate `__init__.py` import.

4. Add it to the correct phase in `orchestrator.py`.

5. If it writes to a new KB field, add the dataclass to `knowledge_base.py`
   and update `KnowledgeBase` with the new field. Also update
   `load_kb_from_json` in `run.py` to restore it.

---

## How to add a new KB field

1. Add a `@dataclass` to `knowledge_base.py`.
2. Add the field to `KnowledgeBase` with `field(default_factory=...)`.
3. Update `kb.status()` if the field is worth showing in status output.
4. Update `load_kb_from_json` in `run.py` to restore it from JSON.
5. Update `gate_extraction_complete` or `gate_writing_complete` in
   `orchestrator.py` if the field should be a gate condition.
6. Document the new field in this `CLAUDE.md` under the data model section.

---

## Known issues and edge cases

### `_tool_read_kb` called in task_prompt before run
`layer1.py` task prompts call `self.kb._tool_read_kb(...)` directly as
Python. This works because by the time Phase 2 agents run, Phase 1 has
already populated the KB. However Phase 1 agents calling `_tool_read_kb`
in their task prompts will get empty KB fields — this is expected and those
agents should rely only on `repo_path` and `extra_context` in their prompts.

### MockReviewer `name` property vs class attribute
`MockReviewer` uses `@property` for `name` (because it depends on `profile`).
The orchestrator uses `agent.name` after instantiation, which correctly
returns the property value. But `agent_class.__name__` (used in error
messages) returns `"MockReviewer"` for all three instances. This is
cosmetically imperfect but functionally fine.

### JSON round-trip for nested dataclasses
`kb.save()` serialises via `__dict__`, which flattens nested dataclasses
to dicts. `load_kb_from_json` reconstructs them best-effort but loses
type information on deeply nested structures. This is acceptable for the
current use case (resume pipeline from checkpoint) but would need a proper
serialisation library (e.g. `dacite`, `cattrs`) for production use.

### write_kb value coercion
`write_kb` tries `json.loads(value)` on all incoming strings. This means
agents should pass structured data as JSON strings. Plain strings that
happen to be valid JSON (e.g. `"true"`, `"42"`) will be coerced to their
Python equivalents. This is generally desirable but could cause issues if
an agent writes a string like `"null"` intending to store the literal word.

### Async/sync boundary in `BaseAgent.run()`
The current implementation uses `anyio.run(self._run_async, verbose)`.
This works when called from a synchronous context (the orchestrator).
If the orchestrator is ever made async (e.g. for parallel phase execution),
replace `anyio.run` with `await self._run_async(verbose)` in each call site.

---

## Testing approach

There are no automated tests yet. When adding them:

- Unit test KB dataclasses with `dataclasses.asdict` round-trips
- Unit test gate functions with synthetic KB states
- Unit test `_read_file`, `_list_directory`, `_read_kb`, `_write_kb`
  with a fixture repo directory
- Integration test: run Phase 1 only on a small synthetic repo and
  verify the KB is populated correctly
- Do not mock the Claude Agent SDK in integration tests — run against
  real Claude Code with a test account

Suggested test fixture: the `manuscript_agents` directory itself is a
valid Python repo with a README and source code. Phase 1 agents can be
run on it as a smoke test.

---

## Style conventions

- Python 3.10+; use `from __future__ import annotations` in all files
- Type hints everywhere; `Any` only when genuinely necessary
- Docstrings on all classes and public methods
- `# ── Section name ──...` comment style for visual section breaks
  (consistent with existing code)
- `rich` for all terminal output in `orchestrator.py` and `run.py`
- No `print()` in agent files except inside `BaseAgent._run_async`
  for verbose agent output — use `kb.log()` for structured logging
- All KB writes from agents go through the MCP `write_kb` tool, never
  via direct Python attribute assignment during a run
