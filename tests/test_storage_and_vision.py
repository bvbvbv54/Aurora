from aurora.config import Settings, apply_storage_root
from aurora.llm.providers import AIProviderConfig
from aurora.llm.vision_classifier import classify_image


def test_storage_root_redirects_all_mutable_runtime_paths(tmp_path):
    settings = Settings(
        raw={
            "database": {"url": "sqlite:///old.db"},
            "output": {"directory": "./reports"},
            "browser": {"user_data_dir": "./profile"},
        },
        source=tmp_path / "config.yaml",
    )
    root = tmp_path / "runtime"
    redirected = apply_storage_root(settings, root)
    assert redirected.database_url.endswith("/runtime/aurora.db")
    assert redirected.report_dir == root / "reports"
    assert redirected.section("browser")["user_data_dir"] == str(root / "browser-profile")
    assert redirected.section("storage")["thumbnails"] == str(root / "thumbnails")


def test_thumbnail_classifier_accepts_short_valid_json(monkeypatch, tmp_path):
    image = tmp_path / "thumb.jpg"
    image.write_bytes(b"fixture")
    monkeypatch.setattr(
        "aurora.llm.vision_classifier.generate_image_json",
        lambda *_args, **_kwargs: {"label": "high", "confidence": 97},
    )
    result = classify_image(
        image,
        "thumbnail",
        AIProviderConfig(provider="openrouter", model="MODEL"),
    )
    assert result.label == "high"
    assert result.confidence == 97
    assert result.status == "collected"


def test_graph_classifier_rejects_unrecognized_output(monkeypatch, tmp_path):
    image = tmp_path / "graph.png"
    image.write_bytes(b"fixture")
    monkeypatch.setattr(
        "aurora.llm.vision_classifier.generate_image_json",
        lambda *_args, **_kwargs: {"label": "guess", "confidence": 99},
    )
    result = classify_image(
        image,
        "graph",
        AIProviderConfig(provider="openrouter", model="MODEL"),
    )
    assert result.status == "invalid"
