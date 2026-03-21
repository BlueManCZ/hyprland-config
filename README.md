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

Requires Python 3.12+. Zero runtime dependencies.

## Why this library

This is a round-trip parser. It keeps comments, blank lines, variable definitions, and formatting intact — editing one option doesn't rewrite the rest of the file.

It follows `source` directives across multiple files, resolves globs (including absolute paths for NixOS/home-manager setups), detects cycles, and only writes back files that actually changed. Writes are atomic (temp file + fsync + rename) so a crash mid-save won't corrupt your config.

300+ tests, including property-based and fuzz testing with Hypothesis.

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

### Check for deprecations

Track Hyprland deprecations across versions and apply automatic migrations:

```python
from hyprland_config import load, check_deprecated, migrate

config = load()

# Check for deprecated options (covers v0.33–v0.53+)
warnings = check_deprecated(config)
for w in warnings:
    print(f"{w.key}: {w.message} (deprecated in v{w.version_deprecated})")

# Auto-migrate what can be migrated
result = migrate(config)
print(f"Applied {len(result.applied)} migrations")
config.save()
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
- Lenient parsing mode for malformed or partial configs
- Deprecation checking and automatic migration (v0.33–v0.53+)
- Section listing and iteration
- Dirty tracking — only modified files are written to disk
- Atomic writes (temp file + fsync + rename)
- `ParseError` with file name and line number on malformed input
- Fully typed with `py.typed` marker

## License

MIT
