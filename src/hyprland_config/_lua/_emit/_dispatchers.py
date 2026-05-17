"""Hyprlang dispatcher → Lua ``hl.dsp.*`` mapping.

A single dispatch table (:data:`_DISPATCHERS`) wires each Hyprlang
dispatcher name to a callable that produces the matching Lua snippet.
Shared by the bind emitter (config-side) and :func:`dispatch_to_lua`
(runtime live-apply side) so both sides produce the same translation.
"""

import re
from collections.abc import Callable

from hyprland_config._lua._emit._format import (
    coerce_value,
    emit_keyword_setter_closure,
    format_value,
    parse_hyprctl_dispatch,
    parse_hyprctl_keyword,
    quote_string,
)


def _extract_address_selector(arg: str) -> tuple[str, str | None]:
    """Strip a window selector (``address:0x…`` / ``,address:0x…``) from *arg*.

    Returns ``(arg_without_selector, address_selector_or_None)``. Covers the
    two shapes per-window dispatchers can take:

    - bare-arg form: ``togglefloating address:0x…`` (entire arg is the selector)
    - comma form: ``movetoworkspacesilent N,address:0x…`` (selector after comma)
    """
    stripped = arg.strip()
    if not stripped:
        return "", None
    if stripped.startswith("address:"):
        return "", stripped
    idx = stripped.rfind(",address:")
    if idx != -1:
        return stripped[:idx].rstrip(), stripped[idx + 1 :].strip()
    return stripped, None


def _dispatch_workspace(arg: str) -> str:
    """``workspace, N`` / ``workspace, e+1`` / ``workspace, name:foo``."""
    return f"hl.dsp.focus({{ workspace = {format_value(coerce_value(arg), 0)} }})"


def _dispatch_movetoworkspace(arg: str, *, silent: bool = False) -> str:
    """``movetoworkspace[silent], N[,address:0x…]`` → ``hl.dsp.window.move({…})``.

    The optional ``,address:…`` suffix targets a specific window — passes
    through to the Lua emitter as a ``window`` selector.
    """
    rest, selector = _extract_address_selector(arg)
    value = format_value(coerce_value(rest), 0)
    parts = [f"workspace = {value}"]
    if silent:
        parts.append("silent = true")
    if selector:
        parts.append(f"window = {quote_string(selector)}")
    return f"hl.dsp.window.move({{ {', '.join(parts)} }})"


# Hyprlang's movefocus and friends use single-letter directions (l/r/u/d);
# Hyprland's Lua API takes the long form. Source of truth for both the
# forward emitter and the reverse reader (which inverts this map).
DIR_MAP = {"l": "left", "r": "right", "u": "up", "d": "down"}


def _dispatch_movefocus(arg: str) -> str | None:
    """``movefocus, dir`` where ``dir`` is one of l/r/u/d (or the long form)."""
    direction = DIR_MAP.get(arg.strip().lower(), arg.strip().lower())
    if direction not in ("left", "right", "up", "down"):
        return None
    return f'hl.dsp.focus({{ direction = "{direction}" }})'


def _dispatch_movewindow(arg: str, *, mouse: bool = False) -> str | None:
    """``movewindow`` (bindm = drag) / ``movewindow, dir|mon:NAME[,address:0x…]``.

    Forms handled:

    - empty + ``mouse`` (``bindm``) → ``hl.dsp.window.drag()``
    - direction (l/r/u/d) → ``hl.dsp.window.move({ direction = … })``
    - ``mon:NAME[,address:0x…]`` → ``hl.dsp.window.move({ monitor = …[, window = …] })``
    """
    rest, selector = _extract_address_selector(arg)
    if not rest:
        if mouse and selector is None:
            return "hl.dsp.window.drag()"
        return None
    lower = rest.lower()
    direction = DIR_MAP.get(lower, lower)
    if direction in ("left", "right", "up", "down"):
        parts = [f'direction = "{direction}"']
        if selector:
            parts.append(f"window = {quote_string(selector)}")
        return f"hl.dsp.window.move({{ {', '.join(parts)} }})"
    if rest.lower().startswith("mon:"):
        monitor = rest[4:].strip()
        parts = [f"monitor = {quote_string(monitor)}"]
        if selector:
            parts.append(f"window = {quote_string(selector)}")
        return f"hl.dsp.window.move({{ {', '.join(parts)} }})"
    return None


