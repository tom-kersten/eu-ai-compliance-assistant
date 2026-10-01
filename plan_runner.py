#!/usr/bin/env python3
"""
plan_runner.py - run an implementation plan task by task, unattended.

For each task in the plan, in dependency order:
  1. Cursor (plan mode, read-only) writes a build plan.
  2. Claude Code (headless, read-only) reviews it against the task spec and the repo docs.
       approve -> continue
       revise  -> the plan is corrected (by Claude or by Cursor) and reviewed again
  3. Cursor implements the approved plan (auto-run).
  4. Gate: `make lint` and `make test` must pass (Cursor gets a few tries to fix failures).
  5. The result is committed.
Anything unrecoverable halts the run with a clear reason. State and artifacts live in
<repo>/.plan_runner/ (git-ignored automatically), so a halted run can be resumed.

Standard library only. Needs the Cursor CLI (`agent`) and Claude Code (`claude`) on PATH.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

WORKDIR = ".plan_runner"
PLAN_TIMEOUT, REVIEW_TIMEOUT, EXEC_TIMEOUT, GATE_TIMEOUT = 900, 900, 3600, 1800

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "revise"]},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["blocker", "minor"]},
                    "problem": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "problem", "fix"],
            },
        },
        "revised_plan": {"type": "string"},
    },
    "required": ["verdict", "issues", "revised_plan"],
}


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "basis": {"type": "string"},
                    "grounded": {"type": "boolean"},
                },
                "required": ["question", "answer", "basis", "grounded"],
            },
        }
    },
    "required": ["answers"],
}

MAX_QUESTION_ROUNDS = 2
QUESTION_RULE = (
    "If something you need is not settled by the task spec or the documents and you would otherwise "
    "have to guess, do not guess and do not ask in prose: make your final message start with the line "
    "QUESTIONS: followed by a numbered list of specific questions (nothing else; leave any work already "
    "done in place). A project lead will answer and you will be run again. Ask only what genuinely blocks you."
)


class Halt(Exception):
    """Unrecoverable problem: a human needs to look."""


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------- plan parsing


@dataclass
class Task:
    id: str
    title: str
    deps: list[str]
    section: str  # the task's full markdown section


def parse_plan(text: str) -> tuple[list[Task], str]:
    """Tasks come from the overview table (order, title, dependencies) and the
    `### T<N>. Title` sections (spec). Returns (tasks, 'rules for every task' text)."""
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 5 and re.fullmatch(r"T\d+", cells[0]):
                rows[cells[0]] = cells

    sections: dict[str, str] = {}
    next_heading = re.compile(r"^#{2,3} ", re.M)
    for m in re.finditer(r"^### (T\d+)\. .+$", text, re.M):
        nxt = next_heading.search(text, m.end())
        sections[m.group(1)] = text[m.start(): nxt.start() if nxt else len(text)].strip()

    if set(rows) != set(sections):
        raise Halt(
            "Overview table and task sections disagree. "
            f"Only in table: {sorted(set(rows) - set(sections))}; "
            f"only as sections: {sorted(set(sections) - set(rows))}"
        )

    tasks = []
    for tid, cells in rows.items():
        if cells[4].strip().lower() == "all":
            deps = [t for t in rows if t != tid]
        else:
            deps = re.findall(r"T\d+", cells[4])
        tasks.append(Task(tid, cells[1], deps, sections[tid]))

    m = re.search(r"\*\*Rules for every task:\*\*\s*(.+)", text)
    return tasks, (m.group(1).strip() if m else "")


# --------------------------------------------------------------------------- helpers


def run(cmd, cwd: Path, timeout: int, input_text: str | None = None, shell: bool = False):
    try:
        return subprocess.run(
            cmd, cwd=cwd, input=input_text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, shell=shell,
        )
    except subprocess.TimeoutExpired:
        raise Halt(f"timed out after {timeout}s: {cmd if shell else cmd[0]}")


def parse_json(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def rel(cfg, path: Path) -> str:
    return path.relative_to(cfg.repo).as_posix()


def git(cfg, *args: str, check: bool = True, input_text: str | None = None) -> str:
    p = run(["git", *args], cfg.repo, 120, input_text=input_text)
    if check and p.returncode != 0:
        raise Halt(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


def load_state(cfg) -> dict:
    f = cfg.work / "state.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def save_state(cfg, state: dict) -> None:
    cfg.work.mkdir(exist_ok=True)
    tmp = cfg.work / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(cfg.work / "state.json")


# --------------------------------------------------------------------------- tool calls


def call_cursor(cfg, prompt: str, *, write: bool, timeout: int) -> str:
    """Ask mode (read-only) when write=False; auto-run with file edits when write=True.
    Not --mode=plan: in that mode Cursor routes its plan into a dedicated "create plan"
    tool call instead of the final chat message, so the JSON `result` field (which this
    function reads) ends up with only a one-line narration ("I'll read X now.") and the
    reviewer always rejects it as empty. --mode=ask is also read-only but answers directly
    in the final message, confirmed by direct testing against the real CLI."""
    cmd = [cfg.cursor_bin, "-p", "--output-format", "json"]
    cmd += ["--force"] if write else ["--mode=ask"]
    if cfg.cursor_model:
        cmd += ["--model", cfg.cursor_model]
    cmd += shlex.split(cfg.cursor_args) + [prompt]
    p = run(cmd, cfg.repo, timeout)
    data = parse_json(p.stdout)
    if p.returncode != 0 or (isinstance(data, dict) and data.get("is_error")):
        raise Halt(f"Cursor CLI failed (exit {p.returncode}): {(p.stderr or p.stdout)[-800:]}")
    result = data["result"] if isinstance(data, dict) and "result" in data else p.stdout
    if not write and not result.strip():
        raise Halt("Cursor returned an empty plan")
    return result


def call_claude(cfg, prompt: str, schema: dict, valid) -> tuple[dict, float]:
    """Claude Code headless, read-only tools, schema-validated JSON output."""
    cmd = [
        cfg.claude_bin, "-p", "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--allowedTools", "Read,Grep,Glob",
        "--disallowedTools", "Edit,Write,Bash",
        "--max-turns", "30",
    ]
    if cfg.claude_model:
        cmd += ["--model", cfg.claude_model]
    cmd += shlex.split(cfg.claude_args)

    detail = ""
    for attempt in (1, 2):
        p = run(cmd, cfg.repo, REVIEW_TIMEOUT, input_text=prompt)  # prompt via stdin
        data = parse_json(p.stdout)
        out = data.get("structured_output") if isinstance(data, dict) else None
        if isinstance(out, str):
            out = parse_json(out)
        if isinstance(out, dict) and valid(out):
            return out, float(data.get("total_cost_usd") or 0)
        # Prefer showing the parsed-but-invalid object (e.g. a schema-valid but
        # empty `answers` list) over a raw stdout tail, which is usually a cut-off
        # JSON blob of telemetry fields and not actionable.
        detail = json.dumps(out) if isinstance(out, dict) else (p.stderr or p.stdout)[-600:]
        log(f"Claude gave no valid structured output (attempt {attempt}/2)")
    raise Halt(f"Claude failed to return valid structured output: {detail}")


def call_reviewer(cfg, prompt: str) -> tuple[dict, float]:
    def valid(o: dict) -> bool:
        if o.get("verdict") in ("approve", "revise") and isinstance(o.get("issues"), list):
            o.setdefault("revised_plan", "")
            return True
        return False
    return call_claude(cfg, prompt, REVIEW_SCHEMA, valid)


def extract_questions(message: str) -> str | None:
    """Cursor signals it is blocked on questions with a line starting with QUESTIONS:.
    In practice the model often prepends a short narration sentence with no separator
    (e.g. "I'll check the repo first.QUESTIONS:\n1. ..."), so this matches QUESTIONS:
    anywhere in the message rather than requiring it to be the very first token."""
    m = re.search(r"QUESTIONS:\s*(.*)", message, re.S)
    return m.group(1).strip() if m else None


def answer_questions(cfg, task, questions: str, st: dict) -> None:
    """Claude answers Cursor's questions from the project documents; answers are logged for audit."""
    log("Cursor has questions; asking Claude to answer them from the project documents...")
    out, cost = call_claude(
        cfg, answer_prompt(cfg, task, questions), ANSWER_SCHEMA,
        lambda o: isinstance(o.get("answers"), list) and len(o["answers"]) > 0)
    st["review_cost_usd"] = round(st.get("review_cost_usd", 0) + cost, 4)
    clar = cfg.work / task.id / "clarifications.md"
    ungrounded = []
    with clar.open("a", encoding="utf-8") as f:
        for a in out["answers"]:
            tag = "" if a["grounded"] else " [ASSUMPTION: the documents do not settle this]"
            f.write(f"Q: {a['question']}\nA: {a['answer']}{tag}\nBasis: {a['basis']}\n\n")
            log(f"  Q: {a['question']}\n     A: {a['answer']}{tag}")
            if not a["grounded"]:
                ungrounded.append(a["question"])
    if ungrounded and cfg.on_ungrounded == "halt":
        raise Halt(f"{task.id}: the documents do not settle: {ungrounded}. "
                   f"Answers so far are in {rel(cfg, clar)}; edit it if you like and rerun.")


