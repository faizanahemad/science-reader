"""
Regression test for the shared-connection concurrency bug.

A single ``sqlite3.Connection`` is shared process-wide (``check_same_thread=
False``). sqlite3 raises ``SQLITE_MISUSE`` ("bad parameter or other API misuse")
when one connection is used concurrently from multiple threads — which happened
when the embedding store's parallel ``compute_and_store`` wrote embeddings, and
when concurrent hybrid-search strategies read the connection at the same time.
``PKBDatabase`` now serializes connection access with a reentrant lock; these
tests exercise concurrent writes + reads and assert no error escapes.
"""

import threading

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase


@pytest.fixture
def db(tmp_path):
    d = PKBDatabase(PKBConfig(db_path=str(tmp_path / "concurrency.sqlite")))
    d.connect()
    d.initialize_schema()
    d.execute("CREATE TABLE IF NOT EXISTS scratch (id INTEGER PRIMARY KEY, v TEXT)")
    d.connect().commit()
    yield d
    d.close()


def _run_concurrently(workers, fn):
    """Run fn(i) in `workers` threads; return the list of exceptions raised."""
    errors = []
    barrier = threading.Barrier(workers)

    def wrapped(i):
        barrier.wait()  # maximize overlap / contention
        try:
            fn(i)
        except Exception as e:  # noqa: BLE001 - we assert on this
            errors.append(e)

    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_concurrent_transactions_do_not_misuse(db):
    """Many threads writing via transaction() concurrently must not raise."""
    def write_many(i):
        for j in range(40):
            with db.transaction() as conn:
                conn.execute(
                    "INSERT INTO scratch (v) VALUES (?)", (f"t{i}-{j}",)
                )

    errors = _run_concurrently(16, write_many)
    assert not errors, f"concurrent writes raised: {errors[:3]}"
    assert db.fetchone("SELECT COUNT(*) AS c FROM scratch")["c"] == 16 * 40


def test_concurrent_reads_and_writes_do_not_misuse(db):
    """Interleaved fetchone/fetchall + writes across threads must not raise."""
    def mixed(i):
        for j in range(40):
            with db.transaction() as conn:
                conn.execute("INSERT INTO scratch (v) VALUES (?)", (f"m{i}-{j}",))
            db.fetchone("SELECT COUNT(*) AS c FROM scratch")
            db.fetchall("SELECT id FROM scratch LIMIT 5")

    errors = _run_concurrently(16, mixed)
    assert not errors, f"concurrent read/write raised: {errors[:3]}"
