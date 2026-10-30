# -*- coding: utf-8 -*-
"""claimed-after-ship-close: progress 100%/git SHA -> shipped; Pass MAIL mill done."""
from __future__ import annotations

from agent_coord.server.records.todo import (
    is_validator_pass_body,
    pass_mail_closes,
    progress_git_sha,
    progress_is_done,
)
from agent_coord.protocol.mail import MAIL_BODY_MAX


def test_progress_git_sha_and_done():
    assert progress_git_sha("100% git ad4198c tests pass") == "ad4198c"
    assert progress_is_done("git ad4198c tests pass") is True
    assert progress_is_done("implementing") is False


def test_pass_mail_closes_by_sha_and_need_id():
    needs = [
        {
            "need_id": "presence-root-office-dest",
            "status": "shipped",
            "progress": "100% git ad4198c tests pass",
        },
        {
            "need_id": "mill-cli-version",
            "status": "shipped",
            "progress": "100% git ad4198c mill --version",
        },
        {
            "need_id": "other-job",
            "status": "claimed",
            "progress": "implementing",
        },
    ]
    body = (
        "Validation Verdict: PASSED WITH WARNINGS (#23+#27 Valid git ad4198c). "
        "KPI pytest. Prefer mill."
    )
    assert is_validator_pass_body("build-validator", body) is True
    assert is_validator_pass_body("builder", body) is False
    closed = pass_mail_closes("build-validator", body, needs)
    assert "presence-root-office-dest" in closed
    assert "mill-cli-version" in closed
    assert "other-job" not in closed


def test_mail_body_max_4096():
    assert MAIL_BODY_MAX == 4096