def _dispatch_window_float(action: str, arg: str) -> str:
    """``togglefloating|setfloating|settiled [address:0x…]`` → ``hl.dsp.window.float({…})``.

    *action* is the Lua ``action`` field (``"toggle"`` / ``"set"`` / ``"unset"``).
    An ``address:`` selector targets a specific window — otherwise the active
    window. Follows the same ``window = "address:…"`` convention as
    ``hl.dsp.window.set_prop``.
    """
    _, selector = _extract_address_selector(arg)
    parts = [f'action = "{action}"']
    if selector:
        parts.append(f"window = {quote_string(selector)}")
    return f"hl.dsp.window.float({{ {', '.join(parts)} }})"


def _dispatch_pin(arg: str) -> str:
    """``pin [address:0x…]`` → ``hl.dsp.window.pin([{ window = "address:…" }])``.

    Empty-arg form returns the no-options call. Address-targeted form
    passes a ``window`` selector, following the same convention as
    ``set_prop`` / ``float``.
    """
    _, selector = _extract_address_selector(arg)
    if not selector:
        return "hl.dsp.window.pin()"
    return f"hl.dsp.window.pin({{ window = {quote_string(selector)} }})"


def _dispatch_fullscreenstate(arg: str) -> str | None:
    """``fullscreenstate INTERNAL CLIENT[,address:0x…]`` → ``hl.dsp.window.fullscreen_state({…})``.

    Hyprland's ``fullscreenstate`` takes two ints (-1 = no change, 0..2 =
    states). The Lua API exposes this as a separate ``fullscreen_state``
    dispatcher (distinct from ``fullscreen``) that wants a table
    ``{ internal, client, action?, window? }``.
    """
    rest, selector = _extract_address_selector(arg)
    tokens = rest.split()
    if len(tokens) != 2:
        return None
    try:
        internal = int(tokens[0])
        client = int(tokens[1])
    except ValueError:
        return None
    parts = [f"internal = {internal}", f"client = {client}"]
    if selector:
        parts.append(f"window = {quote_string(selector)}")
    return f"hl.dsp.window.fullscreen_state({{ {', '.join(parts)} }})"


def _dispatch_pixel_move_or_resize(call: str, arg: str) -> str | None:
    """Shared body for ``movewindowpixel`` / ``resizewindowpixel`` translation.

    Hyprlang defaults the bare ``X Y`` form to relative; the literal ``exact``
    prefix switches to absolute. The Lua API has the opposite default —
    ``{x, y}`` is absolute (``relative = false`` per Hyprland's
    ``LuaBindingsDispatchers.cpp``) and ``relative = true`` switches to
    relative. We translate both directions explicitly so the round-trip
    survives.
    """
    rest, selector = _extract_address_selector(arg)
    tokens = rest.split()
    exact = False
    if tokens and tokens[0].lower() == "exact":
        exact = True
        tokens = tokens[1:]
    if len(tokens) != 2:
        return None
    try:
        x = int(tokens[0])
        y = int(tokens[1])
    except ValueError:
        return None
    parts = [f"x = {x}", f"y = {y}"]
    if not exact:
        parts.append("relative = true")
    if selector:
        parts.append(f"window = {quote_string(selector)}")
    return f"{call}({{ {', '.join(parts)} }})"


def _dispatch_movewindowpixel(arg: str) -> str | None:
    """``movewindowpixel [exact] X Y[,address:0x…]`` → ``hl.dsp.window.move({…})``."""
    return _dispatch_pixel_move_or_resize("hl.dsp.window.move", arg)


def _dispatch_resizewindowpixel(arg: str) -> str | None:
    """``resizewindowpixel [exact] W H[,address:0x…]`` → ``hl.dsp.window.resize({…})``.

    The Lua API spells the resize dimensions as ``x``/``y`` (not
    ``width``/``height``) — confirmed against Hyprland 0.55, which
    explicitly rejects the ``width``/``height`` shape with
    "'x' and 'y' are required".
    """
    return _dispatch_pixel_move_or_resize("hl.dsp.window.resize", arg)


def _dispatch_resizewindow(arg: str, *, mouse: bool = False) -> str | None:
    """``resizewindow`` (bindm = interactive resize) / ``resizewindow, x y``."""
    if not arg.strip():
        return "hl.dsp.window.resize()" if mouse else None
    return None  # Active resize with absolute/relative pixel args needs manual review.


def _dispatch_togglespecialworkspace(arg: str) -> str:
    """``togglespecialworkspace[, name]`` → ``hl.dsp.workspace.toggle_special(name)``."""
    name = arg.strip()
    return f"hl.dsp.workspace.toggle_special({quote_string(name)})"


