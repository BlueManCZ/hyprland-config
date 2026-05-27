# Changelog

All notable changes to hyprland-config will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.5] - 2026-05-27

### Added

- `togglesplit`, `swapsplit`, and `splitratio` dispatcher → `layoutmsg` migration and deprecation warnings for Hyprland 0.55

## [0.9.4] - 2026-05-27

### Fixed

- `noborder` and `norounding` v2→v3 windowrule migration now emits `border_size 0` / `rounding 0` instead of `no_border on` / `no_rounding on`, matching Hyprland 0.53+'s replacement effects
- v2 windowrule matcher splitting now preserves spaces inside regex values (e.g. `title:(^Settings — Albert$)`)

## [0.9.3] - 2026-05-26

### Fixed

- A single-color border with a redundant `0deg` (e.g. `general:col.active_border = 0xffed333b 0deg`) now emits the bare color `"0xffed333b"` rather than the `"<color> 0deg"` string, which Hyprland's Lua config manager rejects with `invalid color`. Multi-stop gradients and non-zero angles still emit the structured `{colors=…, angle=…}` table. https://github.com/BlueManCZ/hyprmod/issues/43

## [0.9.2] - 2026-05-21

### Fixed

- `serialize_lua_tree` now resolves cross-file `$variable` references. A `$terminal` defined in `variables.conf` and used in `keybindings.conf` previously leaked through as the literal `"$terminal"` (which Hyprland's Lua parser rejects). Such variables now emit as a bare `var_X = …` global in their defining file and read as that global elsewhere; file-local variables still emit as `local`, and single-chunk `serialize_lua` is unchanged
- `$var` references inside v3 `windowrule` / `layerrule` matchers and effects (e.g. `match:class $myclass`, `bordersize $mywidth`) now emit as the Lua `var_NAME` identifier instead of the literal `"$NAME"` string; the Rule emission path previously bypassed the variable-expansion step that the keyword path already used
- `hl.monitor` now always emits an `output` field, so the catch-all rule `monitor = , preferred, auto, 1` (empty output name) becomes `output = ""` instead of dropping the key — Hyprland's Lua API requires `output` to be a string. https://github.com/BlueManCZ/hyprland-config/pull/1

## [0.9.1] - 2026-05-21

### Changed

- `serialize_lua_tree` now bridges sourced sub-files with `require("module.name")` rather than an absolute `dofile(...)`. `require` is the form the shipped Hyprland example recommends and the only one the compositor's autoreload watches, so edits to a sub-file now trigger a reload. Sub-files `require` can't name — those outside the config directory, or with a literal `.` in the path — keep an absolute `dofile`
- `.conf.d` drop-in directories now flatten to a plain `X/` (`hyprland.conf.d/` becomes `hyprland/`) instead of the previous dotted `X.lua.d/`. The dot-free name still dodges a live `source = …/X.conf.d/*` glob in the untouched `.conf` and lets the drop-ins be named by `require`, so they reload on save like every other sub-file

### Fixed

- The Lua reader resolves `require()` against the main config file's directory (matching Hyprland's `package.path`) instead of the requiring file's directory, so a `require` in a nested sub-file finds the same file the compositor would; previously deeper sub-files were dropped from the parsed `Document`
- `LuaFile.unmapped` and the `-- TODO` manual-conversion block leaked the internal `\x01`/`\x02` variable-marker sentinels from `expand_value_lua` around any `$variable` in an untranslatable line, instead of the line's original text; both now record the source as written, e.g. `bind = $mainMod SHIFT, V, workspaceopt, allfloat`

## [0.9.0] - 2026-05-21

### Added

