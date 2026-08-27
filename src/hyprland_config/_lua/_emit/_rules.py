"""Rule emitters — ``windowrule`` / ``windowrulev2`` / ``layerrule`` / ``workspace``.

Both line-style (``windowrule = float on, match:class …``) and block-style
(``windowrule { match:class = …; float = on; }``) syntaxes are supported.
Line-style assembly happens here; block-style buffer collection lives in
the document walker because it spans multiple input lines.
"""

from typing import Any

from hyprland_config._core._model import Rule
from hyprland_config._core._rule_split import split_top_level
from hyprland_config._core._rules import (
    LAYER_BOOL_EFFECTS,
    V3_BOOL_EFFECTS,
    split_rule_body,
)
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


def _legacy_window_matchers(parts: list[str], v2: bool) -> list[tuple[str, str]]:
    """Read pre-v3 windowrule matcher tokens into ``(key, value)`` pairs.

    Two syntaxes predate the ``match:KEY VALUE`` grammar:

    - v2 (keyword ``windowrulev2``): ``class:^kitty$``, ``title:bar`` —
      ``key:value`` tokens.
    - v1 (keyword ``windowrule``): a single bare regex matching the class.

    v3 bodies never reach here; :func:`split_rule_body` reads those.
    """
    if not parts:
        return []
    pairs = [
        (key.strip(), value.strip())
        for key, sep, value in (token.partition(":") for token in parts)
        if sep
    ]
    if pairs:
        return pairs
    return [] if v2 else [("class", parts[0])]


def _effect_value_to_lua(name: str, args: str) -> Any:
    """Coerce a Rule's stringly-typed effect args back to Lua-native form.

    Bool effects come in as ``"on"`` / ``"off"`` from the Hyprlang side;
    Lua wants ``true`` / ``false``. Numeric and string args route through
    :func:`coerce_value` so quoted/escaped output matches what the user
    would write by hand. Empty args on a known bool effect default to
    ``true`` (Hyprland's "missing value" interpretation for these names).
    """
    stripped = args.strip()
    if name in V3_BOOL_EFFECTS or name in LAYER_BOOL_EFFECTS:
        if not stripped:
            return True
        parsed = parse_hyprlang_bool(stripped)
        if parsed is not None:
            return parsed
    return coerce_value(stripped)


def render_rule_lua(rule: Rule) -> str:
    """Render a structured :class:`Rule` as one ``hl.window_rule({…})``
    / ``hl.layer_rule({…})`` call string.

    Both rule kinds share the same table shape (``name``, ``enabled``,
    ``match``, plus effect fields); only the wrapping function differs.
    Used by the walker for full-document emission, by the single-line
    emitters below, and by single-Rule consumers (e.g. hyprmod's
    edit-dialog Lua preview) that need the same snippet without
    standing up a Document.
    """
    table: dict[str, Any] = {}
    if rule.name:
        table["name"] = rule.name
    if not rule.enabled:
        table["enabled"] = False
    if rule.matchers:
        table["match"] = {k: coerce_value(v) for k, v in rule.matchers}
    for name, args in rule.effects:
        table[name] = _effect_value_to_lua(name, args)
    fn = "hl.layer_rule" if rule.kind == "layerrule" else "hl.window_rule"
    return f"{fn}({format_table(table, indent=0)})"


def _legacy_rule_parts(parts: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Split a pre-v3 rule body into ``(effects, matcher tokens)``.

    The v1 and v2 grammars put a single effect first and the matchers
    after it, so there is exactly one effect to find. v3 bodies don't
    come through here: :func:`split_rule_body` reads those.
    """
    name, _, args = parts[0].partition(" ")
    return [(name.strip(), args.strip())], parts[1:]


def emit_windowrule(args: str, *, v2: bool) -> str | None:
    """Shared implementation for ``windowrule`` and ``windowrulev2``.

    Handles raw Hyprlang single-line input — ``windowrule = match:K V,
    EFFECT [ARGS]`` and the v1 / v2 legacy shapes. Block-form rules
    (named, disabled, anything with structure that doesn't fit a
    single line) are normalised to :class:`Rule` nodes by
    :func:`hyprland_config.migrate` and emitted via the walker's
    structured-rule path; they never reach this single-line emitter.

    Returns ``None`` for a body with no effect to apply, which Hyprland
    rejects too. Callers surface that as an untranslatable line rather
    than emitting Lua that silently does nothing.
    """
    # Bracket-aware split: regex matchers like ``class:^(foo|bar,baz)$`` carry
    # commas inside parens that a naive ``str.split(",")`` would mangle.
    parts = split_top_level(args)
    if not parts:
        return None

    if any(p.startswith("match:") for p in parts):
        matcher_pairs, effects = split_rule_body(args)
    else:
        effects, matcher_tokens = _legacy_rule_parts(parts)
        matcher_pairs = _legacy_window_matchers(matcher_tokens, v2=v2)

    if not effects:
        return None
    keyword = "windowrulev2" if v2 else "windowrule"
    return render_rule_lua(
        Rule(
            raw=f"{keyword} = {args}",
            kind="windowrule",
            matchers=matcher_pairs,
            effects=effects,
        )
    )


def emit_layerrule(args: str) -> str | None:
    """``layerrule = match:namespace REGEX, EFFECT VALUE`` → ``hl.layer_rule({...})``.

    Accepts both the modern ``match:namespace …, effect …`` form and the
    legacy ``effect, REGEX`` shape. The legacy form treats the second
    token as the namespace regex when no ``match:`` prefix is present
    anywhere. Block-form layer rules are emitted via the structured
    Rule path (same as windowrules — see :func:`emit_windowrule`).
    """
    # Bracket-aware split — see emit_windowrule for the regex-matcher case.
    parts = split_top_level(args)
    if not parts:
        return None

    if any(p.startswith("match:") for p in parts):
        matcher_pairs, effects = split_rule_body(args)
    else:
        effects, matcher_tokens = _legacy_rule_parts(parts)
        # Legacy: a single bare regex matches the layer namespace.
        matcher_pairs = [("namespace", matcher_tokens[0])] if matcher_tokens else []

    if not effects:
        return None
    return render_rule_lua(
        Rule(
            raw=f"layerrule = {args}",
            kind="layerrule",
            matchers=matcher_pairs,
            effects=effects,
        )
    )


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
