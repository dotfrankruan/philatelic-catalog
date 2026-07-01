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
        assert "Upload Folder" in response.text
        assert "Selected Folder" in response.text
        assert "Upload Progress" in response.text
        assert "updateUploadSelectionSummary" in response.text
        assert "xhr.upload.onprogress" in response.text


def test_importer_preview_uses_service(monkeypatch, tmp_path) -> None:
    source_root = tmp_path / "Letters"
    source_root.mkdir()

    captured: dict[str, object] = {}

    def fake_describe_import_letter_sources(session, source_paths, archive_root, *, limit=None):
        captured["limit"] = limit
        captured["source_paths"] = list(source_paths)
        captured["archive_root"] = archive_root
        return (
            ImportSummary(scanned=3, imported=2, updated=1, copied_assets=4, tracking_events=7, dry_run=True),
            [
                type(
                    "PreviewRow",
                    (),
                    {
                        "country": "Mainland China",
                        "category": "EMS",
                        "title": "1015382228937 (Guangzhou, Guangdong)",
                        "tracking_number": "1015382228937",
                        "source_relpath": "Mainland China/EMS/1015382228937 (Guangzhou, Guangdong)",
                        "location": "Guangzhou, Guangdong",
                        "asset_count": 4,
                        "tracking_event_count": 15,
                        "action": "update",
                    },
                )()
            ],
        )

    monkeypatch.setattr(ui_module, "describe_import_letter_sources", fake_describe_import_letter_sources)

    with TestClient(app) as client:
        response = client.post(
            "/import",
            content=f"source_paths={source_root.as_posix()}&limit=5&mode=preview",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 200
    assert "Dry run complete." in response.text
    assert "Latest Run" in response.text
    assert "Dry Run Items" in response.text
    assert "1015382228937" in response.text
    assert captured["limit"] == 5


def test_importer_run_starts_background_job(monkeypatch, tmp_path) -> None:
    source_root = tmp_path / "Letters"
    source_root.mkdir()

    monkeypatch.setattr(ui_module, "start_import_job", lambda source_paths, limit: "job-123")

    with TestClient(app) as client:
        response = client.post(
            "/import",
            content=f"source_paths={source_root.as_posix()}&mode=import",
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/import?job_id=job-123"


def test_importer_page_renders_existing_job_state(monkeypatch) -> None:
    monkeypatch.setattr(
        ui_module,
        "snapshot_job",
        lambda job_id: {
            "job_id": job_id,
            "state": "running",
            "completed": 1,
            "total": 3,
            "current_item": "A",
            "summary": {"scanned": 1, "imported": 1, "updated": 0, "copied_assets": 2, "tracking_events": 4, "dry_run": False},
        },
    )

    with TestClient(app) as client:
        response = client.get("/import?job_id=job-123")

    assert response.status_code == 200
    assert "Live Progress" in response.text
    assert "job-123" in response.text


def test_importer_page_completed_job_does_not_poll_again(monkeypatch) -> None:
    monkeypatch.setattr(
        ui_module,
        "snapshot_job",
        lambda job_id: {
            "job_id": job_id,
            "state": "completed",
            "completed": 3,
            "total": 3,
            "current_item": "",
            "summary": {"scanned": 3, "imported": 2, "updated": 1, "copied_assets": 4, "tracking_events": 7, "dry_run": False},
        },
    )

    with TestClient(app) as client:
        response = client.get("/import?job_id=job-123")

    assert response.status_code == 200
    assert "Import complete." in response.text
    assert "Run Status" in response.text
    assert "fetch(`/import/jobs/" not in response.text


def test_importer_job_status_returns_json(monkeypatch) -> None:
    monkeypatch.setattr(
        ui_module,
        "snapshot_job",
        lambda job_id: {"job_id": job_id, "state": "completed", "completed": 3, "total": 3},
    )

    with TestClient(app) as client:
        response = client.get("/import/jobs/job-123")

    assert response.status_code == 200
    assert response.json()["state"] == "completed"


def test_importer_upload_preview_uses_uploaded_tree(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_describe_import_letter_sources(session, source_paths, archive_root, *, limit=None):
        captured["source_paths"] = list(source_paths)
        captured["limit"] = limit
        return (
            ImportSummary(scanned=1, imported=1, updated=0, copied_assets=2, tracking_events=3, dry_run=True),
            [
                type(
                    "PreviewRow",
                    (),
                    {
                        "country": "Hong Kong",
                        "category": "Postcards",
                        "title": "AUG192024",
                        "tracking_number": "AUG192024",
                        "source_relpath": "Hong Kong/Postcards/AUG192024",
                        "location": None,
                        "asset_count": 2,
                        "tracking_event_count": 3,
                        "action": "import",
                    },
                )()
            ],
        )

    monkeypatch.setattr(ui_module, "describe_import_letter_sources", fake_describe_import_letter_sources)

    with TestClient(app) as client:
        response = client.post(
            "/import/upload",
            files=[
                ("files", ("Hong Kong/Postcards/AUG192024/front.png", b"front", "image/png")),
                ("files", ("Hong Kong/Postcards/AUG192024/back.png", b"back", "image/png")),
                ("mode", (None, "preview")),
                ("limit", (None, "4")),
            ],
        )

    assert response.status_code == 200
    assert "Dry run complete." in response.text
    assert "AUG192024" in response.text
    assert captured["limit"] == 4


def test_importer_upload_import_redirects_to_job(monkeypatch) -> None:
    monkeypatch.setattr(ui_module, "start_import_job", lambda source_paths, limit: "upload-job-123")

    with TestClient(app) as client:
        response = client.post(
            "/import/upload",
            files=[
                ("files", ("Hong Kong/Postcards/AUG192024/front.png", b"front", "image/png")),
                ("mode", (None, "import")),
                ("limit", (None, "")),
            ],
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/import?job_id=upload-job-123"


def test_display_title_removes_embedded_bracket_tags() -> None:
    assert ui_module.display_title("[govt] CC554844919NZ [fragile]") == "CC554844919NZ"


def test_display_location_uses_parenthetical_suffix_or_na() -> None:
    assert ui_module.display_location("1217507254208 (Changzhou, Jiangsu)", None) == "Changzhou, Jiangsu"
    assert ui_module.display_location("1217507254208", None) == "N/A"
    assert ui_module.display_location("1217507254208 (Changzhou, Jiangsu)", "Manual Update") == "Manual Update"


def test_parse_location_parts_splits_common_comma_format() -> None:
    parts = ui_module.parse_location_parts("1217507254208 (Changzhou, Jiangsu, China)", None)

    assert parts["location"] == "Changzhou, Jiangsu, China"
    assert parts["city"] == "Changzhou"
    assert parts["region"] == "Jiangsu"
    assert parts["country"] == "China"


def test_parse_location_parts_returns_na_when_missing() -> None:
    parts = ui_module.parse_location_parts("1217507254208", None)

    assert parts["city"] == "N/A"
    assert parts["region"] == "N/A"
    assert parts["country"] == "N/A"


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


def test_detail_page_shows_location_breakdown() -> None:
    with TestClient(app) as client:
        response = client.get("/?country=Australia&category=Registered+Mail")

        assert response.status_code == 200
        assert "City" in response.text
        assert "Region" in response.text
