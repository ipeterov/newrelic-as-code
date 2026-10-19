"""PreToolUse(Bash) guard for Claude Code, wired from .claude/settings.json.

Reads the hook payload as JSON on stdin and inspects the bash command Claude is
about to run. It blocks (exit 2, reason on stderr) git the developer couldn't
walk back. Claude may stage and commit: the developer reviews each local commit
before pushing and can drop any of them. So the guard blocks whatever would take
that ability away -- pushing, destroying uncommitted work, changing existing
commits, wiping the reflog, skipping the commit hooks (the full rules are on
``_forbidden_git``; see CLAUDE.md, "Git and version control").

Ported from imaginarium's ``claude-tools hooks bash-guard``. It lives outside the
package (nothing here ships to PyPI) and uses only the standard library, and its
doctests run with the test suite.
"""

import json
import re
import shlex
import sys


# A shell separator: &&, ||, ;, a pipe, a newline, or a lone & that sends a
# command to the background (but not the & of a redirection like 2>&1 or &>).
_SHELL_SEPARATOR = re.compile(r"&&|\|\||;|\||\n|(?<![>&])&(?![&>])")


def _shell_commands(line: str) -> list[str]:
    """The separate commands a shell line runs, so the guard judges every
    command on its own flags. Matching the whole line lets a flag from one
    command excuse another.

    Quotes aren't parsed, so a separator inside quotes splits too. That can
    only make the guard stricter, never let a command through.

    >>> _shell_commands("git status; git diff | head && echo done")
    ['git status', 'git diff', 'head', 'echo done']
    >>> _shell_commands("make 2>&1 || sleep 1 &>/dev/null & wait")
    ['make 2>&1', 'sleep 1 &>/dev/null', 'wait']
    """
    return [command.strip() for command in _SHELL_SEPARATOR.split(line) if command.strip()]


# Subcommands that are never Claude's to run, whatever the flags: they leave
# the machine, destroy uncommitted work, change commits that already exist, or
# wipe the reflog that makes everything else recoverable.
_FORBIDDEN_GIT_SUBCOMMANDS = {
    "push",
    "pull",
    "merge",
    "rebase",
    "cherry-pick",
    "revert",
    "reset",
    "checkout",
    "switch",
    "restore",
    "stash",
    "clean",
    "update-ref",
    "gc",
    "prune",
    "filter-branch",
}

# Global options that take their value as the next token (``git -C path``).
_GIT_GLOBAL_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
}


def _git_invocation(command: str) -> tuple[list[str], str, list[str]] | None:
    """Split one shell command into git's global options, its subcommand and
    the subcommand's arguments, or None if the command doesn't run git.

    >>> _git_invocation("git -C code -c a.b=c commit -m 'two words'")
    (['-C', 'code', '-c', 'a.b=c'], 'commit', ['-m', 'two words'])
    >>> _git_invocation("ls -la")
    """
    try:
        tokens = shlex.split(command)
    except ValueError:  # Unbalanced quotes; judge the words as they are.
        tokens = command.split()
    starts = [i for i, token in enumerate(tokens) if token.split("/")[-1] == "git"]
    if not starts:
        return None
    rest = tokens[starts[0] + 1 :]
    global_options: list[str] = []
    while rest and rest[0].startswith("-"):
        option = rest.pop(0)
        global_options.append(option)
        if option in _GIT_GLOBAL_OPTIONS_WITH_VALUE and rest:
            global_options.append(rest.pop(0))
    if not rest:
        return None
    return global_options, rest[0], rest[1:]


