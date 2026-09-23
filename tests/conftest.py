import pytest


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """No test reads or writes the developer's real cache under data/cache.

    Without this, a session recovered on this machine leaks into assertions
    about an empty cache and the suite passes or fails by who ran it last.
    """
    monkeypatch.setenv("SURF_CACHE_DIR", str(tmp_path / "cache"))
