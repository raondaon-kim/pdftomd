from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

from app.models import BBox, LectureContext, PageAnalysis, SlideOutlineEntry
from app.pipeline.packager import build_markdown, package_result


def _ctx() -> LectureContext:
    return LectureContext(
        title="데이터 분석 인공지능 앱 제작하기",
        topic_summary="AI 교육 차시 요약입니다.",
        slide_outline=[SlideOutlineEntry(page=6, title="모델", one_line="개념")],
        key_terms=["PAPS", "BMI"],
        domain_hints="AI 교육",
    )


def _sample_pages() -> list[PageAnalysis]:
    return [
        PageAnalysis(page_num=1, classification="cover", title="", markdown_body="", reasoning="cover"),
        PageAnalysis(
            page_num=2,
            classification="section_divider",
            title="오늘의 학습",
            markdown_body="",
            reasoning="divider",
        ),
        PageAnalysis(
            page_num=6,
            classification="content",
            title="데이터 분석 모델이란?",
            markdown_body="본문 텍스트입니다.",
            reasoning="r",
        ),
        PageAnalysis(
            page_num=7,
            classification="content",
            title="모델 만들기",
            markdown_body="5단계 프로세스",
            image_region=BBox(x_min=60, y_min=160, x_max=970, y_max=950),
            image_caption="모델 생성 5단계",
            image_filename="07_모델_만들기.png",
            reasoning="r",
        ),
        PageAnalysis(
            page_num=19,
            classification="decorative_only",
            title="실습 영상",
            markdown_body="영상을 보고 잘 만들었는지 확인합니다.",
            reasoning="deco",
        ),
    ]


def test_build_markdown_skips_cover():
    md = build_markdown(_sample_pages(), pdf_filename="x", model_id="claude-haiku-4-5")
    assert "슬라이드 1 " not in md


def test_build_markdown_section_divider_keeps_only_h2():
    md = build_markdown(_sample_pages(), pdf_filename="x", model_id="claude-haiku-4-5")
    # H2 line for page 2 should appear; no body content beyond.
    assert "## 슬라이드 2 — 오늘의 학습" in md


def test_build_markdown_content_includes_body_and_image_link():
    md = build_markdown(_sample_pages(), pdf_filename="x", model_id="claude-haiku-4-5")
    assert "본문 텍스트입니다." in md
    assert "![모델 생성 5단계](images/07_모델_만들기.png)" in md


def test_build_markdown_decorative_keeps_short_note():
    md = build_markdown(_sample_pages(), pdf_filename="x", model_id="claude-haiku-4-5")
    assert "영상을 보고 잘 만들었는지 확인합니다." in md


def test_build_markdown_header_uses_lecture_context():
    md = build_markdown(
        _sample_pages(),
        pdf_filename="deepco_kdc_18",
        model_id="claude-haiku-4-5",
        context=_ctx(),
        extracted_on=date(2026, 4, 29),
    )
    assert md.startswith("# 데이터 분석 인공지능 앱 제작하기")
    assert "## 강의 요약" in md
    assert "PAPS, BMI" in md
    assert "추출 일시: 2026-04-29" in md
    assert "Claude Haiku 4.5" in md


def test_package_result_creates_zip(tmp_path: Path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "07_모델_만들기.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    md_path, zip_path = package_result(
        _sample_pages(),
        output_dir=tmp_path,
        pdf_filename="x",
        model_id="claude-haiku-4-5",
        context=_ctx(),
    )
    assert md_path.exists()
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert "content.md" in names
    assert "images/07_모델_만들기.png" in names
