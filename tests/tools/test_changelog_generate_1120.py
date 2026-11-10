"""Card 1120: generate CHANGELOG.md at bump from PR ## Changelog sections."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "tools"))
import changelog_generate as cg  # noqa: E402

SAMPLE = textwrap.dedent(
    """\
    # Changelog

    ## TBD (upcoming)

    Upcoming changes are our current plan, not a promise; they can change or move at release time.

    - card 1053: later work

    ## New changes

    - card 1113: unreleased mid-cycle bullet (#387)

    0.8.10 (2026-11-09)

    - card 1098: shipped in 0.8.10 (#373)

    ## Last changes

    0.8.9 (2026-11-06)

    - card 970: shipped in 0.8.9 (#360)
    """
)


def _pr(number: int, title: str, body: str = "", sha: str = "") -> cg.MergedPR:
    return cg.MergedPR(number=number, title=title, body=body, sha=sha)


def test_parse_one_line_changelog_section():
    body = textwrap.dedent(
        """\
        ## summary

        long detail

        ## Changelog

        card 1120: generate the changelog at bump

        ## claims

        claim 1
        """
    )
    assert cg.parse_changelog_section(body) == "card 1120: generate the changelog at bump"


def test_parse_strips_bullet_and_ignores_empty_or_missing():
    assert (
        cg.parse_changelog_section("## Changelog\n\n- card 1: a change\n")
        == "card 1: a change"
    )
    assert cg.parse_changelog_section("## summary\n\nno section\n") is None
    assert cg.parse_changelog_section("## Changelog\n\n<!-- later -->\n\n") is None


def test_collect_uses_section_and_falls_back_to_squash_title():
    prs = [
        _pr(10, "card 10: title is ignored (#10)", "## Changelog\n\ncard 10: from the body\n"),
        _pr(11, "card 11: squash title only (#11)", "## summary\n\nno changelog section\n"),
    ]
    assert cg.collect_bullets(prs) == [
        "card 10: from the body",
        "card 11: squash title only (#11)",
    ]


def test_empty_window_yields_no_bullets():
    assert cg.collect_bullets([]) == []


def test_revert_same_window_drops_both():
    prs = [
        _pr(20, "card 20: add a switch (#20)", "## Changelog\n\ncard 20: add a switch\n"),
        _pr(
            21,
            'Revert "card 20: add a switch (#20)"',
            "This reverts commit abcdef1234567.\n\n## Changelog\n\nReverts #20\n",
        ),
        _pr(22, "card 22: stays (#22)", "## Changelog\n\ncard 22: stays\n"),
    ]
    assert cg.collect_bullets(prs) == ["card 22: stays"]


def test_revert_detected_from_github_title_and_commit_body_without_section():
    prs = [
        _pr(30, "card 30: landed (#30)", "## Changelog\n\ncard 30: landed\n"),
        _pr(31, 'Revert "card 30: landed (#30)"', "This reverts commit deadbeefcafebabe.\n"),
    ]
    assert cg.collect_bullets(prs) == []


def test_revert_of_earlier_release_is_listed():
    prs = [
        _pr(40, "card 40: new work (#40)", "## Changelog\n\ncard 40: new work\n"),
        _pr(41, 'Revert "card 5: old work (#5)"', "This reverts commit 1111111.\n"),
    ]
    assert cg.collect_bullets(prs) == [
        "card 40: new work",
        "Reverts #5",
    ]


def test_revert_from_commit_sha_when_title_has_no_pr():
    prs = [
        _pr(50, "card 50: in window (#50)", "## Changelog\n\ncard 50: in window\n"),
        _pr(51, 'Revert "card 50: in window"', "This reverts commit aaabbbcccddd.\n"),
    ]
    subjects = {"aaabbbcccddd": "card 50: in window (#50)"}
    assert cg.collect_bullets(prs, commit_subjects=subjects) == []


def test_rotate_writes_current_and_rolls_prior(tmp_path: Path):
    out = cg.apply_rotation(
        SAMPLE,
        version="0.8.11",
        date="2026-11-10",
        bullets=["card 1113: lock order (#387)", "card 1090: tw hops (#382)"],
    )
    tbd, new, last = cg.split_changelog(out)
    assert "card 1053: later work" in tbd
    assert new.startswith("0.8.11 (2026-11-10)")
    assert "- card 1113: lock order (#387)" in new
    assert "0.8.10" not in new
    assert "unreleased mid-cycle" not in new
    assert last.startswith("0.8.10 (2026-11-09)")
    assert "card 1098: shipped in 0.8.10" in last
    assert "0.8.9" not in last
    # three sections still, newest first
    heads = [ln for ln in out.splitlines() if ln.startswith("## ")]
    assert heads == list(cg.SECTIONS)


def test_empty_set_still_opens_the_version_heading():
    out = cg.apply_rotation(SAMPLE, version="0.8.11", date="2026-11-10", bullets=[])
    _tbd, new, last = cg.split_changelog(out)
    assert new == "0.8.11 (2026-11-10)"
    assert last.startswith("0.8.10 (2026-11-09)")


def test_idempotent_second_run_does_not_roll_last_again():
    first = cg.apply_rotation(
        SAMPLE, version="0.8.11", date="2026-11-10", bullets=["card 1: one"]
    )
    second = cg.apply_rotation(
        first, version="0.8.11", date="2026-11-10", bullets=["card 1: one", "card 2: two"]
    )
    _tbd, new, last = cg.split_changelog(second)
    assert new.startswith("0.8.11 (2026-11-10)")
    assert "- card 2: two" in new
    assert last.startswith("0.8.10 (2026-11-09)")
    assert "0.8.9" not in last
    third = cg.apply_rotation(
        second, version="0.8.11", date="2026-11-10", bullets=["card 1: one", "card 2: two"]
    )
    assert third == second


def test_malformed_changelog_raises():
    with pytest.raises(ValueError, match="three sections"):
        cg.split_changelog("# Changelog\n\n## New changes\n\n")


def test_generate_end_to_end_with_revert_and_fallback():
    prs = [
        _pr(387, "card 1113: lock order (#387)", "## Changelog\n\ncard 1113: lock order\n"),
        _pr(382, "card 1090: tw hops through the sitting connect (#382)", ""),
        _pr(5, 'Revert "card 2: already shipped (#2)"', "This reverts commit f00.\n"),
    ]
    out = cg.generate(SAMPLE, version="0.8.11", date="2026-11-10", prs=prs)
    _tbd, new, last = cg.split_changelog(out)
    assert "- card 1113: lock order" in new
    assert "- card 1090: tw hops through the sitting connect (#382)" in new
    assert "- Reverts #2" in new
    assert last.startswith("0.8.10 (2026-11-09)")


def _rows(*pairs: tuple[str, str]) -> list[tuple[str, str]]:
    return list(pairs)


def test_single_pr_flow_collects_squash_merges_to_main():
    """Card PRs squash-merge to main: each (#N) squash subject is an entry."""
    rows = _rows(
        ("a1", "card 10: first squash (#10)"),
        ("a2", "card 11: second squash (#11)"),
        ("a3", "the mill 0.8.11: version bump + changelog"),
    )
    bodies = {
        10: {"title": "card 10: first squash", "body": "## Changelog\n\ncard 10: first squash\n"},
        11: {"title": "card 11: second squash", "body": "## Changelog\n\ncard 11: second squash\n"},
    }
    prs = cg.merged_prs_from_log(rows, fetch=lambda n: bodies[n])
    assert [p.number for p in prs] == [10, 11]
    assert cg.collect_bullets(prs) == ["card 10: first squash", "card 11: second squash"]


def test_release_fold_flow_collects_card_prs_not_the_release_pr():
    """Card PRs merge into release/X.Y.Z; the release PR to main is not an entry."""
    rows = _rows(
        ("b1", "card 1120: generate changelog at bump"),
        ("b2", "Merge pull request #20 from si4ai/feat/1120-changelog-at-bump"),
        ("b3", "card 1112: desk identity direct"),
        ("b4", "Merge pull request #21 from si4ai/feat/1112-desk-identity"),
        ("b5", "the mill 0.8.11: version bump + changelog"),
        ("b6", "Merge pull request #99 from si4ai/release/0.8.11"),
    )
    bodies = {
        20: {
            "title": "card 1120: generate changelog at bump",
            "body": "## Changelog\n\ncard 1120: generate changelog at bump\n",
            "head": {"ref": "feat/1120-changelog-at-bump"},
        },
        21: {
            "title": "card 1112: desk identity direct",
            "body": "## Changelog\n\ncard 1112: desk identity direct\n",
            "head": {"ref": "feat/1112-desk-identity"},
        },
        99: {
            "title": "the mill 0.8.11",
            "body": "## Changelog\n\nthe mill 0.8.11 release\n",
            "head": {"ref": "release/0.8.11"},
            "base": {"ref": "main"},
        },
    }
    prs = cg.merged_prs_from_log(rows, fetch=lambda n: bodies[n])
    assert [p.number for p in prs] == [20, 21]
    assert cg.collect_bullets(prs) == [
        "card 1120: generate changelog at bump",
        "card 1112: desk identity direct",
    ]


def test_mixed_window_dedupes_by_pr_and_applies_reverts_across_flows():
    """A window can mix squash-to-main and release-fold PRs; reverts apply across both."""
    rows = _rows(
        ("c1", "card 30: already on main (#30)"),
        ("c2", "card 31: folded work"),
        ("c3", "Merge pull request #31 from si4ai/feat/31-fold"),
        # same PR appearing again as a squash-style subject must not duplicate
        ("c4", "card 31: folded work (#31)"),
        ("c5", 'Revert "card 30: already on main (#30)"'),
        ("c6", "Merge pull request #32 from si4ai/revert-30"),
        ("c7", 'Revert "card 9: shipped last release (#9)"'),
        ("c8", "Merge pull request #33 from si4ai/revert-9"),
        ("c9", "Merge pull request #99 from si4ai/release/0.8.11"),
    )
    bodies = {
        30: {"title": "card 30: already on main", "body": "## Changelog\n\ncard 30: already on main\n", "head": {"ref": "feat/30"}},
        31: {"title": "card 31: folded work", "body": "## Changelog\n\ncard 31: folded work\n", "head": {"ref": "feat/31-fold"}},
        32: {
            "title": 'Revert "card 30: already on main (#30)"',
            "body": "This reverts commit c1c1c1c.\n",
            "head": {"ref": "revert-30"},
        },
        33: {
            "title": 'Revert "card 9: shipped last release (#9)"',
            "body": "This reverts commit oldold.\n",
            "head": {"ref": "revert-9"},
        },
        99: {"title": "the mill 0.8.11", "body": "", "head": {"ref": "release/0.8.11"}},
    }
    prs = cg.merged_prs_from_log(rows, fetch=lambda n: bodies[n])
    assert [p.number for p in prs] == [30, 31, 32, 33]
    # #30 and its same-window revert #32 drop together; #31 stays;
    # revert of earlier-release #9 stays; release PR #99 is not an entry.
    assert cg.collect_bullets(prs) == [
        "card 31: folded work",
        "Reverts #9",
    ]