def _has_flag(args: list[str], short: str, long: str, value_flags: str = "") -> bool:
    """Whether ``args`` set a flag: ``-x``, ``x`` inside a cluster like
    ``-ax``, or ``--long`` -- or any prefix of it, since git accepts
    unambiguous abbreviations. Inside a cluster, a letter from
    ``value_flags`` takes the rest of the cluster as its value, so the
    ``n`` in ``-uno`` (``-u`` with mode ``no``) isn't a flag.

    Errs strict: a value that looks like a flag (``-m --amend``) counts.

    >>> _has_flag(["-anm", "x"], "n", "no-verify", value_flags="m")
    True
    >>> _has_flag(["-uno"], "n", "no-verify", value_flags="u")
    False
    >>> _has_flag(["--no-veri"], "n", "no-verify")
    True
    >>> _has_flag(["--no-edit"], "n", "no-verify")
    False
    """
    for arg in args:
        if arg == "--":
            break
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            if long and len(name) > 2 and f"--{long}".startswith(name):
                return True
        elif arg.startswith("-"):
            for letter in arg[1:]:
                if letter in short:
                    return True
                if letter in value_flags:
                    break
    return False


def _forbidden_git(line: str) -> str | None:
    """The git invocation in ``line`` that Claude may not run, if any.

    Claude may stage and commit, because the developer can always drop a
    local commit and get back to where they were. Blocked is whatever takes
    that ability away: leaving the machine, destroying uncommitted work,
    changing commits that already exist (dropping them is the developer's
    call), wiping the reflog, or skipping the commit hooks that gate what
    lands.

    >>> _forbidden_git("git add -A && git commit -am 'fix push' -F msg.txt")
    >>> _forbidden_git("git -C code rm old.py; git mv a.py b.py")
    >>> _forbidden_git("git status && gh pr view --add-label x")
    >>> _forbidden_git("git reflog -n 5; git branch --show-current")
    >>> _forbidden_git("git log --oneline; git stash")
    'stash'
    >>> _forbidden_git("git -C code push")
    'push'
    >>> _forbidden_git("git commit --amend --no-edit")
    'commit --amend'
    >>> _forbidden_git("git commit -nm 'x'")
    'commit --no-verify'
    >>> _forbidden_git("git -c core.hooksPath=/dev/null commit -m x")
    'commit with core.hooksPath'
    >>> _forbidden_git("git config core.hooksPath /dev/null")
    'config core.hooksPath'
    >>> _forbidden_git("git branch -D old")
    'branch --delete'
    >>> _forbidden_git("git reflog expire --all")
    'reflog expire'
    >>> _forbidden_git("git rm -rf code/")
    'rm --force'
    >>> _forbidden_git("git mv -f a.py b.py")
    'mv --force'
    """
    for command in _shell_commands(line):
        if (invocation := _git_invocation(command)) is None:
            continue
        global_options, subcommand, args = invocation
        if subcommand in _FORBIDDEN_GIT_SUBCOMMANDS:
            return subcommand
        if subcommand == "commit":
            if _has_flag(args, "", "amend"):
                return "commit --amend"
            if _has_flag(args, "n", "no-verify", value_flags="mFCctSu"):
                return "commit --no-verify"
            if any("hookspath" in option.lower() for option in global_options):
                return "commit with core.hooksPath"
        if subcommand == "config" and any("hookspath" in a.lower() for a in args):
            return "config core.hooksPath"
        if subcommand == "branch":
            if _has_flag(args, "dD", "delete", value_flags="u"):
                return "branch --delete"
            if _has_flag(args, "fMC", "force", value_flags="u"):
                return "branch --force"
        if subcommand == "reflog" and args[:1] in (["expire"], ["delete"]):
            return f"reflog {args[0]}"
        if subcommand in ("rm", "mv") and _has_flag(args, "f", "force"):
            return f"{subcommand} --force"
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return  # Nothing to inspect; let the command through.

    command = payload.get("tool_input", {}).get("command", "")
    if forbidden_git := _forbidden_git(command):
        sys.stderr.write(
            f"Blocked: 'git {forbidden_git}'. Claude may stage and commit, "
            "but never pushes, destroys uncommitted work, changes commits "
            "that already exist, wipes the reflog, or skips the commit hooks "
            "-- the developer reviews each local commit before pushing, and "
            "dropping or rewriting commits is their call (see CLAUDE.md, "
            "'Git and version control'). If you need one of these, stop and "
            "ask the developer to run it.\n"
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
