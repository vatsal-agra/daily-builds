import time

import pytest

from cascade.fakenet import FakeInternet


@pytest.fixture
def fakenet():
    with FakeInternet() as net:
        time.sleep(0.2)
        yield net
