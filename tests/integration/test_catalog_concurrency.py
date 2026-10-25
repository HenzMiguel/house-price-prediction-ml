import threading
from contextlib import contextmanager

import pytest

from house_price.catalog import CatalogLockUnavailable


class SingleOwnerLock:
    def __init__(self) -> None:
        self.lock = threading.Lock()

    @contextmanager
    def mutation_lock(self):
        if not self.lock.acquire(blocking=False):
            raise CatalogLockUnavailable("catalog mutation active")
        try:
            yield object()
        finally:
            self.lock.release()


def test_concurrent_catalog_mutation_has_one_owner_and_exit_code_8() -> None:
    repository = SingleOwnerLock()
    entered = threading.Event()
    release = threading.Event()

    def owner():
        with repository.mutation_lock():
            entered.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=owner)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(CatalogLockUnavailable) as failure:
        with repository.mutation_lock():
            pass
    assert failure.value.exit_code == 8
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()

