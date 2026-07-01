from fastapi.testclient import TestClient

from app.main import app


def test_home_page_renders() -> None:
    with TestClient(app) as client:
        response = client.get("/")

        assert response.status_code == 200
        assert "Archive Browser" in response.text
        assert "Philatelic Catalog" in response.text
        assert "Apply Filters" in response.text
