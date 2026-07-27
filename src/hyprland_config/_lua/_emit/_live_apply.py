"""Single-line emit APIs used by live-apply (``hyprctl eval``) callers.

The walker uses these one-liners too, via :data:`STATIC_KEYWORD_EMITTERS`,
to translate keyword lines during document emit. Centralising the
mapping here keeps the live-apply path and the bulk emit path in sync.
"""

from collections.abc import Callable
from functools import partial
from typing import Any

from hyprland_config._hyprlang._bind import is_bind_keyword, parse_bind_line
from hyprland_config._hyprlang._parser import is_keyword
from hyprland_config._lua._emit._bind import emit_bind, emit_unbind
from hyprland_config._lua._emit._dispatchers import (
    dispatcher_drops_address_selector,
    translate_dispatcher,
)
from hyprland_config._lua._emit._format import (
    INDENT,
    coerce_value,
    format_table,
    quote_string,
    set_nested,
    split_key,
    translate_exec_arg,
)
from hyprland_config._lua._emit._keywords import (
    emit_animation,
    emit_bezier,
    emit_env,
    emit_gesture,
    emit_monitor,
    emit_permission,
    emit_plugin_load,
)
from hyprland_config._lua._emit._rules import (
    emit_layerrule,
    emit_windowrule,
    emit_workspace_rule,
)

# Every static (non-bind) keyword name → its one-line emitter. Bind variants
# (``bind``, ``binde``, ``bindm``, …) aren't here — they're routed through
# :func:`emit_bind` separately because of suffix parsing. ``submap`` is
# absent because Lua's submap API is declarative — binds have to be defined
# inside the ``hl.define_submap`` function body, so a per-line emitter can't
# express it. Runtime callers compose the whole submap at once via
# :func:`define_submap_to_lua` instead.
# One-shot live-apply emitter for exec keywords: same translation as the
# doc-walking path, but ``indent=0`` because the caller wants a stand-alone
# snippet (not wrapped in an ``hl.on`` block).
_emit_exec_toplevel = partial(translate_exec_arg, indent=0)

STATIC_KEYWORD_EMITTERS: dict[str, Callable[[str], "str | None"]] = {
    "env": emit_env,
    "monitor": emit_monitor,
    "bezier": emit_bezier,
    "animation": emit_animation,
    "windowrule": partial(emit_windowrule, v2=False),
    "windowrulev2": partial(emit_windowrule, v2=True),
    "layerrule": emit_layerrule,
    "workspace": emit_workspace_rule,
    "gesture": emit_gesture,
    "permission": emit_permission,
    "exec": _emit_exec_toplevel,
    "exec-once": _emit_exec_toplevel,
    "exec-shutdown": _emit_exec_toplevel,
    # ``unbind = MODS, KEY`` (Hyprlang) → ``hl.unbind("MODS + KEY")`` (Lua).
    # Lets callers override an existing Lua bind by emitting an ``unbind``
    # ahead of the replacement, leveraging Hyprland's last-write-wins order.
    "unbind": emit_unbind,
    "plugin": emit_plugin_load,
}


def emit_keyword_line(key: str, value: str) -> str | None:
    """Emit the Lua call for a single ``key = value`` line.

    Suitable for one-shot ``hyprctl eval`` payloads. Returns a one-line
    Lua snippet representing the keyword's effect, or ``None`` when no
    Lua translation exists (unmapped dispatcher, unsupported keyword,
    malformed value).

    For ``exec``/``exec-once``/``exec-shutdown``, returns a bare
    ``hl.exec_cmd(...)`` call — without the surrounding
    ``hl.on("hyprland.start", function() … end)`` block that the
    serializer wraps autostart entries in.
    """
    if is_bind_keyword(key):
        return emit_bind(key, value)
    emitter = STATIC_KEYWORD_EMITTERS.get(key)
    if emitter is None:
        return None
    return emitter(value)


def emit_option_assignment(full_key: str, value: str) -> str:
    """Emit ``hl.config({...})`` for one ``full_key = value`` line.

    ``full_key`` uses colon-separated section paths (``general:gaps_in``,
    ``general:col.inactive_border``). Both the colon and the dot sub-prefix
    convention become nesting boundaries in the Lua table, mirroring
    Hyprland's Lua config layout.
    """
    tree: dict[str, Any] = {}
    set_nested(tree, split_key(full_key), coerce_value(value))
    return f"hl.config({format_table(tree, indent=0)})"


