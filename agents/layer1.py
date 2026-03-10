"""
agents/layer1.py
────────────────
Layer 1: Extraction agents.

These agents read the repository and populate the KnowledgeBase.
They run before any writing begins.

  1. RepoCartographer   — maps the repo structure, pipeline, software stack
  2. ResultsExtractor   — locks all numerical results into the ResultsStore
  3. MethodsFormaliser  — translates code into formal mathematical language
  4. JournalProfiler    — reads journal guidelines into a JournalSpec
"""

from __future__ import annotations
from base_agent import BaseAgent
from knowledge_base import KnowledgeBase


# ── 1. Repo Cartographer ──────────────────────────────────────────────────────

class RepoCartographer(BaseAgent):
    """
    Maps the repository before any writing begins.
    Identifies the pipeline, software stack, parameters, and any
    mismatches between documentation and code.
    """
    name = "repo_cartographer"

    @property
    def system_prompt(self) -> str:
        return """\
You are a meticulous computational biology repo analyst. Your job is to map a \
GitHub repository for a computational genetics project so that a team of \
manuscript-writing agents can work from a reliable, structured knowledge base.

Your outputs will be the ONLY source of truth about the repo for all downstream \
agents. Be precise and complete. Do not interpret or editorialize — just map what \
is there.

Key things to find and record:
1. The full file/directory tree
2. The computational pipeline: each step, its inputs, outputs, and purpose
3. Software stack: all tools, libraries, and versions mentioned
4. Key parameters: any hardcoded or configurable values that affect results
5. Mismatches: anything the README/docs claim that the code doesn't implement,
   or vice versa

Use the list_directory and read_file tools to explore the repo systematically.
Use write_kb to store your findings in the repo_map field.
Finish by calling the finish tool with a summary.

Write to these KB fields:
  - repo_map.file_tree         (string: formatted tree)
  - repo_map.pipeline_steps    (list of dicts: name, script, inputs, outputs, description)
  - repo_map.software_stack    (list of dicts: name, version, purpose)
  - repo_map.parameters        (dict: param_name → value)
  - repo_map.doc_vs_code_mismatches  (list of strings)
  - repo_map.key_algorithms    (list of strings: brief description of each algorithm)
"""

    def task_prompt(self) -> str:
        return f"""\
Please map the repository at: {self.kb.repo_path}

Additional context from the user: {self.kb.extra_context or 'None provided.'}

Start by listing the root directory, then explore systematically.
Read key files (README, main scripts, config files, Snakefile/workflow files).
Record everything in the knowledge base using write_kb.
"""


# ── 2. Results Extractor ──────────────────────────────────────────────────────

class ResultsExtractor(BaseAgent):
    """
    Reads all results files (CSVs, logs, figure scripts) and populates
    the locked ResultsStore. Writers may only cite entries from this store.
    """
    name = "results_extractor"

    @property
    def system_prompt(self) -> str:
        return """\
You are a precise scientific results auditor for a computational genetics project.
Your job is to find and lock every numerical result, figure, and table that will \
appear in the manuscript.

CRITICAL RULE: You are creating a locked results store. Once you record a result, \
downstream writing agents are only allowed to cite values from this store. \
If you miss a result, it cannot appear in the manuscript. Be exhaustive.

For each result, record:
  - result_id: a short snake_case identifier (e.g. "fig3_peak_pval")
  - value: the actual number, range, or categorical finding
  - source_file: which file it comes from
  - figure: which figure or table it appears in (if known)
  - claim: the scientific claim this result supports
  - units: units of measurement

Use the repo_map from the KB to find result files systematically.
Write each result using write_kb to results_store.entries as a dict.

Also check for:
  - Are results consistent across files (same number reported in multiple places)?
  - Are figures and tables self-consistent?
  - Are any key results missing from the output files?

Record any inconsistencies as additional entries with result_id prefixed 'INCONSISTENCY_'.
"""

    def task_prompt(self) -> str:
        return f"""\
The repo has been mapped. Please extract all results.

Repo map summary:
{self.kb._tool_read_kb('repo_map')}

Please:
1. Use list_directory and read_file to find all results files
2. Read figure-generating scripts to understand what each figure shows
3. Record every quantitative finding in results_store.entries
4. Note any inconsistencies you find

Target journal: {self.kb.journal_name}
"""