# --------------------------------------------------------------------------- prompts


def deps_hint(cfg, task: Task) -> str:
    paths = [rel(cfg, cfg.work / d / "summary.md") for d in task.deps
             if (cfg.work / d / "summary.md").exists()]
    return ("Summaries from completed tasks this one depends on (read them): "
            + ", ".join(paths)) if paths else ""


def clar_hint(cfg, task: Task) -> str:
    f = cfg.work / task.id / "clarifications.md"
    return (f"Answers to your earlier questions are in {rel(cfg, f)}: treat them as authoritative "
            "and do not ask them again.") if f.exists() else ""


def answer_prompt(cfg, task: Task, questions: str) -> str:
    return f"""You are the project lead answering questions from a coding agent (Cursor) that is working unattended on Task {task.id}. You have read-only repository access (Read, Grep, Glob): use it.

## Task spec
{task.section}

## Questions from the agent
{questions}

## How to answer
1. Read AGENTS.md, the documents and rule files named under "Read first", and any other document in docs/ that a question touches.
2. Answer every question, once each, briefly and concretely, from those documents. In "basis" cite the file and section. Set grounded=true ONLY if the documents actually settle the question.
3. If they do not, choose the most conservative option consistent with the documents (smallest scope, no new dependencies, nothing that pre-empts a later task) and set grounded=false. Never invent requirements and never override a document."""


