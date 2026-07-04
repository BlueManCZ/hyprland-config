-- Record every hl.* call made by a Hyprland Lua config file.
--
-- Driver: hyprland_config._lua_reader._runner. The Python side invokes this
-- script as `lua _wrapper.lua <user_config_path>` and reads recorded calls
-- as one JSON object per stdout line.
--
-- We deliberately don't try to evaluate or replay any side effects — the
-- only purpose is to surface the static-after-evaluation structure of a
-- user's Lua config so a tool can populate UI / round-trip-ish.
--
-- Why this layer exists: the user's Lua can include loops, locals,
-- string concatenation, dofile() chains, and callbacks. Hand-rolling a
-- Lua subset parser to handle all of that is fragile; running real Lua
-- with mocked `hl` / `hl.dsp` tables is robust and small.

local records = {}
local current_source = ""
-- Directory of the main config file, with trailing slash. Hyprland resolves
-- require() against package.path = "<configdir>/?.lua;<configdir>/?/init.lua"
-- (src/config/lua/ConfigManager.cpp) — always relative to the main file's
-- directory, never the requiring file's. We mirror that so dotted module
-- names (require("modules.monitors")) resolve to the file Hyprland would
-- load, even when the require sits in a nested sub-file. Set at entry below.
local config_root_dir = ""
-- nil when at top level (treat exec_cmd as a generic "exec"), or the
-- event name when inside an hl.on callback so the recorder can tag the
-- exec with hyprland.start / hyprland.shutdown.
local current_event = nil

