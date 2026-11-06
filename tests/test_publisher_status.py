from conftest import grant
from fastapi.testclient import TestClient

from chronicle.collector import create_app


def test_publisher_status_is_authenticated_and_redacted(tmp_path):
    app = create_app(
        tmp_path / "collector.db",
        [grant("read", ["read"], projects=["*"]), grant("limited", ["read"], projects=["p2"])],
    )
    with TestClient(app) as client:
        assert client.get("/v1/publisher/status").status_code == 401
        assert (
            client.get(
                "/v1/publisher/status", headers={"Authorization": "Bearer limited"}
            ).status_code
            == 403
        )
        response = client.get("/v1/publisher/status", headers={"Authorization": "Bearer read"})
        assert response.status_code == 200
        assert response.json() == {"configured": False, "last_publish": None, "last_error": None}
