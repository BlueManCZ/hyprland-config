"""Deprecation declarations and the read-only :func:`check_deprecated` reporter.

Sourced from Hyprland changelogs and migration guides. Tools surface
these as warnings; the actual transforms that fix them live in
:mod:`._runner` and :mod:`._windowrule`.
"""

import re
from dataclasses import dataclass
from functools import cached_property

from hyprland_config._core._model import Document, KeyValueLine, Line
from hyprland_config._core._types import parse_version
from hyprland_config._migrate._runner import BLUR_OPTIONS


@dataclass(frozen=True)
class ConfigDeprecation:
    """A single deprecation or migration warning."""

    key: str
    message: str
    version_deprecated: str
    version_removed: str = ""
    suggestion: str = ""
    lineno: int = 0
    source_name: str = ""

    def __str__(self) -> str:
        loc = f"{self.source_name}:{self.lineno}: " if self.source_name else ""
        removed = f" (removed in {self.version_removed})" if self.version_removed else ""
        suggestion = f" → {self.suggestion}" if self.suggestion else ""
        return f"{loc}{self.key}: deprecated in {self.version_deprecated}{removed}{suggestion}"


@dataclass
class _DeprecationRule:
    """Internal rule definition for matching deprecated config patterns."""

    key: str = ""
    key_pattern: str = ""  # regex pattern for key matching (when exact key isn't enough)
    value_pattern: str = ""  # regex pattern for value matching

    # Metadata
    message: str = ""
    version_deprecated: str = ""
    version_removed: str = ""
    suggestion: str = ""

    @cached_property
    def deprecated_ver(self) -> tuple[int, ...]:
        return parse_version(self.version_deprecated)

    @cached_property
    def key_re(self) -> re.Pattern[str] | None:
        return re.compile(self.key_pattern) if self.key_pattern else None

    @cached_property
    def value_re(self) -> re.Pattern[str] | None:
        return re.compile(self.value_pattern) if self.value_pattern else None


_RULES: list[_DeprecationRule] = [
    # v0.41: "no_cursor_warps" renamed to "no_warps"
    _DeprecationRule(
        key="cursor:no_cursor_warps",
        message="no_cursor_warps was renamed",
        version_deprecated="0.41",
        suggestion="Use cursor:no_warps instead",
    ),
    # v0.42: apply_sens_to_raw removed from general
    _DeprecationRule(
        key="general:apply_sens_to_raw",
        message="apply_sens_to_raw was removed",
        version_deprecated="0.42",
        version_removed="0.42",
        suggestion="Remove this option — it has no effect",
    ),
    # v0.34: exec_once renamed to exec-once
    _DeprecationRule(
        key="exec_once",
        message="exec_once was renamed",
        version_deprecated="0.33",
        suggestion="Use exec-once instead",
    ),
    # v0.48: windowrule (v1) deprecated in favour of windowrulev2.
    # Hyprland 0.53+ reused the ``windowrule`` keyword for the v3 syntax
    # (``windowrule = match:KEY VALUE, EFFECT VALUE``), so the keyword
    # alone isn't enough to spot v1 lines. v3 always carries a ``match:``
    # token; the negative-lookahead pattern matches lines that *lack*
    # one, which is the same v1-vs-v3 signal :func:`migrate_windowrule_v1_to_v2`
    # uses to decide whether to rewrite.
    _DeprecationRule(
        key="windowrule",
        value_pattern=r"^(?!.*match:).+",
        message="windowrule (v1) is deprecated",
        version_deprecated="0.48",
        suggestion="Use windowrule v3 syntax: windowrule = <rule>, match:<KEY> <VALUE>",
    ),
    # v0.53: windowrulev2 renamed to windowrule (v3 syntax)
    _DeprecationRule(
        key="windowrulev2",
        message="windowrulev2 was renamed back to windowrule with v3 syntax",
        version_deprecated="0.53",
        suggestion="Use windowrule with v3 syntax: windowrule = <rule>, <match>",
    ),
    # v0.53: layerrule v1 deprecated
    _DeprecationRule(
        key="layerrule",
        value_pattern=r"^[^,]+$",  # v1 has no comma (no explicit match clause)
        message="layerrule v1 syntax (no match clause) is deprecated",
        version_deprecated="0.53",
        suggestion="Use layerrule v2 syntax: layerrule = <rule>, <match>",
    ),
    # Deprecated decoration options moved under decoration:blur
    *[
        _DeprecationRule(
            key=f"decoration:blur_{opt}",
            message=f"blur_{opt} moved to decoration:blur subsection",
            version_deprecated="0.40",
            suggestion=f"Use decoration:blur:{opt} instead",
        )
        for opt in BLUR_OPTIONS
    ],
    # v0.40+: deprecated general options
    _DeprecationRule(
        key="general:max_fps",
        message="max_fps was removed from general",
        version_deprecated="0.40",
        version_removed="0.40",
        suggestion="Remove this option — FPS is handled by the monitor refresh rate",
    ),
    _DeprecationRule(
        key="general:sensitivity",
        message="sensitivity moved to input section",
        version_deprecated="0.40",
        suggestion="Use input:sensitivity instead",
    ),
    # v0.46: deprecated misc options
    _DeprecationRule(
        key="misc:no_vfr",
        message="no_vfr was removed",
        version_deprecated="0.40",
        version_removed="0.46",
        suggestion="Use misc:vfr = true instead (note: inverted logic)",
    ),
    # v0.48+: deprecated animation names
    _DeprecationRule(
        key="animation",
        value_pattern=r"^fade_",
        message="fade_ prefixed animation names are deprecated",
        version_deprecated="0.48",
        suggestion=(
            "Use fadeIn, fadeOut, fadeSwitch, fadeShadow, fadeDim, fadeLayersIn, fadeLayersOut"
        ),
    ),
    # v0.55: pseudotile removed (was a no-op)
    _DeprecationRule(
        key="dwindle:pseudotile",
        message="pseudotile was removed (it wasn't doing anything)",
        version_deprecated="0.55",
        version_removed="0.55",
        suggestion="Remove this option",
    ),
    # v0.55: vfr moved from misc to debug
    _DeprecationRule(
        key="misc:vfr",
        message="vfr was moved to the debug section",
        version_deprecated="0.55",
        suggestion="Use debug:vfr instead",
    ),
    # v0.55: cm_fs_passthrough removed (now automatic with cm_auto_hdr)
    _DeprecationRule(
        key="render:cm_fs_passthrough",
        message="cm_fs_passthrough was removed",
        version_deprecated="0.55",
        version_removed="0.55",
        suggestion="Remove this option — it is now automatic with render:cm_auto_hdr",
    ),
    # v0.55: shadow:ignore_window removed (always enabled now)
    _DeprecationRule(
        key="decoration:shadow:ignore_window",
        message="shadow:ignore_window was removed (always enabled now)",
        version_deprecated="0.55",
        version_removed="0.55",
        suggestion="Remove this option",
    ),
    # v0.55: togglesplit/swapsplit/splitratio moved to layoutmsg
    *[
        _DeprecationRule(
            key_pattern=r"bind\w*",
            value_pattern=rf"^[^,]+,\s*[^,]+,\s*{dispatcher}\b",
            message=f"{dispatcher} dispatcher was moved to layoutmsg",
            version_deprecated="0.55",
            suggestion=f"Use layoutmsg, {dispatcher} instead",
        )
        for dispatcher in ("togglesplit", "swapsplit", "splitratio")
    ],
]


