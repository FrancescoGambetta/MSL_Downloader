from catalog_manager.customization import filter_camera_selection, product_pair


def test_mastcam_combination_is_kept_together() -> None:
    assert product_pair("mastcam", "0000000000000000000000C00_DRCL") == ("C00", "DRCL")
    assert product_pair("mastcam", "0000000000000000000000E01_DRCX") == ("E01", "DRCX")


def test_navcam_combination_uses_camera_and_marker() -> None:
    assert product_pair("navcam", "NLB_690806150ILTLF0912132NCAM00353M1") == ("NLB", "ILTLF")


def test_filter_uses_exact_combinations() -> None:
    payload = {"cameras": {"mastcam": {"product_count": 3, "products": [
        {"product_id": "0000000000000000000000C00_DRCL"},
        {"product_id": "0000000000000000000000E01_DRCL"},
        {"product_id": "0000000000000000000000E01_DRCX"},
    ]}}}
    removed, existing = filter_camera_selection(payload, "mastcam", {
        "C00": ["DRCL"], "E01": ["DRCX"],
    })
    assert removed == 1
    assert existing["C00"] == {"DRCL"}
    assert existing["E01"] == {"DRCL", "DRCX"}
    assert payload["cameras"]["mastcam"]["products"] == [
        {"product_id": "0000000000000000000000C00_DRCL"},
        {"product_id": "0000000000000000000000E01_DRCX"},
    ]
