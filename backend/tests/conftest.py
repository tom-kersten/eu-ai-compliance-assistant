import pytest

SUITE_MARKERS = ("unit", "api", "db", "live")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Fail collection when a test has no suite marker.

    `make test` (and CI) select tests with `-m "unit or api or db"`, so an
    unmarked test would be silently deselected and never run. tryfirst makes
    this run before the built-in -m deselection removes it from `items`.
    """
    unmarked = [
        item.nodeid
        for item in items
        if not any(item.get_closest_marker(name) for name in SUITE_MARKERS)
    ]
    if unmarked:
        raise pytest.UsageError(
            "Tests without a suite marker ("
            + ", ".join(SUITE_MARKERS)
            + "):\n  "
            + "\n  ".join(unmarked)
        )
