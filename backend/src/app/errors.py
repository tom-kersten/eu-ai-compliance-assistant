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
