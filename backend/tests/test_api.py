"""API tests using FastAPI TestClient.

Background pipeline is monkey-patched so tests run instantly without LLM calls.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import job_store as job_store_module


@pytest.fixture(autouse=True)
def reset_store():
    job_store_module.reset_job_store_for_tests()
    yield
    job_store_module.reset_job_store_for_tests()


def _build_app(
    tmp_path: Path,
    *,
    anthropic_key: str | None = "sk-ant-test",
    gemini_key: str | None = "gemini-test",
    openai_key: str | None = "sk-openai-test",
):
    """Build a fresh FastAPI app with hand-injected Settings.

    Hermetic: ignores ambient env and .env via ``_env_file=None``.
    """
    from app.core import config

    settings = config.Settings(
        _env_file=None,
        anthropic_api_key=anthropic_key,
        gemini_api_key=gemini_key,
        openai_api_key=openai_key,
        data_dir=tmp_path,
    )
    config.set_settings_for_tests(settings)

    from app.main import create_app

    return create_app()


@pytest.fixture(autouse=True)
def restore_settings():
    yield
    from app.core import config

    config.set_settings_for_tests(None)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(_build_app(tmp_path))


@pytest.fixture
def fake_pipeline(monkeypatch: pytest.MonkeyPatch):
    """Replace run_pipeline_job with a no-op that just marks the job done.

    Lets us test the API surface without burning LLM tokens.
    """
    def _stub(*, job_id: str, pdf_path: str, output_dir: str, model_id: str) -> None:
        from app.core.job_store import get_job_store

        store = get_job_store()
        store.mark_started(job_id)
        store.update_progress(job_id, step="analyzing_page", progress_pct=50, current_page=1)
        # Write minimal artifacts so /download and /content can succeed.
        from pathlib import Path as _P

        out = _P(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "content.md").write_text("# stub\n", encoding="utf-8")
        (out / "result.zip").write_bytes(b"PK\x03\x04")  # zip magic
        store.mark_done(job_id)

    monkeypatch.setattr("app.api.jobs.run_pipeline_job", _stub)


GOLDEN_PDF = Path(__file__).parent / "golden" / "deepco_kdc_18" / "input.pdf"


# ---------------------------------------------------------------------------
# /health and /models
# ---------------------------------------------------------------------------


def test_health_ok(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "data_dir" in body


def test_models_lists_all_with_enabled_flags(client: TestClient):
    r = client.get("/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["models"]]
    assert ids == [
        "claude-haiku-4-5",
        "gemini-2-5-flash",
        "gemini-3-flash",
        "gpt-5-mini",
        "gpt-5.4-mini",
    ]
    for m in r.json()["models"]:
        assert m["enabled"] is True  # all keys set in fixture


# ---------------------------------------------------------------------------
# POST /jobs validation
# ---------------------------------------------------------------------------


def test_create_job_rejects_unknown_model(client: TestClient):
    if not GOLDEN_PDF.exists():
        pytest.skip("golden PDF missing")
    with open(GOLDEN_PDF, "rb") as f:
        r = client.post(
            "/jobs",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"model": "gpt-5"},
        )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_MODEL"


def test_create_job_rejects_non_pdf_extension(client: TestClient):
    r = client.post(
        "/jobs",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"model": "claude-haiku-4-5"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_FILE_TYPE"


def test_create_job_rejects_fake_pdf(client: TestClient):
    r = client.post(
        "/jobs",
        files={"file": ("fake.pdf", b"not a real pdf", "application/pdf")},
        data={"model": "claude-haiku-4-5"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_FILE_TYPE"


def test_create_job_rejects_model_without_key(tmp_path: Path):
    c = TestClient(_build_app(tmp_path, gemini_key=None))
    if not GOLDEN_PDF.exists():
        pytest.skip("golden PDF missing")
    with open(GOLDEN_PDF, "rb") as f:
        r = c.post(
            "/jobs",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"model": "gemini-3-flash"},
        )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "MODEL_NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# Full happy path with stubbed worker
# ---------------------------------------------------------------------------


def test_full_lifecycle_with_stub(client: TestClient, fake_pipeline):
    if not GOLDEN_PDF.exists():
        pytest.skip("golden PDF missing")
    with open(GOLDEN_PDF, "rb") as f:
        r = client.post(
            "/jobs",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"model": "claude-haiku-4-5"},
        )
    assert r.status_code == 201, r.json()
    body = r.json()
    job_id = body["job_id"]
    assert body["model"] == "claude-haiku-4-5"
    assert body["total_pages"] == 28

    # Once the response returns, BackgroundTasks have already run for TestClient.
    status = client.get(f"/jobs/{job_id}").json()
    assert status["status"] == "done"
    assert status["progress_pct"] == 100

    # Download.
    download = client.get(f"/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert download.content.startswith(b"PK")

    # Markdown preview endpoint.
    content_md = client.get(f"/jobs/{job_id}/content")
    assert content_md.status_code == 200
    assert content_md.text.startswith("# stub")


def test_get_unknown_job_returns_404(client: TestClient):
    r = client.get("/jobs/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_download_before_done_returns_404(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Stub the worker so the job stays QUEUED; download should refuse."""
    monkeypatch.setattr("app.api.jobs.run_pipeline_job", lambda **_: None)
    if not GOLDEN_PDF.exists():
        pytest.skip("golden PDF missing")
    with open(GOLDEN_PDF, "rb") as f:
        r = client.post(
            "/jobs",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"model": "claude-haiku-4-5"},
        )
    job_id = r.json()["job_id"]
    download = client.get(f"/jobs/{job_id}/download")
    assert download.status_code == 404
    assert download.json()["error"]["code"] == "RESULT_NOT_READY"


def test_image_path_traversal_rejected(client: TestClient, fake_pipeline):
    if not GOLDEN_PDF.exists():
        pytest.skip("golden PDF missing")
    with open(GOLDEN_PDF, "rb") as f:
        r = client.post(
            "/jobs",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"model": "claude-haiku-4-5"},
        )
    job_id = r.json()["job_id"]
    bad = client.get(f"/jobs/{job_id}/images/..%2F..%2Fetc%2Fpasswd")
    # The decoded `..` triggers our guard (FastAPI does not auto-decode path
    # separators inside path params, but starlette will pass the raw string).
    assert bad.status_code in (400, 404)


def test_delete_job_removes_state(client: TestClient, fake_pipeline):
    if not GOLDEN_PDF.exists():
        pytest.skip("golden PDF missing")
    with open(GOLDEN_PDF, "rb") as f:
        r = client.post(
            "/jobs",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"model": "claude-haiku-4-5"},
        )
    job_id = r.json()["job_id"]
    delete = client.delete(f"/jobs/{job_id}")
    assert delete.status_code == 204
    after = client.get(f"/jobs/{job_id}")
    assert after.status_code == 404
