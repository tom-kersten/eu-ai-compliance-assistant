import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


REQUIRED_HEADINGS = [
    "What and why",
    "Quickstart (online)",
    "Quickstart (offline)",
    "Architecture",
    "Design decisions and trade-offs",
    "Eval results",
    "Known limitations",
    "Next steps at production scale",
    "Demo questions",
]


def parse_make_targets(makefile_text: str) -> set[str]:
    pattern = re.compile(r"^([a-zA-Z0-9_-]+):.*##", re.MULTILINE)
    return set(pattern.findall(makefile_text))


def test_readme_and_makefile_targets():
    root = Path("/repo")
    makefile = root / "Makefile"
    assert makefile.exists(), "Makefile not mounted into backend-test at /repo"
    make_text = makefile.read_text(encoding="utf8")
    targets = parse_make_targets(make_text)

    readme = root / "README.md"
    assert readme.exists(), "README.md is required for the assessor-facing docs"
    content = readme.read_text(encoding="utf8")

    # Check required headings exist
    for heading in REQUIRED_HEADINGS:
        assert heading in content, f"Missing required heading in README: {heading}"

    # Find all make invocations in the README and ensure they exist in the Makefile
    mentioned = set(re.findall(r"make\s+([a-zA-Z0-9_-]+)", content))
    missing = mentioned - targets
    assert not missing, f"README references unknown Makefile targets: {sorted(missing)}"
