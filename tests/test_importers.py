from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.models import Item
from app.services.importers import build_parsed_item, import_letters_archive, parse_manifest_text


def test_parse_manifest_text_extracts_status_and_events() -> None:
    manifest = """Number: CC554844919NZ
Package status: Delivered (15 Days)
Country: New Zealand -> China
August 19, 2024 17:07, 常州市, 您的邮件已妥收【本人签收，本人】
August 5, 2024 13:46, Picked up/Collected, Your item has been collected
======================================
Powered by www.17track.net
"""

    tracking_number, status, route, events = parse_manifest_text(manifest)

    assert tracking_number == "CC554844919NZ"
    assert status == "Delivered (15 Days)"
    assert route == "New Zealand -> China"
    assert len(events) == 2
    assert events[0].location == "常州市"
    assert events[1].status == "Picked up/Collected"


def test_build_parsed_item_infers_tracking_and_flags(tmp_path: Path) -> None:
    source_root = tmp_path / "Letters"
    item_dir = source_root / "Mainland China" / "Postcards" / "[RETURN] 7000440251050 (Nanjing, Jiangsu)"
    item_dir.mkdir(parents=True)
    (item_dir / "front.png").write_bytes(b"front")
    (item_dir / "back.png").write_bytes(b"back")
    (item_dir / "manifest.txt").write_text(
        "Number: 7000440251050\nPackage status: Delivered\nCountry: China -> China\n",
        encoding="utf-8",
    )

    parsed = build_parsed_item(item_dir, source_root, tmp_path / "managed_archive")

    assert parsed.country == "Mainland China"
    assert parsed.category == "Postcards"
    assert parsed.tracking_number == "7000440251050"
    assert parsed.origin == "Nanjing, Jiangsu"
    assert parsed.is_returned is True
    assert "return" in parsed.tags


def test_import_letters_archive_copies_and_persists(tmp_path: Path) -> None:
    source_root = tmp_path / "Letters"
    archive_root = tmp_path / "managed_archive"
    item_dir = source_root / "New Zealand" / "Parcels" / "CC554844919NZ"
    item_dir.mkdir(parents=True)
    (item_dir / "front.png").write_bytes(b"front")
    (item_dir / "back.png").write_bytes(b"back")
    (item_dir / "manifest.txt").write_text(
        "\n".join(
            [
                "Number: CC554844919NZ",
                "Package status: Delivered (15 Days)",
                "Country: New Zealand -> China",
                "August 19, 2024 17:07, Delivered, Your item has been delivered",
                "August 5, 2024 13:46, Picked up/Collected, Your item has been collected",
            ]
        ),
        encoding="utf-8",
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        summary = import_letters_archive(session, source_root, archive_root)

        assert summary.scanned == 1
        assert summary.imported == 1
        assert summary.copied_assets == 3
        item = session.scalar(select(Item))
        assert item is not None
        assert item.source_path == str(item_dir)
        assert item.archive_path == str(archive_root / "New Zealand" / "Parcels" / "CC554844919NZ")
        assert (archive_root / "New Zealand" / "Parcels" / "CC554844919NZ" / "front.png").exists()
        assert len(item.assets) == 3
        assert len(item.tracking_events) == 2