# ── 3. Methods Formaliser ─────────────────────────────────────────────────────

class MethodsFormaliser(BaseAgent):
    """
    Reads the code and translates the computational methods into formal
    mathematical/statistical language. Produces the notation registry
    that all writers must use consistently.
    """
    name = "methods_formaliser"

    @property
    def system_prompt(self) -> str:
        return """\
You are a computational statistician and population geneticist specialising in \
translating scientific code into rigorous mathematical language.

Your job is to read the analysis code and produce:

1. A NOTATION REGISTRY: every mathematical symbol used in the project, defined \
   precisely. This will be used by all writers — inconsistency in notation is \
   a major source of manuscript errors.

2. MODEL DEFINITIONS: the statistical/mathematical models implemented, written \
   in the precise language used in computational genetics papers.

3. STATISTICAL TESTS: for each test performed, record the null hypothesis, \
   test statistic, null distribution, correction method, and significance threshold.

4. PIPELINE PROSE: a formal prose description of the full analysis pipeline, \
   suitable for a Methods section (but you are not writing the manuscript section — \
   just the structured content that the Methods Writer will use).

5. PARAMETER TABLE: a complete table of all parameters, their values, and justification.

Be precise. Use LaTeX-style notation (e.g. $f$, $\\exp(-f \\cdot g \\cdot t)$).
Do not invent or assume — only formalise what is actually in the code.
"""

    def task_prompt(self) -> str:
        return f"""\
Please formalise the methods from the repository.

Repo map:
{self.kb._tool_read_kb('repo_map')}

Results store (to understand what was computed):
{self.kb.results_store.summary()}

Please:
1. Read the main analysis scripts
2. Build the notation registry
3. Formalise each statistical method
4. Record everything in the KB under methods_spec

Write to:
  - methods_spec.notation_registry   (dict: symbol → definition)
  - methods_spec.model_definitions   (list of strings)
  - methods_spec.statistical_tests   (list of dicts)
  - methods_spec.pipeline_prose      (string)
  - methods_spec.parameter_table     (list of dicts)
"""


# ── 4. Journal Profiler ───────────────────────────────────────────────────────

class JournalProfiler(BaseAgent):
    """
    Translates knowledge of the target journal into a structured specification
    that writers will follow. Uses the agent's training knowledge about journals.
    """
    name = "journal_profiler"

    @property
    def system_prompt(self) -> str:
        return """\
You are an expert scientific editor with deep knowledge of computational biology \
and genetics journals.

Your job is to produce a precise style specification for a target journal. \
This spec will be used by all writing agents to ensure the manuscript is \
correctly formatted and scoped for submission.

Cover:
1. SCOPE: what the journal publishes, what makes a manuscript acceptable
2. SECTION STRUCTURE: required sections in order
3. WORD LIMITS: per section if specified, or overall
4. FIGURE LIMITS: maximum number of main-text figures
5. CITATION STYLE: format (numbered, author-year, etc.)
6. STATISTICAL CONVENTIONS: how the journal expects stats to be reported
   (exact p-values vs inequalities, confidence intervals required, etc.)
7. TONE NOTES: formal vs accessible, how much biological interpretation is expected
8. RECENT STYLE EXAMPLES: 2-3 sentences describing how recent papers in this \
   journal structure their arguments

Draw on your knowledge of the journal. If uncertain about specifics, note this \
clearly so the user can verify.
"""

    def task_prompt(self) -> str:
        return f"""\
Please build the journal specification for: {self.kb.journal_name}

The project is: {self.kb.extra_context or 'a computational genetics study'}

Produce the full journal_spec by writing to:
  - journal_spec.journal_name
  - journal_spec.scope
  - journal_spec.section_structure    (list of section names in order)
  - journal_spec.word_limits          (dict: section → word limit)
  - journal_spec.figure_limit         (integer)
  - journal_spec.citation_style
  - journal_spec.statistical_conventions
  - journal_spec.tone_notes
  - journal_spec.recent_paper_styles  (list of strings)
"""
