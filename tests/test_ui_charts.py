from app.ui.main import prepare_charts, prepare_distribution


def test_app_distribution_uses_storage_and_file_counts():
    distribution = prepare_distribution([
        {"meta": {"source": "laptop_store", "app": "Small", "bytes": 25, "files": 2}},
        {"meta": {"source": "laptop_store", "app": "Large", "bytes": 75, "files": 6}},
    ])

    assert distribution == {
        "kind": "apps",
        "apps": [
            {"app": "Large", "bytes": 75, "files": 6},
            {"app": "Small", "bytes": 25, "files": 2},
        ],
        "totals": {"bytes": 100, "files": 8},
    }


def test_app_distribution_totals_include_folders_outside_top_twelve():
    records = [
        {"meta": {"source": "laptop_store", "app": f"App {index}", "bytes": index, "files": index * 2}}
        for index in range(1, 14)
    ]

    distribution = prepare_distribution(records)

    assert len(distribution["apps"]) == 12
    assert distribution["totals"] == {"bytes": sum(range(1, 14)), "files": sum(index * 2 for index in range(1, 14))}


def test_import_distribution_groups_records_by_platform_and_category():
    distribution = prepare_distribution([
        {"platform": "instagram", "category": "account"},
        {"platform": "instagram", "category": "account"},
        {"platform": "spotify", "category": "interest"},
    ])

    assert distribution["kind"] == "records"
    assert distribution["counts"] == {
        "instagram": {"account": 2, "interest": 0},
        "spotify": {"account": 0, "interest": 1},
    }


def test_connection_layout_has_three_dimensions():
    _, positions, _, _ = prepare_charts({
        "graph": {
            "nodes": [
                {"id": "user", "type": "user"},
                {"id": "service", "type": "service"},
            ],
            "edges": [{"source": "user", "target": "service"}],
        },
        "records": [],
    })

    assert all(len(position) == 3 for position in positions.values())
