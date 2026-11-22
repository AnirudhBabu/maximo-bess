from __future__ import annotations

import json
import logging
import re

import pytest
import requests
import responses

from mxbess.client import (
    AuthenticationError,
    MaximoClient,
    MaximoConnectionError,
    MaximoHTTPError,
    NotFoundError,
    ValidationError,
)

BASE = "https://mock.maximo.com/maximo"
ASSETS_URL = f"{BASE}/api/os/mxapiasset"


def make_client(**overrides) -> MaximoClient:
    options = {
        "timeout": 5,
        "max_retries": 0,
        "backoff_seconds": 0.5,
        "page_size": 100,
        "sleep": lambda _seconds: None,
    }
    options.update(overrides)
    return MaximoClient(BASE, "secret-api-key", **options)


def test_sends_apikey_header_and_default_paging(rsps):
    rsps.add(responses.GET, ASSETS_URL, json={"member": [{"ASSETNUM": "A1"}]})
    client = make_client()
    assert client.get_all("asset") == [{"ASSETNUM": "A1"}]
    request = rsps.calls[0].request
    assert request.headers["apikey"] == "secret-api-key"
    assert request.headers["Accept"] == "application/json"
    assert "oslc.pageSize=100" in request.url


def test_query_parameters_are_sent(rsps):
    rsps.add(responses.GET, ASSETS_URL, json={"member": []})
    make_client().get_all("asset", where='ASSETNUM="A1"', select="ASSETNUM", page_size=5)
    url = rsps.calls[0].request.url
    assert "oslc.where=ASSETNUM" in url
    assert "oslc.select=ASSETNUM" in url
    assert "oslc.pageSize=5" in url


def test_paging_follows_response_info_next_page(rsps):
    next_href = f"{ASSETS_URL}?oslc.page=2"
    rsps.add(
        responses.GET,
        re.compile(re.escape(ASSETS_URL) + r"\?.*"),
        json={
            "member": [{"ASSETNUM": "A1"}],
            "responseInfo": {"nextPage": {"href": next_href}},
        },
    )
    rsps.add(responses.GET, next_href, json={"member": [{"ASSETNUM": "A2"}]})
    assert make_client().get_all("asset") == [{"ASSETNUM": "A1"}, {"ASSETNUM": "A2"}]
    assert len(rsps.calls) == 2


def test_paging_falls_back_to_link_header(rsps):
    next_href = f"{ASSETS_URL}?oslc.page=2"
    rsps.add(
        responses.GET,
        re.compile(re.escape(ASSETS_URL) + r"\?.*"),
        json={"member": [{"ASSETNUM": "A1"}]},
        headers={"Link": f'<{next_href}>; rel="next"'},
    )
    rsps.add(responses.GET, next_href, json={"member": [{"ASSETNUM": "A2"}]})
    assert len(make_client().get_all("asset")) == 2


def test_plain_list_response_is_accepted(rsps):
    rsps.add(responses.GET, ASSETS_URL, json=[{"ASSETNUM": "A1"}])
    assert make_client().get_all("asset") == [{"ASSETNUM": "A1"}]


def test_retries_503_with_exponential_backoff(rsps):
    delays: list[float] = []
    rsps.add(responses.GET, ASSETS_URL, status=503)
    rsps.add(responses.GET, ASSETS_URL, json={"member": []})
    client = make_client(max_retries=1, backoff_seconds=0.25, sleep=delays.append)
    assert client.get_all("asset") == []
    assert delays == [0.25]
    assert len(rsps.calls) == 2


def test_retries_respect_retry_after(rsps):
    delays: list[float] = []
    rsps.add(responses.GET, ASSETS_URL, status=429, headers={"Retry-After": "2"})
    rsps.add(responses.GET, ASSETS_URL, json={"member": []})
    client = make_client(max_retries=1, sleep=delays.append)
    client.get_all("asset")
    assert delays == [2.0]


