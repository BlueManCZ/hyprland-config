"""Hyprland 0.48/0.53 windowrule v1↔v2↔v3 transforms.

This module is split out from :mod:`._runner` because the v2→v3
migration alone is several hundred lines of regex- and string-shape
gymnastics. Public surface is the two transform functions that
:mod:`._runner` registers in its ``_MIGRATIONS`` list, plus
:func:`normalize_rules` which canonicalises window/layer rule lines
into structured :class:`Rule` nodes regardless of source shape
(single-line ``windowrule = …`` or block-form ``windowrule { … }``).
"""

import re

from hyprland_config._core._model import (
    Assignment,
    Document,
    KeyValueLine,
    Keyword,
    Line,
    Rule,
    SectionClose,
    SectionOpen,
)
from hyprland_config._core._rule_split import split_top_level
from hyprland_config._core._rules import (
    V2_EFFECT_REPLACEMENTS,
    V2_TO_V3_EFFECT,
    V2_TO_V3_MATCHER,
    V3_BOOL_EFFECTS,
)
from hyprland_config._core._values import parse_hyprlang_bool
from hyprland_config._migrate._helpers import transform_lines

_V2_PREFIXES = ("title:", "class:", "xwayland:", "floating:", "fullscreen:")

# Every known v2 matcher key. Used by :func:`_split_v2_matchers` to
# distinguish inter-matcher whitespace from spaces inside regex values.
_V2_MATCHER_KEYS: frozenset[str] = (
    frozenset(V2_TO_V3_MATCHER)
    | frozenset(p.rstrip(":") for p in _V2_PREFIXES)
    | frozenset({"workspace", "tag", "focus"})
)

_V2_KEY_SPLIT_RE: re.Pattern[str] = re.compile(
    r"[\s,]+(?=~?(?:" + "|".join(sorted(_V2_MATCHER_KEYS, key=len, reverse=True)) + r"):)"
)


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

