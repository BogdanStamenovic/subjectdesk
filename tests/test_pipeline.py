from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from docx import Document

from subjectdesk.core import (
    SubjectdeskError,
    claim,
    discover,
    init,
    jobs,
    parse_model_output,
    process_one,
    requeue_interrupted,
    retry,
    scan_stable,
    workspace_lock,
)


def test_assignment_moves_into_completed_folder(tmp_path: Path) -> None:
    init(tmp_path)
    subject = tmp_path / "History"
    subject.mkdir()
    source = subject / "roads.md"
    source.write_text("---\nformats: [docx, md]\n---\nResearch Roman roads.", encoding="utf-8")
    seen: dict[str, tuple[int, int]] = {}
    assert scan_stable(tmp_path, seen, "haiku") == []
    assert len(scan_stable(tmp_path, seen, "haiku")) == 1

    def fake_research(assignment, rules):
        assert assignment.model == "haiku"
        assert "Do not use em dashes" in rules
        return "Roman roads", "## Findings\nRoads improved travel—especially trade.\n\n## Sources\nhttps://example.org"

    process_one(tmp_path, fake_research)
    output = subject / "roads"
    assert (output / "roads.md").exists()
    assert (output / "work.md").exists()
    assert (output / "work.docx").exists()
    assert not source.exists()
    assert "—" not in (output / "work.md").read_text(encoding="utf-8")
    assert "Roman roads" in Document(output / "work.docx").paragraphs[0].text
    assert jobs(tmp_path)[0]["status"] == "done"


def test_failure_keeps_source_and_can_retry(tmp_path: Path) -> None:
    init(tmp_path)
    subject = tmp_path / "Biology"
    subject.mkdir()
    source = subject / "cells.txt"
    source.write_text("Research cells", encoding="utf-8")
    job_id = discover(tmp_path)[0]

    def fail(_assignment, _rules):
        raise RuntimeError("API unavailable")

    process_one(tmp_path, fail)
    assert source.exists()
    assert jobs(tmp_path)[0]["status"] == "failed"
    retry(tmp_path, job_id)
    process_one(tmp_path, lambda _assignment, _rules: ("Cells", "Cells are studied."))
    assert jobs(tmp_path)[0]["status"] == "done"


def test_model_output_requires_document_and_cleans_style() -> None:
    title, body = parse_model_output(
        json.dumps({"title": "Title😀", "body_markdown": '<cite index="1-2">Hello—world.</cite>'})
    )
    assert title == "Title"
    assert body == "Hello, world."


def test_workers_claim_distinct_jobs(tmp_path: Path) -> None:
    init(tmp_path)
    subject = tmp_path / "Math"
    subject.mkdir()
    for index in range(5):
        (subject / f"task-{index}.txt").write_text("Explain primes", encoding="utf-8")
    discover(tmp_path)
    with ThreadPoolExecutor(max_workers=5) as pool:
        claimed = list(pool.map(lambda _: claim(tmp_path), range(5)))
    assert all(row is not None for row in claimed)
    assert len({row["id"] for row in claimed if row is not None}) == 5


def test_restart_requeues_interrupted_job_and_locks_workspace(tmp_path: Path) -> None:
    init(tmp_path)
    subject = tmp_path / "Art"
    subject.mkdir()
    (subject / "task.txt").write_text("Research pigments", encoding="utf-8")
    discover(tmp_path)
    with workspace_lock(tmp_path):
        assert claim(tmp_path) is not None
        with pytest.raises(SubjectdeskError, match="another worker"), workspace_lock(tmp_path):
            pass
    assert requeue_interrupted(tmp_path) == 1
    assert jobs(tmp_path)[0]["status"] == "queued"