def test_retry_exhaustion_raises_http_error(rsps):
    rsps.add(responses.GET, ASSETS_URL, status=503)
    rsps.add(responses.GET, ASSETS_URL, status=503)
    client = make_client(max_retries=1)
    with pytest.raises(MaximoHTTPError) as excinfo:
        client.get_all("asset")
    assert excinfo.value.status == 503
    assert len(rsps.calls) == 2


def test_401_maps_to_authentication_error(rsps):
    rsps.add(responses.GET, ASSETS_URL, status=401, json={"Error": "bad key"})
    with pytest.raises(AuthenticationError) as excinfo:
        make_client().get_all("asset")
    assert excinfo.value.status == 401


def test_404_maps_to_not_found(rsps):
    rsps.add(responses.GET, f"{ASSETS_URL}/A1", status=404, json={"Error": "no asset"})
    with pytest.raises(NotFoundError):
        make_client().get_one("asset", "A1")


def test_400_maps_to_validation_error_with_detail(rsps):
    rsps.add(responses.POST, ASSETS_URL, status=400, json={"Error": "ASSETNUM required"})
    with pytest.raises(ValidationError) as excinfo:
        make_client().create("asset", {"DESCRIPTION": "x"})
    assert "ASSETNUM required" in str(excinfo.value)


def test_connection_error_after_retries(rsps):
    rsps.add(responses.GET, ASSETS_URL, body=requests.ConnectionError("down"))
    rsps.add(responses.GET, ASSETS_URL, body=requests.ConnectionError("down"))
    client = make_client(max_retries=1)
    with pytest.raises(MaximoConnectionError):
        client.get_all("asset")
    assert len(rsps.calls) == 2


def test_get_one_quotes_the_key(rsps):
    rsps.add(
        responses.GET,
        re.compile(re.escape(ASSETS_URL) + r"/A%2FB%20C$"),
        json={"ASSETNUM": "A/B C"},
    )
    assert make_client().get_one("asset", "A/B C") == {"ASSETNUM": "A/B C"}


def test_create_and_update(rsps):
    rsps.add(responses.POST, ASSETS_URL, status=201, json={"ASSETNUM": "A1"})
    rsps.add(responses.PATCH, f"{ASSETS_URL}/A1", json={"ASSETNUM": "A1"})
    client = make_client()
    assert client.create("asset", {"ASSETNUM": "A1"}) == {"ASSETNUM": "A1"}
    assert client.update("asset", "A1", {"DESCRIPTION": "new"}) == {"ASSETNUM": "A1"}
    assert json.loads(rsps.calls[0].request.body) == {"ASSETNUM": "A1"}
    assert json.loads(rsps.calls[1].request.body) == {"DESCRIPTION": "new"}
    assert rsps.calls[1].request.method == "PATCH"


def test_find_one_by_key(rsps):
    rsps.add(responses.GET, ASSETS_URL, json={"member": [{"ASSETNUM": "A1"}]})
    assert make_client().find_one_by_key("asset", 'ASSETNUM="A1"') == {"ASSETNUM": "A1"}
    rsps.add(responses.GET, ASSETS_URL, json={"member": []})
    assert make_client().find_one_by_key("asset", 'ASSETNUM="A2"') is None


def test_no_secret_in_logs_or_repr(rsps, caplog):
    caplog.set_level(logging.DEBUG, logger="mxbess.client")
    rsps.add(responses.GET, ASSETS_URL, json={"member": []})
    client = make_client()
    client.get_all("asset")
    assert "secret-api-key" not in caplog.text
    assert "secret-api-key" not in repr(client)


def test_object_url_allows_raw_object_structure_name():
    client = make_client()
    assert client.object_url("mxapipm") == f"{BASE}/api/os/mxapipm"


def test_context_manager_closes_session():
    client = make_client()
    with client as entered:
        assert entered is client
    assert client._session is not None


def test_empty_api_key_is_rejected():
    with pytest.raises(ValueError):
        MaximoClient(BASE, "")
