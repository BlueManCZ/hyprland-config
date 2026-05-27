"""v3 windowrule / layerrule grammar constants.

The boolean-effect and boolean-matcher sets are intrinsic to the rule
grammar — Hyprland 0.53+ rejects bare boolean effects with "missing a value",
so every emitter (live-apply via ``hl.keyword``, on-disk serialization, the
v2→v3 migration) needs to auto-fill ``on``. Centralised here so the three
consumers share one source of truth.
"""

# v3 ``windowrule`` effects whose only argument is a boolean. Emitters
# auto-fill ``on`` when the args field is empty so Hyprland 0.53+ accepts
# the line.
V3_BOOL_EFFECTS: frozenset[str] = frozenset(
    {
        # Static
        "float", "tile", "fullscreen", "maximize", "center", "pseudo",
        "no_initial_focus", "pin",
        # Dynamic
        "persistent_size", "no_max_size", "stay_focused",
        "allows_input", "dim_around", "decorate", "focus_on_activate",
        "keep_aspect_ratio", "nearest_neighbor",
        "no_anim", "no_blur", "no_dim", "no_focus", "no_follow_mouse",
        "no_shadow", "no_shortcuts_inhibit", "no_screen_share", "no_vrr",
        "opaque", "force_rgbx", "sync_fullscreen", "immediate", "xray",
        "render_unfocused",
    }
)  # fmt: skip


# v3 ``windowrule`` matcher keys whose value is a boolean (``true``/``false``).
V3_BOOL_MATCHERS: frozenset[str] = frozenset(
    {"xwayland", "float", "fullscreen", "pin", "focus", "group", "modal"}
)


# v3 ``layerrule`` effects whose only argument is a boolean. Hyprland 0.54.3
# rejects bare bool layer effects with "missing a value", same as v3 windowrule
# effects.
LAYER_BOOL_EFFECTS: frozenset[str] = frozenset(
    {
        "no_anim",
        "blur",
        "blur_popups",
        "dim_around",
        "xray",
        "no_screen_share",
    }
)


# ---------------------------------------------------------------------------
# v2 ↔ v3 renames + version boundaries
# ---------------------------------------------------------------------------
#
# The v2→v3 migration (:mod:`hyprland_config._migrate._windowrule`) reads
# these to rewrite old config text; the Hyprlang serializer inverts them to
# emit pre-v3 syntax when the *running* compositor predates the v3 grammar.
# Both directions key off the same data so the round-trip stays consistent.

# Hyprland version at which each rule kind adopted the v3 ``match:`` grammar.
# Below the boundary the serializer falls back to the older effect-first form
# (window: ``windowrulev2 = float, class:^(x)$``; layer: ``layerrule = blur,
# ^(x)$``).
WINDOWRULE_V3_VERSION: tuple[int, int] = (0, 53)
LAYERRULE_V3_VERSION: tuple[int, int] = (0, 54)

# v2 effects that were removed in v3 and replaced by a different effect
# with a fixed argument. The migration uses the full ``(name, args)`` pair
# directly instead of going through the rename+bool-fill path.
V2_EFFECT_REPLACEMENTS: dict[str, tuple[str, str]] = {
    "noborder": ("border_size", "0"),
    "norounding": ("rounding", "0"),
}

# v2 → v3 windowrule effect renames. Anything absent is unchanged in v3
# (including custom plugin actions).
V2_TO_V3_EFFECT: dict[str, str] = {
    "noblur": "no_blur",
    "noshadow": "no_shadow",
    "noanim": "no_anim",
    "nodim": "no_dim",
    "nofocus": "no_focus",
    "noinitialfocus": "no_initial_focus",
    "nofollowmouse": "no_follow_mouse",
    "noshortcutsinhibit": "no_shortcuts_inhibit",
    "noscreenshare": "no_screen_share",
    "novrr": "no_vrr",
    "nomaxsize": "no_max_size",
    "stayfocused": "stay_focused",
    "idleinhibit": "idle_inhibit",
    "bordercolor": "border_color",
    "bordersize": "border_size",
    "maxsize": "max_size",
    "minsize": "min_size",
    "suppressevent": "suppress_event",
    "noclosefor": "no_close_for",
    "syncfullscreen": "sync_fullscreen",
    "forcergbx": "force_rgbx",
    "focusonactivate": "focus_on_activate",
    "keepaspectratio": "keep_aspect_ratio",
    "nearestneighbor": "nearest_neighbor",
    "renderunfocused": "render_unfocused",
    "scrollmouse": "scroll_mouse",
    "scrolltouchpad": "scroll_touchpad",
    "scrollingwidth": "scrolling_width",
    "allowsinput": "allows_input",
    "dimaround": "dim_around",
    "persistentsize": "persistent_size",
    "fullscreenstate": "fullscreen_state",
    "roundingpower": "rounding_power",
}

# v2 → v3 windowrule matcher key renames. ``floating`` → ``float`` and
# ``pinned`` → ``pin``: in v3 the matcher key matches the effect word.
V2_TO_V3_MATCHER: dict[str, str] = {
    "initialClass": "initial_class",
    "initialTitle": "initial_title",
    "floating": "float",
    "pinned": "pin",
    "xdgtag": "xdg_tag",
    # ``onworkspace`` collapsed into ``workspace`` in v3.
    "onworkspace": "workspace",
    "fullscreenstate": "fullscreen_state",
}

# Inverse maps, used by the serializer to emit pre-v3 syntax. The forward
# maps are injective, so the inverse is unambiguous.
V3_TO_V2_EFFECT: dict[str, str] = {v: k for k, v in V2_TO_V3_EFFECT.items()}
V3_TO_V2_MATCHER: dict[str, str] = {v: k for k, v in V2_TO_V3_MATCHER.items()}

# v3 → pre-0.54 ``layerrule`` effect renames. Layer rules gained both the
# ``match:`` grammar and snake_case effect names in 0.54; below that the
# old run-together spellings apply.
V3_TO_LEGACY_LAYER_EFFECT: dict[str, str] = {
    "no_anim": "noanim",
    "blur_popups": "blurpopups",
    "dim_around": "dimaround",
    "ignore_alpha": "ignorealpha",
}
