"""Records → Document walker.

Consumes the JSON record stream produced by the Lua wrapper and
synthesises a tree-shaped :class:`Document` that mirrors what the
Hyprlang parser would produce for the equivalent ``.conf``.

``__dofile_enter`` / ``__dofile_exit`` markers from the wrapper delimit
scope transitions: on enter we attach a :class:`Source` node to the
current document and push a new sub-Document for its body; on exit we
pop. Each ``hl.<keyword>(...)`` call routes through :data:`RECORD_HANDLERS`
to the right inverse-shape converter.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from hyprland_config._core._model import Document, Keyword, Source
from hyprland_config._lua._read._bind import bind_value, unbind_value
from hyprland_config._lua._read._config import emit_config_assignments, scalar_to_hyprlang
from hyprland_config._lua._read._keywords import (
    animation_value,
    bezier_value,
    emit_device,
    gesture_value,
    monitor_value,
    rule_to_node,
    workspace_value,
)

RecordHandler = Callable[[Document, list[Any], str], None]

# Sentinel ``call`` names emitted by ``_wrapper.lua``. Must stay in sync
# with that file — see the "dofile recursion" comment block there.
_DOFILE_ENTER = "__dofile_enter"
_DOFILE_EXIT = "__dofile_exit"
_WRAPPER_INTERNAL_PREFIX = "__"


def records_to_document(
    records: list[dict[str, Any]], *, entry_path: Path | None = None
) -> Document:
    """Walk the recorded ``hl.*`` calls and synthesise a tree-shaped Document.

    ``__dofile_enter`` / ``__dofile_exit`` markers from the Lua wrapper
    delimit scope transitions: on enter we attach a :class:`Source` node
    to the current document and push a new sub-Document for its body;
    on exit we pop. The shape mirrors what the Hyprlang parser produces
    for ``source = …`` so callers can iterate either format the same way.
    """
    root = Document(path=entry_path, sources_followed=True, lua=True)
    stack: list[Document] = [root]
    for rec in records:
        call = rec["call"]
        args = rec.get("args", [])
        # The wrapper tags every record with the file that issued the
        # ``hl.*`` call. Enter/exit markers carry the parent file in
        # ``source`` so the Source node lands on the parent's line list.
        source = str(rec.get("source", ""))
        cur = stack[-1]

        if call == _DOFILE_ENTER:
            sub_path_str = str(args[0]) if args else ""
            sub_doc = _open_sub_document(cur, sub_path_str, parent_source=source)
            stack.append(sub_doc)
            continue
        if call == _DOFILE_EXIT:
            # Defensive — a malformed record stream shouldn't pop the root.
            if len(stack) > 1:
                stack.pop()
            continue
        if call.startswith(_WRAPPER_INTERNAL_PREFIX):
            # Wrapper-internal error markers — already on stderr.
            continue

        handler = _RECORD_HANDLERS.get(call)
        if handler is not None:
            handler(cur, args, source)
    return root


def _open_sub_document(parent: Document, path_str: str, *, parent_source: str) -> Document:
    """Attach a :class:`Source` node to *parent* and return the new sub-Document.

    The Source node mirrors the shape Hyprlang's parser produces for
    ``source = …`` — ``path_str`` is the literal ``dofile`` argument,
    ``resolved_paths`` is a single-element list with the canonical
    absolute path (or empty when resolution fails, e.g. for a missing
    file), and ``documents`` holds the sub-Document we're about to fill.
    """
    sub_path: Path | None
    resolved: list[Path] = []
    try:
        sub_path = Path(path_str).expanduser()
        resolved = [sub_path.resolve()]
    except OSError:
        sub_path = None
    sub_doc = Document(path=sub_path, sources_followed=True, lua=True)
    source_node = Source(
        raw=f'dofile("{path_str}")\n',
        source_name=parent_source,
        path_str=path_str,
        resolved_paths=resolved,
        documents=[sub_doc],
    )
    parent.lines.append(source_node)
    return sub_doc


def _emit_keyword(doc: Document, name: str, value: str, *, source: str = "") -> None:
    doc.lines.append(
        Keyword(
            raw=f"{name} = {value}\n",
            key=name,
            value=value,
            full_key=name,
            source_name=source,
        )
    )


def _join_csv(args: list[Any]) -> str:
    """Join positional ``hl.*`` args back into a Hyprlang comma list."""
    return ", ".join(scalar_to_hyprlang(a) for a in args)


# ---------------------------------------------------------------------------
# Record handlers
# ---------------------------------------------------------------------------


def _handle_simple(keyword: str) -> RecordHandler:
    """Handler factory: join positional ``hl.*`` args into a comma-separated value."""
    return lambda doc, args, source: _emit_keyword(doc, keyword, _join_csv(args), source=source)


def _handle_table(keyword: str, value_fn: Callable[[dict[str, Any]], str]) -> RecordHandler:
    """Handler factory: expects ``args[0]`` to be a dict, renders it via *value_fn*."""

    def handler(doc: Document, args: list[Any], source: str) -> None:
        if args and isinstance(args[0], dict):
            _emit_keyword(doc, keyword, value_fn(args[0]), source=source)

    return handler


def _handle_rule(kind: str) -> RecordHandler:
    """Handler factory: emits a structured :class:`Rule` node for
    ``hl.window_rule({...})`` / ``hl.layer_rule({...})``.

    Skips the Hyprlang-string detour the other ``_handle_table`` cases
    take — Rule is a first-class Document node so the table maps to its
    fields directly.
    """

    def handler(doc: Document, args: list[Any], source: str) -> None:
        if not args or not isinstance(args[0], dict):
            return
        rule = rule_to_node(kind, args[0])
        rule.source_name = source
        doc.lines.append(rule)

    return handler


def _handle_config(doc: Document, args: list[Any], source: str) -> None:
    if args and isinstance(args[0], dict):
        emit_config_assignments(doc, args[0], source=source)


def _handle_curve(doc: Document, args: list[Any], source: str) -> None:
    if len(args) >= 2 and isinstance(args[1], dict):
        _emit_keyword(doc, "bezier", bezier_value(args[0], args[1]), source=source)


def _handle_device(doc: Document, args: list[Any], source: str) -> None:
    if args and isinstance(args[0], dict):
        emit_device(doc, args[0], source=source)


def _handle_plugin_load(doc: Document, args: list[Any], source: str) -> None:
    # ``hl.plugin.load("/path/to.so")`` is the Lua-side equivalent of the
    # Hyprlang ``plugin = /path/to.so`` keyword — recover the canonical
    # Hyprlang shape so downstream consumers see a uniform Document
    # regardless of source language.
    if args:
        _emit_keyword(doc, "plugin", str(args[0]), source=source)


def _handle_exec_cmd(doc: Document, args: list[Any], source: str) -> None:
    # ``hl.exec_cmd(cmd, event?)`` — the wrapper tags the call with the
    # surrounding ``hl.on`` event (or ``nil`` at top level). Hyprland tears
    # down the Lua state on reload and re-executes every config file, so
    # top-level calls fire on every reload (= ``exec``) while ``hl.on``
    # callbacks only fire when their event does. ``hyprland.start`` only
    # fires at actual session startup, not on reload, which is exactly the
    # ``exec-once`` semantic.
    if not args:
        return
    cmd = str(args[0])
    event = args[1] if len(args) >= 2 else None
    if event == "hyprland.start":
        keyword = "exec-once"
    elif event == "hyprland.shutdown":
        keyword = "exec-shutdown"
    else:
        keyword = "exec"
    _emit_keyword(doc, keyword, cmd, source=source)


def _handle_bind(doc: Document, args: list[Any], source: str) -> None:
    result = bind_value(args)
    if result is None:
        return
    bind_type, value = result
    _emit_keyword(doc, bind_type, value, source=source)


def _handle_unbind(doc: Document, args: list[Any], source: str) -> None:
    _emit_keyword(doc, "unbind", unbind_value(args), source=source)


# Recorded ``hl.*`` call name → handler that synthesises the matching
# Document line(s).
_RECORD_HANDLERS: dict[str, RecordHandler] = {
    "config": _handle_config,
    "env": _handle_simple("env"),
    "monitor": _handle_table("monitor", monitor_value),
    "curve": _handle_curve,
    "animation": _handle_table("animation", animation_value),
    "bind": _handle_bind,
    "unbind": _handle_unbind,
    "window_rule": _handle_rule("windowrule"),
    "layer_rule": _handle_rule("layerrule"),
    "workspace_rule": _handle_table("workspace", workspace_value),
    "gesture": _handle_table("gesture", gesture_value),
    "permission": _handle_simple("permission"),
    "device": _handle_device,
    "plugin_load": _handle_plugin_load,
    "exec_cmd": _handle_exec_cmd,
}
