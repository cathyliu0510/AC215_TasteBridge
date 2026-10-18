import logging

from fastapi.testclient import TestClient


def test_every_request_logs_method_path_status_and_duration(client: TestClient, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="tastebridge.requests"):
        client.get("/books/w_9999")

    [message] = [r.getMessage() for r in caplog.records if r.name == "tastebridge.requests"]
    method, path, status, duration = message.split()
    assert (method, path, status) == ("GET", "/books/w_9999", "404")
    assert duration.endswith("ms")


def test_startup_log_names_model_and_data_version(client_factory, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="tastebridge"):
        with client_factory():
            pass

    startup = [r.getMessage() for r in caplog.records if r.name == "tastebridge"]
    assert any(
        "sample-shelf-toy-v1" in m and "data hand-curated-sample-52" in m for m in startup
    )
