"""Typed value parsing for Hyprland config values.

Provides Color, Gradient, and Vec2 types for parsing color literals,
gradient specifications, and coordinate pairs commonly found in
Hyprland configuration files.
"""

import re
from dataclasses import dataclass
from typing import Self

_RGBA_RE = re.compile(r"^rgba\(([0-9a-fA-F]{8})\)$")
_RGB_RE = re.compile(r"^rgb\(([0-9a-fA-F]{6})\)$")
_HEX_ARGB_RE = re.compile(r"^(?:0x)?([0-9a-fA-F]{8})$")
_ANGLE_RE = re.compile(r"(\d+)deg$")


@dataclass(frozen=True, slots=True)
class Color:
    """An RGBA color value.

    Attributes:
        r: Red channel (0–255).
        g: Green channel (0–255).
        b: Blue channel (0–255).
        a: Alpha channel (0–255, default 255 = fully opaque).
    """

    r: int
    g: int
    b: int
    a: int = 255

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse a Hyprland color literal.

        Supported formats:
        - ``rgba(rrggbbaa)`` — 8-digit hex with alpha
        - ``rgb(rrggbb)`` — 6-digit hex, alpha defaults to 255
        - ``0xAARRGGBB`` — 8-digit hex, alpha in high byte
        - ``AARRGGBB`` — bare 8-digit hex (IPC format), alpha in high byte

        Raises ValueError if the text doesn't match any format.
        """
        text = text.strip()

        m = _RGBA_RE.match(text)
        if m:
            h = m.group(1)
            return cls(r=int(h[0:2], 16), g=int(h[2:4], 16), b=int(h[4:6], 16), a=int(h[6:8], 16))

        m = _RGB_RE.match(text)
        if m:
            h = m.group(1)
            return cls(r=int(h[0:2], 16), g=int(h[2:4], 16), b=int(h[4:6], 16))

        m = _HEX_ARGB_RE.match(text)
        if m:
            h = m.group(1)
            return cls(a=int(h[0:2], 16), r=int(h[2:4], 16), g=int(h[4:6], 16), b=int(h[6:8], 16))

        raise ValueError(f"Cannot parse color: {text!r}")

    def to_rgba(self) -> str:
        """Format as ``rgba(rrggbbaa)``."""
        return f"rgba({self.r:02x}{self.g:02x}{self.b:02x}{self.a:02x})"

    def to_rgb(self) -> str:
        """Format as ``rgb(rrggbb)``, discarding alpha."""
        return f"rgb({self.r:02x}{self.g:02x}{self.b:02x})"

    def to_hex(self) -> str:
        """Format as ``0xAARRGGBB``."""
        return f"0x{self.a:02x}{self.r:02x}{self.g:02x}{self.b:02x}"

    def __str__(self) -> str:
        """Format as ``rgba(rrggbbaa)``."""
        return self.to_rgba()


@dataclass(frozen=True, slots=True)
class Gradient:
    """A gradient specification: one or more colors with an optional angle.

    Attributes:
        colors: List of Color values in the gradient.
        angle: Angle in degrees (default 0).
    """

    colors: tuple[Color, ...]
    angle: int = 0

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse a Hyprland gradient value.

        Format: ``color1 color2 [... colorN] [angle_deg]``

        Example: ``rgba(33ccffee) rgba(00ff99ee) 45deg``

        Raises ValueError if no colors can be parsed.
        """
        text = text.strip()
        angle = 0

        m = _ANGLE_RE.search(text)
        if m:
            angle = int(m.group(1))
            text = text[: m.start()].strip()

        # Split remaining tokens and parse each as a color
        colors = [Color.parse(token) for token in text.split()]

        if not colors:
            raise ValueError(f"Cannot parse gradient: no colors found in {text!r}")

        return cls(colors=tuple(colors), angle=angle)

    def __str__(self) -> str:
        """Format the gradient as a Hyprland value string."""
        parts = [c.to_rgba() for c in self.colors]
        if self.angle != 0:
            parts.append(f"{self.angle}deg")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class Vec2:
    """A 2D coordinate pair.

    Attributes:
        x: X component (float).
        y: Y component (float).
    """

    x: int | float
    y: int | float

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse a coordinate pair from space-separated values.

        Format: ``x y`` where x and y are numeric values.

        Example: ``1920 1080``, ``2.5 3.0``

        Raises ValueError if parsing fails.
        """
        parts = text.strip().split()
        if len(parts) != 2:
            raise ValueError(f"Cannot parse Vec2: expected 2 values, got {len(parts)} in {text!r}")
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            raise ValueError(f"Cannot parse Vec2: non-numeric values in {text!r}") from None
        # Use int if values are whole numbers
        return cls(x=int(x) if x.is_integer() else x, y=int(y) if y.is_integer() else y)

    def __str__(self) -> str:
        """Format as ``x y``."""
        return f"{self.x} {self.y}"