def check_deprecated(
    doc: Document,
    *,
    min_version: str | None = None,
    hyprland_version: str | None = None,
    recursive: bool | None = None,
) -> list[ConfigDeprecation]:
    """Check a document for deprecated config patterns.

    Returns a list of ``ConfigDeprecation`` objects describing deprecated
    syntax found in the document.

    Parameters
    ----------
    doc:
        The parsed document to check.
    min_version:
        Only report deprecations from this version onward.  For example,
        ``min_version="0.48"`` will skip rules deprecated before v0.48.
    hyprland_version:
        The Hyprland version the user is running.  Rules whose
        ``version_deprecated`` is newer than this are skipped — those
        deprecations haven't taken effect yet for that user.  For example,
        on Hyprland 0.49 the v0.53 ``windowrulev2`` rename is not yet a
        deprecation, so it should not be reported.
    recursive:
        Whether to check sourced sub-documents.  Defaults to the
        document's ``sources_followed`` flag.
    """
    warnings: list[ConfigDeprecation] = []
    min_ver = parse_version(min_version) if min_version is not None else None
    hypr_ver = parse_version(hyprland_version) if hyprland_version is not None else None

    for _owner_doc, line in doc.iter_lines(recursive):
        for rule in _RULES:
            if min_ver is not None and rule.deprecated_ver < min_ver:
                continue
            if hypr_ver is not None and rule.deprecated_ver > hypr_ver:
                continue
            if _rule_matches(rule, line):
                warnings.append(
                    ConfigDeprecation(
                        key=_line_key(line),
                        message=rule.message,
                        version_deprecated=rule.version_deprecated,
                        version_removed=rule.version_removed,
                        suggestion=rule.suggestion,
                        lineno=line.lineno,
                        source_name=line.source_name,
                    )
                )
    return warnings


def _line_key(line: Line) -> str:
    """Extract the key identifier from a line node."""
    if isinstance(line, KeyValueLine):
        return line.full_key
    return line.raw.strip()


def _rule_matches(rule: _DeprecationRule, line: Line) -> bool:
    """Check if a deprecation rule matches a line."""
    if not isinstance(line, KeyValueLine):
        return False
    if rule.key:
        if line.full_key != rule.key and line.key != rule.key:
            return False
    elif rule.key_re is not None:
        if not rule.key_re.fullmatch(line.key):
            return False
    else:
        return False
    if rule.value_re is not None:
        return bool(rule.value_re.search(line.value))
    return True
