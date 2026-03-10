"""
base_agent.py
─────────────
Base class for all manuscript agents — Claude Agent SDK version.

Uses the claude-agent-sdk (which runs Claude Code CLI under the hood)
instead of calling the Anthropic API directly. Authentication flows through
your Claude Code login, so usage draws from your Max subscription rather
than pay-per-token API billing.

Key differences from the direct-API version:
  - No manual tool-use loop: Claude Code manages the agentic loop internally
  - Tools are Python functions decorated with @tool, not JSON schema dicts
  - No ANTHROPIC_API_KEY needed: auth comes from `claude login`
  - Async execution via anyio
"""

from __future__ import annotations
import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import anyio
from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeAgentOptions,
    ClaudeSDKClient,
)
from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock

from knowledge_base import KnowledgeBase


class BaseAgent(ABC):
    """
    Base class for all manuscript pipeline agents — Agent SDK version.

    Subclasses implement:
      - system_prompt (property)  — the agent's specialised instructions
      - task_prompt() -> str      — the user turn constructed from KB state

    The KB read/write tools and file tools are registered automatically
    as an in-process MCP server; Claude Code calls them natively during
    its internal agentic loop.
    """

    name: str = "base_agent"

    def __init__(self, kb: KnowledgeBase, repo_root: str = ""):
        self.kb = kb
        self.repo_root = Path(repo_root or kb.repo_path)

    # ── Abstract interface ────────────────────────────────────────────────────

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def task_prompt(self) -> str: ...

    # ── Tool implementations ──────────────────────────────────────────────────

    def _read_file(self, path: str, max_lines: int = 200) -> str:
        target = self.repo_root / path
        if not target.exists():
            target = Path(path)
        if not target.exists():
            return f"File not found: {path}"
        try:
            content = target.read_text(errors="replace")
            lines = content.splitlines()
            if max_lines != -1 and len(lines) > max_lines:
                return "\n".join(lines[:max_lines]) + f"\n\n[truncated at {max_lines} lines]"
            return content
        except Exception as e:
            return f"Could not read {path}: {e}"

    def _list_directory(self, path: str = ".", recursive: bool = False) -> str:
        target = self.repo_root / path
        if not target.exists():
            target = Path(path)
        if not target.exists():
            return f"Directory not found: {path}"
        try:
            entries = sorted(target.rglob("*") if recursive else target.iterdir())
            lines = []
            for e in entries:
                try:
                    rel = e.relative_to(self.repo_root)
                except ValueError:
                    rel = e
                lines.append(f"  {rel}" + ("/" if e.is_dir() else ""))
            return "\n".join(lines) if lines else "(empty)"
        except Exception as e:
            return f"Could not list {path}: {e}"

    def _read_kb(self, field: str, subfield: str = "") -> str:
        obj = getattr(self.kb, field, None)
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

    def _write_kb(self, field: str, value: Any, subfield: str = "") -> str:
        obj = getattr(self.kb, field, None)
        if obj is None:
            return f"KB field '{field}' not found."
        if subfield:
            if hasattr(obj, subfield):
                setattr(obj, subfield, value)
                return f"Wrote to {field}.{subfield}"
            elif isinstance(obj, dict):
                obj[subfield] = value
                return f"Wrote to {field}[{subfield}]"
            return f"Cannot set subfield '{subfield}' on {field}"
        setattr(self.kb, field, value)
        return f"Wrote to KB.{field}"

    def _finish(self, summary: str, success: bool = True) -> str:
        self.kb.log(self.name, "finished", summary)
        return f"Finished. success={success}. Summary recorded in KB."

    # ── MCP server factory ────────────────────────────────────────────────────

    def _build_mcp_server(self):
        """
        Build an in-process MCP server exposing the KB tools to Claude Code.
        Closures capture self so tools have access to kb and repo_root.
        """
        agent = self  # capture for closures

        @tool("read_file",
              "Read a file from the repository by path (relative to repo root).",
              {"path": str, "max_lines": int})
        async def read_file(args):
            return {"content": [{"type": "text",
                "text": agent._read_file(args["path"], args.get("max_lines", 200))}]}

        @tool("list_directory",
              "List files and directories within the repository.",
              {"path": str, "recursive": bool})
        async def list_directory(args):
            return {"content": [{"type": "text",
                "text": agent._list_directory(args.get("path", "."),
                                               args.get("recursive", False))}]}

        @tool("read_kb",
              ("Read a field from the shared KnowledgeBase. "
               "Available: repo_map, results_store, methods_spec, "
               "journal_spec, draft, audit, review, extra_context."),
              {"field": str, "subfield": str})
        async def read_kb(args):
            return {"content": [{"type": "text",
                "text": agent._read_kb(args["field"], args.get("subfield", ""))}]}

        @tool("write_kb",
              "Write a value to a field in the shared KnowledgeBase.",
              {"field": str, "subfield": str, "value": str})
        async def write_kb(args):
            value = args["value"]
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
            return {"content": [{"type": "text",
                "text": agent._write_kb(args["field"], value, args.get("subfield", ""))}]}

        @tool("finish",
              "Signal that this agent has completed its task.",
              {"summary": str, "success": bool})
        async def finish(args):
            return {"content": [{"type": "text",
                "text": agent._finish(args["summary"], args.get("success", True))}]}

        return create_sdk_mcp_server(
            name=f"{self.name}_kb",
            version="1.0.0",
            tools=[read_file, list_directory, read_kb, write_kb, finish],
        )

    # ── Async run ─────────────────────────────────────────────────────────────

    async def _run_async(self, verbose: bool = True) -> bool:
        """Run this agent via the Claude Agent SDK."""
        mcp_server = self._build_mcp_server()
        server_name = f"{self.name}_kb"

        options = ClaudeAgentOptions(
            system_prompt=self.system_prompt,
            mcp_servers={server_name: mcp_server},
            allowed_tools=[
                f"mcp__{server_name}__read_file",
                f"mcp__{server_name}__list_directory",
                f"mcp__{server_name}__read_kb",
                f"mcp__{server_name}__write_kb",
                f"mcp__{server_name}__finish",
            ],
        )

        if verbose:
            print(f"\n{'═' * 60}")
            print(f"  AGENT: {self.name.upper()}  [Claude Code / Max subscription]")
            print(f"{'═' * 60}")

        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(self.task_prompt())
                async for message in client.receive_response():
                    if verbose and isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock) and block.text.strip():
                                print(f"  [thinking] {block.text.strip()[:200]}...")
                            elif isinstance(block, ToolUseBlock):
                                print(f"  [tool] {block.name}({json.dumps(block.input)[:100]})")

            if verbose:
                print(f"  ✓ {self.name} completed.")
            self.kb.log(self.name, "completed", "Agent SDK run finished")
            return True

        except Exception as e:
            self.kb.log(self.name, "error", str(e))
            print(f"  ✗ {self.name} failed: {e}")
            return False

    def run(self, verbose: bool = True) -> bool:
        """Synchronous wrapper — the orchestrator calls this."""
        return anyio.run(self._run_async, verbose)