def plan_prompt(cfg, task: Task, tdir: Path) -> str:
    return f"""You are PLANNING (not implementing) Task {task.id} of {cfg.plan_rel}.
1. Read AGENTS.md, the "How to use this plan" section and the Task {task.id} section of {cfg.plan_rel} (the task spec is also in {rel(cfg, tdir / 'task.md')}).
2. Read every document and rule file listed under "Read first" in the task.
3. {deps_hint(cfg, task) or "No earlier task summaries are available."} {clar_hint(cfg, task)}
4. Produce a local build plan: the files to create or change, the tests you will write first (in order), and how you will check each acceptance criterion. Stay strictly inside this task's scope and do not deviate from the documents.
Do NOT edit any files. Output the complete plan as your final message, in markdown.
{QUESTION_RULE}"""


def replan_prompt(cfg, task: Task, plan_file: Path, feedback_file: Path) -> str:
    return f"""Your build plan for Task {task.id} of {cfg.plan_rel} was reviewed and needs changes.
Your previous plan: {rel(cfg, plan_file)}
Reviewer feedback: {rel(cfg, feedback_file)}
Re-read the task spec and the "Read first" documents as needed, then produce a corrected, COMPLETE plan (not a diff) that resolves every blocker. Do NOT edit any files. Output the complete plan as your final message, in markdown.
{clar_hint(cfg, task)}
{QUESTION_RULE}"""


