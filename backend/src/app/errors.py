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