def _unmappable_detail(key: str, value: str) -> str:
    """Name the part of an untranslatable ``key = value`` line that caused it.

    For a bind, the keyword is almost never the problem: ``binde`` translates
    fine and it is the dispatcher (unknown, or handed an arg shape it doesn't
    accept) that has no Lua form. Blaming the keyword sends readers looking
    for missing ``binde`` support that isn't missing.
    """
    if is_bind_keyword(key):
        bind = parse_bind_line(f"{key} = {value}")
        if bind is not None:
            target = f"dispatcher {bind.dispatcher!r}"
            if bind.arg:
                target += f" with arg {bind.arg!r}"
            return f"{target} in {key} = {value!r}"
    return f"keyword {key!r} = {value!r}"


def keyword_to_lua(key: str, value: Any) -> str:
    """Translate a single ``key = value`` line to its Lua ``hl.*`` form.

    Suitable as the body of a ``hyprctl eval``. Keywords (``bind``, ``env``,
    ``monitor``, …) route to their dedicated emitter; option assignments
    (``general:gaps_in``, …) emit a single ``hl.config({...})`` call with the
    value nested at the right depth.

    Raises ``ValueError`` when the keyword has no Lua equivalent the emitter
    can produce (``submap``, an unmapped dispatcher, a malformed line).
    """
    value_str = str(value)
    if is_keyword(key):
        snippet = emit_keyword_line(key, value_str)
        if snippet is None:
            raise ValueError(f"No Lua mapping for {_unmappable_detail(key, value_str)}")
        return snippet
    return emit_option_assignment(key, value_str)


def define_submap_to_lua(name: str, binds: list[tuple[str, str]]) -> str:
    """Emit ``hl.define_submap(NAME, function() <binds> end)`` for live-apply eval.

    *binds* is a list of ``(keyword, value)`` pairs — typically ``[("bind",
    "SUPER, Q, killactive")]``. Each pair is run through
    :func:`emit_keyword_line` to produce one ``hl.bind(...)`` (or other
    keyword-emitter) line inside the function body.

    Hyprland refuses to register a submap with no binds; an empty *binds*
    list raises ``ValueError`` because the resulting ``hl.define_submap``
    call would silently no-op without registering anything.

    Raises ``ValueError`` when any bind has no Lua emitter.
    """
    if not binds:
        raise ValueError(
            f"Cannot register submap {name!r} with no binds: Hyprland rejects empty submaps"
        )
    body_lines = []
    for kw, value in binds:
        snippet = emit_keyword_line(kw, value)
        if snippet is None:
            raise ValueError(f"No Lua mapping in submap {name!r}: {_unmappable_detail(kw, value)}")
        body_lines.append(snippet)
    indented = "\n".join(f"{INDENT}{line}" for line in body_lines)
    return f"hl.define_submap({quote_string(name)}, function()\n{indented}\nend)"


def dispatch_to_lua(dispatcher: str, arg: str = "") -> str:
    """Emit ``hl.dispatch(hl.dsp.*())`` for one runtime dispatch.

    The Lua equivalent of a ``/dispatch`` IPC. ``hl.dispatch`` expects a
    dispatcher value (a function call on the ``hl.dsp.*`` namespace),
    *not* a string — Hyprland 0.55's legacy shorthand reports this with
    an "expected a dispatcher" error. We reuse the same translation the
    bind emitter uses, then wrap it in ``hl.dispatch(...)`` to execute it.

    Raises ``ValueError`` when no Lua translation exists (unknown
    dispatcher or unsupported arg shape — e.g. an ``address:`` selector
    on a dispatcher whose Lua emitter doesn't yet accept it).
    """
    name = dispatcher.strip()
    if dispatcher_drops_address_selector(name, arg):
        raise ValueError(
            f"No Lua mapping for address-targeted dispatch "
            f"{name!r} {arg!r}: dispatcher emitter ignores the selector"
        )
    call = translate_dispatcher(name, arg)
    if call is None:
        raise ValueError(f"No Lua mapping for dispatch {name!r} {arg!r}")
    return f"hl.dispatch({call})"
