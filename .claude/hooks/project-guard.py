#!/usr/bin/env python3
"""Claude Code PreToolUse guard for repository-protected operations."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import shlex
import sys
from typing import Any, Literal

Decision = Literal["allow", "deny", "ask"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]

SECRET_PATTERNS = (
    ".env",
    "**/.env",
    ".env.*",
    "**/.env.*",
    "*.pem",
    "**/*.pem",
    "*.key",
    "**/*.key",
    "**/id_rsa",
    "**/id_ed25519",
)

PROTECTED_PATTERNS = (
    "backend/alembic/versions/*.py",
    "backend/docker-compose.yml",
    "backend/Caddyfile",
    "backend/app/core/config.py",
    "backend/app/core/security.py",
    "backend/app/core/ratelimit.py",
    "backend/app/api/webhooks.py",
    "backend/app/api/dependencies.py",
    "backend/app/graph/prompts.py",
    "backend/app/graph/safety.py",
    "backend/app/graph/grounding.py",
    "backend/app/graph/tools.py",
    "**/persona*.md",
    "frontend/src/index.css",
    "Makefile",
    "backend/Makefile",
    "frontend/Makefile",
    "backend/pyproject.toml",
    "frontend/package.json",
    "frontend/package-lock.json",
)

CONTROL_TOKENS = {";", "&&", "||", "|", "&"}
OUTPUT_REDIRECTS = {">", ">>", ">|"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "pip", "pip3", "poetry"}
PACKAGE_ACTIONS = {
    "add",
    "i",
    "install",
    "remove",
    "rm",
    "sync",
    "uninstall",
    "update",
    "upgrade",
}


def _relative_path(raw_path: object, cwd: str) -> str | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path(cwd) / path
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR", PROJECT_ROOT)).resolve()
    try:
        return path.resolve(strict=False).relative_to(project).as_posix()
    except ValueError:
        return path.resolve(strict=False).as_posix()


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _is_secret(path: str) -> bool:
    if path.endswith(".env.example"):
        return False
    return _matches(path, SECRET_PATTERNS)


def _path_decision(path: str) -> tuple[Decision, str] | None:
    if _is_secret(path):
        return "deny", f"Agent writes to secret material are prohibited: {path}"
    if _matches(path, PROTECTED_PATTERNS):
        return "ask", f"Explicit human approval is required before editing {path}"
    return None


def _tokenize(command: str) -> list[str]:
    try:
        # Non-POSIX mode preserves quote characters, letting us distinguish a
        # literal quoted ">" search term from an actual shell redirection.
        lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return []


def _segments(tokens: list[str]) -> list[list[str]]:
    result: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in CONTROL_TOKENS:
            if current:
                result.append(current)
                current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        return token[1:-1]
    return token


def _strip_wrappers(tokens: list[str]) -> list[str]:
    remaining = tokens[:]
    while remaining:
        name = Path(remaining[0]).name
        if name == "command":
            remaining = remaining[1:]
            continue
        if name == "corepack":
            remaining = remaining[1:]
            continue
        if name == "env":
            remaining = remaining[1:]
            while remaining and (remaining[0].startswith("-") or "=" in remaining[0]):
                remaining = remaining[1:]
            continue
        if name == "sudo":
            remaining = remaining[1:]
            while remaining and remaining[0].startswith("-"):
                option = remaining.pop(0)
                if option in {"-u", "-g", "-h", "-p", "-C", "-T"} and remaining:
                    remaining.pop(0)
            continue
        break
    return remaining


def _option_letters(args: list[str]) -> set[str]:
    letters: set[str] = set()
    for arg in args:
        if arg.startswith("--"):
            if arg == "--recursive":
                letters.add("r")
            if arg == "--force":
                letters.add("f")
        elif arg.startswith("-"):
            letters.update(arg[1:].lower())
    return letters


def _git_command(tokens: list[str]) -> tuple[str | None, list[str]]:
    index = 1
    options_with_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
    while index < len(tokens):
        token = tokens[index]
        if token in options_with_value:
            index += 2
        elif token.startswith("-"):
            index += 1
        else:
            return token, tokens[index + 1 :]
    return None, []


def _package_command(tokens: list[str]) -> bool:
    name = Path(tokens[0]).name
    args = tokens[1:]
    if name.startswith("python") and len(args) >= 2 and args[:2] == ["-m", "pip"]:
        name, args = "pip", args[2:]
    if name == "uv":
        args = _strip_uv_global_options(args)
    if name == "uv" and args and args[0] == "pip":
        name, args = "pip", args[1:]
    elif name == "uv":
        action = next((arg for arg in args if not arg.startswith("-")), None)
        return action in PACKAGE_ACTIONS
    if name not in PACKAGE_MANAGERS:
        return False
    value_options = {"--prefix", "--cwd", "--dir", "--global-dir", "-C"}
    index = 0
    action = None
    while index < len(args):
        arg = args[index]
        if arg in value_options:
            index += 2
        elif arg.startswith("-"):
            index += 1
        else:
            action = arg
            break
    return action in PACKAGE_ACTIONS or (name == "npm" and action == "ci")


def _strip_uv_global_options(args: list[str]) -> list[str]:
    value_options = {
        "--project",
        "--directory",
        "--config-file",
        "--python",
        "--cache-dir",
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in value_options:
            index += 2
        elif any(arg.startswith(f"{option}=") for option in value_options):
            index += 1
        elif arg.startswith("-"):
            index += 1
        else:
            break
    return args[index:]


def _make_requires_approval(tokens: list[str]) -> bool:
    if Path(tokens[0]).name != "make":
        return False
    value_options = {"-C", "--directory", "-f", "--file", "--makefile"}
    targets: list[str] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in value_options:
            index += 2
        elif token.startswith("--directory=") or token.startswith("--file="):
            index += 1
        elif token.startswith("-") or "=" in token:
            index += 1
        else:
            targets.append(token)
            index += 1
    return any(target.startswith("deploy") or target == "restore-prod" for target in targets)


def _protected_output(tokens: list[str], cwd: str) -> tuple[Decision, str] | None:
    for index, token in enumerate(tokens[:-1]):
        if token not in OUTPUT_REDIRECTS:
            continue
        path = _relative_path(_unquote(tokens[index + 1]), cwd)
        decision = _path_decision(path) if path is not None else None
        if decision is not None:
            return decision
    return None


def _protected_mutation(tokens: list[str], cwd: str) -> tuple[Decision, str] | None:
    name = Path(tokens[0]).name
    args = tokens[1:]
    candidates: list[str] = []
    in_place = "i" in _option_letters(args) or any(
        arg == "--in-place" or arg.startswith("--in-place=") for arg in args
    )
    if name in {"sed", "perl"} and in_place:
        candidates = [arg for arg in args if not arg.startswith("-")]
    elif name == "tee":
        candidates = [arg for arg in args if not arg.startswith("-")]
    elif name == "cp" and "-t" in args:
        index = args.index("-t")
        if index + 1 < len(args):
            target = args[index + 1]
            candidates = [str(Path(target) / Path(source).name) for source in args[index + 2 :]]
    elif name == "cp" and any(arg.startswith("--target-directory=") for arg in args):
        option = next(arg for arg in args if arg.startswith("--target-directory="))
        target = option.split("=", 1)[1]
        sources = [arg for arg in args if not arg.startswith("-")]
        candidates = [str(Path(target) / Path(source).name) for source in sources]
    elif name == "truncate":
        index = 0
        while index < len(args):
            arg = args[index]
            if arg in {"-s", "--size", "-o", "--io-blocks", "-r", "--reference"}:
                index += 2
            elif arg.startswith("-"):
                index += 1
            else:
                candidates.append(arg)
                index += 1
    elif name in {"cp", "mv", "install"}:
        candidates = args[-1:]
    elif name == "rm":
        candidates = [arg for arg in args if not arg.startswith("-")]
    for candidate in candidates:
        path = _relative_path(candidate, cwd)
        decision = _path_decision(path) if path is not None else None
        if decision is not None:
            return decision
    return None


def _segment_decision(tokens: list[str], cwd: str) -> tuple[Decision, str] | None:
    output_decision = _protected_output(tokens, cwd)
    if output_decision is not None:
        return output_decision

    tokens = [_unquote(token) for token in tokens]
    tokens = _strip_wrappers(tokens)
    if not tokens:
        return None
    name = Path(tokens[0]).name
    args = tokens[1:]

    if name in SHELLS and "-c" in args:
        index = args.index("-c")
        if index + 1 < len(args):
            return _command_decision(args[index + 1], cwd)
    if name == "xargs":
        value_options = {"-a", "-E", "-I", "-L", "-n", "-P", "-s"}
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token in value_options:
                index += 2
            elif token.startswith("-"):
                index += 1
            else:
                return _segment_decision(tokens[index:], cwd)
    mutation_decision = _protected_mutation(tokens, cwd)
    if mutation_decision is not None:
        return mutation_decision
    if name == "rm" and {"r", "f"}.issubset(_option_letters(args)):
        return "deny", "Destructive recursive forced remove blocked by repository policy"
    if name == "git":
        subcommand, git_args = _git_command(tokens)
        if subcommand == "reset" and "--hard" in git_args:
            return "deny", "Destructive Git reset blocked by repository policy"
        if subcommand == "clean" and "f" in _option_letters(git_args):
            return "deny", "Destructive Git clean blocked by repository policy"
        if subcommand == "checkout":
            creates_branch = any(
                arg in {"-b", "-B", "--orphan", "--detach"} for arg in git_args
            )
            positional = [arg for arg in git_args if not arg.startswith("-")]
            existing_path = any((Path(cwd) / arg).exists() for arg in positional)
            if not creates_branch and (
                "-f" in git_args
                or "--force" in git_args
                or "--" in git_args
                or len(positional) > 1
                or existing_path
            ):
                return "deny", "Potentially destructive git checkout blocked by repository policy"
        if subcommand == "restore" and not (
            ("--staged" in git_args or "-S" in git_args)
            and "--worktree" not in git_args
            and "-W" not in git_args
        ):
            return "deny", "Potentially destructive git restore blocked by repository policy"
        if subcommand == "switch" and any(
            flag in git_args for flag in {"--discard-changes", "--force", "-f"}
        ):
            return "deny", "Destructive git switch blocked by repository policy"
    if _make_requires_approval(tokens) or _package_command(tokens):
        return "ask", "This operation requires explicit human approval"
    python_alembic = name.startswith("python") and args[:2] == ["-m", "alembic"]
    uv_args = _strip_uv_global_options(args) if name == "uv" else args
    uv_alembic = name == "uv" and uv_args[:2] == ["run", "alembic"]
    if (name == "alembic" and "revision" in args) or (
        python_alembic and "revision" in args[2:]
    ) or (
        uv_alembic and "revision" in uv_args[2:]
    ):
        return "ask", "Creating a migration requires explicit human approval"
    if name == "docker" and "compose" in args:
        actions = {"up", "down", "restart", "pull", "build", "create", "start", "stop"}
        compose_files: list[str] = []
        for index, arg in enumerate(args):
            if arg in {"-f", "--file"} and index + 1 < len(args):
                compose_files.append(args[index + 1])
            elif arg.startswith("--file="):
                compose_files.append(arg.split("=", 1)[1])
        resolved_compose_files = [
            path
            for item in compose_files
            if (path := _relative_path(item, cwd)) is not None
        ]
        uses_dev_compose = any(
            path.endswith("docker-compose.dev.yml") for path in resolved_compose_files
        )
        uses_prod_compose = "backend/docker-compose.yml" in resolved_compose_files
        if actions.intersection(args) and (
            not uses_dev_compose
            and (uses_prod_compose or (Path(cwd).name == "backend" and not compose_files))
        ):
            return "ask", "Production Compose operations require explicit human approval"
    return None


def _command_decision(command: str, cwd: str) -> tuple[Decision, str] | None:
    for segment in _segments(_tokenize(command)):
        decision = _segment_decision(segment, cwd)
        if decision is not None:
            return decision
    return None


def evaluate(payload: dict[str, Any]) -> tuple[Decision, str] | None:
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "Bash":
        command = tool_input.get("command")
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
        return _command_decision(command, cwd) if isinstance(command, str) else None
    if tool_name in {"Edit", "Write", "MultiEdit", "NotebookEdit"}:
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
        path = _relative_path(tool_input.get("file_path"), cwd)
        return _path_decision(path) if path is not None else None
    return None


def _emit(decision: Decision, reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    result = evaluate(payload)
    if result is not None:
        _emit(*result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
