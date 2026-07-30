# hyprland-config

Round-trip parser and editor for Hyprland configuration files.

## Quick start

```python
from hyprland_config import load

config = load()
config.set("general:gaps_in", 20)
config.save()
```

That's it. `load()` reads `~/.config/hypr/hyprland.conf`, follows all `source` directives, and builds a navigable document tree. `set()` finds the option in whichever sourced file defines it and updates it in place. `save()` writes only the files that were actually modified.

## Installation

```
pip install hyprland-config
```

Requires Python 3.12+. Zero Python runtime dependencies. Reading Lua-format configs (`load_lua()`) additionally requires a `lua` interpreter (5.3+) on `PATH` — already present on any host running Hyprland 0.55+.

## Why this library

This is a round-trip parser. It keeps comments, blank lines, variable definitions, and formatting intact — editing one option doesn't rewrite the rest of the file.

It follows `source` directives (Hyprland's include/import mechanism) across multiple files, resolves globs (including absolute paths for NixOS/home-manager setups), detects cycles, and only writes back files that actually changed. Writes are atomic (temp file + fsync + rename) so a crash mid-save won't corrupt your config.

600+ tests, including property-based and fuzz testing with Hypothesis.

## Usage

### Edit config options

```python
from hyprland_config import load

config = load()

# Update existing options (finds them across all sourced files)
config.set("general:gaps_in", 10)
config.set("decoration:rounding", 8)
config.set("decoration:blur:enabled", True)

# Remove an option
config.remove("misc:vfr")

# Add a keybind (appends after existing binds)
config.append("bind", "SUPER, T, exec, kitty")

# Remove a specific keybind
config.remove_where("bind", lambda v: "killactive" in v)

# Remove an animation by name
config.remove_where("animation", lambda v: v.startswith("windows,"))

# Check which files have pending changes
config.dirty_files()
# [PosixPath('/home/user/.config/hypr/hyprland.conf.d/02_general.conf'),
#  PosixPath('/home/user/.config/hypr/hyprland.conf.d/03_decoration.conf')]

# Save only the files that changed
config.save()
```

### Read config as a flat dict

```python
from hyprland_config import parse_to_dict

options = parse_to_dict("~/.config/hypr/hyprland.conf")

# Unique keys are strings
print(options["general:gaps_in"])  # "5"

# Repeated keys become lists
print(options["bind"])  # ["SUPER, Q, killactive,", "SUPER, Return, exec, kitty", ...]
```

### Read option values

```python
from hyprland_config import load

config = load()

# Get a value (returns string or None)
gaps = config.get("general:gaps_in")           # "5"
missing = config.get("nonexistent", "default") # "default"

# Get all values for a repeated key
all_binds = config.get_all("bind")  # ["SUPER, Q, killactive,", ...]

# Get the full node for more details
node = config.find("general:gaps_in")
print(f"{node.full_key} = {node.value} (line {node.lineno})")

# Find all binds as nodes
binds = config.find_all("bind")

# Expand variables
print(config.expand("$mainMod + Q"))  # "SUPER + Q"

# Navigate sourced files
from hyprland_config import Source
for line in config.lines:
    if isinstance(line, Source):
        for sub_doc in line.documents:
            print(f"{sub_doc.path.name}: {len(sub_doc.lines)} lines")
```

Variables (`$foo`) expand only when defined with `$foo = ...` in the config. Environment variables like `$HOME` or `$XDG_CONFIG_HOME` are **not** expanded — this matches Hyprland's own behavior. The `env = ...` keyword sets environment variables for child processes; it does not define config variables.

### Parse from a string

```python
from hyprland_config import parse_string

doc = parse_string("""
general {
    gaps_in = 5
    gaps_out = 10
}
bind = SUPER, Q, killactive,
""")

print(doc.get("general:gaps_in"))  # "5"
```

### Lenient mode

By default, the parser raises `ParseError` on malformed input. In lenient mode, unparseable lines are preserved as error nodes instead, so you can work with partially valid configs:

```python
config = load(lenient=True)

# Inspect any lines that couldn't be parsed
for err in config.errors:
    print(f"{err.source_name}:{err.lineno}: {err.raw}")
```

### Emit a Lua config (Hyprland 0.55.0+)

Hyprland 0.55.0 introduced Lua as the default config language. `serialize_lua()` walks a parsed document and emits the equivalent Lua, suitable for tools that want to write a `.lua` managed config alongside (or in place of) a Hyprlang one.

```python
from hyprland_config import parse_string, serialize_lua

doc = parse_string("""
general {
    gaps_in = 5
    col.inactive_border = rgba(595959aa)
}
decoration:blur:enabled = true
env = XCURSOR_SIZE, 24
bezier = easeOut, 0.05, 0.9, 0.1, 1.0
animation = windows, 1, 7, easeOut, slide
""")
print(serialize_lua(doc))
```

```lua
hl.config({
    general = {
        gaps_in = 5,
        col = {
            inactive_border = "rgba(595959aa)",
        },
    },
    decoration = {
        blur = {
            enabled = true,
        },
    },
})

hl.env("XCURSOR_SIZE", "24")
hl.curve("easeOut", { type = "bezier", points = { {0.05, 0.9}, {0.1, 1.0} } })
hl.animation({
    leaf = "windows",
    enabled = true,
    speed = 7,
    bezier = "easeOut",
    style = "slide",
})
```

Currently covered:

- Category-keyed assignments → merged into one `hl.config({...})` call. Both colon (`decoration:blur:size`) and dot (`general:col.inactive_border`) act as nesting separators.
- `env` → `hl.env`, `monitor` → `hl.monitor`, `bezier` → `hl.curve`, `animation` → `hl.animation`.
- `bind` family (`bind`, `binde`, `bindm`, `bindl`, `bindr`, `bindel`, `bindd`, `binded`, `bindmd`, …) → `hl.bind(KEY, hl.dsp.*, FLAGS)`. Suffix chars map to flag fields (`e`→`repeating`, `l`→`locked`, `m`→`mouse`, `r`→`release`, `n`→`non_consuming`, `t`→`transparent`, `i`→`ignore_mods`), plus `d` adds an extra description string (`bindd = MODS, KEY, DESCRIPTION, DISPATCHER, ARG`). Common dispatchers (`exec`, `killactive`, `togglefloating`, `movefocus`, `workspace`, `movetoworkspace`, `togglespecialworkspace`, `changegroupactive`, `moveintogroup`, `moveoutofgroup`, `resizeactive`, `setprop`, `swapwindow`, `tagwindow`, `layoutmsg`, …) map to their `hl.dsp.*` counterparts.
- `windowrule` / `windowrulev2` → `hl.window_rule({ match = { … }, ACTION = VALUE })`. Both line-style (`windowrule = float on, match:class …`) **and** block-style (`windowrule { match:class = …; float = on; }`) are supported, in either matcher-first or effect-first ordering.
- `layerrule` → `hl.layer_rule(...)`, also accepting block syntax.
- `workspace = ID, monitor:DP-1, default:true, …` → `hl.workspace_rule({...})`.
- `gesture` → `hl.gesture({...})`.
- `permission = REGEX, TYPE, ACTION` → `hl.permission("REGEX", "TYPE", "ACTION")`.
- `device { name = …; sensitivity = …; }` block → `hl.device({...})`.
- `exec` → `hl.exec_cmd(...)` at top level (every-reload semantics). `exec-once` → wrapped in `hl.on("hyprland.start", function() … end)` (start-only semantics). `exec-shutdown` → matching `hyprland.shutdown` block.
- `# hyprlang if/elif/else/endif` blocks → native Lua `if … elseif … else … end`. Supported operators: `==`, `!=`, `>`, `<`, `>=`, `<=`, and bare-`$VAR` truthy checks. Compound boolean expressions (`and` / `or` / `not`) and `# hyprlang noerror` aren't translated.

Anything we can't translate confidently — an unmapped dispatcher, an unsupported bind flag suffix, `unbind`, `submap`, `plugin`, a compound conditional expression — lands in a `-- TODO: manual conversion` block at the bottom of the output. The emitter is one-way: blank lines are dropped, and `$variable` references survive as named `local var_NAME = "value"` declarations at the top of the output (in `serialize_lua_tree`, variables used across files become Lua globals on the shared `_G` instead, since each sub-file is its own chunk). Top-level `# …` comments become `-- …` Lua comments and split the following assignments into their own `hl.config({...})` call, keeping the topical structure the user wrote.

`serialize_lua()` flattens everything into one Lua document, inlining each `source = …` directive at its position. If your Hyprlang config is split across multiple files and you want the same shape on the Lua side, use `serialize_lua_tree()`:

```python
from hyprland_config import load, serialize_lua_tree

doc = load()  # ~/.config/hypr/hyprland.conf
tree = serialize_lua_tree(doc)

# tree is a list of LuaFile(path, source_path, content, unmapped):
#   LuaFile(path=Path("~/.../hyprland.lua"),       content="...", unmapped=[]),
#   LuaFile(path=Path("~/.../hyprland/00_env.lua"), content="...", unmapped=[]),
#   ...
# Each parent file's content has `require("module.name")` calls in place
# of the original `source = …/foo.conf` lines (the recommended form for Hyprland 0.55+).

for entry in tree:
    entry.path.write_text(entry.content)
```

Each sub-document gets its own `.lua` file (`.conf` swapped for `.lua`) and the parent stitches them together with `require("module.name")` calls resolved against the main config directory, matching Hyprland's own `package.path` resolution. Caveat: each emitted file's `hl.config({...})` block is the merged last-wins result of *that file's* assignments — if you depend on a parent assignment that comes *after* a `source` directive overriding the same key in the child, use `serialize_lua()` instead so the merge spans the whole tree.

### Read a Lua config

`load_lua()` is the inverse direction — it parses an existing `hyprland.lua` (and any files it pulls in via `require()`) into the same `Document` tree the Hyprlang parser produces, so the rest of the API works identically regardless of on-disk format:

```python
from hyprland_config import load_lua

config = load_lua("~/.config/hypr/hyprland.lua")

config.get("general:gaps_in")        # "5"
config.get_all("bind")               # ["SUPER, Q, killactive,", ...]
config.set("decoration:rounding", 8) # works the same as on Hyprlang configs
config.save()                        # writes Lua back, not Hyprlang
```

Under the hood `load_lua()` shells out to a `lua` interpreter to run the user's config under a sandboxed `hl.*` shim and captures the effects. Comments, blank lines, and the user's own local variables are not preserved — only the `hl.*` calls the config produces. If `lua` is missing from `PATH`, `LuaReaderError` (a subclass of `ParseError`) is raised with a clear message.

Because of that, `save()` rewrites each modified file rather than patching lines in place, and only the files that changed are touched (`Document.lua` records which format the document came from). Sub-files stay split: each `require()` position is re-emitted as a `require()` call instead of being inlined into the parent. A rewritten file leads with its own `hl.config({...})` block, so an option the parent sets *after* a `require()` that sets the same key will lose to the required file on the next load.

### Format-agnostic load and serialize

When a caller doesn't know in advance whether the user is on Hyprlang or Lua, the `*_any` helpers dispatch on the file suffix:

```python
from hyprland_config import default_entrypoint, load_any, serialize_any

path = default_entrypoint()  # hyprland.lua if it exists, else hyprland.conf
doc = load_any(path)
doc.set("general:gaps_in", 20)
doc.save()                   # each dirty file in the format it was read as

# Or render to text without touching disk (diffs, previews, other targets)
preview = serialize_any(doc, path)
```

`default_entrypoint()` mirrors Hyprland's own resolution: it returns `hyprland.lua` when present (Hyprland 0.55+), falling back to `hyprland.conf`. The companion `default_config_dir()`, `default_hyprlang_entrypoint()`, and `default_lua_entrypoint()` return their parts individually.

`save(path)` converts when the target names the other format: a Lua document saved to a `.conf` path comes out as Hyprlang, and a Hyprlang one saved to `.lua` comes out as Lua. Any other suffix keeps the document's own format.

### Convert a Hyprlang config to Lua

For a one-shot migration off Hyprlang onto Hyprland 0.55+'s default Lua format, `analyze_conversion()` and `execute_conversion()` form a safe two-phase API. `analyze_conversion()` parses the input, plans every output file, and surfaces anything the emitter can't translate — without writing anything to disk:

```python
from pathlib import Path
from hyprland_config import analyze_conversion, execute_conversion

plan = analyze_conversion(Path.home() / ".config/hypr/hyprland.conf")

# Inspect before committing
print(f"Would write {len(plan.output_files)} files ({plan.sourced_count} sourced)")
for unmapped in plan.unmapped:
    print(f"  TODO ({unmapped.source.name}): {unmapped.line}")
if plan.has_conflicts:
    print(f"Existing .lua files would be skipped: {plan.existing_lua}")

# Commit (refuses to overwrite existing .lua files unless overwrite=True)
result = execute_conversion(plan)
if not result.ok:
    print(f"Conversion failed: {result.errors}")
```

`execute_conversion()` writes every file to a staging path first, then renames them onto their final paths only if the entire batch succeeded. The original `.conf` files are never modified. A partial failure cleans up the staged files and reports which paths were written before the abort, so callers can recover without surprises.

### Check for deprecations

Track Hyprland deprecations across versions and apply automatic migrations:

```python
from hyprland_config import load, check_deprecated, migrate

config = load()

# Check for deprecated options (covers v0.33–v0.55+)
warnings = check_deprecated(config)
for w in warnings:
    print(f"{w.key}: {w.message} (deprecated in v{w.version_deprecated})")

# Auto-migrate what can be migrated
result = migrate(config)
print(f"Applied {len(result.applied)} migrations")
config.save()
```

`migrate()` also rewrites deprecated keys. When you only want the structural part — collapsing `windowrule` / `layerrule` lines into structured `Rule` nodes without touching anything deprecated — call `normalize_rules(doc)` directly. It operates on a single document (no source recursion) and returns `True` if any line was rewritten:

```python
from hyprland_config import normalize_rules

changed = normalize_rules(config)
```

## Features

- Nested `category { }` blocks, including `device[name] { }`
- Inline category syntax (`general:gaps_in = 5`)
- One-line blocks (`general { gaps_in = 5 }`)
- `source = path` following with glob and `~` expansion, cycle detection
- `$variable` definitions and expansion
- Expression evaluation (`{{2 + 2}}`) with `\{{` escape support
- Conditional directives (`# hyprlang if/elif/else/endif`) and `# hyprlang noerror`
- Comments, inline comments, `##` escape, blank lines
- Special keywords: bind (all flag variants), monitor, animation, bezier, env, exec, workspace, windowrule, and more
- Comment-preserving round-trip editing
- Lua format support (Hyprland 0.55+): read existing `hyprland.lua` configs back into `Document` via `load_lua()`, emit Lua via `serialize_lua()` / `serialize_lua_tree()`, and migrate Hyprlang trees onto Lua atomically via `analyze_conversion()` / `execute_conversion()`
- Format-agnostic `load_any()` / `serialize_any()` helpers that dispatch on file suffix, and a `save()` that writes each file back in the format it was read as
- Lenient parsing mode for malformed or partial configs
- Deprecation checking and automatic migration (v0.33–v0.55+)
- Section listing and iteration
- Dirty tracking — only modified files are written to disk
- Atomic writes (temp file + fsync + rename)
- `ParseError` with file name and line number on malformed input
- Fully typed with `py.typed` marker

## License

MIT