def review_prompt(cfg, task: Task, plan: str, rules: str, rnd: int) -> str:
    if cfg.revise_mode == "claude":
        revise = ('If the verdict is "revise", put the COMPLETE corrected plan in revised_plan '
                  "(markdown, same structure as the proposed plan) resolving every blocker. "
                  'If the verdict is "approve", revised_plan must be an empty string.')
    else:
        revise = ("Always leave revised_plan as an empty string; the planner will revise "
                  "the plan from your issues.")
    clar_file = cfg.work / task.id / "clarifications.md"
    clar = (f"## Clarifications already given to the planner (authoritative)\n"
            f"{clar_file.read_text(encoding='utf-8')}\n") if clar_file.exists() else ""
    return f"""You are the independent reviewer in an automated pipeline. A coding agent wrote a build plan for ONE task of a larger implementation plan. Decide whether the plan is good enough to be implemented exactly as written. You have read-only repository access (Read, Grep, Glob): use it.

## Task spec (authoritative)
{task.section}

## Rules that apply to every task
{rules or "(none extracted)"}

{clar}## Proposed build plan (round {rnd})
{plan}

## How to review
1. Read AGENTS.md and the documents and rule files named under "Read first" in the spec, and check the plan against them. Verify that files the plan modifies actually exist and that new files do not collide with existing ones (completed earlier tasks: {", ".join(cfg.done_ids) or "none"}).
2. Check that: every deliverable is covered; every "Tests first" item appears as a test written BEFORE the code it tests, in a sensible order; every acceptance criterion has a concrete check; nothing is out of scope (no work belonging to later tasks, no speculative extras); nothing conflicts with the documents (deviations are not allowed).
3. Ground every issue in the spec or the documents. Do not nitpick style. "blocker" = would lead to a wrong, incomplete or out-of-scope implementation. "minor" = worthwhile but not blocking.
Verdict "approve" is only allowed when there are no blockers. Each issue needs a concrete fix.
{revise}"""


def execute_prompt(cfg, task: Task, approved: Path, summary: Path, partial: bool) -> str:
    resume = ("\nA previous attempt left partial work in the working tree: inspect it with git status/git diff and continue from there."
              if partial else "")
    return f"""Implement Task {task.id} from {cfg.plan_rel}.
The approved build plan is {rel(cfg, approved)}: follow it. Also read AGENTS.md, the "How to use this plan" section (including the rules for every task) and the "Read first" documents of the task. {deps_hint(cfg, task)} {clar_hint(cfg, task)}{resume}
- Implement test-first in small steps; every step ends green (make test, make lint).
- Before writing your summary, you MUST actually run `make lint` and `make test` yourself, in this shell, and wait for them to finish. They work in this environment. Do not guess, assume, or state that they cannot be run or that a dependency (docker, pytest, ...) is unavailable without first actually trying the command and showing the real error. A separate, independent check re-runs them after you anyway, so a false claim here only wastes a round; an honest failure is fine.
- Stay inside Task {task.id}'s scope. Nobody can answer you interactively (see the QUESTIONS rule below). If the plan and the documents conflict, follow the documents and record the deviation in your summary.
- {QUESTION_RULE}
- Do NOT commit, push, or touch anything under {WORKDIR}/ (other than the summary file below).
- If you cannot complete the task without violating the documents, stop and make the first word of the summary BLOCKED, followed by the reason.
- When finished, write your report to {rel(cfg, summary)}. It becomes the git commit message body, so write plain text (no markdown headings, lines under 100 characters) with these labeled parts: "Changes:" (a short bullet list of what was added or changed, by file or module), "Tests:" (the exact commands you ran and their real pass/fail output, not a guess), "Deviations:" (from the documents, or "none"), "Next task:" (what the next task needs to know)."""


def fix_prompt(cfg, task: Task, cmd: str, log_file: Path, approved: Path) -> str:
    return f"""Task {task.id} of {cfg.plan_rel} has been implemented (plan: {rel(cfg, approved)}) but the verification gate failed.
Failing command: {cmd}
Its output is in {rel(cfg, log_file)}. Inspect the working tree (git status/git diff), fix the cause without expanding scope, and re-run the command until it passes. Do NOT commit or push."""


# --------------------------------------------------------------------------- pipeline steps


def render_feedback(review: dict) -> str:
    lines = ["# Reviewer feedback", ""]
    for i in review["issues"]:
        lines.append(f"- **{i['severity']}**: {i['problem']}\n  - Fix: {i['fix']}")
    return "\n".join(lines) + "\n"


def plan_with_questions(cfg, task: Task, tdir: Path, make_prompt, st: dict) -> str:
    """Ask Cursor for a plan; if it asks questions instead, Claude answers and Cursor retries."""
    for n in range(MAX_QUESTION_ROUNDS + 1):
        out = call_cursor(cfg, make_prompt(), write=False, timeout=PLAN_TIMEOUT)
        questions = extract_questions(out)
        if questions is None:
            return out
        if n == MAX_QUESTION_ROUNDS:
            raise Halt(f"{task.id}: Cursor still has questions after {MAX_QUESTION_ROUNDS} rounds:\n{questions}")
        answer_questions(cfg, task, questions, st)
    raise AssertionError("unreachable")


