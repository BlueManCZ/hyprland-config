"""Document → Lua emitter — the bulk walker.

Walks a :class:`Document` and produces Lua source by routing each line
to the right per-keyword emitter (see :mod:`._keywords`, :mod:`._bind`,
:mod:`._rules`). The per-section state machine handles ``device { … }``,
``windowrule { … }``, and ``layerrule { … }`` blocks which collect their
contents across multiple input lines.

Coverage:

- ``section:key = value`` → merged into one ``hl.config({...})`` call,
  with nested tables for both colon (``section:sub:key``) and dot
  (``section:col.inactive_border``) separators.
- ``env``, ``monitor``, ``bezier``, ``animation`` → dedicated calls
  (``hl.env``, ``hl.monitor``, ``hl.curve``, ``hl.animation``).
- ``bind`` family (``bind``, ``binde``, ``bindm``, …) → ``hl.bind(KEY,
  hl.dsp.*, FLAGS)``.
- ``windowrule`` / ``windowrulev2`` / ``layerrule`` / ``workspace`` /
  ``gesture`` / ``permission`` → matching ``hl.*`` calls.
- ``device { … }`` section → ``hl.device({...})``.
- ``exec`` / ``exec-once`` → batched into one
  ``hl.on("hyprland.start", function() … end)`` block; ``exec-shutdown``
  into the matching ``hyprland.shutdown`` block.
- ``exec, hyprctl keyword <section>:<option> <value>`` (in a bind or at
  top level) → ``hl.config({...})``: Lua-mode Hyprland rejects the
  ``keyword`` IPC verb, so the shell-out would silently break post-
  migration. Bind dispatchers become a closure
  (``function() hl.config({...}) end``), top-level execs become a bare
  ``hl.config({...})`` inside the start/shutdown block.

Anything we can't translate confidently (an unmapped dispatcher, a malformed
rule, ``unbind``, ``submap``, ``plugin``) lands at the bottom in a trailing
manual-conversion block so users can see exactly what wasn't migrated.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hyprland_config._core._model import (
    Assignment,
    Comment,
    Document,
    Keyword,
    Line,
    SectionClose,
    SectionOpen,
    Source,
)
from hyprland_config._hyprlang._bind import is_bind_keyword
from hyprland_config._lua._emit._bind import emit_bind
from hyprland_config._lua._emit._dispatchers import (
    rewrite_hyprctl_dispatch_in_shell,
    translate_dispatcher,
)
from hyprland_config._lua._emit._format import (
    coerce_value,
    emit_exec_cmd_call,
    emit_keyword_config_call,
    format_table,
    parse_hyprctl_dispatch,
    parse_hyprctl_keyword,
    quote_string,
    set_nested,
    split_key,
)
from hyprland_config._lua._emit._keywords import format_exec_block
from hyprland_config._lua._emit._public import STATIC_KEYWORD_EMITTERS
from hyprland_config._lua._emit._rules import add_block_rule_field


@dataclass
class _Group:
    """One topical chunk of output, delimited by Comment lines in the source.

    The walker opens a fresh group whenever it sees a Comment, so a Hyprlang
    config like ``# Keybinds\\nbind = …`` emits the Lua bind calls under a
    ``-- Keybinds`` header. Groups carry their own config_tree / extras /
    exec buckets — assignments don't merge across topical boundaries even
    when they could (last-write-wins still applies; values just live in
    separate ``hl.config({...})`` calls).
    """

    header: str | None = None
    config_tree: dict[str, Any] = field(default_factory=dict)
    extras: list[str] = field(default_factory=list)
    exec_start: list[str] = field(default_factory=list)  # exec / exec-once
    exec_shutdown: list[str] = field(default_factory=list)


@dataclass
class _EmitState:
    """Accumulator for everything we've emitted while walking the document.

    ``groups`` always holds at least one group — the leading unnamed group
    that collects content before any comment is seen. ``skipped`` is global
    rather than per-group because the trailing manual-conversion block is
    one list for the whole file, not per topical section.
    """

    groups: list[_Group] = field(default_factory=lambda: [_Group()])
    skipped: list[str] = field(default_factory=list)
    section_stack: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    emit_migration_markers: bool = True

    @property
    def current(self) -> _Group:
        return self.groups[-1]

    def open_group(self, header: str) -> None:
        self.groups.append(_Group(header=header))


@dataclass(frozen=True, slots=True)
class LuaFile:
    """One ``.lua`` file produced by :func:`serialize_lua_tree`.

    ``path`` is the resolved output ``.lua`` path; ``source_path`` is
    the originating ``.conf`` (the input to the emitter). ``unmapped``
    lists the original Hyprlang lines from this file that the emitter
    couldn't translate — they're absent from ``content`` (other than
    as the trailing manual-conversion comment block) and the user needs
    to port them by hand.
    """

    path: Path
    source_path: Path
    content: str
    unmapped: list[str]


def serialize_lua(doc: Document, *, emit_migration_markers: bool = True) -> str:
    """Render *doc* as a single Lua config string.

    Walks the document in Hyprland's evaluation order — ``source = …``
    directives are inlined at their position so a multi-file config emits
    as one Lua document, matching how Hyprland resolves it at runtime.
    Returns a string ending in a newline; an empty document returns an
    empty string. The library does not stamp its own ``-- Generated by``
    banner — consumers brand their output via Comment nodes if they want
    one.

    ``emit_migration_markers`` controls one-shot migration hints — currently
    the ``-- TODO: was exec-once`` suffix on translated ``exec-once`` shell
    commands. Defaults to ``True`` so a standalone Hyprlang→Lua conversion
    surfaces the ambiguity (Lua has no built-in distinction between
    "fire-at-start" and "fire-at-start-and-every-reload"). Tools that
    repeatedly re-serialize their own managed config — where the user has
    already disambiguated intent through a UI — should pass ``False`` to
    keep saves quiet.

    Use :func:`serialize_lua_tree` instead when you want to preserve the
    original ``hyprland.conf.d/*.conf`` split as separate ``.lua`` files
    bridged by ``dofile()`` calls.
    """
    state = _EmitState(emit_migration_markers=emit_migration_markers)
    for owning_doc, line in doc.iter_lines(recursive=True):
        _process_line(line, state, owning_doc)
    return _assemble_lua(state)


def serialize_lua_tree(doc: Document, *, emit_migration_markers: bool = True) -> list[LuaFile]:
    """Emit one Lua file per parsed sub-document, mirroring source structure.

    Returns one :class:`LuaFile` per document reached via ``source = …``;
    each carries the resolved output path (``.conf`` swapped for ``.lua``,
    ``X.conf.d`` directories remapped to ``X.lua.d``), the rendered
    content, and the list of original lines that didn't translate. The
    parent's content gets ``dofile("…/foo.lua")`` calls at the position
    of each ``source`` line.

    Documents without a ``path`` attribute (e.g. ``parse_string`` input)
    are skipped — there's no natural file name to use for them.

    Caveat: each output file's ``hl.config({...})`` block is the merged
    last-wins result of *that file's* assignments. If you depend on a
    parent assignment that comes *after* a ``source`` directive overriding
    the same key in the child, prefer :func:`serialize_lua` so the merge
    happens across the whole tree in evaluation order.

    See :func:`serialize_lua` for the meaning of ``emit_migration_markers``.
    """
    output: list[LuaFile] = []
    _emit_doc_tree(doc, output, emit_migration_markers=emit_migration_markers)
    return output


def _emit_doc_tree(doc: Document, output: list[LuaFile], *, emit_migration_markers: bool) -> None:
    """Recursively render *doc* and its sourced children into *output*."""
    state = _EmitState(emit_migration_markers=emit_migration_markers)
    for line in doc.lines:
        if isinstance(line, Source):
            for sub_doc in line.documents:
                _emit_doc_tree(sub_doc, output, emit_migration_markers=emit_migration_markers)
                sub_lua_path = _conf_path_to_lua(sub_doc.path)
                if sub_lua_path is not None:
                    state.current.extras.append(f"dofile({quote_string(str(sub_lua_path))})")
            continue
        _process_line(line, state, doc)

    out_path = _conf_path_to_lua(doc.path)
    if out_path is None or doc.path is None:
        return
    output.append(
        LuaFile(
            path=out_path,
            source_path=doc.path,
            content=_assemble_lua(state),
            unmapped=list(state.skipped),
        )
    )


def _conf_path_to_lua(path: Path | None) -> Path | None:
    """Map a Hyprlang config path to its ``.lua`` output path.

    The file's own ``.conf`` suffix becomes ``.lua``. Any parent directory
    whose name ends in ``.conf.d`` — the standard Unix "drop-in include"
    convention Hyprland configs use a lot — also gets remapped to
    ``.lua.d``. This stops Hyprlang configs that wildcard-source the dir
    (``source = ~/.config/hypr/hyprland.conf.d/*``) from picking up the
    new ``.lua`` files and trying to parse them as Hyprlang.
    """
    if path is None:
        return None
    parts = tuple(_remap_d_dir(part) for part in path.parent.parts)
    return Path(*parts) / (path.stem + ".lua")


def _remap_d_dir(name: str) -> str:
    """Translate a single path component: ``X.conf.d`` → ``X.lua.d``."""
    if name.endswith(".conf.d"):
        return name[: -len(".conf.d")] + ".lua.d"
    return name


def _assemble_lua(state: _EmitState) -> str:
    """Render an accumulated :class:`_EmitState` to a Lua source string.

    Each group becomes one section (header line plus its bucket contents);
    sections are joined with a blank line between them. The trailing
    manual-conversion block, when present, sits after every group.
    """
    sections: list[str] = []
    for group in state.groups:
        rendered = _render_group(group)
        if rendered is not None:
            sections.append(rendered)
    if state.skipped:
        todo = ["-- TODO: the following entries need manual conversion to Lua:\n"]
        todo.extend(f"--   {entry}\n" for entry in state.skipped)
        sections.append("".join(todo))

    return "\n".join(sections)


def _render_group(group: _Group) -> str | None:
    """Render one group as a section string, or None if it's empty and unheaded.

    A group with a header but no content emits the header line on its own
    (preserves decorative comments and section-only stubs). A group with
    content but no header emits the content alone (the leading unnamed
    group, or any topical block in a comment-free config).
    """
    parts: list[str] = []
    if group.config_tree:
        parts.append(f"hl.config({format_table(group.config_tree, indent=0)})\n")
    if group.extras:
        parts.append("".join(f"{call}\n" for call in group.extras))
    if group.exec_start:
        parts.append(format_exec_block("hyprland.start", group.exec_start))
    if group.exec_shutdown:
        parts.append(format_exec_block("hyprland.shutdown", group.exec_shutdown))

    if not parts and group.header is None:
        return None

    if group.header is None:
        header_line = ""
    elif group.header:
        header_line = f"-- {group.header}\n"
    else:
        header_line = "--\n"
    return header_line + "\n".join(parts)


_BLOCK_RULE_SECTIONS = frozenset({"windowrule", "windowrulev2", "layerrule"})


def _process_line(line: Line, state: _EmitState, owning_doc: Document) -> None:
    """Route a single line to the right accumulator on *state*.

    *owning_doc* is the Document that originally contained *line* (the parent
    when sources are followed). We use its variable scope to expand
    ``$var`` references in keyword arguments before emitting.
    """
    if isinstance(line, Comment):
        # Comments delimit topical groups — open a fresh accumulator so the
        # following lines emit under their own `-- header` and don't merge
        # back into the prior section's hl.config call.
        state.open_group(line.text)
        return

    if isinstance(line, SectionOpen):
        # `device { … }`, `windowrule { … }`, `windowrulev2 { … }`, and
        # `layerrule { … }` blocks all produce a single Lua call when the
        # section closes — we collect their contents into a buffer instead
        # of merging into the general config_tree. Other sections fall
        # through to the normal Assignment full_key handling.
        if line.name == "device":
            buffer: dict[str, Any] = {}
            if line.section_key:
                buffer["name"] = line.section_key
            state.section_stack.append(("device", buffer))
        elif line.name in _BLOCK_RULE_SECTIONS:
            state.section_stack.append((line.name, {}))
        else:
            state.section_stack.append((line.name, None))
        return

    if isinstance(line, SectionClose):
        if state.section_stack:
            close_name, close_buf = state.section_stack.pop()
            if close_name == "device" and close_buf is not None:
                state.current.extras.append(f"hl.device({format_table(close_buf, indent=0)})")
            elif close_name in ("windowrule", "windowrulev2") and close_buf is not None:
                state.current.extras.append(f"hl.window_rule({format_table(close_buf, indent=0)})")
            elif close_name == "layerrule" and close_buf is not None:
                state.current.extras.append(f"hl.layer_rule({format_table(close_buf, indent=0)})")
        return

    if isinstance(line, Assignment):
        if state.section_stack:
            cur_name, cur_buf = state.section_stack[-1]
            if cur_name == "device" and cur_buf is not None:
                cur_buf[line.key] = coerce_value(line.value)
                return
            if cur_name in _BLOCK_RULE_SECTIONS and cur_buf is not None:
                add_block_rule_field(cur_buf, line.key, line.value)
                return
        set_nested(state.current.config_tree, split_key(line.full_key), coerce_value(line.value))
        return

    if isinstance(line, Keyword):
        _process_keyword(line, state, owning_doc)


def _try_translate_hyprctl_dispatch(cmd: str) -> str | None:
    """Return the ``hl.dsp.*`` snippet when *cmd* is a single ``hyprctl dispatch``.

    Returns ``None`` if the shape doesn't match (anything more complex than a
    single hyprctl invocation, e.g. ``sleep && hyprctl …``), or if the verb
    has no native translation — leaving the caller to fall back to the
    embedded-rewrite path.
    """
    parsed = parse_hyprctl_dispatch(cmd)
    if parsed is None:
        return None
    return translate_dispatcher(parsed[0], parsed[1])


def _process_keyword(line: Keyword, state: _EmitState, owning_doc: Document) -> None:
    """Route a Keyword line to the right accumulator or fallback bucket."""
    name = line.key
    # Variables like ``$mainMod`` only resolve inside the document that
    # defined them, so we use the owning doc's scope for expansion.
    args = owning_doc.expand(line.value)

    # The exec family writes into dedicated buckets so the assembler can
    # wrap them in ``hl.on("hyprland.start", function() … end)`` blocks
    # at the end. For one-shot migrations ``exec-once`` gets an inline
    # marker comment since the Lua API doesn't carry that semantics —
    # the user gets a visible reminder that the line will fire on every
    # reload after migration. Tools doing repeat round-trip serialization
    # of their own managed config disable the marker via the state flag.
    if name in ("exec", "exec-once", "exec-shutdown"):
        keyword = parse_hyprctl_keyword(args)
        dispatch_translation = _try_translate_hyprctl_dispatch(args)
        if keyword is not None:
            # exec/exec-once distinction is moot for a keyword setter
            # (idempotent on every call), so the inline marker comment
            # is dropped in that branch.
            translated = emit_keyword_config_call(*keyword, indent=1)
        elif dispatch_translation is not None:
            translated = f"hl.dispatch({dispatch_translation})"
        elif name == "exec-once" and state.emit_migration_markers:
            cmd_call = emit_exec_cmd_call(rewrite_hyprctl_dispatch_in_shell(args))
            translated = f"{cmd_call}  -- TODO: was exec-once"
        else:
            translated = emit_exec_cmd_call(rewrite_hyprctl_dispatch_in_shell(args))
        bucket = (
            state.current.exec_shutdown if name == "exec-shutdown" else state.current.exec_start
        )
        bucket.append(translated)
        return

    if is_bind_keyword(name):
        result = emit_bind(name, args)
        if result is None:
            state.skipped.append(f"{name} = {args}")
        else:
            state.current.extras.append(result)
        return

    emitter = STATIC_KEYWORD_EMITTERS.get(name)
    if emitter is None:
        # ``submap`` lands here on purpose (see ``STATIC_KEYWORD_EMITTERS``
        # docstring); anything else is a future / plugin keyword we don't
        # yet translate. Either way, surface the original line in the
        # manual-conversion block instead of silently producing invalid Lua.
        state.skipped.append(f"{name} = {args}")
        return
    result = emitter(args)
    if result is None:
        state.skipped.append(f"{name} = {args}")
    else:
        state.current.extras.append(result)
