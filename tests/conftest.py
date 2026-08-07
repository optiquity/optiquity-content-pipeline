"""Shared pytest markers for the pipeline test suite.

The SINGLE canonical home for the optional-diagram-tool skip markers (imported by every test module
that DRIVES a real `dot`/`d2`/`rsvg-convert`). Diagram GENERATION shells to the real `dot`/`d2`, and
a docx SVG embed rasterizes via `rsvg-convert` — all THREE are OPTIONAL. On a tool-less host the
pipeline DEGRADES gracefully (a requested diagram is skipped and its text-alt substituted; a docx
SVG embed drops to alt text — the ratified "works without graphviz" contract), so a test requiring a
real tool SKIPS when its binary is absent rather than failing CI. The tool-ABSENCE degradation is
proven tool-lessly by the dedicated degradation tests, which SIMULATE absence and run regardless.
"""

from __future__ import annotations

import shutil

import pytest

#: SKIP a `dot`-generating test when graphviz `dot` is absent (the tool is optional; absence
#: degrades to the text-alt, proven separately). Keyed on `shutil.which` — tracks the real PATH.
requires_dot = pytest.mark.skipif(
    shutil.which("dot") is None,
    reason="graphviz `dot` not installed — diagram generation is optional (degrades to text-alt)",
)

#: SKIP a `d2`-generating test when the `d2` binary is absent (optional, same contract as `dot`).
requires_d2 = pytest.mark.skipif(
    shutil.which("d2") is None,
    reason="`d2` not installed — diagram generation is optional (degrades to text-alt)",
)

#: SKIP a docx SVG-embed test when `rsvg-convert` is absent — a docx SVG embed degrades to alt text
#: when it is missing (optional), so the embed-PRESENT assertion only holds where the tool is there.
requires_rsvg = pytest.mark.skipif(
    shutil.which("rsvg-convert") is None,
    reason="`rsvg-convert` not installed — a docx SVG embed degrades to alt text (optional)",
)
