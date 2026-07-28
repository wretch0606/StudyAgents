"""Prepare the two local-only PDF samples used by the one-week MVP.

The source repository is public but has no declared license. This script
downloads the files for local project evaluation only. It never writes course
materials into the Git repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    import pymupdf
except ImportError as exc:  # pragma: no cover - depends on local environment
    raise SystemExit(
        "PyMuPDF is required. Install the project's document-processing "
        "dependencies before running this script."
    ) from exc


SOURCE_REPOSITORY = "Asever611/NKU-SE-Passport"
SOURCE_COMMIT = "bbb111f2241211c9037afbfa9829216d04d34eaa"
COURSE_NAME = "数据库系统原理"
INSTRUCTOR = "李旭东"
RASTER_DPI = 150

DIGITAL_PATH = (
    "2_2_数据库系统原理_李旭东/课件/"
    "lecture01DbSystemIntroBasicR6.pdf"
)
DIGITAL_SHA256 = (
    "5c9509194e36bceda7dfa711e72596868af43519266c1f5821ee141070fa69fe"
)

EXAM_PATH = (
    "2_2_数据库系统原理_李旭东/期末/"
    "数据库期末考试真题2018-2019(A).pdf"
)
EXAM_SHA256 = (
    "64298082b4783c9e0957af026d6e7b886f54a367f49d08c4920509f4fe83e74e"
)


def raw_url(path: str) -> str:
    encoded_path = quote(path, safe="/()_.-")
    return (
        "https://raw.githubusercontent.com/"
        f"{SOURCE_REPOSITORY}/{SOURCE_COMMIT}/{encoded_path}"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path, expected_sha256: str) -> None:
    if destination.exists() and sha256(destination) == expected_sha256:
        return

    request = Request(url, headers={"User-Agent": "StudyAgents-sample-preparer"})
    with urlopen(request, timeout=60) as response:
        data = response.read()
    destination.write_bytes(data)

    actual_sha256 = sha256(destination)
    if actual_sha256 != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ValueError(
            f"SHA-256 mismatch for {destination.name}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )


def pdf_metrics(path: Path) -> dict[str, object]:
    with pymupdf.open(path) as document:
        text_chars = [
            len(page.get_text("text").strip()) for page in document
        ]
        return {
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "pages": document.page_count,
            "pages_with_text": sum(value >= 20 for value in text_chars),
            "text_chars_per_page": text_chars,
        }


def create_image_only_pdf(
    source_pdf: Path,
    destination: Path,
    page_indexes: tuple[int, ...],
) -> None:
    matrix = pymupdf.Matrix(RASTER_DPI / 72, RASTER_DPI / 72)
    output = pymupdf.open()
    try:
        with pymupdf.open(source_pdf) as source:
            for page_index in page_indexes:
                source_page = source[page_index]
                pixmap = source_page.get_pixmap(matrix=matrix, alpha=False)
                png_bytes = pixmap.tobytes("png")
                output_page = output.new_page(
                    width=source_page.rect.width,
                    height=source_page.rect.height,
                )
                output_page.insert_image(output_page.rect, stream=png_bytes)

        output.set_metadata(
            {
                "title": "StudyAgents local OCR test sample",
                "author": "StudyAgents",
                "subject": "Image-only derivative for local OCR evaluation",
                "keywords": "StudyAgents, OCR, local test sample",
                "creator": "scripts/prepare_course_samples.py",
                "producer": "PyMuPDF",
            }
        )
        output.save(destination, garbage=4, deflate=True, clean=True)
    finally:
        output.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".local-data/course-samples"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate the image-only OCR sample.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    digital_pdf = output_dir / "digital-lecture-intro.pdf"
    source_exam = output_dir / "_source-exam-2018-2019-A.pdf"
    scan_pdf = output_dir / "scan-exam-2018-2019-A-pages-1-2.pdf"

    download(raw_url(DIGITAL_PATH), digital_pdf, DIGITAL_SHA256)
    download(raw_url(EXAM_PATH), source_exam, EXAM_SHA256)
    if args.force or not scan_pdf.exists():
        create_image_only_pdf(source_exam, scan_pdf, (0, 1))

    digital_metrics = pdf_metrics(digital_pdf)
    scan_metrics = pdf_metrics(scan_pdf)
    if digital_metrics["pages_with_text"] != digital_metrics["pages"]:
        raise ValueError("Digital sample does not have text on every page.")
    if scan_metrics["pages_with_text"] != 0:
        raise ValueError("OCR sample unexpectedly contains a text layer.")

    manifest = {
        "course": {
            "name": COURSE_NAME,
            "instructor": INSTRUCTOR,
        },
        "source": {
            "repository": f"https://github.com/{SOURCE_REPOSITORY}",
            "commit": SOURCE_COMMIT,
            "license_declared": False,
            "usage": "local evaluation only; do not commit or redistribute",
        },
        "samples": [
            {
                "kind": "digital_pdf",
                "source_path": DIGITAL_PATH,
                **digital_metrics,
            },
            {
                "kind": "image_only_ocr_pdf",
                "derived_from": EXAM_PATH,
                "source_sha256": EXAM_SHA256,
                "source_pages": [1, 2],
                "raster_dpi": RASTER_DPI,
                **scan_metrics,
            },
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Prepared samples in {output_dir}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