def plan_and_review(cfg, task: Task, tdir: Path, rules: str, st: dict) -> None:
    log("planning (Cursor, plan mode)...")
    plan = plan_with_questions(cfg, task, tdir, lambda: plan_prompt(cfg, task, tdir), st)
    for rnd in range(1, cfg.max_rounds + 1):
        plan_file = tdir / f"plan-{rnd}.md"
        plan_file.write_text(plan, encoding="utf-8")
        log(f"reviewing plan, round {rnd}/{cfg.max_rounds} (Claude Code)...")
        review, cost = call_reviewer(cfg, review_prompt(cfg, task, plan, rules, rnd))
        st["review_cost_usd"] = round(st.get("review_cost_usd", 0) + cost, 4)
        (tdir / f"review-{rnd}.json").write_text(json.dumps(review, indent=2), encoding="utf-8")

        blockers = [i for i in review["issues"] if i["severity"] == "blocker"]
        if review["verdict"] == "approve" and not blockers:
            (tdir / "approved_plan.md").write_text(plan, encoding="utf-8")
            st.update(status="approved", rounds=rnd)
            log(f"plan approved in round {rnd} ({len(review['issues'])} minor note(s))")
            return

        log(f"plan needs changes: {len(blockers)} blocker(s), "
            f"{len(review['issues']) - len(blockers)} minor")
        for i in blockers:
            log(f"  - {i['problem']}")
        if rnd == cfg.max_rounds:
            break
        if cfg.revise_mode == "claude" and review["revised_plan"].strip():
            log("using Claude's revised plan")
            plan = review["revised_plan"]
        else:
            fb = tdir / f"feedback-{rnd}.md"
            fb.write_text(render_feedback(review), encoding="utf-8")
            log("asking Cursor to revise the plan from the feedback...")
            plan = plan_with_questions(cfg, task, tdir,
                                       lambda: replan_prompt(cfg, task, plan_file, fb), st)
    raise Halt(f"{task.id}: plan not approved after {cfg.max_rounds} rounds; see {rel(cfg, tdir)}/")


def run_gate(cfg, tdir: Path, attempt: int):
    for cmd in cfg.gate:
        log(f"gate: {cmd}")
        p = run(cmd, cfg.repo, GATE_TIMEOUT, shell=True)
        if p.returncode != 0:
            f = tdir / f"gate-failure-{attempt}.log"
            f.write_text(f"$ {cmd}\n\n{p.stdout}\n{p.stderr}", encoding="utf-8")
            return cmd, f
    return None


def commit(cfg, task: Task, report: str, fix_rounds: int, clarifications: str = "") -> str:
    """Title: 'T4: Task Title'. Body: the change report written by Cursor."""
    git(cfg, "add", "-A")
    if git(cfg, "status", "--porcelain") == "":
        log("warning: the task produced no changes to commit")
        return ""
    body = report.strip() or "(Cursor provided no report)"
    if clarifications.strip():
        body += ("\n\nClarifications (Cursor's questions, answered by Claude from the project docs):\n"
                 + clarifications.strip())
    if fix_rounds:
        body += f"\n\nNote: {fix_rounds} automated fix attempt(s) were needed to get make lint/test green."
    git(cfg, "commit", "-F", "-", input_text=f"{task.id}: {task.title}\n\n{body}\n")
    return git(cfg, "rev-parse", "--short", "HEAD")