def _dispatch_focuswindow(arg: str) -> str:
    """``focuswindow, addr`` → ``hl.dsp.focus({ window = "addr" })``."""
    return f"hl.dsp.focus({{ window = {quote_string(arg.strip())} }})"


def _dispatch_focusmonitor(arg: str) -> str:
    """``focusmonitor, name`` → ``hl.dsp.focus({ monitor = "name" })``."""
    return f"hl.dsp.focus({{ monitor = {quote_string(arg.strip())} }})"


def _dispatch_movecurrentworkspacetomonitor(arg: str) -> str:
    """``movecurrentworkspacetomonitor, MONITOR`` → ``hl.dsp.workspace.move({...})``."""
    return f"hl.dsp.workspace.move({{ monitor = {quote_string(arg.strip())} }})"


def _dispatch_moveworkspacetomonitor(arg: str) -> str | None:
    """``moveworkspacetomonitor, WORKSPACE MONITOR`` → ``hl.dsp.workspace.move({...})``."""
    parts = arg.strip().split(None, 1)
    if len(parts) != 2:
        return None
    workspace, monitor = parts
    return (
        f"hl.dsp.workspace.move({{ workspace = {quote_string(workspace)}, "
        f"monitor = {quote_string(monitor)} }})"
    )


def _dispatch_setprop(arg: str) -> str | None:
    """``setprop, [WINDOW] PROP VALUE`` → ``hl.dsp.window.set_prop({...})``.

    Two layouts:
    - ``setprop, PROP VALUE`` — operates on the active window.
    - ``setprop, WINDOW PROP VALUE`` — explicit window selector
      (e.g. ``active``, ``address:0x…``).
    """
    parts = arg.strip().split(None, 2)
    if len(parts) == 2:
        prop, value = parts
        return (
            f"hl.dsp.window.set_prop({{ prop = {quote_string(prop)}, "
            f"value = {quote_string(value)} }})"
        )
    if len(parts) == 3:
        window, prop, value = parts
        return (
            f"hl.dsp.window.set_prop({{ prop = {quote_string(prop)}, "
            f"value = {quote_string(value)}, window = {quote_string(window)} }})"
        )
    return None


def _dispatch_swapwindow(arg: str) -> str | None:
    """``swapwindow, DIR`` → ``hl.dsp.window.swap({ direction = "DIR" })``."""
    direction = DIR_MAP.get(arg.strip().lower(), arg.strip().lower())
    if direction in ("left", "right", "up", "down"):
        return f'hl.dsp.window.swap({{ direction = "{direction}" }})'
    return None


def _dispatch_tagwindow(arg: str) -> str:
    """``tagwindow, TAG`` → ``hl.dsp.window.tag({ tag = "TAG" })``."""
    return f"hl.dsp.window.tag({{ tag = {quote_string(arg.strip())} }})"


def _dispatch_alterzorder(arg: str) -> str | None:
    """``alterzorder, top/bottom`` → ``hl.dsp.window.alter_zorder({ mode = … })``."""
    mode = arg.strip().lower()
    if mode in ("top", "bottom"):
        return f'hl.dsp.window.alter_zorder({{ mode = "{mode}" }})'
    return None


def _dispatch_changegroupactive(arg: str) -> str | None:
    """``changegroupactive, b/f`` → ``hl.dsp.group.prev()`` / ``hl.dsp.group.next()``.

    ``changegroupactive`` without an argument cycles to the next window in
    the group (Hyprland's default), so we emit ``hl.dsp.group.next()``.
    """
    direction = arg.strip().lower()
    if not direction or direction in ("f", "forward", "next"):
        return "hl.dsp.group.next()"
    if direction in ("b", "back", "backward", "prev", "previous"):
        return "hl.dsp.group.prev()"
    return None


def _dispatch_resizeactive(arg: str) -> str | None:
    """``resizeactive, [exact] X Y`` → ``hl.dsp.window.resize({ x, y, relative? })``.

    Hyprlang defaults to relative resize (``resizeactive, 50 0``); the
    literal ``exact`` prefix switches to absolute. The Lua API has the
    opposite default — absent ``relative`` means absolute, ``relative =
    true`` means relative — so the field is emitted only for the relative
    case.
    """
    tokens = arg.strip().split()
    relative = True
    if tokens and tokens[0].lower() == "exact":
        relative = False
        tokens = tokens[1:]
    if len(tokens) != 2:
        return None
    x = coerce_value(tokens[0])
    y = coerce_value(tokens[1])
    relative_field = ", relative = true" if relative else ""
    return (
        f"hl.dsp.window.resize({{ x = {format_value(x, 0)}, "
        f"y = {format_value(y, 0)}{relative_field} }})"
    )