# Full set of known v3 effect names. Used by the corruption-recovery
# heuristic in :func:`_uncorrupt_v3_pretending_to_be_v2` to decide
# whether a token after ``title:`` is a real v3 effect (signalling
# corrupted output from buggy older migrations) vs. a legitimate
# v2 ``title:<regex>`` matcher.
_V3_EFFECT_NAMES: frozenset[str] = V3_BOOL_EFFECTS | frozenset(
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

    v2 accepted commas and whitespace as separators. We split on commas
    unconditionally, and on whitespace only when it precedes a known v2
    matcher key — this preserves spaces inside regex values like
    ``title:^(My App)$``.
    """
    result: list[str] = []
    for comma_tok in raw.split(","):
        for sub_tok in _V2_KEY_SPLIT_RE.split(comma_tok.strip()):
            sub_tok = sub_tok.strip()
            if sub_tok:
                result.append(sub_tok)
    return result


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

    # Some v2 effects were removed entirely and replaced by a
    # different effect with fixed args (e.g. noborder → border_size 0).
    if action_name in V2_EFFECT_REPLACEMENTS:
        new_name, args = V2_EFFECT_REPLACEMENTS[action_name]
    else:
        new_name = V2_TO_V3_EFFECT.get(action_name, action_name)
        args = action_args.strip()
        # Boolean effects in v2 had no args; in v3 they require ``on``.
        if not args and new_name in V3_BOOL_EFFECTS:
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
        new_key = V2_TO_V3_MATCHER.get(key.strip(), key.strip())
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


def migrate_windowrule_v2_to_v3(doc: Document) -> bool:
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

    return transform_lines(doc, predicate, transform)


def migrate_windowrule_v1_to_v2(doc: Document) -> bool:
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

    return transform_lines(doc, predicate, transform)


# ---------------------------------------------------------------------------
# Structured Rule normalisation
# ---------------------------------------------------------------------------
#
# Hyprland accepts windowrule / layerrule in two source shapes:
#
#     windowrule = match:class ^(firefox)$, float on            # single-line
#
#     windowrule {                                              # block form
#         name        = my-rule
#         match:class = ^(firefox)$
#         border_size = 10
#         no_blur     = on
#     }
#
# Both are recognised by Hyprland (the latter via the ``addSpecialCategory``
# registration in ConfigManager.cpp keyed on ``name``). Block form is the
# only way to express a named or disabled rule and the only way to bundle
# multiple effects under one logical entry.
#
# This normaliser collapses both shapes into a single :class:`Rule` node so
# downstream consumers (hyprmod, the Lua emitter) iterate structured fields
# (name, enabled, matchers, effects) instead of re-parsing strings. The
# language-specific serializers in :mod:`hyprland_config._hyprlang._serializer`
# and :mod:`hyprland_config._lua._emit` render Rule back to whichever shape
# fits — Hyprlang picks block-form when name/disabled/multi-effect demand it,
# Lua always emits ``hl.window_rule({ … })`` / ``hl.layer_rule({ … })``.

_RULE_KEYWORDS = frozenset({"windowrule", "layerrule"})


def _section_close_index(lines: list[Line], start: int) -> int | None:
    """Return the index of the SectionClose matching ``lines[start]``
    (a SectionOpen), tracking nested opens. ``None`` if the document is
    malformed (unclosed block at EOF).
    """
    depth = 1
    for i in range(start + 1, len(lines)):
        node = lines[i]
        if isinstance(node, SectionOpen):
            depth += 1
        elif isinstance(node, SectionClose):
            depth -= 1
            if depth == 0:
                return i
    return None


def _collect_block_fields(
    body: list[Line],
) -> tuple[str | None, list[tuple[str, str]], list[tuple[str, str]], bool]:
    """Extract (name, matchers, effects, enabled) from a block body."""
    name: str | None = None
    enabled = True
    matchers: list[tuple[str, str]] = []
    effects: list[tuple[str, str]] = []
    for node in body:
        if not isinstance(node, Assignment):
            continue
        key = node.key.strip()
        value = node.value.strip()
        if key == "name":
            name = value
        elif key == "enable":
            # Default to enabled unless the value is an unambiguous "false" word.
            enabled = parse_hyprlang_bool(value) is not False
        elif key.startswith("match:"):
            matchers.append((key[len("match:") :].strip(), value))
        elif key:
            effects.append((key, value))
    return name, matchers, effects, enabled


def _parse_single_line_body(
    body: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Tokenise a v3 single-line rule body into (matchers, effects).

    Single-line rules carry no name or enable flag — Hyprland's
    handler rejects those tokens — so this returns only the matcher
    and effect pairs. Bool effects without an explicit value (``float``
    on its own) get ``"on"`` filled in to match Hyprland 0.53+ requirements.
    """
    matchers: list[tuple[str, str]] = []
    effects: list[tuple[str, str]] = []
    for token in split_top_level(body):
        stripped = token.strip()
        if not stripped:
            continue
        if stripped.startswith("match:"):
            rest = stripped[len("match:") :]
            key, _, value = rest.partition(" ")
            matchers.append((key.strip(), value.strip()))
            continue
        name, _, args = stripped.partition(" ")
        name = name.strip()
        args = args.strip()
        if not name:
            continue
        if not args and name in V3_BOOL_EFFECTS:
            args = "on"
        effects.append((name, args))
    return matchers, effects


def _rule_from_keyword(kw: Keyword) -> Rule | None:
    """Build a Rule from a single-line ``windowrule = …`` / ``layerrule = …``
    Keyword. Returns ``None`` when:

    - the body has no effects (Hyprland rejects effectless rules), or
    - the body has no ``match:`` token (legacy v1 / malformed v2 input
      that the version migrations declined to touch — leaving the Keyword
      verbatim is safer than guessing what the author meant).

    Preserving the original Keyword in those cases means downstream
    tooling can still surface the line as-is.
    """
    if "match:" not in kw.value:
        return None
    matchers, effects = _parse_single_line_body(kw.value)
    if not effects:
        return None
    return Rule(
        raw=kw.raw,
        lineno=kw.lineno,
        source_name=kw.source_name,
        kind=kw.key,
        matchers=matchers,
        effects=effects,
    )


def _rule_from_block(
    section_open: SectionOpen,
    body: list[Line],
) -> Rule | None:
    """Build a Rule from a ``windowrule { … }`` / ``layerrule { … }`` block.

    Falls back to ``None`` when the block has no effects — same reasoning
    as :func:`_rule_from_keyword`, plus the original SectionOpen/Assign/
    SectionClose triplet is preserved verbatim by the caller so user-
    authored content isn't silently dropped.
    """
    name, matchers, effects, enabled = _collect_block_fields(body)
    if name is None and section_open.section_key:
        # ``windowrule[my-name] { … }`` form: section key carries the name.
        name = section_open.section_key
    if not effects:
        return None
    return Rule(
        raw=section_open.raw,
        lineno=section_open.lineno,
        source_name=section_open.source_name,
        kind=section_open.name,
        name=name or "",
        enabled=enabled,
        matchers=matchers,
        effects=effects,
    )


def normalize_rules(doc: Document) -> bool:
    """Canonicalise windowrule / layerrule lines into :class:`Rule` nodes.

    Both authored shapes — single-line ``windowrule = match:K V, EFFECT
    ARGS`` and the block form ``windowrule { name = …; match:K = V; …}``
    — collapse to a single Rule per logical entry. Downstream consumers
    work with the structured fields instead of re-parsing the value
    string, and the language-specific serializers pick the right output
    shape (block vs. single-line in Hyprlang, ``hl.window_rule({…})`` in
    Lua) based on the Rule's contents.

    Operates on a single document; the :func:`migrate` runner walks
    sourced sub-documents itself. Returns True if any node was rewritten.
    """
    new_lines: list[Line] = []
    changed = False
    i = 0
    while i < len(doc.lines):
        node = doc.lines[i]

        if isinstance(node, SectionOpen) and node.name in _RULE_KEYWORDS:
            close_idx = _section_close_index(doc.lines, i)
            if close_idx is None:
                # Malformed (unclosed at EOF) — preserve verbatim for
                # lenient callers to surface as-is.
                new_lines.append(node)
                i += 1
                continue
            body = doc.lines[i + 1 : close_idx]
            rule = _rule_from_block(node, body)
            if rule is not None:
                new_lines.append(rule)
                changed = True
            else:
                # Effectless block — keep the original lines so user
                # content isn't silently deleted.
                new_lines.extend(doc.lines[i : close_idx + 1])
            i = close_idx + 1
            continue

        if isinstance(node, Keyword) and node.key in _RULE_KEYWORDS:
            rule = _rule_from_keyword(node)
            if rule is not None:
                new_lines.append(rule)
                changed = True
            else:
                new_lines.append(node)
            i += 1
            continue

        new_lines.append(node)
        i += 1

    if changed:
        doc.lines = new_lines
        doc.mark_dirty()
    return changed