- `render_rule_hyprlang(rule, version=...)` and `serialize_hyprlang(doc, version=...)` accept the running Hyprland version and emit the grammar that compositor understands — v3 `windowrule = match:…` for 0.53+ (0.54+ for layerrules) and the older effect-first form (`windowrulev2 = effect, class:regex` / `layerrule = effect, namespace`) below those boundaries. `version=None` (the default) keeps emitting v3
- `render_rule_live(rule, version=...)` returns the `(keyword, value)` pairs to push via `hyprctl keyword` for live-apply — a single pair for v3, one per effect on the pre-v3 grammar (which is one-effect-per-line)
- Public `WINDOWRULE_V3_VERSION` / `LAYERRULE_V3_VERSION` constants and the canonical v2↔v3 rename maps (`V2_TO_V3_EFFECT`, `V2_TO_V3_MATCHER`, `V3_TO_V2_EFFECT`, `V3_TO_V2_MATCHER`, `V3_TO_LEGACY_LAYER_EFFECT`); the v2→v3 migration shares them so the round-trip stays consistent
- `parse_hyprlang_bool(value)` in `hyprland_config` — the single source of truth for translating Hyprlang's boolean vocabulary (`true`/`yes`/`on`/`1` and their negatives) into Python bools. Returns `None` when the value isn't bool-shaped, so callers pick the fallback explicitly
- `HYPRLAND_CONFIG_LUA` environment variable overrides the Lua interpreter the reader probes for; the default search now covers `lua5.5` and `lua5.2` alongside the existing `lua` / `lua5.4` / `lua5.3`

### Changed

- **Breaking:** dropped the deprecated `emit_migration_markers` parameter from `serialize_lua`, `serialize_lua_tree`, and `serialize_any`. It was a no-op since 0.6.6 — call sites should remove the kwarg
- **Breaking:** trimmed the top-level `hyprland_config` re-exports to the API actually consumed downstream. Internal AST nodes (`KeyValueLine`, `Line`, `Variable`, `Conditional`, `ErrorLine`, `SectionOpen`, `SectionClose`), value types (`Vec2`, `Gradient`), and helpers (`evaluate_expression`, `ExprError`, `is_keyword`, `BIND_FLAG_MAP`, `parse_file`) are now reachable only via their owning submodules

### Fixed

- Hyprlang serializer now uses `LAYER_BOOL_EFFECTS` (not `V3_BOOL_EFFECTS`) when auto-filling `on` for bare layer effects; `blur`/`xray`/`dim_around`/… no longer render without their required value
- `Color.parse` rejects strings with trailing garbage instead of silently swallowing them (the regex was anchored with `match` rather than `fullmatch`)
- `evaluate_expression("(1 + 2")` raises `ExprError("mismatched parentheses")` via a structural paren-count check instead of relying on CPython's English error wording
- `is_bind_keyword("bindeeeee")` now returns `False`; the matcher accepts each suffix flag char at most once

## [0.8.0] - 2026-05-20

### Fixed

- Hyprlang `$var` references in assignments, binds, and rules now survive Lua migration as named `local var_NAME` declarations instead of being inlined or surfacing as the literal string `"$var"` (which Hyprland rejected at reload — noctalia-colors). https://github.com/BlueManCZ/hyprmod/issues/38
- Block-form `windowrule { enable = 0; … }` emits Lua `enabled = false` instead of `enable = 0`

## [0.7.0] - 2026-05-20

### Added

- `Rule` line node for `windowrule` / `layerrule` entries. Both authored shapes — single-line `windowrule = match:K V, EFFECT ARGS` and block-form `windowrule { name = …; match:K = V; … }` — canonicalise into one structured node with `kind`, `name`, `enabled`, `matchers`, and `effects` fields after `migrate()` runs. `load_lua()` builds `Rule` nodes directly from `hl.window_rule(...)` / `hl.layer_rule(...)` tables, so consumers iterate structured fields instead of re-parsing stringly-typed bodies
- `render_rule_hyprlang()` / `render_rule_lua()` to render a single `Rule` to either output format. Hyprlang picks block-form vs. single-line based on whether `name` / `enabled` / multi-effect demand it; Lua always emits one `hl.window_rule({...})` / `hl.layer_rule({...})` call

### Fixed

- `hl.window_rule({ name = "X", … })` (Lua) no longer mis-renders the `name` field as a rule effect — named rules round-trip through `load_lua()` → `serialize_lua()` intact. https://github.com/BlueManCZ/hyprmod/issues/37
- Block-form `windowrule { match:class = … }` now parses with the correct full key (`windowrule:match:class`); previously the section prefix was silently dropped for keys containing a colon, breaking downstream lookups and round-tripping