def _dispatch_moveintogroup(arg: str) -> str | None:
    """``moveintogroup, dir`` → ``hl.dsp.window.move({ into_group = "dir" })``."""
    direction = DIR_MAP.get(arg.strip().lower(), arg.strip().lower())
    if direction in ("left", "right", "up", "down"):
        return f'hl.dsp.window.move({{ into_group = "{direction}" }})'
    return None


# Hyprlang dispatcher name → handler that produces the Lua ``hl.dsp.*``
# snippet (or ``None`` if the args don't fit). Every callable takes
# ``(arg, is_mouse)``; handlers that don't use either drop them via ``*_``.
# Window-selector aware handlers (the ``togglefloating``/``pin``/… family)
# handle empty-arg correctly on their own — no fast-path fork needed.
_DISPATCHERS: dict[str, Callable[[str, bool], "str | None"]] = {
    # Static (no arg)
    "exit": lambda *_: "hl.dsp.exit()",
    "killactive": lambda *_: "hl.dsp.window.close()",
    "closewindow": lambda *_: "hl.dsp.window.close()",
    "forcekillactive": lambda *_: "hl.dsp.window.kill()",
    "fullscreen": lambda *_: "hl.dsp.window.fullscreen()",
    "pseudo": lambda *_: "hl.dsp.window.pseudo()",
    "centerwindow": lambda *_: "hl.dsp.window.center()",
    "cyclenext": lambda *_: "hl.dsp.window.cycle_next()",
    "togglesplit": lambda *_: 'hl.dsp.layout("togglesplit")',
    "swapsplit": lambda *_: 'hl.dsp.layout("swapsplit")',
    "togglegroup": lambda *_: "hl.dsp.group.toggle()",
    "forcerendererreload": lambda *_: "hl.dsp.force_renderer_reload()",
    "moveoutofgroup": lambda *_: "hl.dsp.window.move({ out_of_group = true })",
    "focuscurrentorlast": lambda *_: "hl.dsp.focus({ last = true })",
    "bringactivetotop": lambda *_: "hl.dsp.window.bring_to_top()",
    "noop": lambda *_: "hl.dsp.no_op()",
    "swapnext": lambda *_: "hl.dsp.window.swap({ next = true })",
    # Window-selector aware (handle empty arg internally)
    "togglefloating": lambda arg, _: _dispatch_window_float("toggle", arg),
    "setfloating": lambda arg, _: _dispatch_window_float("set", arg),
    "settiled": lambda arg, _: _dispatch_window_float("unset", arg),
    "pin": lambda arg, _: _dispatch_pin(arg),
    "fullscreenstate": lambda arg, _: _dispatch_fullscreenstate(arg),
    "movewindowpixel": lambda arg, _: _dispatch_movewindowpixel(arg),
    "resizewindowpixel": lambda arg, _: _dispatch_resizewindowpixel(arg),
    # Quoted-string passthrough
    "submap": lambda arg, _: f"hl.dsp.submap({quote_string(arg.strip())})",
    "layoutmsg": lambda arg, _: f"hl.dsp.layout({quote_string(arg.strip())})",
    "dpms": lambda arg, _: f"hl.dsp.dpms({quote_string(arg.strip())})",
    # Parameterized
    "workspace": lambda arg, _: _dispatch_workspace(arg),
    "movetoworkspace": lambda arg, _: _dispatch_movetoworkspace(arg),
    "movetoworkspacesilent": lambda arg, _: _dispatch_movetoworkspace(arg, silent=True),
    "movefocus": lambda arg, _: _dispatch_movefocus(arg),
    "movewindow": lambda arg, is_mouse: _dispatch_movewindow(arg, mouse=is_mouse),
    "resizewindow": lambda arg, is_mouse: _dispatch_resizewindow(arg, mouse=is_mouse),
    "togglespecialworkspace": lambda arg, _: _dispatch_togglespecialworkspace(arg),
    "focuswindow": lambda arg, _: _dispatch_focuswindow(arg),
    "focusmonitor": lambda arg, _: _dispatch_focusmonitor(arg),
    "changegroupactive": lambda arg, _: _dispatch_changegroupactive(arg),
    "moveintogroup": lambda arg, _: _dispatch_moveintogroup(arg),
    "movecurrentworkspacetomonitor": lambda arg, _: _dispatch_movecurrentworkspacetomonitor(arg),
    "moveworkspacetomonitor": lambda arg, _: _dispatch_moveworkspacetomonitor(arg),
    "setprop": lambda arg, _: _dispatch_setprop(arg),
    "swapwindow": lambda arg, _: _dispatch_swapwindow(arg),
    "tagwindow": lambda arg, _: _dispatch_tagwindow(arg),
    "alterzorder": lambda arg, _: _dispatch_alterzorder(arg),
    "resizeactive": lambda arg, _: _dispatch_resizeactive(arg),
}


