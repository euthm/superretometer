"""pytest fixtures for adversarial benchmark."""
import sys, os, pytest
import logging
# Add transports/ to path for memory_adapter and runtime_server imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "transports"))
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

log = logging.getLogger(__name__)


class BenchmarkRecorder:
    """Lightweight test recorder: asserts pass==actual, collects results."""
    def __init__(self):
        self.results = []

    def record(self, name, expected, actual, msg=""):
        assert expected == actual, f"[{name}] Expected {expected}, got {actual}. {msg}"
        self.results.append({"name": name, "expected": expected, "actual": actual, "msg": msg})


@pytest.fixture
def storage():
    return InMemoryStorage()


@pytest.fixture
def bench(storage):
    return BenchmarkRecorder()
