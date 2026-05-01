"""Deprecation checking and migration helpers for Hyprland config files.

Tracks known breaking changes across Hyprland versions so tools can warn
users about deprecated syntax or automatically migrate configs.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from hyprland_config._model import Comment, Document, KeyValueLine, Line


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

    # What to match — either a key pattern or a callable check
    key: str = ""
    line_pattern: str = ""  # regex pattern for raw line matching (e.g. comment syntax)
    value_pattern: str = ""  # regex pattern for value matching

    # Metadata
    message: str = ""
    version_deprecated: str = ""
    version_removed: str = ""
    suggestion: str = ""

    # Precomputed for fast comparison in hot loop
    _deprecated_ver: tuple[int, ...] = field(init=False, repr=False)
    _line_re: re.Pattern[str] | None = field(init=False, repr=False)
    _value_re: re.Pattern[str] | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._deprecated_ver = _version_tuple(self.version_deprecated)
        self._line_re = re.compile(self.line_pattern) if self.line_pattern else None
        self._value_re = re.compile(self.value_pattern) if self.value_pattern else None


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse a version string like '0.48' into a comparable tuple."""
    return tuple(int(x) for x in version.split("."))


# Blur options that moved from decoration:blur_* to decoration:blur:*
_BLUR_OPTIONS = ("size", "passes", "new_optimizations", "ignore_opacity")

# ── Known Deprecation Rules ─────────────────────────────────────────
#
# Sourced from Hyprland changelogs and migration guides.

