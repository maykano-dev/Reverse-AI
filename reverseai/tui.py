"""An interactive terminal for ReverseAI - the Claude Code-style experience.

A stdlib-only REPL (no Textual/Rich, so the core stays zero-dependency). It runs
multi-turn conversations with the real agent, shows the plan and the natural
narration as it works, and supports slash commands:

    /help     list commands
    /clear    start a fresh conversation
    /cost     session token + cost estimate
    /compact  shrink the conversation context (keep the goal, drop the bulk)
    /undo     restore the last workspace checkpoint and drop the last turn
    /doctor   diagnose providers, sandbox, and optional backends
    /project <path>   work in a folder on disk
    /mode [ask|build|modify|optimize|autonomous]   show or set the mode
    /exit     quit

Line editing and history come from the stdlib ``readline`` when present.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# --- colors ----------------------------------------------------------------
def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("REVERSEAI_TUI_NOCOLOR") == "1":
        return False
    return sys.stdout.isatty()


class _C:
    def __init__(self, on: bool) -> None:
        self.on = on

    def _w(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.on else s

    def dim(self, s): return self._w("2", s)
    def bold(self, s): return self._w("1", s)
    def accent(self, s): return self._w("38;5;75", s)
    def green(self, s): return self._w("38;5;71", s)
    def red(self, s): return self._w("38;5;203", s)
    def yellow(self, s): return self._w("38;5;179", s)


_GLYPH = {"file": "▸", "code": "▸", "terminal": "»", "search": "⌕", "globe": "◍",
          "check": "✓", "bars": "▤", "bookmark": "✚", "box": "▣", "sparkle": "✦",
          "alert": "!", "lock": "⌾", "undo": "↶", "x": "✗", "chart": "▤",
          "archive": "▤", "model": "·"}


class TUI:
    def __init__(self, provider: str = "", permission: str = "write",
                 template: str = "general", mode: str = "",
                 target: str | None = None, project_dir: str | None = None,
                 store: str | None = None) -> None:
        from .agent import Agent, Permission, get_provider
        from .agent.memory import MemoryStore, default_memory_path
        from .agent.skills import load_skills

        self.c = _C(_use_color())
        perm = {"read": Permission.READ, "execute": Permission.EXECUTE,
                "write": Permission.WRITE}[permission]
        self.provider_name = provider or os.environ.get("REVERSEAI_PROVIDER", "deepseek")
        self.provider = get_provider(self.provider_name)
        skills_root = os.environ.get("REVERSEAI_SKILLS")
        self.agent = Agent(
            self.provider, max_permission=perm, template=template, mode=mode,
            memory=MemoryStore(default_memory_path()),
            skills=load_skills(Path(skills_root) if skills_root else None))
        self.template = template
        self.mode = mode
        self.target = target
        self.project_dir = project_dir
        self.store = store
        self.conv = None
        self._usage = {"tokens": 0, "cost": 0.0}
        self._streaming = False

    # --- conversation lifecycle ------------------------------------------
    def _new_conv(self):
        self.conv = self.agent.open(
            target_path=self.target, project_dir=self.project_dir, mode=self.mode)
        return self.conv

    # --- event rendering --------------------------------------------------
    def _on_event(self, ev: dict[str, Any]) -> None:
        t = ev.get("type")
        c = self.c
        if t == "plan":
            steps = ev.get("steps") or []
            if steps:
                print(c.dim("  plan: " + " · ".join(self._plan_label(s) for s in steps)))
        elif t == "reason":
            glyph = _GLYPH.get(ev.get("icon", ""), "·")
            title = ev.get("title") or ev.get("detail") or "working"
            print(c.accent(f"  {glyph} ") + c.dim(title))
        elif t == "tool_result":
            if not ev.get("ok"):
                name = ev.get("name", "step")
                print(c.red(f"    ✗ {name}: ") + c.dim((ev.get("content") or "")[:160]))
        elif t == "finding":
            if ev.get("tier") == "verified":
                print(c.green("    ✓ ") + c.dim("verified: " + (ev.get("claim") or "")[:120]))
        elif t == "error":
            print(c.red("  error: ") + (ev.get("error") or "unknown error"))
        elif t == "final":
            self._accumulate(ev.get("usage") or {})

    @staticmethod
    def _plan_label(s: Any) -> str:
        if isinstance(s, dict):
            return str(s.get("title") or s.get("label") or s.get("detail") or "")
        if isinstance(s, (list, tuple)) and s:
            return str(s[0])
        return str(s)

    def _accumulate(self, usage: dict) -> None:
        for k, v in usage.items():
            if not isinstance(v, (int, float)):
                continue
            if "token" in k.lower():
                self._usage["tokens"] += int(v) if "total" in k.lower() or "token" == k.lower() else 0
            if "cost" in k.lower():
                self._usage["cost"] += float(v)
        # Fallback: a plain 'tokens'/'total_tokens' key.
        for key in ("total_tokens", "tokens"):
            if isinstance(usage.get(key), (int, float)):
                self._usage["tokens"] = self._usage["tokens"] or 0

    # --- turns ------------------------------------------------------------
    def _run_turn(self, text: str) -> None:
        if self.conv is None:
            self._new_conv()
        try:
            job = self.conv.run_turn(text, on_event=self._on_event)
        except Exception as exc:  # pragma: no cover - defensive, keep REPL alive
            print(self.c.red(f"  turn failed: {exc}"))
            return
        print()
        answer = job.final_answer or "(no conclusion)"
        print(self._render_answer(answer))
        u = job.usage or {}
        self._accumulate(u)
        tok = self._usage["tokens"]
        tokstr = (f"{tok/1000:.1f}k" if tok >= 1000 else str(tok)) + " tokens"
        print(self.c.dim(f"\n  [{job.status}] {tokstr} · ~${self._usage['cost']:.4f} · {job.steps} steps"))
        if job.artifact_meta and job.artifact_meta.get("filename"):
            print(self.c.green("  file: ") + job.artifact_meta["filename"])

    def _render_answer(self, text: str) -> str:
        # Light markdown: bold **x**, dim headings, keep it plain otherwise.
        import re
        if not self.c.on:
            return text
        out = re.sub(r"\*\*(.+?)\*\*", lambda m: self.c.bold(m.group(1)), text)
        return out

    # --- slash commands ---------------------------------------------------
    def _command(self, line: str) -> bool:
        """Return False to exit the REPL."""
        parts = line.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        c = self.c
        if cmd in ("/exit", "/quit", "/q"):
            return False
        if cmd in ("/help", "/?"):
            self._help()
        elif cmd == "/clear":
            self._new_conv()
            self._usage = {"tokens": 0, "cost": 0.0}
            print(c.dim("  started a fresh conversation"))
        elif cmd == "/cost":
            tok = self._usage["tokens"]
            print(c.dim(f"  session: {tok} tokens · ~${self._usage['cost']:.4f}"))
        elif cmd == "/compact":
            self._compact()
        elif cmd == "/undo":
            self._undo()
        elif cmd == "/doctor":
            self._doctor()
        elif cmd == "/project":
            self._set_project(arg)
        elif cmd == "/mode":
            self._set_mode(arg)
        else:
            print(c.dim(f"  unknown command {cmd} (try /help)"))
        return True

    def _help(self) -> None:
        c = self.c
        rows = [
            ("/help", "show this help"),
            ("/clear", "start a fresh conversation"),
            ("/cost", "session token + cost estimate"),
            ("/compact", "shrink the conversation context"),
            ("/undo", "restore the last workspace checkpoint, drop the last turn"),
            ("/doctor", "diagnose providers, sandbox, optional backends"),
            ("/project <path>", "work in a folder on disk"),
            ("/mode [name]", "show or set the mode"),
            ("/exit", "quit"),
        ]
        print(c.bold("  commands:"))
        for cmd, desc in rows:
            print(f"    {c.accent(cmd.ljust(18))} {c.dim(desc)}")

    def _compact(self) -> None:
        if self.conv is None:
            print(self.c.dim("  nothing to compact yet"))
            return
        from .agent.context import compact_messages
        before = len(self.conv.messages)
        self.conv.messages = compact_messages(
            self.conv.messages, self.agent.max_context_chars)
        print(self.c.dim(f"  compacted context: {before} -> {len(self.conv.messages)} messages"))

    def _undo(self) -> None:
        c = self.c
        if self.conv is None:
            print(c.dim("  nothing to undo yet"))
            return
        # Restore the latest workspace checkpoint, if any.
        restored = ""
        try:
            mgr = self.conv.ctx.extra.get("checkpoints")
            cps = mgr.list() if mgr else []
            if cps:
                latest = cps[0] if cps[0].created_at >= cps[-1].created_at else cps[-1]
                mgr.restore(latest.id, overwrite=True)
                restored = latest.id
        except Exception:
            restored = ""
        # Drop the last user+assistant exchange from the context.
        msgs = self.conv.messages
        from .agent.conversation import Role
        cut = len(msgs)
        for i in range(len(msgs) - 1, 0, -1):
            if msgs[i].role == Role.USER:
                cut = i
                break
        dropped = len(msgs) - cut
        if dropped:
            del msgs[cut:]
        note = f"  undid last turn (dropped {dropped} messages)"
        if restored:
            note += f", restored workspace checkpoint {restored[:8]}"
        print(c.dim(note))

    def _doctor(self) -> None:
        c = self.c
        print(c.bold("  diagnostics:"))

        def row(name, ok, detail=""):
            mark = c.green("ok ") if ok else c.yellow("-- ")
            print(f"    {mark} {name}" + (f"  {c.dim(detail)}" if detail else ""))

        # provider / key
        key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
                   or os.environ.get("ANTHROPIC_API_KEY"))
        row(f"provider: {self.provider_name}", True)
        row("model API key", key or self.provider_name == "mock",
            "" if key else "set DEEPSEEK_API_KEY (or use --provider mock)")
        # sandbox
        try:
            from .sandbox import SandboxPolicy, SandboxUnavailable, create_sandbox
            try:
                sb = create_sandbox(SandboxPolicy())
                row("sandbox", True, sb.name)
            except SandboxUnavailable as exc:
                row("sandbox", False, str(exc)[:80])
        except Exception as exc:
            row("sandbox", False, str(exc)[:80])
        # optional backends
        for label, fn in (("decompiler (ghidra)", self._ghidra),
                          ("OCR", self._ocr),
                          ("vision (inspect_image)", self._vision)):
            ok, detail = fn()
            row(label, ok, detail)

    @staticmethod
    def _ghidra():
        try:
            from .decompile import ghidra_available
            return bool(ghidra_available()), ""
        except Exception:
            return False, "not configured"

    @staticmethod
    def _ocr():
        try:
            from .ocr import ocr_any_available
            return bool(ocr_any_available()), ""
        except Exception:
            return False, "not configured"

    @staticmethod
    def _vision():
        try:
            from .vision import available
            return bool(available()), ""
        except Exception:
            return False, "not configured"

    def _set_project(self, path: str) -> None:
        c = self.c
        if not path:
            print(c.dim(f"  project folder: {self.project_dir or '(none)'}"))
            return
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        p = p.resolve()
        if not p.is_dir():
            print(c.red(f"  no such folder: {p}"))
            return
        self.project_dir = str(p)
        if self.conv is not None:
            self.conv.ctx.extra["project_dir"] = str(p)
        print(c.dim(f"  working folder set to {p}"))

    def _set_mode(self, mode: str) -> None:
        c = self.c
        valid = {"ask", "build", "modify", "optimize", "autonomous", ""}
        if not mode:
            print(c.dim(f"  mode: {self.mode or '(default)'}"))
            return
        if mode not in valid:
            print(c.red(f"  unknown mode {mode}; choose from ask/build/modify/optimize/autonomous"))
            return
        self.mode = mode
        print(c.dim(f"  mode set to {mode} (applies to the next conversation; /clear to apply now)"))

    # --- REPL -------------------------------------------------------------
    def run(self) -> int:
        try:
            import readline  # noqa: F401 - enables history/line editing
        except Exception:
            pass
        c = self.c
        print(c.bold("ReverseAI") + c.dim("  interactive terminal.  /help for commands, /exit to quit."))
        if self.target:
            print(c.dim(f"  target: {self.target}"))
        if self.project_dir:
            print(c.dim(f"  project: {self.project_dir}"))
        self._new_conv()
        while True:
            try:
                line = input(c.accent("\n› "))
            except (EOFError, KeyboardInterrupt):
                print()
                break
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                if not self._command(line):
                    break
                continue
            self._run_turn(line)
        print(c.dim("bye."))
        return 0


def run_tui(**kwargs) -> int:
    try:
        return TUI(**kwargs).run()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
