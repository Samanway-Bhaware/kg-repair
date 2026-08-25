"""
P7b -- AppTest smoke for the two screens this phase added.

One test per screen: it renders, its primary control is present, and the path a
user hits first when they have not done the previous step shows a message rather
than a traceback.

Deliberately thin. The behaviour these screens drive is covered by
`tests/test_viewer_upload_flow.py` against `app.logic`, where it runs in
milliseconds; an AppTest that re-derived candidates through the UI would buy the
same assurance at a much larger share of the suite's time budget. The timeout
here matches the one the existing viewer suites use and is not raised.
"""
from __future__ import annotations

import os

from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")
TIMEOUT = 30


def _at_on(screen: str) -> AppTest:
    at = AppTest.from_file(APP)
    at.run(timeout=TIMEOUT)
    at.sidebar.radio[0].set_value(screen).run(timeout=TIMEOUT)
    return at


def _text(at) -> str:
    parts = [el.value for el in at.info] + [el.value for el in at.markdown]
    parts += [el.value for el in at.error] + [el.value for el in at.caption]
    return "\n".join(str(p) for p in parts)


def test_the_derive_screen_renders_with_its_primary_control():
    """The Load screen selects a fixture by default, so Derive comes up ready to
    run rather than asking for a graph."""
    at = _at_on("Derive")
    assert not at.exception
    assert any(b.label == "Derive candidates" for b in at.button)
    text = _text(at)
    assert "Nothing proposed here can repair anything" in text
    assert "worked out one entry at a time" in text or "Review screen" in text


def test_the_review_screen_renders_and_asks_for_candidates_first():
    at = _at_on("Review")
    assert not at.exception
    assert "Derive candidates" in _text(at)


def test_both_new_screens_are_reachable_from_the_sidebar():
    at = AppTest.from_file(APP)
    at.run(timeout=TIMEOUT)
    options = list(at.sidebar.radio[0].options)
    assert "Derive" in options and "Review" in options
    # the order a user meets them: load, check, then the derive path, then repair
    assert options.index("Derive") < options.index("Review") < options.index("Repair")


def test_the_load_screen_states_the_scope_before_the_upload_control():
    """The P7 scope caption, checked where a user actually meets it."""
    at = _at_on("Load")
    assert not at.exception
    captions = "\n".join(str(el.value) for el in at.caption)
    assert "runs locally on this machine only" in captions
    # the caption must still carry the substance of the scope statement: an
    # upload is not filtered by the allow-lists, and its content is the
    # user's responsibility.
    assert "not filtered by the project's Level-0 allow-lists" in captions
    assert "the responsibility for it, is yours" in captions