_RULES: list[_DeprecationRule] = [
    # v0.37: old comment syntax "#!" removed
    _DeprecationRule(
        line_pattern=r"^#!.*",
        message="The #! comment syntax was removed",
        version_deprecated="0.36",
        version_removed="0.37",
        suggestion="Use plain # comments instead",
    ),
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
    # v0.48: windowrule (v1) deprecated in favour of windowrulev2
    _DeprecationRule(
        key="windowrule",
        message="windowrule (v1) is deprecated",
        version_deprecated="0.48",
        suggestion="Use windowrulev2 with explicit matching: windowrulev2 = <rule>, <match>",
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
        for opt in _BLUR_OPTIONS
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
    # v0.45: deprecated input options
    _DeprecationRule(
        key="input:numlock_by_default",
        message="numlock_by_default was renamed",
        version_deprecated="0.45",
        suggestion="Use input:kb_numlock instead",
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
]


def check_deprecated(
    doc: Document,
    *,
    min_version: str | None = None,
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
    recursive:
        Whether to check sourced sub-documents.  Defaults to the
        document's ``sources_followed`` flag.
    """
    warnings: list[ConfigDeprecation] = []
    min_ver = _version_tuple(min_version) if min_version is not None else None

    for _owner_doc, line in doc.iter_lines(recursive):
        for rule in _RULES:
            if min_ver is not None and rule._deprecated_ver < min_ver:
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
    # Raw line pattern match (for comment-based rules like #!)
    if rule._line_re is not None:
        if not isinstance(line, Comment):
            return False
        return bool(rule._line_re.match(line.raw.strip()))

    # Exact key match
    if rule.key and isinstance(line, KeyValueLine):
        if line.full_key != rule.key and line.key != rule.key:
            return False
        # Optional value pattern check
        if rule._value_re is not None:
            return bool(rule._value_re.search(line.value))
        return True

    return False


# ── Simple Migration Transforms ──────────────────────────────────────


@dataclass
class MigrationResult:
    """Result of a migration operation."""

    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def changes_made(self) -> bool:
        return bool(self.applied)


@dataclass
class _Migration:
    description: str
    from_version: str
    to_version: str
    transform: Callable[[Document], bool]

    _from_ver: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._from_ver = _version_tuple(self.from_version)


def _transform_lines(
    doc: Document,
    predicate: Callable[[KeyValueLine], bool],
    transform: Callable[[KeyValueLine], None],
) -> bool:
    """Apply a transform to matching key-value lines. Returns True if any changed."""
    changed = False
    for line in doc.lines:
        if isinstance(line, KeyValueLine) and predicate(line):
            transform(line)
            changed = True
    if changed:
        doc.mark_dirty()
    return changed


def _rewrite_line_key(line: KeyValueLine, new_full_key: str) -> None:
    """Rewrite ``line`` to use ``new_full_key``, preserving flat-vs-sectioned syntax.

    The parser exposes two shapes:

    - Flat colon syntax (e.g. ``decoration:blur:size = 8`` at top level):
      ``line.key == line.full_key`` — the whole colon path is written inline.
    - Sectioned syntax (inside ``decoration { blur { size = 8 } }``):
      ``line.key`` is the leaf ``size`` while ``line.full_key`` is the full path.

    Migrations must preserve whichever shape the line already has — otherwise
    a flat ``decoration:blur_size = 8`` line rewrites as ``size = 8``, losing
    its section context.
    """
    is_flat = line.key == line.full_key
    line.full_key = new_full_key
    new_leaf = new_full_key.rsplit(":", 1)[-1]
    line.key = new_full_key if is_flat else new_leaf
    line.update_raw()


def _migrate_blur_options(doc: Document) -> bool:
    """Move decoration:blur_* options to decoration:blur:* subsection."""
    renames = {f"decoration:blur_{opt}": f"decoration:blur:{opt}" for opt in _BLUR_OPTIONS}

    def transform(line: KeyValueLine) -> None:
        _rewrite_line_key(line, renames[line.full_key])

    return _transform_lines(doc, lambda ln: ln.full_key in renames, transform)


_V2_PREFIXES = ("title:", "class:", "xwayland:", "floating:", "fullscreen:")


# ---------------------------------------------------------------------------
# v2 → v3 windowrule migration (Hyprland 0.52 → 0.53)
# ---------------------------------------------------------------------------
#
# Hyprland 0.53 introduced a new single-line windowrule syntax::
#
#     windowrule = match:class ^(firefox)$, float on
#
# replacing the v2 form::
#
#     windowrulev2 = float, class:^(firefox)$
#
# Key differences this migration handles:
#
# - Keyword renames from ``windowrulev2`` back to ``windowrule``.
# - Matcher tokens move from ``key:value`` to ``match:KEY VALUE`` —
#   note the space, not a colon, between key and value.
# - Boolean effects (``float``, ``pin``, ``no_blur``, …) require an
#   explicit ``on`` argument; v2 allowed them bare.
# - Several effects and matchers were renamed (``noblur`` → ``no_blur``,
#   ``initialClass`` → ``initial_class``, etc.).
# - Negation moved from a leading ``~`` on the matcher to a
#   ``negative:`` prefix on the value.

# v3 effects whose only argument is a boolean. We always emit ``on``
# for these — Hyprland 0.53+ rejects bare boolean effects.
_V3_BOOL_EFFECTS: frozenset[str] = frozenset(
    {
        # Static
        "float", "tile", "fullscreen", "maximize", "center", "pseudo",
        "no_initial_focus", "pin",
        # Dynamic
        "persistent_size", "no_max_size", "stay_focused",
        "allows_input", "dim_around", "decorate", "focus_on_activate",
        "keep_aspect_ratio", "nearest_neighbor",
        "no_anim", "no_blur", "no_dim", "no_focus", "no_follow_mouse",
        "no_shadow", "no_shortcuts_inhibit", "no_screen_share", "no_vrr",
        "opaque", "force_rgbx", "sync_fullscreen", "immediate", "xray",
        "render_unfocused",
    }
)  # fmt: skip


# v2 → v3 effect renames. Anything not in this dict is assumed to be
# the same name in v3 (including custom plugin actions).
_V2_TO_V3_EFFECT: dict[str, str] = {
    "noblur": "no_blur",
    "noshadow": "no_shadow",
    "noborder": "no_border",
    "noanim": "no_anim",
    "nodim": "no_dim",
    "nofocus": "no_focus",
    "noinitialfocus": "no_initial_focus",
    "nofollowmouse": "no_follow_mouse",
    "noshortcutsinhibit": "no_shortcuts_inhibit",
    "noscreenshare": "no_screen_share",
    "novrr": "no_vrr",
    "norounding": "no_rounding",
    "nomaxsize": "no_max_size",
    "stayfocused": "stay_focused",
    "idleinhibit": "idle_inhibit",
    "bordercolor": "border_color",
    "bordersize": "border_size",
    "maxsize": "max_size",
    "minsize": "min_size",
    "suppressevent": "suppress_event",
    "noclosefor": "no_close_for",
    "syncfullscreen": "sync_fullscreen",
    "forcergbx": "force_rgbx",
    "focusonactivate": "focus_on_activate",
    "keepaspectratio": "keep_aspect_ratio",
    "nearestneighbor": "nearest_neighbor",
    "renderunfocused": "render_unfocused",
    "scrollmouse": "scroll_mouse",
    "scrolltouchpad": "scroll_touchpad",
    "scrollingwidth": "scrolling_width",
    "allowsinput": "allows_input",
    "dimaround": "dim_around",
    "persistentsize": "persistent_size",
    "fullscreenstate": "fullscreen_state",
    "roundingpower": "rounding_power",
}


# v2 → v3 matcher key renames. Note ``floating`` → ``float`` and
# ``pinned`` → ``pin``: in v3 the matcher key is the same word as the
# corresponding effect, which matches the wiki.
_V2_TO_V3_MATCHER: dict[str, str] = {
    "initialClass": "initial_class",
    "initialTitle": "initial_title",
    "floating": "float",
    "pinned": "pin",
    "xdgtag": "xdg_tag",
    # ``onworkspace`` collapsed into ``workspace`` in v3.
    "onworkspace": "workspace",
    "fullscreenstate": "fullscreen_state",
}


# Full set of known v3 effect names. Used by the corruption-recovery
# heuristic in :func:`_uncorrupt_v3_pretending_to_be_v2` to decide
# whether a token after ``title:`` is a real v3 effect (signalling
# corrupted output from buggy older migrations) vs. a legitimate
# v2 ``title:<regex>`` matcher.
_V3_EFFECT_NAMES: frozenset[str] = _V3_BOOL_EFFECTS | frozenset(
    {
        "opacity", "size", "move", "workspace", "monitor", "rounding",
        "rounding_power", "border_color", "border_size", "min_size",
        "max_size", "idle_inhibit", "animation", "scroll_mouse",
        "scroll_touchpad", "suppress_event", "tag", "xdg_tag",
        "no_close_for", "fullscreen_state", "scrolling_width",
    }
)  # fmt: skip


def _split_v2_matchers(raw: str) -> list[str]:
    """Split a v2 matcher string into per-matcher tokens.

    v2 accepted commas and whitespace as separators.
    """
    tokens: list[str] = []
    for chunk in raw.split(","):
        for tok in chunk.split():
            if tok:
                tokens.append(tok)
    return tokens


def _v2_body_to_v3(body: str) -> str:
    """Translate a v2 windowrule body string to its v3 equivalent.

    Input: ``ACTION, MATCHERS`` where MATCHERS are ``key:value``
    tokens space- or comma-separated.

    Output: ``match:KEY VALUE, …, EFFECT [args]`` with the effect
    coming last (the v3 conventional order).

    Pure string-to-string transformation — no Document mutation, no
    side effects.
    """
    action_part, _, matcher_part = body.partition(",")
    action = action_part.strip()
    if not action:
        return body  # malformed; leave alone

    # Split the action into name + args (e.g. "size 1920 1080").
    action_name, _, action_args = action.partition(" ")
    new_name = _V2_TO_V3_EFFECT.get(action_name, action_name)
    args = action_args.strip()
    # Boolean effects in v2 had no args; in v3 they require ``on``.
    if not args and new_name in _V3_BOOL_EFFECTS:
        args = "on"
    effect = f"{new_name} {args}".strip() if args else new_name

    matcher_tokens: list[str] = []
    for tok in _split_v2_matchers(matcher_part):
        # v2 negation was ``~key:value`` — strip the ``~`` and prepend
        # ``negative:`` to the value, the v3 form.
        negated = tok.startswith("~")
        if negated:
            tok = tok[1:]
        key, sep, value = tok.partition(":")
        if not sep:
            # Unparseable token — preserve verbatim so nothing is lost.
            matcher_tokens.append(("~" if negated else "") + tok)
            continue
        new_key = _V2_TO_V3_MATCHER.get(key.strip(), key.strip())
        new_value = value.strip()
        if negated and new_value:
            new_value = f"negative:{new_value}"
        matcher_tokens.append(f"match:{new_key} {new_value}")

    return ", ".join([*matcher_tokens, effect])


def _uncorrupt_v3_pretending_to_be_v2(body: str) -> str | None:
    """Try to recover a v3 body from the ``hyprland-config<0.4.4`` corruption.

    Versions of this library before 0.4.4 had a v1→v2 windowrule
    migration that didn't recognise v3 syntax and incorrectly fired
    on v3 lines, producing output of the shape::

        windowrulev2 = <v3 matcher>, title:<v3 effect> <effect args>

    where the ``title:`` prefix and the keyword rename are bogus
    (the input was already valid v3). When we see a ``windowrulev2``
    line that contains a ``match:`` token (a v3 marker) AND a
    ``title:<known-effect>`` token, we strip the bogus ``title:``
    and return the cleaned body so the v3 parser can take over.

    Returns ``None`` if the line doesn't match the corruption pattern,
    in which case the caller should treat it as a regular v2 line.
    """
    # v3 marker: at least one comma-separated token starts with ``match:``.
    tokens = [t.strip() for t in body.split(",")]
    if not any(t.startswith("match:") for t in tokens):
        return None

    repaired: list[str] = []
    fixed_one = False
    for tok in tokens:
        if not fixed_one and tok.startswith("title:"):
            inner = tok[len("title:") :].strip()
            head, _, _ = inner.partition(" ")
            if head and head in _V3_EFFECT_NAMES:
                # Strip the bogus title:; the rest is the original
                # effect token.
                repaired.append(inner)
                fixed_one = True
                continue
        repaired.append(tok)

    if not fixed_one:
        return None
    return ", ".join(repaired)


def _migrate_windowrule_v2_to_v3(doc: Document) -> bool:
    """Convert ``windowrulev2`` (v2) lines to ``windowrule`` (v3) syntax.

    Handles two cases that share the keyword:

    1. **Real v2 lines** (``windowrulev2 = float, class:^(firefox)$``)
       are translated to v3 (``windowrule = match:class ^(firefox)$,
       float on``) via :func:`_v2_body_to_v3`.
    2. **Corrupted-v3 lines** — output of a buggy older v1→v2
       migration that wrapped v3 syntax in v2 packaging — are
       recovered to their original v3 form via
       :func:`_uncorrupt_v3_pretending_to_be_v2`. The check fires
       only when the body contains a ``match:`` token (a v3 marker
       that real v2 never uses) plus a stray ``title:<v3 effect>``.
    """

    def predicate(line: KeyValueLine) -> bool:
        return line.key == "windowrulev2"

    def transform(line: KeyValueLine) -> None:
        recovered = _uncorrupt_v3_pretending_to_be_v2(line.value)
        new_value = recovered if recovered is not None else _v2_body_to_v3(line.value)
        line.key = "windowrule"
        line.full_key = line.full_key.replace("windowrulev2", "windowrule", 1)
        line.value = new_value
        line.update_raw()

    return _transform_lines(doc, predicate, transform)


def _migrate_windowrule_v1_to_v2(doc: Document) -> bool:
    """Convert windowrule (v1) to windowrulev2 syntax.

    Only triggers on lines that look unambiguously like v1 — the
    "rule, regex" two-part form with no v2/v3 prefixes anywhere. v3
    Hyprland 0.53+ reused the ``windowrule`` keyword for a different
    syntax (``windowrule = match:KEY VALUE, EFFECT VALUE``); we MUST
    NOT migrate v3 lines back to v2 form, because Hyprland 0.53+
    rejects v2 outright. v3 lines always carry at least one
    ``match:`` token, so the presence of ``match:`` anywhere in the
    value is a hard "this is not v1" signal.
    """

    def predicate(line: KeyValueLine) -> bool:
        if line.key != "windowrule":
            return False
        # v3 lines are recognised by the ``match:`` prefix on at
        # least one of their comma-separated tokens. Skip those —
        # migrating them as v1 would corrupt the line and produce
        # invalid v2 syntax that Hyprland 0.53+ rejects.
        if any(t.strip().startswith("match:") for t in line.value.split(",")):
            return False
        parts = line.value.split(",", 1)
        if len(parts) != 2:
            return False
        window = parts[1].strip()
        return not any(window.startswith(p) for p in _V2_PREFIXES)

    def transform(line: KeyValueLine) -> None:
        rule, window = (p.strip() for p in line.value.split(",", 1))
        line.key = "windowrulev2"
        line.full_key = line.full_key.replace("windowrule", "windowrulev2", 1)
        line.value = f"{rule}, title:{window}"
        line.update_raw()

    return _transform_lines(doc, predicate, transform)


def _make_rename_migration(
    old_full_key: str,
    new_full_key: str,
    *,
    match_by: Literal["full_key", "key"] = "full_key",
) -> Callable[[Document], bool]:
    """Build a migration that renames a key.

    *match_by* controls how lines are matched:
    - ``"full_key"`` (default): match on ``line.full_key == old_full_key``
    - ``"key"``: match on ``line.key == old_full_key`` (for top-level keywords)
    """

    def transform(line: KeyValueLine) -> None:
        # Rewrite the full_key via substring replacement so callers can pass
        # partial paths (e.g. the "key" match_by case) and still land on the
        # right target; then resync the raw form via _rewrite_line_key, which
        # preserves flat-colon vs. sectioned syntax.
        replaced_full_key = line.full_key.replace(old_full_key, new_full_key, 1)
        _rewrite_line_key(line, replaced_full_key)

    if match_by == "key":
        old_leaf = old_full_key.rsplit(":", 1)[-1]
        return lambda doc: _transform_lines(doc, lambda ln: ln.key == old_leaf, transform)
    return lambda doc: _transform_lines(doc, lambda ln: ln.full_key == old_full_key, transform)


# Sorted by from_version so migrate() can iterate directly.
_MIGRATIONS: list[_Migration] = sorted(
    [
        _Migration(
            "Rename exec_once → exec-once",
            "0.33",
            "0.34",
            _make_rename_migration("exec_once", "exec-once", match_by="key"),
        ),
        _Migration(
            "Move blur options to decoration:blur subsection",
            "0.39",
            "0.40",
            _migrate_blur_options,
        ),
        _Migration(
            "Rename no_cursor_warps → no_warps",
            "0.40",
            "0.41",
            _make_rename_migration("cursor:no_cursor_warps", "cursor:no_warps"),
        ),
        _Migration(
            "Rename numlock_by_default → kb_numlock",
            "0.44",
            "0.45",
            _make_rename_migration("input:numlock_by_default", "input:kb_numlock"),
        ),
        _Migration(
            "Move sensitivity from general to input",
            "0.39",
            "0.40",
            _make_rename_migration("general:sensitivity", "input:sensitivity"),
        ),
        _Migration(
            "Convert windowrule v1 → windowrulev2",
            "0.47",
            "0.48",
            _migrate_windowrule_v1_to_v2,
        ),
        _Migration(
            "Convert windowrulev2 → windowrule v3",
            "0.52",
            "0.53",
            _migrate_windowrule_v2_to_v3,
        ),
    ],
    key=lambda m: m._from_ver,
)


def migrate(
    doc: Document,
    *,
    from_version: str | None = None,
    to_version: str | None = None,
    recursive: bool | None = None,
) -> MigrationResult:
    """Apply known migration transforms to a document.

    Transforms are applied in version order.  Only migrations whose
    ``from_version`` falls within the ``[from_version, to_version)`` range
    are executed.

    Parameters
    ----------
    doc:
        The document to migrate **in place**.
    from_version:
        The Hyprland version the config was written for.  Migrations older
        than this are skipped.
    to_version:
        The target Hyprland version.  Migrations newer than this are
        skipped.  Defaults to the latest known version.
    recursive:
        Whether to migrate sourced sub-documents.  Defaults to the
        document's ``sources_followed`` flag.

    Returns
    -------
    MigrationResult:
        Lists of applied and skipped migration descriptions.
    """
    result = MigrationResult()
    from_ver = _version_tuple(from_version) if from_version is not None else None
    to_ver = _version_tuple(to_version) if to_version is not None else None

    for m in _MIGRATIONS:
        if from_ver is not None and m._from_ver < from_ver:
            continue
        if to_ver is not None and m._from_ver >= to_ver:
            continue
        applied = False
        for target_doc in doc.target_documents(recursive):
            if m.transform(target_doc):
                applied = True
        if applied:
            result.applied.append(m.description)
        else:
            result.skipped.append(m.description)

    return result
