from fastapi.testclient import TestClient

from app.main import app
import app.ui as ui_module
from app.services.importers import ImportSummary


def test_home_page_renders() -> None:
    with TestClient(app) as client:
        response = client.get("/")

        assert response.status_code == 200
        assert "Archive Browser" in response.text
        assert "Philatelic Catalog" in response.text
        assert "Apply Filters" in response.text


def test_admin_page_renders() -> None:
    with TestClient(app) as client:
        response = client.get("/admin/items/3")

        assert response.status_code == 200
        assert "Admin Console" in response.text
        assert "Save Metadata" in response.text


def test_importer_page_renders() -> None:
    with TestClient(app) as client:
        response = client.get("/import")

        assert response.status_code == 200
        assert "Batch Importer" in response.text
        assert "Preview Import" in response.text


def test_importer_preview_uses_service(monkeypatch, tmp_path) -> None:
    source_root = tmp_path / "Letters"
    source_root.mkdir()

    captured: dict[str, object] = {}

    def fake_import_letter_sources(session, source_paths, archive_root, *, dry_run=False, limit=None):
        captured["dry_run"] = dry_run
        captured["limit"] = limit
        captured["source_paths"] = list(source_paths)
        captured["archive_root"] = archive_root
        return ImportSummary(scanned=3, imported=0, updated=0, copied_assets=0, tracking_events=7, dry_run=True)

    monkeypatch.setattr(ui_module, "import_letter_sources", fake_import_letter_sources)

    with TestClient(app) as client:
        response = client.post(
            "/import",
            content=f"source_paths={source_root.as_posix()}&limit=5&mode=preview",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 200
    assert "Dry run complete." in response.text
    assert "Latest Run" in response.text
    assert captured["dry_run"] is True
    assert captured["limit"] == 5


def test_display_title_removes_embedded_bracket_tags() -> None:
    assert ui_module.display_title("[govt] CC554844919NZ [fragile]") == "CC554844919NZ"


def test_display_location_uses_parenthetical_suffix_or_na() -> None:
    assert ui_module.display_location("1217507254208 (Changzhou, Jiangsu)", None) == "Changzhou, Jiangsu"
    assert ui_module.display_location("1217507254208", None) == "N/A"
    assert ui_module.display_location("1217507254208 (Changzhou, Jiangsu)", "Manual Update") == "Manual Update"


def test_home_page_uses_hierarchical_browser() -> None:
    with TestClient(app) as client:
        response = client.get("/?country=Australia")

        assert response.status_code == 200
        assert "Choose a mail type" in response.text
        assert "Mail Types" in response.text


def test_admin_page_shows_location_field() -> None:
    with TestClient(app) as client:
        response = client.get("/admin/items/3")

        assert response.status_code == 200
        assert "Location" in response.text
