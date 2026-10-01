"""Domain exceptions for the backend."""


class ChecksumMismatch(Exception):
    """An already-applied migration file has changed on disk."""

    def __init__(self, version: str, expected: str, actual: str) -> None:
        self.version = version
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"migration {version} checksum mismatch: "
            f"recorded={expected}, on_disk={actual}"
        )


class MissingCorpusFile(Exception):
    """A corpus file listed in the manifest is not on disk."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"corpus file not found: {path}")


class UnknownAmendment(Exception):
    """An amended_by key is not present in the corpus manifest."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"unknown amendment document key: {key}")


class ChunkTooLarge(Exception):
    """A single sentence exceeds the split token limit and cannot be chunked."""

    def __init__(self, token_estimate: int, token_limit: int) -> None:
        self.token_estimate = token_estimate
        self.token_limit = token_limit
        super().__init__(
            f"sentence token estimate {token_estimate} exceeds limit {token_limit}"
        )


class SelectionInvalid(Exception):
    """Raised when a selection result is invalid for the retrieved set."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("selection invalid: " + "; ".join(problems))


class AnswerInvalid(Exception):
    """Raised when an answer result violates pipeline rules."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("answer invalid: " + "; ".join(problems))