## [0.6.6] - 2026-05-18

### Fixed

- Lua emitter no longer collapses `exec` and `exec-once` into the same `hl.on("hyprland.start", …)` block. `exec` now emits at top level (re-runs on reload, matching Hyprlang's semantics); `exec-once` stays inside `hl.on` so its callback fires only at session startup
- Lua reader maps `hl.exec_cmd(...)` calls inside `hl.on("hyprland.start", …)` back to `exec-once` rather than `exec`, preserving the distinction across round-trips
- Hyprlang boolean aliases `yes`/`no`/`on`/`off` (case-insensitive) now coerce to Lua `true`/`false` instead of quoted strings — Hyprland's Lua loader rejected the quoted form with `boolean type requires a bool`. Match is lenient on trailing characters, matching Hyprland's own parser

### Changed

- `emit_migration_markers` on `serialize_lua()`, `serialize_lua_tree()`, and `serialize_any()` is now a no-op. The `-- TODO: was exec-once` hint it controlled is unnecessary now that `exec` and `exec-once` are shape-distinct. Parameter kept for backwards compatibility

## [0.6.5] - 2026-05-18

### Added

- `# hyprlang if/elif/else/endif` blocks translate to Lua `if/elseif/else/end`; referenced `$VAR`s emit as `local` declarations. Supports `==`, `!=`, `>`, `<`, `>=`, `<=`, and bare-`$VAR` truthy checks. Compound expressions and `# hyprlang noerror` fall back to the manual-conversion block.
- `submap = NAME` … `submap = reset` blocks translate to `hl.define_submap(NAME, function() <hl.bind…> end)`; binds inside the range are scoped to the named submap instead of leaking to the global keymap.

### Fixed

- `# hyprlang if/endif` body lines no longer emit unconditionally in Lua output — previously the directives were dropped while their wrapped assignments leaked into the result.
- `$name = value # comment` variable definitions no longer keep the trailing `# comment` as part of the value, fixing every downstream `$name` expansion.
- `workspace = N` inside a `windowrule { … }` block stays as a field of the surrounding `hl.window_rule({...})` call instead of leaking out as a separate `hl.workspace_rule(...)`.
- `source = $HOME/...` (and other unresolved `$NAME` references) now expand from the environment when no config-scope variable shadows them, matching how Hyprland resolves source paths.
- `bind = SUPER, J, layoutmsg, togglesplit,` (trailing comma) no longer glues the empty trailing field onto the dispatcher arg as `"togglesplit,"`.

## [0.6.4] - 2026-05-17

### Added

- `dpms` dispatcher support in Lua emitter
- `hyprctl dispatch` translation for Lua mode (Hyprland 0.55+): whole-command `hyprctl dispatch VERB ARGS` collapses to native `hl.dsp.*` dispatchers; when embedded in shell scripts (e.g. `sleep 1 && hyprctl dispatch …`), the inner dispatch is rewritten in place to preserve timing semantics

## [0.6.3] - 2026-05-17

### Added

- `hyprland_version` parameter to `check_deprecated` skips rules whose `version_deprecated` is newer than the running Hyprland, so callers only see deprecations that have actually taken effect. Pair with `migrate(..., to_version=hyprland_version)` for the same gate on the rewrite side.

### Fixed

- `movewindowpixel` / `resizewindowpixel` / `resizeactive` translation between Hyprlang and Lua: previously emitted a non-existent `exact = true` field and silently flipped the relative/absolute default. Both directions now use the `relative` boolean correctly, and the Lua reader translates `hl.dsp.window.move({x, y})` back to `movewindowpixel` instead of an invalid `window.move` literal.

## [0.6.2] - 2026-05-17

### Fixed

- Workspace rule field translation between Hyprlang and Lua: field name renames (`gapsin` ↔ `gaps_in`, `bordersize` ↔ `border_size`, `defaultName` ↔ `default_name`, `on-created-empty` ↔ `on_created_empty`), inverted boolean sense for `border`/`rounding`/`shadow` (Hyprlang `border:false` ↔ Lua `no_border = true`), and CSS-shorthand gap expansion (`gapsout:5 10` ↔ `{top=5, right=10, bottom=5, left=10}`). Unknown fields pass through unchanged.
- `check_deprecated` no longer flags Hyprland 0.53+ v3 `windowrule` lines (those with a `match:` token) as deprecated v1

### Removed

- `input:numlock_by_default` → `input:kb_numlock` rename migration and its `check_deprecated` warning https://github.com/BlueManCZ/hyprmod/issues/34

## [0.6.1] - 2026-05-16

### Added

- `emit_migration_markers` parameter to `serialize_lua()`, `serialize_lua_tree()`, and `serialize_any()` to control whether `exec-once` migration hints appear in Lua output; tools doing repeat round-trip serialization of managed configs can pass `False` to suppress hints for non-interactive saves

## [0.6.0] - 2026-05-16

### Added

- Comment-grouped Lua output: `# Section header` lines in the Hyprlang source now emit as `-- Section header` in the Lua output and split following assignments into their own `hl.config({...})` call, preserving the topical structure the user wrote
- Public exports for the animation grammar: `ANIMATION_TREE`, `ANIM_FLAT`, `ANIM_LOOKUP`, `ANIM_CHILDREN`, `HYPRLAND_NATIVE_CURVES`, `AnimationData`, `BezierData`, and `get_styles_for()`
- Public exports for v3 rule grammar: `V3_BOOL_EFFECTS`, `V3_BOOL_MATCHERS`, `LAYER_BOOL_EFFECTS`
- Public `split_top_level()` helper — bracket-aware comma splitter used for window-rule / layer-rule bodies

### Changed

- `serialize_lua()` / `serialize_lua_tree()` no longer prepend a `-- Generated by hyprland-config …` banner, and the one-shot converter no longer adds one either; empty documents now serialize to an empty string (API breaking change)

## [0.5.0] - 2026-05-14

### Added

- Lua support: `serialize_lua()` emits Lua configs, `load_lua()` reads Lua configs back into `Document`, and `load_any()` / `serialize_any()` auto-select format by file suffix
- Lua output covers bind variants, rules (`windowrule`/`windowrulev2`/`layerrule`), `workspace`, `gesture`, `permission`, `device`, `exec` family, `unbind`, and plugin loading
- `serialize_lua_tree()` emits one `.lua` file per sourced document and wires parents via `dofile(...)`, including `.conf.d` -> `.lua.d` remapping
- Hyprlang -> Lua converter: `analyze_conversion()` produces a dry-run `ConversionPlan` (with `UnmappedLine` reports); `execute_conversion()` commits it as an all-or-nothing batch via staged writes and returns a `ConversionResult`
- `serialize_hyprlang()` reconstructs a `Document`'s Hyprlang text from its line nodes (explicit replacement for `Document.serialize()`)
- `load_lua()` requires a system `lua` interpreter on `PATH`; raises `LuaReaderError` (subclass of `ParseError`) when missing or when the user's Lua config fails to execute
- New public helpers: `keyword_to_lua()`, `emit_keyword_line()`, `emit_option_assignment()`, `dispatch_to_lua()`, `define_submap_to_lua()`, `normalize_gradient_string()`, `default_config_dir()`, `default_hyprlang_entrypoint()`, `default_lua_entrypoint()`, `default_entrypoint()`, and `parse_version()`
- New public types: `LuaFile` (per-file output of `serialize_lua_tree`), `ConversionPlan`, `ConversionResult`, `UnmappedLine`, `LuaReaderError`
- New migration coverage for Hyprland v0.55 (`dwindle:pseudotile`, `misc:vfr`, `render:cm_fs_passthrough`, `decoration:shadow:ignore_window`)

### Removed

- `Document.serialize()` method removed (API breaking change); use module-level `serialize_hyprlang(doc)` instead

### Fixed

- Sectioned key moves in migrations now reinsert keys into the correct target section instead of only rewriting `full_key`
- IPC-style bare-hex gradients (`AARRGGBB ... Ndeg`) can now be normalized to config-safe `0x` tokens

## [0.4.5] - 2026-05-01

### Fixed

- `bindm` lines rejected by Hyprland with `bind: too many args` - `BindData.to_line()` no longer appends a trailing comma when `arg` is empty; `bindm` is strict about argument count where other bind variants tolerate either form. https://github.com/BlueManCZ/hyprmod/issues/20
- `parse_bind_line` rejects non-bind lines - keywords other than `bind` / `binde` / `bindm` / ... now return `None` instead of a bogus `BindData`
- Empty `XDG_CONFIG_HOME` is now treated the same as unset; previously it resolved against the current working directory

### Changed

- Booleans now serialize as `true` / `false` (canonical Hyprlang form), replacing IPC-style `0` / `1`
- `Document.iter_lines()`, `target_documents()`, and `mark_dirty()` are now public APIs
- `value_to_conf` is now a thin `str()` pass-through; gradient hex auto-`0x`-prefixing moved to `Gradient.parse()`

## [0.4.4] - 2026-04-29

### Added

- `windowrulev2` -> `windowrule` v3 migration for Hyprland 0.52 -> 0.53: keyword rename, `key:value` matchers rewritten to `match:KEY VALUE`, boolean effects now include required `on`, snake_case effect/matcher renames (`noblur` -> `no_blur`, `initialClass` -> `initial_class`, ...), and `~key:value` negation rewritten to `match:key negative:value`

### Fixed

- v3 `windowrule` lines are no longer downgraded to v2; v3 lines are now detected by the presence of a `match:` token and skipped by v1 -> v2 migration
- Recovery for configs corrupted by `hyprland-config<0.4.4`: malformed lines shaped as `windowrulev2 = match:..., title:<v3 effect> ...` are now recognized and cleaned up to valid v3 form

## [0.4.3] - 2026-04-20

### Fixed

- Flat-syntax preservation in migrations: renaming a deprecated option on a flat colon-prefixed line (for example `decoration:blur_size = 8`) no longer drops the section prefix and rewrites it as `size = 8`

### Changed

- Expression evaluator rewritten on top of `ast`; behavior preserved while replacing the handwritten tokenizer/parser in `_expr.py`
- Unified key matching in `_model.py`: `_match_key()` now takes a comparator, so glob and equality paths share one implementation

### Chore

- Dev dependencies refreshed: `hypothesis` 6.151.9 -> 6.152.1, `pytest` 9.0.2 -> 9.0.3, `ruff` 0.15.7 -> 0.15.11

## [0.4.2] - 2026-04-05

### Fixed

- Hyphenated variable names are now parsed correctly (for example `$terminal-float = kitty`). https://github.com/BlueManCZ/hyprmod/issues/9

## [0.4.1] - 2026-04-02

### Fixed

- Colon-namespaced section parsing: section names containing colons (for example `plugin:dynamic-cursors { }`) are now parsed correctly; previously parser failed to recognize them as valid section blocks. https://github.com/BlueManCZ/hyprmod/issues/8

## [0.4.0] - 2026-03-31

### Removed

- `ParseError.source` renamed to `ParseError.source_name` (API breaking change)
- `BindData.owned` field removed; it was always `True` and unused
- `Color.to_string()` removed; use `str(color)` or `color.to_rgba()`
- `Gradient.to_string()` and `Vec2.to_string()` removed; use `str(gradient)` and `str(vec2)`

### Fixed

- Hyphenated section names now parse correctly, including plugin sections like `split-monitor-workspaces { }` and one-line blocks like `split-monitor-workspaces { count = 2 }`. https://github.com/BlueManCZ/hyprmod/issues/2

### Changed

- Simplified migration internals: `_DeprecationRule` and `_Migration` no longer use `frozen=True` with `object.__setattr__()` workarounds; computed fields now set via normal `__post_init__` assignment
- Cleaner predicate naming in document model: internal `_kv_matches_key` wrapper removed, `_kv_predicate` renamed to `_key_predicate`
- Stricter gradient detection in `value_to_conf()`: bare `"deg"` substring check replaced with a `\b\d+deg\b` regex to avoid false positives on non-gradient strings

## [0.3.0] - 2026-03-26

### Added

- Keyword bare-key matching: `find("animation")` and `find_all("animation")` now match keywords inside sections (for example inside `animations { }`), matching Hyprland behavior; section-qualified lookups like `find("animations:animation")` still work. Assignments still require full section-qualified keys
- Source exclusion in `find_all()` via new `exclude_sources` parameter accepting a frozenset of resolved paths whose source documents should be skipped

### Changed

- Tighter type annotations in `_values.py`: `Any` return types replaced with `bool | int | float | str` on `coerce_config_value()` and `value_to_conf()`, and `"choice"` type is now handled as `int`
- Glob matching in `find_all()` now matches keywords by both bare key and full section-qualified key

## [0.2.0] - 2026-03-24

### Added

- `parse_bind_line()` parses `bind = MODS, KEY, dispatcher, arg` lines into structured `BindData` with combo normalization, round-trip serialization, and display formatting
- `coerce_config_value()` converts config strings to typed Python values (`bool`, `int`, `float`); `value_to_conf()` converts back and normalizes gradient hex tokens with `0x` prefixes
- Public `is_bind_keyword()` API to detect bind-variant keywords (`bind`, `binde`, `bindm`, ...)

### Changed

- Source exclusion in queries: `get()` and `find()` accept `exclude_sources` to skip specific source files during resolution
- `Color.parse()` now accepts bare `AARRGGBB` format (8-digit hex without `0x`) used by Hyprland IPC responses
- `Color`, `Gradient`, and `Vec2` dataclasses now use `slots=True` for lower memory usage

## [0.1.1] - 2026-03-24

### Fixed

- Packaging: sdist and wheel now include only package code; tests and other non-package files are excluded from published artifacts
- Type safety: replaced `type: ignore` suppression in `Document.find()` with a proper `cast`, and cleaned up variable unpacking in `Document.set_variable()`
- Migration: hoisted `_V2_PREFIXES` constant out of inner function in `_migrate_windowrule_v1_to_v2`

## [0.1.0] - 2026-03-21

Initial release - round-trip parser and editor for Hyprland configuration files.

### Added

- Round-trip editing that preserves comments, blank lines, and formatting
- `source = ...` following across multiple files with glob and `~` expansion, symlink support, and cycle detection
- Zero dependencies; pure Python (3.12+)
- Atomic writes (temp file + fsync + rename)
- Nested `category { }` blocks, `device[name] { }` keyed sections, inline syntax (`general:gaps_in = 5`), and one-line blocks
- `$variable` definitions and expansion
- Expression evaluation (`{{2 + 2}}`) with `\{{` escape support
- Conditional directives (`# hyprlang if/elif/else/endif`) and `# hyprlang noerror`
- Comments, inline comments, and `##` escape handling
- Special keywords including bind variants, monitor, animation, bezier, env, exec, workspace, and windowrule
- Lenient parsing mode where unparseable lines become error nodes instead of raising
- Deprecation checking and automatic migration covering Hyprland v0.33-v0.53+
- Dirty tracking so `save()` only writes files that changed
- `ParseError` with file name and line number on malformed input

[0.9.5]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.9.5
[0.9.4]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.9.4
[0.9.3]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.9.3
[0.9.2]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.9.2
[0.9.1]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.9.1
[0.9.0]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.9.0
[0.8.0]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.8.0
[0.7.0]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.7.0
[0.6.6]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.6.6
[0.6.5]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.6.5
[0.6.4]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.6.4
[0.6.3]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.6.3
[0.6.2]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.6.2
[0.6.1]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.6.1
[0.6.0]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.6.0
[0.5.0]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.5.0
[0.4.5]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.4.5
[0.4.4]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.4.4
[0.4.3]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.4.3
[0.4.2]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.4.2
[0.4.1]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.4.1
[0.4.0]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.4.0
[0.3.0]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.3.0
[0.2.0]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.2.0
[0.1.1]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.1.1
[0.1.0]: https://github.com/BlueManCZ/hyprland-config/releases/tag/v0.1.0
