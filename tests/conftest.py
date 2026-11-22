from __future__ import annotations

import pytest
import responses

from mxbess.client import MaximoClient
from mxbess.repository import ApiRepository
from tests.support import AS_OF, MOCK_BASE, FakeMaximo, tiny_dataset


@pytest.fixture
def tiny():
    return tiny_dataset()


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mocked:
        yield mocked


@pytest.fixture
def fake_maximo(rsps):
    fake = FakeMaximo()
    fake.install(rsps)
    return fake


@pytest.fixture
def make_api_repo(fake_maximo):
    def factory(*, max_retries: int = 0) -> ApiRepository:
        client = MaximoClient(
            MOCK_BASE,
            "test-api-key",
            max_retries=max_retries,
            page_size=100,
            sleep=lambda _seconds: None,
        )
        return ApiRepository(client, site_id="BISHA-BESS", org_id="BISHA", as_of=AS_OF)

    return factory
