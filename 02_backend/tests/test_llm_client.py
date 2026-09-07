import threading

import pytest


@pytest.fixture(autouse=True)
def _reset_llm_client_globals():
    """_token_param/_drop_temperature are module globals shared by all workers
    (deliberately — see llm_client._completion). Reset around every test."""
    from agents import llm_client

    llm_client._token_param = "max_tokens"
    llm_client._drop_temperature = False
    yield
    llm_client._token_param = "max_tokens"
    llm_client._drop_temperature = False


class _FakeResponse:
    def __init__(self, content="OK"):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


class _FakeClient:
    """Records every create() call; rejects max_tokens until the shim flips it."""

    def __init__(self, reject_max_tokens=True, reject_temperature=False):
        self.calls = []
        self.reject_max_tokens = reject_max_tokens
        self.reject_temperature = reject_temperature
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **params):
        self.calls.append(params)
        if self.reject_max_tokens and "max_tokens" in params:
            raise Exception("Unsupported parameter: 'max_tokens' is not supported with this model. "
                             "Use 'max_completion_tokens' instead.")
        if self.reject_temperature and "temperature" in params:
            raise Exception("temperature: only the default (1) value is supported with this model.")
        return _FakeResponse()


def test_completion_flips_max_tokens_to_max_completion_tokens():
    from agents import llm_client

    client = _FakeClient(reject_max_tokens=True)
    resp = llm_client._completion(client, "gpt-5.1", [{"role": "user", "content": "hi"}], stream=False)

    assert resp.choices[0].message.content == "OK"
    assert llm_client._token_param == "max_completion_tokens"
    # first call used max_tokens (rejected), second call used max_completion_tokens
    assert "max_tokens" in client.calls[0]
    assert "max_completion_tokens" in client.calls[1]


def test_completion_drops_temperature_when_unsupported():
    from agents import llm_client

    client = _FakeClient(reject_max_tokens=False, reject_temperature=True)
    llm_client._completion(client, "o1", [{"role": "user", "content": "hi"}], stream=False)

    assert llm_client._drop_temperature is True
    assert "temperature" not in client.calls[-1]


def test_completion_shim_is_deterministic_under_concurrent_threads():
    """4 workers call _completion in parallel; the global token-param flip must
    not flap back and forth (each thread's client independently rejects
    max_tokens until the shared global is flipped once)."""
    from agents import llm_client

    errors = []

    def worker():
        try:
            client = _FakeClient(reject_max_tokens=True)
            llm_client._completion(client, "gpt-5.1", [{"role": "user", "content": "hi"}], stream=False)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert llm_client._token_param == "max_completion_tokens"
