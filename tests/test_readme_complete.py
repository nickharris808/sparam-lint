"""The README must stay complete.

Not a style rule. Each item here is something a stranger needs in order to
decide whether to trust this and how to run it, and every one of them has gone
missing from some README in this portfolio at some point -- a badge pointing at
a workflow that had been renamed, a quickstart whose output no longer matched,
a contributing pointer to a file that did not exist.

The checks are structural. Whether the *content* is honest is enforced
separately, by the guards that re-run the transcripts and diff them.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
_RAW = (HERE / "README.md").read_text(encoding="utf-8")
# Hugging Face cards open with YAML front-matter. It is metadata, not prose,
# and counting it as the top of the document made the tagline check look past
# the tagline entirely.
README = re.sub(r"\A---\n.*?\n---\n", "", _RAW, flags=re.S)


def test_there_is_a_one_line_description_near_the_top() -> None:
    """A stranger should know what this is within two screens-worth of text."""
    head = "\n".join(README.splitlines()[:14])
    # The tagline may wrap; `re.S` lets `.` cross the line break.
    assert re.search(r"^\*\*.+?\*\*", head, re.M | re.S), (
        "no bold description in the first 14 lines after any front-matter"
    )


def test_every_required_section_is_present() -> None:
    missing = [s for s in ['30-second quickstart', 'Scope, honestly', 'Contributing', 'Citation', 'Licence'] if f"## {s}" not in README]
    assert not missing, f"README is missing section(s): {missing}"


def test_every_badge_is_an_image_link_with_an_https_target() -> None:
    badges = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", README)
    assert badges, "no badges"
    bad = [b for b in badges if not b.startswith("https://")]
    assert not bad, f"badge(s) with a non-https target: {bad}"


def test_local_links_point_at_files_that_exist() -> None:
    """A dead relative link is the cheapest possible broken promise."""
    targets = re.findall(r"\]\((?!https?://|#)([^)\s]+)\)", README)
    missing = [t for t in targets if not (HERE / t.split("#")[0]).exists()]
    assert not missing, f"README links to path(s) that do not exist: {missing}"


def test_it_cross_links_the_portfolio_and_the_docs_site() -> None:
    assert "nickharris808.github.io/physics-lint" in README, "no docs-site link"
    assert re.search(r"rest of the toolkit|## Related", README), (
        "no cross-links to the sibling artifacts"
    )


def test_the_scope_section_says_what_this_does_not_prove() -> None:
    m = re.search(r"^## Scope, honestly$(.*?)(?=^## |\Z)", README, re.M | re.S)
    assert m, "no honest-scope section"
    body = m.group(1).lower()
    assert re.search(r"\bnot\b|never|does not", body), (
        "the scope section states no limitation, which is not a scope section"
    )