-- ----------------------------------------------------------------------
-- JSON serializer
--   Small enough to inline. Handles: nil, boolean, number, string,
--   array tables (1..#t), and dict tables (mixed keys).
-- ----------------------------------------------------------------------

local function escape_string(s)
    -- string.format("%q", ...) handles most cases but escapes ``\n`` as
    -- ``\<newline>`` (literal newline preceded by backslash) which breaks
    -- our line-per-record framing. Build the escape ourselves.
    s = s:gsub("\\", "\\\\")
    s = s:gsub('"', '\\"')
    s = s:gsub("\n", "\\n")
    s = s:gsub("\r", "\\r")
    s = s:gsub("\t", "\\t")
    s = s:gsub("\b", "\\b")
    s = s:gsub("\f", "\\f")
    -- Strip remaining control chars (JSON forbids them in strings).
    s = s:gsub("[%c]", function(c) return string.format("\\u%04x", string.byte(c)) end)
    return '"' .. s .. '"'
end

local encode
encode = function(v)
    local t = type(v)
    if t == "nil" then
        return "null"
    elseif t == "boolean" then
        return tostring(v)
    elseif t == "number" then
        if v ~= v then
            return "null"  -- NaN
        elseif v == math.huge or v == -math.huge then
            return "null"
        elseif v == math.floor(v) and math.abs(v) < 1e15 then
            return tostring(math.floor(v))
        end
        return tostring(v)
    elseif t == "string" then
        return escape_string(v)
    elseif t == "table" then
        -- Decide between array-style (sequential 1..N) and dict-style.
        local n = #v
        local is_dict = false
        local count = 0
        for k, _ in pairs(v) do
            count = count + 1
            if type(k) ~= "number" or k < 1 or k > n or k ~= math.floor(k) then
                is_dict = true
                break
            end
        end
        if not is_dict and count ~= n then
            is_dict = true  -- sparse array → treat as dict
        end
        if is_dict then
            local parts = {}
            local keys = {}
            for k in pairs(v) do keys[#keys+1] = k end
            table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
            for _, k in ipairs(keys) do
                parts[#parts+1] = escape_string(tostring(k)) .. ":" .. encode(v[k])
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
        local parts = {}
        for i = 1, n do
            parts[i] = encode(v[i])
        end
        return "[" .. table.concat(parts, ",") .. "]"
    end
    -- Function / userdata / thread: serialise as null with a tag in the
    -- holder. Callers usually expect a stub.
    return "null"
end

-- ----------------------------------------------------------------------
-- Recorder
-- ----------------------------------------------------------------------

local function record(call, ...)
    local args = {...}
    -- table.pack would set .n, which we don't want serialised. Keep the
    -- positional list as a plain array — Lua's ``select("#", ...)`` would
    -- count nils, but for hl.* args we don't expect nil holes.
    records[#records+1] = {
        call = call,
        args = args,
        source = current_source,
    }
end

-- ----------------------------------------------------------------------
-- Mock hl table
-- ----------------------------------------------------------------------

hl = {}

hl.config = function(t) record("config", t) end
hl.env = function(name, value) record("env", name, value) end
hl.monitor = function(t) record("monitor", t) end
hl.curve = function(name, t) record("curve", name, t) end
hl.animation = function(t) record("animation", t) end
hl.window_rule = function(t) record("window_rule", t) end
hl.layer_rule = function(t) record("layer_rule", t) end
hl.workspace_rule = function(t) record("workspace_rule", t) end
hl.gesture = function(t) record("gesture", t) end
hl.permission = function(...) record("permission", ...) end
hl.device = function(t) record("device", t) end
hl.bind = function(keys, dispatcher, flags) record("bind", keys, dispatcher, flags) end
hl.unbind = function(keys) record("unbind", keys) end

-- ``hl.plugin`` is a namespace table on real Hyprland (``hl.plugin.load(path)``
-- is the actual call shape). Without an explicit shim the catch-all
-- ``__index`` below makes ``hl.plugin`` a no-op function and ``hl.plugin.load``
-- crashes with "attempt to index a function value".
hl.plugin = {
    load = function(path) record("plugin_load", path) end,
}
local _dummy_plugin_table = {}
setmetatable(_dummy_plugin_table, {
    __index = function(self, key) return _dummy_plugin_table end,
    __newindex = function(self, key, value) end,
    __call = function(...) return _dummy_plugin_table end,
})

setmetatable(hl.plugin, {
    __index = function(self, key)
        if key == "load" then return rawget(self, key) end
        return _dummy_plugin_table
    end
})

-- Submap declaration runs its body inline so the body's hl.bind calls
-- land in the main record list. The Document model has no submap nesting,
-- so we don't emit start/end markers — the binds inside become regular
-- top-level binds. Lossy on purpose; recovering submap context here would
-- need a Document representation we don't yet have.
hl.define_submap = function(name, reset_or_fn, fn)
    local body = fn or reset_or_fn
    if type(body) == "function" then
        local ok, err = pcall(body)
        if not ok then
            record("__error", "submap body failed: " .. tostring(err))
        end
    end
end

-- hl.on registers an event handler. We execute the callback so any
-- ``hl.exec_cmd`` calls inside get recorded — that's where users put
-- their autostart commands per the example config. ``current_event``
-- tells the recorded call which event it belongs to so the Python side
-- can route it back to ``exec`` / ``exec-shutdown``.
hl.on = function(event, callback)
    if type(callback) == "function" then
        local prev = current_event
        current_event = event
        local ok, err = pcall(callback)
        if not ok then
            record("__error", "hl.on(" .. tostring(event) .. ") callback failed: " .. tostring(err))
        end
        current_event = prev
    end
end

-- Tag immediate exec_cmd with the surrounding hl.on event so the Python
-- side can route it to the right Hyprlang keyword.
hl.exec_cmd = function(cmd, rules) record("exec_cmd", cmd, current_event) end
hl.dispatch = function(d) record("dispatch_immediate", d) end

-- Things we explicitly ignore (timers, version checks, etc.) — they
-- have no on-disk-config equivalent. Reading them would just add noise.
hl.timer = function() end
hl.version = function() return "0.0.0" end
hl.print = print

-- Anything else under hl gets a no-op shim so unknown future APIs don't
-- blow up the reader.
setmetatable(hl, {__index = function() return function() end end})

-- ----------------------------------------------------------------------
-- Mock hl.dsp — dispatcher factories return tagged tables we can
-- recognise when they appear as the second arg to hl.bind.
-- ----------------------------------------------------------------------

local function make_dispatcher_factory(qualified_name)
    return function(...)
        local args = {...}
        return {
            __dsp = qualified_name,
            args = args,
        }
    end
end

-- A "namespace" entry under hl.dsp can be:
--   - called as a function: hl.dsp.workspace(1)
--     (some configs and the older wiki examples treat the namespace
--     itself as a shorthand dispatcher — switch to workspace 1 / focus
--     the cursor, etc.)
--   - indexed for sub-dispatchers: hl.dsp.workspace.toggle_special("scratch"),
--     hl.dsp.window.close(), hl.dsp.group.next(), etc.
-- Support both by giving each namespace a metatable with __call and
-- __index; calling the namespace records as ``<prefix>`` and indexing
-- records as ``<prefix>.<sub>`` once that field is invoked.
local function make_dsp_namespace(prefix)
    return setmetatable({}, {
        __index = function(_, name)
            return make_dispatcher_factory(prefix .. "." .. name)
        end,
        __call = function(_, ...)
            return make_dispatcher_factory(prefix)(...)
        end,
    })
end

hl.dsp = setmetatable({
    cursor = make_dsp_namespace("cursor"),
    group = make_dsp_namespace("group"),
    window = make_dsp_namespace("window"),
    workspace = make_dsp_namespace("workspace"),
}, {
    __index = function(_, name)
        return make_dispatcher_factory(name)
    end,
})

-- ----------------------------------------------------------------------
-- dofile recursion: emit enter/exit markers so the Python side can
-- rebuild the scope tree (parent Document with a Source node wrapping
-- each sub-Document, matching how the Hyprlang parser models
-- ``source = …``). The enter marker is tagged with the parent file
-- (so it lives in the parent's line list); the body's records carry
-- the sub-file path; the exit marker is tagged with the parent again.
-- ----------------------------------------------------------------------

local _real_loadfile = loadfile

function dofile(path)
    record("__dofile_enter", path)
    local prev = current_source
    current_source = path
    local f, err = _real_loadfile(path)
    if not f then
        record("__error", "dofile load failed: " .. tostring(err))
        current_source = prev
        record("__dofile_exit", path)
        return
    end
    -- Preserve the chunk's return value — real ``dofile`` returns
    -- whatever the loaded file returns, and some configs rely on this
    -- to expose helper tables to the parent scope.
    local ok, result = pcall(f)
    if not ok then
        record("__error", tostring(result))
        result = nil
    end
    current_source = prev
    record("__dofile_exit", path)
    return result
end

-- Some configs (and everything the migrator emits) use require for
-- sub-files. Resolve it the way Hyprland does — against the config root,
-- trying "<root>/<mod>.lua" then "<root>/<mod>/init.lua", the two
-- package.path templates — and route the hit through the same enter/exit
-- markers as dofile so the recorded source is the real file path. Anything
-- we can't resolve falls back to the real require (which may still find a
-- system module via the default package path).
local _real_require = require
function require(modname)
    if config_root_dir ~= "" then
        local rel = config_root_dir .. modname:gsub("%.", "/")
        for _, candidate in ipairs({ rel .. ".lua", rel .. "/init.lua" }) do
            local f = _real_loadfile(candidate)
            if f then
                record("__dofile_enter", candidate)
                local prev = current_source
                current_source = candidate
                local ok, result = pcall(f)
                current_source = prev
                record("__dofile_exit", candidate)
                if not ok then
                    record("__error", "require failed: " .. tostring(result))
                    return
                end
                return result
            end
        end
    end
    local ok, result = pcall(_real_require, modname)
    if not ok then
        record("__error", "require failed: " .. tostring(result))
        return nil
    end
    return result
end

-- ----------------------------------------------------------------------
-- Entry: load the user file, then dump records.
-- ----------------------------------------------------------------------

local user_file = arg[1]
if not user_file then
    io.stderr:write("usage: lua _wrapper.lua <config_path>\n")
    os.exit(2)
end

current_source = user_file
config_root_dir = user_file:match("(.*/)") or ""
local entry, err = _real_loadfile(user_file)
if not entry then
    io.stderr:write("load failed: " .. tostring(err) .. "\n")
    os.exit(1)
end

local ok, perr = pcall(entry)
if not ok then
    record("__error", tostring(perr))
end

for _, r in ipairs(records) do
    print(encode(r))
end
