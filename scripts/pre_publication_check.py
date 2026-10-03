from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_BYTES = 2_000_000
GIT = shutil.which("git")
if GIT is None:
    raise RuntimeError("git executable not found")
LOCAL_HOME_PATTERN = re.compile(
    r"(?:/" + r"Users/[^/\s]+|/" + r"home/[^/\s]+|[A-Za-z]:[/\\]" + r"Users[/\\][^/\\\s]+)"
)


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]


RULES = (
    Rule("private-key", re.compile(r"BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY")),
    Rule("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    Rule("github-token", re.compile(r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    Rule("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    Rule("openai-style-token", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    Rule("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    Rule("google-oauth-secret", re.compile(r"GOCSPX-[0-9A-Za-z_-]{16,}")),
    Rule("authorization-header", re.compile(r"Authorization:\s*(?:Bearer|Basic)\s+\S+", re.IGNORECASE)),
    Rule(
        "credentialed-connection-string",
        re.compile(r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s/:]+:[^\s/@]+@", re.IGNORECASE),
    ),
    Rule(
        "private-ipv4",
        re.compile(
            r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|192\.168\.\d{1,3}\.\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
        ),
    ),
    Rule(
        "local-home-path",
        LOCAL_HOME_PATTERN,
    ),
)


def candidate_files() -> list[Path]:
    result = subprocess.run(  # noqa: S603 - fixed local executable and constant arguments
        [GIT, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def load_denylist() -> tuple[str, ...]:
    configured = os.getenv("PUBLICATION_DENYLIST_FILE")
    if not configured:
        return ()
    path = Path(configured).expanduser().resolve()
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            terms.append(value.casefold())
    return tuple(terms)


def scan_text(path: Path, text: str, denylist: tuple[str, ...], *, prefix: str = "") -> list[str]:
    problems: list[str] = []
    relative = path.relative_to(ROOT).as_posix()
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            if rule.pattern.search(line):
                problems.append(f"{prefix}{relative}:{line_number}: matched {rule.name}")
        lowered = line.casefold()
        for index, term in enumerate(denylist, start=1):
            if term in lowered:
                problems.append(f"{prefix}{relative}:{line_number}: matched private denylist term #{index}")
    return problems


def scan_worktree(denylist: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    for path in candidate_files():
        # Large, source-reviewed CycloneDX inventories are bounded JSON; still scan every line.
        limit = 12_000_000 if path.parent == ROOT / "docs/verification/sbom" else MAX_TEXT_BYTES
        if path.stat().st_size > limit:
            problems.append(f"{path.relative_to(ROOT)}: file exceeds {limit} bytes")
            continue
        data = path.read_bytes()
        if b"\0" in data:
            problems.append(f"{path.relative_to(ROOT)}: binary file requires manual review")
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path.relative_to(ROOT)}: non-UTF-8 file requires manual review")
            continue
        problems.extend(scan_text(path, text, denylist))
    return problems


def scan_history(denylist: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    revisions = subprocess.run(  # noqa: S603 - fixed local executable and constant arguments
        [GIT, "rev-list", "--all"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    for revision in revisions:
        if re.fullmatch(r"[0-9a-f]{40,64}", revision) is None:
            problems.append("history: git returned an invalid revision identifier")
            continue
        paths = subprocess.run(  # noqa: S603 - revision is validated hexadecimal Git output
            [GIT, "ls-tree", "-r", "--name-only", "-z", revision],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        for encoded_path in paths:
            if not encoded_path:
                continue
            relative = encoded_path.decode()
            data = subprocess.run(  # noqa: S603 - no shell; revision validated and path comes from Git
                [GIT, "show", f"{revision}:{relative}"], cwd=ROOT, check=True, capture_output=True
            ).stdout
            if len(data) > MAX_TEXT_BYTES:
                problems.append(f"history:{revision[:12]}:{relative}: file exceeds {MAX_TEXT_BYTES} bytes")
                continue
            if b"\0" in data:
                problems.append(f"history:{revision[:12]}:{relative}: binary file requires manual review")
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                problems.append(f"history:{revision[:12]}:{relative}: non-UTF-8 file requires manual review")
                continue
            problems.extend(scan_text(ROOT / relative, text, denylist, prefix=f"history:{revision[:12]}:"))
    return problems


def main() -> None:
    denylist = load_denylist()
    problems = scan_worktree(denylist) + scan_history(denylist)
    if problems:
        print("Publication check failed:")
        for problem in sorted(set(problems)):
            print(f"- {problem}")
        raise SystemExit(1)
    print(f"Publication check passed: {len(candidate_files())} files and reachable Git history reviewed.")


if __name__ == "__main__":
    main()