# Dispatchers whose Lua emitter accepts a ``window = "address:…"`` selector
# in the arg. For everything else, an ``address:`` token in the arg would
# be silently dropped and the dispatch would target the active window.
_ADDRESS_AWARE: frozenset[str] = frozenset(
    {
        "togglefloating",
        "setfloating",
        "settiled",
        "pin",
        "fullscreenstate",
        "movewindowpixel",
        "resizewindowpixel",
        "movetoworkspace",
        "movetoworkspacesilent",
        "movewindow",
        "setprop",
    }
)


_SHELL_SEGMENT_RE = re.compile(r"(\s*(?:&&|\|\||;)\s*)")


def rewrite_hyprctl_dispatch_in_shell(cmd: str) -> str:
    """Rewrite each ``hyprctl [flags] dispatch VERB ARGS`` segment in *cmd* to
    use Lua-call syntax, returning the modified shell command.

    Lua-mode Hyprland parses ``hyprctl dispatch <ARG>`` as ``hl.dispatch(<ARG>)``,
    breaking the legacy space-separated form. This helper preserves the shell
    wrapper (so patterns like ``sleep 1 && hyprctl dispatch …`` keep their
    timing semantics) while swapping just the inner verb+args for a quoted
    Lua expression that the new parser accepts.

    Segments without a recognized ``hyprctl dispatch`` shape, or with a verb
    that has no native ``hl.dsp.*`` translation, are returned unchanged.
    """
    parts = _SHELL_SEGMENT_RE.split(cmd)
    for i, part in enumerate(parts):
        if not part or _SHELL_SEGMENT_RE.fullmatch(part):
            continue
        parsed = parse_hyprctl_dispatch(part)
        if parsed is None:
            continue
        verb, args = parsed
        translation = translate_dispatcher(verb, args)
        if translation is None:
            continue
        prefix, sep, _ = part.rpartition("dispatch")
        # ``translation`` is double-quoted Lua source; wrap with shell
        # single-quotes so the outer Lua string (when emitted into
        # ``hl.dsp.exec_cmd("…")``) doesn't need to escape every inner quote.
        parts[i] = f"{prefix}{sep} '{translation}'"
    return "".join(parts)


def translate_dispatcher(name: str, arg: str, *, is_mouse: bool = False) -> str | None:
    """Translate ``(dispatcher_name, arg)`` to a Lua ``hl.dsp.*`` call.

    Returns ``None`` when we don't know how to render the dispatcher.
    Shared by the bind emitter (config-side) and ``dispatch_to_lua``
    (runtime live-apply side) so both produce the same translation.
    """
    if name == "exec":
        # Lua-mode rejects both the ``keyword`` and ``dispatch`` IPC verbs
        # invoked via ``hyprctl``. Three layered translations:
        #   1. Whole arg is ``hyprctl keyword …`` → inline ``hl.config`` closure.
        #   2. Whole arg is ``hyprctl dispatch VERB ARGS`` → native dispatcher,
        #      bypassing the shell roundtrip entirely.
        #   3. Otherwise, rewrite any embedded ``hyprctl dispatch …`` syntax
        #      inside the shell string so the residual shell wrapper still
        #      drives a dispatch that the Lua parser accepts.
        keyword = parse_hyprctl_keyword(arg)
        if keyword is not None:
            return emit_keyword_setter_closure(*keyword)
        dispatch = parse_hyprctl_dispatch(arg)
        if dispatch is not None:
            translation = translate_dispatcher(dispatch[0], dispatch[1])
            if translation is not None:
                return translation
        return f"hl.dsp.exec_cmd({quote_string(rewrite_hyprctl_dispatch_in_shell(arg))})"
    handler = _DISPATCHERS.get(name)
    if handler is None:
        return None
    return handler(arg, is_mouse)


def dispatcher_drops_address_selector(name: str, arg: str) -> bool:
    """Detect an ``address:`` selector the dispatcher's Lua emitter would drop."""
    if name in _ADDRESS_AWARE:
        return False
    return arg.startswith("address:") or ",address:" in arg
