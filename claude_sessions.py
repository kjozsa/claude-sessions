#!/usr/bin/env python3
"""Browse and resume Claude Code sessions interactively."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECTS_DIR = Path.home() / ".claude" / "projects"
PROMPT_MAX_LEN = 120


def extract_session_info(jsonl_path: Path) -> dict | None:
    """Extract key info from a session JSONL file."""
    session_id = jsonl_path.stem
    first_user_prompt = None
    last_timestamp = None
    cwd = None
    project_dir = jsonl_path.parent.name  # e.g. -home-kjozsa-workspace-foo

    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") != "user":
                    continue

                ts_str = entry.get("timestamp")
                if ts_str:
                    last_timestamp = ts_str

                if cwd is None:
                    cwd = entry.get("cwd", "")

                if first_user_prompt is None:
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        text = content.strip()
                    elif isinstance(content, list):
                        # content is a list of blocks
                        parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                parts.append(block.get("text", ""))
                            elif isinstance(block, str):
                                parts.append(block)
                        text = " ".join(parts).strip()
                    else:
                        text = ""

                    if text:
                        first_user_prompt = text

    except OSError:
        return None

    if first_user_prompt is None or last_timestamp is None:
        return None

    # Parse timestamp
    try:
        dt = datetime.fromisoformat(last_timestamp.replace("Z", "+00:00"))
        dt_local = dt.astimezone()
    except ValueError:
        return None

    # Human-readable project path: convert -home-kjozsa-foo-bar -> ~/foo/bar
    human_path = project_dir.lstrip("-").replace("-", "/")
    if human_path.startswith("home/"):
        parts = human_path.split("/", 2)
        human_path = "~/" + parts[2] if len(parts) > 2 else "~"

    return {
        "session_id": session_id,
        "timestamp": dt_local,
        "first_prompt": first_user_prompt,
        "cwd": cwd or "",
        "project": human_path,
    }


def load_all_sessions() -> list[dict]:
    """Load all sessions from all project directories, sorted by timestamp desc."""
    sessions = []

    if not PROJECTS_DIR.exists():
        print(f"No projects directory found at {PROJECTS_DIR}", file=sys.stderr)
        sys.exit(1)

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            info = extract_session_info(jsonl_file)
            if info:
                sessions.append(info)

    sessions.sort(key=lambda s: s["timestamp"], reverse=True)
    return sessions


def format_for_fzf(sessions: list[dict]) -> list[str]:
    """Format sessions as lines for fzf input."""
    lines = []
    for s in sessions:
        dt_str = s["timestamp"].strftime("%Y-%m-%d %H:%M")
        prompt = s["first_prompt"].replace("\n", " ")
        if len(prompt) > PROMPT_MAX_LEN:
            prompt = prompt[:PROMPT_MAX_LEN] + "…"
        project = s["project"]
        line = f"{dt_str}  [{project}]  {prompt}"
        lines.append(line)
    return lines


def pick_with_fzf(sessions: list[dict]) -> dict | None:
    """Launch fzf and return the chosen session."""
    lines = format_for_fzf(sessions)
    fzf_input = "\n".join(lines).encode()

    result = subprocess.run(
        [
            "fzf",
            "--ansi",
            "--exact",
            "--no-sort",
            "--prompt=Resume session> ",
            "--height=40%",
            "--layout=reverse",
            "--info=inline",
            "--preview-window=down:3:wrap",
            "--preview",
            "echo {}",
        ],
        input=fzf_input,
        capture_output=True,
    )

    if result.returncode != 0:
        return None  # user cancelled

    chosen_line = result.stdout.decode().strip()
    if not chosen_line:
        return None

    # Match back to session by index
    for i, line in enumerate(lines):
        if line == chosen_line:
            return sessions[i]

    return None


def resume_session(session: dict) -> None:
    """Invoke claude --resume <session_id> in the session's cwd."""
    session_id = session["session_id"]
    cwd = session["cwd"] or str(Path.home())

    print(f"Resuming session {session_id}")
    print(f"  Project : {session['project']}")
    print(f"  Started : {session['timestamp'].strftime('%Y-%m-%d %H:%M')}")
    print(f"  Prompt  : {session['first_prompt'][:80]}")
    print()

    os.chdir(cwd)
    result = subprocess.run(["claude", "--resume", session_id])
    sys.exit(result.returncode)


def main() -> None:
    sessions = load_all_sessions()

    if not sessions:
        print("No sessions found.", file=sys.stderr)
        sys.exit(1)

    chosen = pick_with_fzf(sessions)
    if chosen is None:
        sys.exit(0)

    resume_session(chosen)


if __name__ == "__main__":
    main()
