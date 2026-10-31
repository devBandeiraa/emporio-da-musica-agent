from pathlib import Path

import pytest

from emporio_agent.store import Store, load_store

DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="session")
def store() -> Store:
    return load_store(DATA_DIR)
