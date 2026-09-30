"""Amendment-marker running state and stripping for consolidated texts."""

from __future__ import annotations

import re

from bs4 import NavigableString, Tag

# Block markers: ▼B, ▼M1, ▼C1, ▼C2. Inline: ►M1 ... ◄ (and C codes).
_BLOCK_MARKER = re.compile(r"▼([BMC]\d*)")
_INLINE_OPEN = re.compile(r"►([MC]\d*)")
_INLINE_CLOSE = "◄"
_MARKER_GLYPHS = re.compile(r"[▼►◄]")
_MARKER_CODE = re.compile(r"^[BMC]\d*$")


class MarkerTracker:
    """Tracks the current amendment marker while walking the document."""

    def __init__(self) -> None:
        self.block_code: str | None = None
        self.inline_code: str | None = None
        self.saw_m1_text: bool = False

    @property
    def current_code(self) -> str | None:
        if self.inline_code is not None:
            return self.inline_code
        return self.block_code

    def observe_text(self, text: str) -> None:
        """Record that body text was seen under the current marker."""
        if text and self.current_code == "M1":
            self.saw_m1_text = True

    def apply_marker_text(self, text: str) -> None:
        """Update state from a marker string such as '▼M1' or '◄'."""
        stripped = text.strip()
        if not stripped:
            return
        block = _BLOCK_MARKER.fullmatch(stripped)
        if block is not None:
            self.block_code = block.group(1)
            self.inline_code = None
            return
        inline = _INLINE_OPEN.fullmatch(stripped)
        if inline is not None:
            self.inline_code = inline.group(1)
            return
        if _INLINE_CLOSE in stripped:
            self.inline_code = None

    def amended_by(self) -> list[str]:
        return ["Omnibus"] if self.saw_m1_text else []


def is_marker_element(node: Tag) -> bool:
    """True when the element is only an amendment marker (or wrapper)."""
    classes = node.get("class") or []
    if "modref" in classes or "arrow" in classes:
        return True
    text = node.get_text(strip=True)
    if not text:
        return False
    if _BLOCK_MARKER.fullmatch(text):
        return True
    if _INLINE_OPEN.fullmatch(text):
        return True
    if text == _INLINE_CLOSE:
        return True
    # Inline wrappers such as a boldface span containing only ►C1 or ◄.
    without_glyphs = _MARKER_GLYPHS.sub("", text).strip()
    if _MARKER_GLYPHS.search(text) and (
        not without_glyphs or _MARKER_CODE.fullmatch(without_glyphs)
    ):
        return True
    return False


def extract_marker_text(node: Tag | NavigableString) -> str | None:
    """Return marker text from a marker node, if any."""
    if isinstance(node, NavigableString):
        text = str(node).strip()
    else:
        if not is_marker_element(node):
            return None
        text = node.get_text(strip=True)
    if not text:
        return None
    if _BLOCK_MARKER.search(text) or _INLINE_OPEN.search(text) or _INLINE_CLOSE in text:
        return text
    return None


def strip_marker_glyphs(text: str) -> str:
    """Remove any leftover amendment marker characters from body text."""
    return _MARKER_GLYPHS.sub("", text)