def run_task(cfg, task: Task, state: dict, rules: str) -> None:
    tdir = cfg.work / task.id
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "task.md").write_text(task.section + "\n", encoding="utf-8")
    approved, summary = tdir / "approved_plan.md", tdir / "summary.md"
    st = state.setdefault(task.id, {})
    st.pop("halt_reason", None)

    log(f"=== {task.id}: {task.title}")
    was_executing = st.get("status") == "executing"
    reuse_plan = st.get("status") in ("approved", "executing") and approved.exists() and not cfg.replan
    if reuse_plan:
        log("reusing the approved plan from the previous run")
    else:
        if cfg.replan or not st.get("status"):  # keep answers across a halted/resumed planning phase
            (tdir / "clarifications.md").unlink(missing_ok=True)
        st["status"] = "planning"
        save_state(cfg, state)
        plan_and_review(cfg, task, tdir, rules, st)

    st["status"] = "executing"
    save_state(cfg, state)
    summary.unlink(missing_ok=True)
    log("implementing (Cursor, auto-run) - this can take a while...")
    for n in range(MAX_QUESTION_ROUNDS + 1):
        final_message = call_cursor(
            cfg, execute_prompt(cfg, task, approved, summary, was_executing or n > 0),
            write=True, timeout=EXEC_TIMEOUT)
        questions = extract_questions(final_message)
        if questions is None:
            break
        if n == MAX_QUESTION_ROUNDS:
            raise Halt(f"{task.id}: Cursor still has questions after {MAX_QUESTION_ROUNDS} rounds:\n{questions}")
        answer_questions(cfg, task, questions, st)
    if summary.exists() and summary.read_text(encoding="utf-8").lstrip().upper().startswith("BLOCKED"):
        raise Halt(f"{task.id}: the agent reported it is blocked; see {rel(cfg, summary)}")

    fix_rounds = 0
    for attempt in range(cfg.fix_attempts + 1):
        failure = run_gate(cfg, tdir, attempt)
        if failure is None:
            break
        cmd, log_file = failure
        if attempt == cfg.fix_attempts:
            raise Halt(f"{task.id}: gate failed (`{cmd}`), see {rel(cfg, log_file)}. "
                       "Working tree left as is; rerun to retry the implementation.")
        log(f"gate failed; asking Cursor to fix ({attempt + 1}/{cfg.fix_attempts})...")
        call_cursor(cfg, fix_prompt(cfg, task, cmd, log_file, approved),
                    write=True, timeout=EXEC_TIMEOUT)
        fix_rounds += 1

    report = summary.read_text(encoding="utf-8") if summary.exists() else final_message
    clar_file = tdir / "clarifications.md"
    sha = commit(cfg, task, report, fix_rounds,
                 clar_file.read_text(encoding="utf-8") if clar_file.exists() else "")
    st.update(status="done", commit=sha, finished=datetime.now().isoformat(timespec="seconds"))
    save_state(cfg, state)
    log(f"{task.id} done" + (f" (commit {sha})" if sha else ""))


# --------------------------------------------------------------------------- setup and main


def parse_args():
    ap = argparse.ArgumentParser(description="Run an implementation plan task by task.")
    ap.add_argument("--repo", default=".", help="repository root (default: current dir)")
    ap.add_argument("--plan", default="docs/IMPLEMENTATION_PLAN.md", help="plan path, relative to the repo")
    ap.add_argument("--only", default="", help="comma-separated task ids to run, e.g. T1 or T4,T5")
    ap.add_argument("--defer", default="T1",
                    help="tasks to skip (and everything depending on them) until named via --only. "
                         "Default T1, which needs a live provider key. Use --defer '' for none.")
    ap.add_argument("--stop-after", default="", help="stop cleanly after this task, e.g. T9")
    ap.add_argument("--max-rounds", type=int, default=3, help="plan review rounds per task")
    ap.add_argument("--revise-mode", choices=["claude", "cursor"], default="claude",
                    help="who rewrites a rejected plan: Claude in place, or Cursor from Claude's feedback")
    ap.add_argument("--fix-attempts", type=int, default=2, help="Cursor fix attempts when the gate fails")
    ap.add_argument("--gate", action="append", help="gate command (repeatable). Default: make lint, make test")
    ap.add_argument("--on-ungrounded", choices=["assume", "halt"], default="assume",
                    help="when Claude's answer to a Cursor question is not settled by the docs: "
                         "'assume' = use the conservative answer and record it; 'halt' = stop for a human")
    ap.add_argument("--replan", action="store_true", help="ignore an approved plan from an earlier run")
    ap.add_argument("--cursor-bin", default=None)
    ap.add_argument("--cursor-model", default=None)
    ap.add_argument("--cursor-args", default="--trust", help="extra Cursor CLI args (default: --trust)")
    ap.add_argument("--claude-bin", default=None)
    ap.add_argument("--claude-model", default=None)
    ap.add_argument("--claude-args", default="", help="extra Claude Code CLI args")
    ap.add_argument("--allow-dirty", action="store_true", help="start with uncommitted changes")
    ap.add_argument("--allow-main", action="store_true", help="allow running on main/master")
    ap.add_argument("--list", action="store_true", help="show parsed tasks and status, then exit")
    return ap.parse_args()


def ids(s: str) -> set[str]:
    return {x.strip().upper() for x in s.split(",") if x.strip()}


