"""Rule emitters — ``windowrule`` / ``windowrulev2`` / ``layerrule`` / ``workspace``.

Both line-style (``windowrule = float on, match:class …``) and block-style
(``windowrule { match:class = …; float = on; }``) syntaxes are supported.
Line-style assembly happens here; block-style buffer collection lives in
the document walker because it spans multiple input lines.
"""

from typing import Any

from hyprland_config._core._rule_split import split_top_level
from hyprland_config._core._values import parse_hyprlang_bool
from hyprland_config._lua._emit._format import (
    coerce_value,
    format_table,
    has_var_marker,
    split_csv,
    to_lua_expr,
)
from hyprland_config._lua._workspace_rules import (
    LAYOUTOPT_HYPRLANG_NAME,
    LAYOUTOPT_LUA_NAME,
    hyprlang_field_to_lua,
    parse_layoutopt,
)


def add_block_rule_field(buffer: dict[str, Any], key: str, value: str) -> None:
    """Add one field from a ``windowrule { … }``-style block to its buffer.

    ``match:PROP = VALUE`` lines build up a nested ``match = {…}`` table;
    everything else lives at the top of the rule. Values pass through the
    same :func:`coerce_value` coercion as line-style rules, so ``float = on``
    → ``true`` while a numeric ``opacity = 1`` stays ``1``.

    The Hyprlang block-form ``enable`` field is renamed to ``enabled`` on
    the way out — Hyprland's Lua ``hl.window_rule`` / ``hl.layer_rule``
    use the longer spelling and reject ``enable`` as an unknown field;
    the integer ``0`` / ``1`` value also flips to ``true`` / ``false``.
    """
    if key.startswith("match:"):
        prop = key[len("match:") :]
        match = buffer.setdefault("match", {})
        if isinstance(match, dict):
            match[prop] = coerce_value(value)
        return
    if key == "enable":
        # Anything we can't read as a bool is treated as enabled — same
        # permissive default Hyprland uses for malformed block fields.
        buffer["enabled"] = parse_hyprlang_bool(value) is not False
        return
    buffer[key] = coerce_value(value)


def _parse_rule_action(action: str) -> tuple[str, Any]:
    """Split a rule action like ``opacity 0.9`` into ``(name, value)``.

    Hyprland's modern (v3) windowrule syntax uses ``ACTION VALUE`` for both
    bool flags (``float on`` / ``pin off``) and valued actions (``opacity 0.9``,
    ``bordercolor rgba(…)``, ``suppress_event maximize``). Legacy v1 just has
    a bare flag (``float``).
    """
    head, sep, tail = action.partition(" ")
    head = head.strip()
    tail = tail.strip()
    if not sep:
        return head, True
    low = tail.lower()
    if low == "on":
        return head, True
    if low == "off":
        return head, False
    return head, coerce_value(tail)


def _parse_matchers(parts: list[str], v2: bool) -> dict[str, Any]:
    """Build a ``match = { … }`` table from windowrule matcher tokens.

    Supports all three windowrule syntaxes that may appear in user configs:

    - Modern v3 (Hyprland 0.53+, keyword ``windowrule``):
      ``match:class ^kitty$``, ``match:title bar`` — explicit ``match:`` prefix,
      key/value split on first space.
    - Legacy v2 (keyword ``windowrulev2``): ``class:^kitty$``, ``title:bar`` —
      key:value tokens without the ``match:`` prefix.
    - Legacy v1 (keyword ``windowrule`` without ``match:`` tokens):
      single bare token treated as a class regex.

    Selection is by presence: if any token starts with ``match:``, the whole
    list is parsed in v3 mode, otherwise we fall back to v2 (when the caller
    flagged it) or v1.
    """
    match: dict[str, Any] = {}
    if not parts:
        return match

    if any(p.startswith("match:") for p in parts):
        for token in parts:
            if not token.startswith("match:"):
                continue
            rest = token[len("match:") :]
            key, _, value = rest.partition(" ")
            match[key.strip()] = coerce_value(value.strip())
        return match

    # Legacy v1/v2 share the ``KEY:VALUE`` matcher syntax — try that first.
    for token in parts:
        key, sep, value = token.partition(":")
        if sep:
            match[key.strip()] = coerce_value(value.strip())
    if match:
        return match

    # Truly legacy v1 (``windowrule = float, ^firefox$``) — a single bare
    # regex matches the window class.
    if not v2:
        match["class"] = parts[0]
    return match


