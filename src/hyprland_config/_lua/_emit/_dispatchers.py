"""Hyprlang dispatcher → Lua ``hl.dsp.*`` mapping.

A single dispatch table (:data:`_DISPATCHERS`) wires each Hyprlang
dispatcher name to a callable that produces the matching Lua snippet.
Shared by the bind emitter (config-side) and :func:`dispatch_to_lua`
(runtime live-apply side) so both sides produce the same translation.
"""

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
    return f"hl.dsp.focus({{ workspace = {format_value(coerce_value(arg), 0)} }})"


def _dispatch_focusworkspaceoncurrentmonitor(arg: str) -> str:
    value = format_value(coerce_value(arg), 0)
    return f"hl.dsp.focus({{ workspace = {value}, on_current_monitor = true }})"


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

_DIRECTIONS: frozenset[str] = frozenset(DIR_MAP.values())


def _parse_direction(arg: str) -> str | None:
    """Map a Hyprlang direction (``l``/``r``/``u``/``d`` or the long form) to
    the canonical long form, or ``None`` when *arg* isn't a direction."""
    direction = arg.strip().lower()
    direction = DIR_MAP.get(direction, direction)
    return direction if direction in _DIRECTIONS else None


def _dispatch_movefocus(arg: str) -> str | None:
    direction = _parse_direction(arg)
    if direction is None:
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
    direction = _parse_direction(rest)
    if direction is not None:
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


def _dispatch_movewindoworgroup(arg: str) -> str | None:
    """``movewindoworgroup, dir`` → ``hl.dsp.window.move({ group_aware = true })``."""
    direction = _parse_direction(arg)
    if direction is None:
        return None
    return f'hl.dsp.window.move({{ direction = "{direction}", group_aware = true }})'


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
    """``resizewindow`` (bindm = interactive resize) — the only shape we translate.

    Active resize with absolute/relative pixel args (``resizewindow, 100 100``)
    has no clean Lua counterpart and is left to manual conversion.
    """
    if mouse and not arg.strip():
        return "hl.dsp.window.resize()"
    return None


def _dispatch_togglespecialworkspace(arg: str) -> str:
    return f"hl.dsp.workspace.toggle_special({quote_string(arg.strip())})"


def _dispatch_focuswindow(arg: str) -> str:
    return f"hl.dsp.focus({{ window = {quote_string(arg.strip())} }})"


def _dispatch_focusmonitor(arg: str) -> str:
    return f"hl.dsp.focus({{ monitor = {quote_string(arg.strip())} }})"


def _dispatch_movecurrentworkspacetomonitor(arg: str) -> str:
    return f"hl.dsp.workspace.move({{ monitor = {quote_string(arg.strip())} }})"


def _dispatch_moveworkspacetomonitor(arg: str) -> str | None:
    parts = arg.strip().split(None, 1)
    if len(parts) != 2:
        return None
    workspace, monitor = parts
    return (
        f"hl.dsp.workspace.move({{ workspace = {quote_string(workspace)}, "
        f"monitor = {quote_string(monitor)} }})"
    )


def _dispatch_swapactiveworkspaces(arg: str) -> str | None:
    parts = arg.strip().split(None, 1)
    if len(parts) != 2:
        return None
    first, second = parts
    return (
        f"hl.dsp.workspace.swap_monitors({{ monitor1 = {quote_string(first)}, "
        f"monitor2 = {quote_string(second)} }})"
    )


def _dispatch_pass(arg: str) -> str | None:
    window = arg.strip()
    if not window:
        return None
    return f"hl.dsp.pass({{ window = {quote_string(window)} }})"


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
    direction = _parse_direction(arg)
    if direction is not None:
        return f'hl.dsp.window.swap({{ direction = "{direction}" }})'
    return None


def _dispatch_tagwindow(arg: str) -> str:
    return f"hl.dsp.window.tag({{ tag = {quote_string(arg.strip())} }})"


def _dispatch_alterzorder(arg: str) -> str | None:
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


def _dispatch_toggle(call: str, arg: str, enable: tuple[str, ...]) -> str:
    """Shared body for the lock/deny dispatchers → ``{ action = … }``.

    The two sides disagree on the fallback: Hyprlang's parsers recognise
    ``toggle`` plus one enable spelling and treat *everything* else as
    disable, while Lua's ``parseToggleStr`` falls back to toggle. Spelling
    the mapping out keeps a stray value meaning what Hyprland meant by it.
    The accepted enable spellings differ per dispatcher, hence *enable*.
    """
    value = arg.strip()
    action = "toggle" if value == "toggle" else "on" if value in enable else "off"
    return f'{call}({{ action = "{action}" }})'