def print_list(tasks: list[Task], state: dict) -> None:
    for t in tasks:
        status = state.get(t.id, {}).get("status", "todo")
        deps = ",".join(t.deps) if len(t.deps) < 6 else "all"
        print(f"{t.id:<4} {status:<10} deps: {deps or '-':<12} {t.title}")


def setup(cfg) -> None:
    cfg.cursor_bin = cfg.cursor_bin or shutil.which("agent") or shutil.which("cursor-agent")
    cfg.claude_bin = cfg.claude_bin or shutil.which("claude")
    if not cfg.cursor_bin:
        raise Halt("Cursor CLI not found on PATH (tried `agent`, `cursor-agent`); use --cursor-bin")
    if not cfg.claude_bin:
        raise Halt("Claude Code not found on PATH; use --claude-bin")
    if git(cfg, "rev-parse", "--is-inside-work-tree", check=False) != "true":
        raise Halt(f"{cfg.repo} is not a git repository")
    branch = git(cfg, "symbolic-ref", "--short", "HEAD", check=False)
    log(f"repo: {cfg.repo}  branch: {branch or '(detached)'}")
    if branch in ("main", "master") and not cfg.allow_main:
        raise Halt("refusing to run on main/master: create a branch first (or pass --allow-main)")
    # keep our artifacts out of git without touching .gitignore
    exclude = Path(git(cfg, "rev-parse", "--git-path", "info/exclude"))
    exclude = exclude if exclude.is_absolute() else cfg.repo / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if f"{WORKDIR}/" not in current:
        exclude.write_text(current + ("\n" if current and not current.endswith("\n") else "")
                           + f"{WORKDIR}/\n", encoding="utf-8")


def main() -> int:
    cfg = parse_args()
    cfg.repo = Path(cfg.repo).resolve()
    cfg.work = cfg.repo / WORKDIR
    cfg.plan_rel = cfg.plan
    cfg.gate = cfg.gate or ["make lint", "make test"]
    cfg.done_ids = []

    try:
        plan_file = cfg.repo / cfg.plan
        if not plan_file.exists():
            raise Halt(f"plan not found: {plan_file}")
        tasks, rules = parse_plan(plan_file.read_text(encoding="utf-8"))
        state = load_state(cfg)
        if cfg.list:
            print_list(tasks, state)
            return 0

        setup(cfg)
        resuming = any(s.get("status") in ("approved", "executing") for s in state.values())
        if git(cfg, "status", "--porcelain") and not (cfg.allow_dirty or resuming):
            raise Halt("working tree has uncommitted changes; commit/stash them first (or --allow-dirty)")

        only, defer = ids(cfg.only), ids(cfg.defer) - ids(cfg.only)
        unknown = (only | defer | ids(cfg.stop_after)) - {t.id for t in tasks}
        if unknown:
            raise Halt(f"unknown task id(s): {sorted(unknown)}")

        def is_done(tid: str) -> bool:
            return state.get(tid, {}).get("status") == "done"

        while True:
            cfg.done_ids = [t.id for t in tasks if is_done(t.id)]
            nxt = next((t for t in tasks
                        if not is_done(t.id) and (not only or t.id in only)
                        and t.id not in defer and all(is_done(d) for d in t.deps)), None)
            if nxt is None:
                break
            try:
                run_task(cfg, nxt, state, rules)
            except Halt as e:
                state.setdefault(nxt.id, {})["halt_reason"] = str(e)
                save_state(cfg, state)
                raise
            if nxt.id in ids(cfg.stop_after):
                log(f"stopping after {nxt.id} as requested")
                break

        left = [t for t in tasks if not is_done(t.id)]
        if not left:
            log("all tasks done")
        else:
            log(f"{len(tasks) - len(left)}/{len(tasks)} tasks done. Not run:")
            for t in left:
                if only and t.id not in only:
                    continue
                if t.id in defer:
                    why = "deferred (run it with --only)"
                else:
                    waiting = [d for d in t.deps if not is_done(d)]
                    why = f"waiting for {', '.join(waiting[:6])}" if waiting else "stopped early"
                log(f"  {t.id}: {why}")
        return 0
    except Halt as e:
        log(f"HALTED: {e}")
        return 2
    except KeyboardInterrupt:
        log("interrupted; state saved, rerun to resume")
        return 130


if __name__ == "__main__":
    sys.exit(main())