def _split_action_and_matchers(parts: list[str]) -> tuple[str, list[str]] | None:
    """Find the action token and return it alongside the remaining matchers.

    Both orders show up in real configs — effect-first (``stay_focused on,
    match:title …``) and match-first (``match:title …, stay_focused on``).
    We figure it out by the ``match:`` prefix: anything with it is a matcher,
    the lone token without it is the action. Without any ``match:`` prefix
    we fall back to legacy v1/v2 (first token is the action).
    """
    if not parts:
        return None

    if any(p.startswith("match:") for p in parts):
        action_tokens = [p for p in parts if not p.startswith("match:")]
        matcher_tokens = [p for p in parts if p.startswith("match:")]
        if not action_tokens:
            return None
        return action_tokens[0], matcher_tokens

    return parts[0], parts[1:]


def emit_windowrule(args: str, *, v2: bool) -> str:
    """Shared implementation for ``windowrule`` and ``windowrulev2``.

    Handles raw Hyprlang single-line input — ``windowrule = match:K V,
    EFFECT [ARGS]`` and the v1 / v2 legacy shapes. Block-form rules
    (named, disabled, anything with structure that doesn't fit a
    single line) are normalised to :class:`Rule` nodes by
    :func:`hyprland_config.migrate` and emitted via the walker's
    structured-rule path; they never reach this single-line emitter.
    """
    # Bracket-aware split: regex matchers like ``class:^(foo|bar,baz)$`` carry
    # commas inside parens that a naive ``str.split(",")`` would mangle.
    parts = split_top_level(args)
    split = _split_action_and_matchers(parts)
    if split is None:
        return f"-- malformed windowrule: {args}"
    action_str, matcher_tokens = split
    action_name, action_value = _parse_rule_action(action_str)
    matchers = _parse_matchers(matcher_tokens, v2=v2)
    table: dict[str, Any] = {}
    if matchers:
        table["match"] = matchers
    table[action_name] = action_value
    return f"hl.window_rule({format_table(table, indent=0)})"


def emit_layerrule(args: str) -> str:
    """``layerrule = match:namespace REGEX, EFFECT VALUE`` → ``hl.layer_rule({...})``.

    Accepts both the modern ``match:namespace …, effect …`` form and the
    legacy ``effect, REGEX`` shape. The legacy form treats the second
    token as the namespace regex when no ``match:`` prefix is present
    anywhere. Block-form layer rules are emitted via the structured
    Rule path (same as windowrules — see :func:`emit_windowrule`).
    """
    # Bracket-aware split — see emit_windowrule for the regex-matcher case.
    parts = split_top_level(args)
    split = _split_action_and_matchers(parts)
    if split is None:
        return f"-- malformed layerrule: {args}"
    action_str, matcher_tokens = split
    action_name, action_value = _parse_rule_action(action_str)

    if matcher_tokens and any(t.startswith("match:") for t in matcher_tokens):
        matchers = _parse_matchers(matcher_tokens, v2=False)
    elif matcher_tokens:
        # Legacy: a single bare regex matches the layer namespace.
        matchers = {"namespace": matcher_tokens[0]}
    else:
        matchers = {}

    table: dict[str, Any] = {}
    if matchers:
        table["match"] = matchers
    table[action_name] = action_value
    return f"hl.layer_rule({format_table(table, indent=0)})"


def emit_workspace_rule(args: str) -> str:
    """``workspace = ID, monitor:DP-1, default:true, ...`` → ``hl.workspace_rule({...})``.

    The first token identifies the workspace selector; the rest are
    ``key:value`` rule fields (``monitor``, ``default``, ``persistent``,
    ``gapsin``, …).

    Field names and three boolean senses differ between the forms (e.g.
    Hyprlang ``border:false`` ↔ Lua ``no_border = true``);
    :func:`hyprlang_field_to_lua` carries the catalogue. Multi-value
    gaps (``gapsout:5 10 5 10``) become 4-key Lua tables. Unknown
    fields pass through unchanged so plugin / future-Hyprland properties
    don't get silently dropped.
    """
    parts = split_csv(args)
    if not parts:
        return f"-- malformed workspace: {args}"
    # The selector stays a string even when numeric: ``hl.workspace_rule``
    # declares ``workspace`` as a string field (hl.meta.lua), and an integer
    # only works through Lua's implicit number→string coercion.
    selector = parts[0].strip()
    table: dict[str, Any] = {
        "workspace": to_lua_expr(selector) if has_var_marker(selector) else selector
    }
    for token in parts[1:]:
        key, sep, value = token.partition(":")
        if not sep:
            continue
        if key.strip() == LAYOUTOPT_HYPRLANG_NAME:
            opt = parse_layoutopt(value.strip())
            if opt is not None:
                opt_key, opt_value = opt
                table.setdefault(LAYOUTOPT_LUA_NAME, {})[opt_key] = opt_value
            continue
        lua_name, lua_value = hyprlang_field_to_lua(key.strip(), value.strip())
        table[lua_name] = lua_value
    return f"hl.workspace_rule({format_table(table, indent=0)})"
