# Setup Guide — Running with Claude Code (Max Subscription)

This guide gets the manuscript agent team running on your Max subscription
rather than pay-per-token API billing.

---

## How the billing works

```
Your Python script
      │
      │  spawns subprocess
      ▼
claude-agent-sdk ──► Claude Code CLI ──► Anthropic API
                           │
                           └── authenticated with your Max subscription
                               (not an API key)
```

The Agent SDK wraps the Claude Code CLI as a library. The CLI handles
authentication. As long as you log in with your claude.ai account (not
an API key), all usage counts against your Max subscription allocation.

---

## Step 1 — Prerequisites

```bash
# Node.js is required by the Claude Code CLI (v18+ recommended)
node --version   # should print v18 or higher

# If not installed:
# macOS:  brew install node
# Linux:  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
#         sudo apt install -y nodejs
```

---

## Step 2 — Install Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code

# Verify
claude --version   # should print 2.x.x or higher
```

---

## Step 3 — Log in with your Max subscription

```bash
claude login
# This opens a browser. Log in with the same account as claude.ai.
# Do NOT use an API key here — that would switch to pay-per-token billing.

# Verify you are on your subscription (not API credits)
claude /status
# Should show something like:
#   Plan: Max ($100/month)
#   Not using API credits
```

---

## Step 4 — Critical: unset any API key

If `ANTHROPIC_API_KEY` is set in your environment, Claude Code uses
pay-per-token API billing regardless of your subscription login.

```bash
# Check if it is set
echo $ANTHROPIC_API_KEY

# If set, unset it for this session
unset ANTHROPIC_API_KEY

# To permanently remove it, remove it from ~/.bashrc / ~/.zshrc / ~/.bash_profile
```

The `run.py` script will warn you if this variable is set.

---

## Step 5 — Install Python dependencies

```bash
cd manuscript_agents
pip install -r requirements.txt
```

---

## Step 6 — Run

```bash
# Dry run — see what will execute without spending any subscription
python run.py \
  --repo /path/to/your/repo \
  --journal "PLOS Genetics" \
  --context "Study of Neanderthal introgression in sub-Saharan Africa" \
  --dry-run

# Phase 1 only (extraction) — cheapest, verify KB before committing
python run.py \
  --repo /path/to/your/repo \
  --journal "PLOS Genetics" \
  --phases 1

# Full pipeline
python run.py \
  --repo /path/to/your/repo \
  --journal "PLOS Genetics" \
  --context "Study of Neanderthal introgression in sub-Saharan Africa"
```

---

## Subscription usage expectations

The pipeline runs ~14 agents. Each agent spawns one Claude Code session.
Rough allocation:

| Phase | Agents | Estimated subscription usage |
|-------|--------|------------------------------|
| 1 — Extraction | 4 | Light–moderate (mostly reading files) |
| 2 — Writing | 4 | Heavy (long outputs) |
| 3 — Auditing | 3 | Moderate |
| 4 — Review | 5 | Moderate–heavy |
| 5 — Abstract | 1 | Light |

A full single run is well within a Max plan's daily allocation for most
usage patterns. Running the pipeline repeatedly on the same day during
a revision cycle may approach limits — in that case, use `--phases` to
run only the phases that changed.

---

## If you hit subscription limits mid-run

The KB is saved as JSON after each phase. Resume from where you stopped:

```bash
# If phase 2 completed but phase 3 hit a limit:
python run.py \
  --repo /path/to/your/repo \
  --journal "PLOS Genetics" \
  --load kb_phase2.json \
  --phases 3 4 5
```

---

## Switching back to API billing (optional)

If you want pay-per-token billing instead (e.g. for automated CI runs):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Claude Code will detect this and use API billing
```

The code works identically either way — only billing changes.

---

## Troubleshooting

**"claude: command not found"**
→ Node.js global bin not in PATH. Try: `export PATH="$PATH:$(npm bin -g)"`

**"Authentication required"**
→ Run `claude login` again. Sessions can expire.

**"Rate limit exceeded"**  
→ You've hit your subscription's rolling window limit.
  Wait for the window to reset, or use `--phases` to run incrementally.

**"ANTHROPIC_API_KEY is set" warning in run.py**
→ Run `unset ANTHROPIC_API_KEY` before running the script.

**Agent produces empty KB fields**
→ The MCP tool names include the agent's `name` attribute.
  If you rename an agent, the `allowed_tools` list in `_build_mcp_server()`
  updates automatically — no manual changes needed.
