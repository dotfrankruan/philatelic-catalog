from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.models import Item, TrackingEvent
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


def test_parse_manifest_text_supports_numeric_dates() -> None:
    manifest = """Number: RD654726415CN
Package status: Delivered (60 Days)
Country: China -> Unknown
2025-04-11 09:31 上海市, 您的邮件已代收【信报箱，xinxiang】
2025-04-11 08:19 上海市, 邮件正在派送中
"""

    tracking_number, status, route, events = parse_manifest_text(manifest)

    assert tracking_number == "RD654726415CN"
    assert status == "Delivered (60 Days)"
    assert route == "China -> Unknown"
    assert len(events) == 2
    assert events[0].location == "上海市"


def test_parse_manifest_text_handles_lines_without_commas() -> None:
    manifest = """Number: RD654726415CN
2025-04-11 09:31 上海市 邮件正在派送中
2025-04-11 08:19 Processing at international depot
"""

    _, _, _, events = parse_manifest_text(manifest)

    assert len(events) == 2
    assert events[0].location == "上海市"
    assert events[0].status == "邮件正在派送中"
    assert events[1].location is None
    assert events[1].status == "Processing at international depot"


def test_parse_manifest_text_keeps_city_and_8_digit_office_code_in_location() -> None:
    manifest = """Number: 1015382228937
2025-09-26 14:12 上海市 20006208 快件到达【上海市普陀区云岭揽投部】
2025-09-23 12:11 广州市 51018010 中国邮政 已收取快件
"""

    _, _, _, events = parse_manifest_text(manifest)

    assert len(events) == 2
    assert events[0].location == "上海市 20006208"
    assert events[0].status == "快件到达【上海市普陀区云岭揽投部】"
    assert events[1].location == "广州市 51018010"
    assert events[1].status == "中国邮政 已收取快件"


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

    parsed = build_parsed_item(item_dir)

    assert parsed.country == "Mainland China"
    assert parsed.category == "Postcards"
    assert parsed.tracking_number == "7000440251050"
    assert parsed.source_relpath == "Mainland China/Postcards/[RETURN] 7000440251050 (Nanjing, Jiangsu)"
    assert len(parsed.archive_id) == 36
    assert parsed.origin == "Nanjing, Jiangsu"
    assert parsed.status is None
    assert parsed.is_returned is True
    assert "returned" in parsed.tags


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
        assert summary.copied_assets == 2
        item = session.scalar(select(Item))
        assert item is not None
        assert item.source_relpath == "New Zealand/Parcels/CC554844919NZ"
        assert len(item.archive_id) == 36
        assert all(asset.path[0] in "0123456789ABCDEF" for asset in item.assets)
        assert all(len(Path(asset.path).parts) == 2 for asset in item.assets)
        assert all(Path(asset.path).is_absolute() is False for asset in item.assets)
        assert all((archive_root / asset.path).exists() for asset in item.assets)
        assert len(item.assets) == 2
        assert len(item.tracking_events) == 2


def test_import_letters_archive_accepts_single_item_directory(tmp_path: Path) -> None:
    archive_root = tmp_path / "managed_archive"
    item_dir = tmp_path / "Letters" / "Belarus" / "Postcards" / "BY-3165002"
    item_dir.mkdir(parents=True)
    (item_dir / "scan.heif").write_bytes(b"heif")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        summary = import_letters_archive(session, item_dir, archive_root)

        assert summary.scanned == 1
        assert summary.imported == 1
        item = session.scalar(select(Item))
        assert item is not None
        assert item.country == "Belarus"
        assert item.category == "Postcards"
        assert item.source_relpath == "Belarus/Postcards/BY-3165002"


def test_import_letters_archive_merges_existing_item_by_tracking_number(tmp_path: Path) -> None:
    archive_root = tmp_path / "managed_archive"
    original_dir = tmp_path / "Letters" / "Hong Kong" / "Postcards" / "AUG192024"
    renamed_dir = tmp_path / "Letters" / "Hong Kong" / "Postcards" / "AUG192024 - Andy W"
    original_dir.mkdir(parents=True)
    renamed_dir.mkdir(parents=True)

    (original_dir / "front.png").write_bytes(b"front-one")
    (renamed_dir / "front.png").write_bytes(b"front-two")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first_summary = import_letters_archive(session, original_dir, archive_root)
        second_summary = import_letters_archive(session, renamed_dir, archive_root)

        assert first_summary.imported == 1
        assert second_summary.updated == 1

        items = list(session.scalars(select(Item)).all())
        assert len(items) == 1
        assert items[0].tracking_number == "AUG192024"
        assert items[0].source_relpath == "Hong Kong/Postcards/AUG192024 - Andy W"


def test_import_replaces_non_manual_tracking_events_but_keeps_manual_ones(tmp_path: Path) -> None:
    source_root = tmp_path / "Letters"
    archive_root = tmp_path / "managed_archive"
    item_dir = source_root / "Mainland China" / "EMS" / "1015382228937"
    item_dir.mkdir(parents=True)
    (item_dir / "front.png").write_bytes(b"front")
    (item_dir / "manifest.txt").write_text(
        "\n".join(
            [
                "Number: 1015382228937",
                "2025-09-26 14:12 上海市 20006208 快件到达【上海市普陀区云岭揽投部】",
            ]
        ),
        encoding="utf-8",
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first_summary = import_letters_archive(session, source_root, archive_root)
        assert first_summary.tracking_events == 1

        item = session.scalar(select(Item))
        assert item is not None
        manual_event = TrackingEvent(
            item_id=item.id,
            occurred_at=item.tracking_events[0].occurred_at,
            location="Manual Desk",
            status="Checked by hand",
            details=None,
            source="manual",
        )
        session.add(manual_event)
        session.commit()

        (item_dir / "manifest.txt").write_text(
            "\n".join(
                [
                    "Number: 1015382228937",
                    "2025-09-26 14:12 上海市 20006208 快件到达【上海市普陀区云岭揽投部】",
                    "2025-09-26 15:10 上海市 20006208 快件正在派送中",
                ]
            ),
            encoding="utf-8",
        )

        second_summary = import_letters_archive(session, source_root, archive_root)
        assert second_summary.tracking_events == 2

        refreshed = session.scalar(select(Item))
        assert refreshed is not None
        manifest_events = [event for event in refreshed.tracking_events if event.source != "manual"]
        manual_events = [event for event in refreshed.tracking_events if event.source == "manual"]
        assert len(manifest_events) == 2
        assert len(manual_events) == 1
        assert manifest_events[0].location == "上海市 20006208"