def _dispatch_movegroupwindow(arg: str) -> str:
    """``movegroupwindow, [b|prev]`` → ``hl.dsp.group.move_window(…)``.

    Hyprlang reads anything other than ``b``/``prev`` as forward, which is
    already the Lua default, so only the backward case carries an argument.
    """
    if arg.strip() in ("b", "prev"):
        return "hl.dsp.group.move_window({ forward = false })"
    return "hl.dsp.group.move_window()"


def _dispatch_moveintogroup(arg: str) -> str | None:
    """``moveintogroup, dir`` → ``hl.dsp.window.move({ into_group = "dir" })``."""
    direction = _parse_direction(arg)
    if direction is not None:
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
    "focusurgentorlast": lambda *_: "hl.dsp.focus({ urgent_or_last = true })",
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
    # ``global, APP:SHORTCUT`` triggers an app-registered global shortcut
    # (hyprland-global-shortcuts-v1 protocol). ``global`` isn't a Lua keyword,
    # so ``hl.dsp.global(...)`` is valid.
    "global": lambda arg, _: f"hl.dsp.global({quote_string(arg.strip())})",
    # ``execr`` runs the command without a shell, so unlike ``exec`` there is
    # no embedded ``hyprctl`` line to rewrite: the arg passes through as-is.
    "execr": lambda arg, _: f"hl.dsp.exec_raw({quote_string(arg)})",
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
    "movewindoworgroup": lambda arg, _: _dispatch_movewindoworgroup(arg),
    "movegroupwindow": lambda arg, _: _dispatch_movegroupwindow(arg),
    "focusworkspaceoncurrentmonitor": lambda arg, _: _dispatch_focusworkspaceoncurrentmonitor(arg),
    "swapactiveworkspaces": lambda arg, _: _dispatch_swapactiveworkspaces(arg),
    "pass": lambda arg, _: _dispatch_pass(arg),
    # Toggle-style args, each with its own accepted enable spelling. An empty
    # arg enables ``lockgroups`` but disables ``lockactivegroup``, matching
    # Hyprland's own two parsers.
    "lockgroups": lambda arg, _: _dispatch_toggle(
        "hl.dsp.group.lock", arg, ("", "lock", "lockgroups")
    ),
    "lockactivegroup": lambda arg, _: _dispatch_toggle("hl.dsp.group.lock_active", arg, ("lock",)),
    "denywindowfromgroup": lambda arg, _: _dispatch_toggle(
        "hl.dsp.window.deny_from_group", arg, ("on",)
    ),
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


def translate_dispatcher(name: str, arg: str, *, is_mouse: bool = False) -> str | None:
    """Translate ``(dispatcher_name, arg)`` to a Lua ``hl.dsp.*`` call.

    Returns ``None`` when we don't know how to render the dispatcher.
    Shared by the bind emitter (config-side) and ``dispatch_to_lua``
    (runtime live-apply side) so both produce the same translation.
    """
    if name == "exec":
        # Lua-mode Hyprland rejects the ``keyword`` IPC verb at config-eval
        # time, so a whole-arg ``hyprctl keyword …`` has to become native Lua.
        # A whole-arg ``hyprctl dispatch …`` can also collapse to a native
        # dispatcher, sparing the shell hop. Anything else (a larger shell
        # command) passes through verbatim:
        #   1. Whole arg is ``hyprctl keyword …`` → inline ``hl.config`` closure.
        #   2. Whole arg is ``hyprctl dispatch VERB ARGS`` → native dispatcher.
        #   3. Otherwise → leave the shell string untouched. ``hyprctl dispatch``
        #      embedded in a larger shell command is a runtime IPC call to the
        #      ``hyprctl`` binary; it behaves identically regardless of config
        #      language, so rewriting it to Lua syntax would only break it.
        keyword = parse_hyprctl_keyword(arg)
        if keyword is not None:
            return emit_keyword_setter_closure(*keyword)
        dispatch = parse_hyprctl_dispatch(arg)
        if dispatch is not None:
            translation = translate_dispatcher(dispatch[0], dispatch[1])
            if translation is not None:
                return translation
        return f"hl.dsp.exec_cmd({quote_string(arg)})"
    handler = _DISPATCHERS.get(name)
    if handler is None:
        return None
    return handler(arg, is_mouse)


def dispatcher_drops_address_selector(name: str, arg: str) -> bool:
    """Detect an ``address:`` selector the dispatcher's Lua emitter would drop."""
    if name in _ADDRESS_AWARE:
        return False
    return arg.startswith("address:") or ",address:" in arg
