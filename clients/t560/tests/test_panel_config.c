#include "test_panel_config.h"

#include "panel_config.h"

#include <glib.h>

/* A minimal Home Assistant state document for the config sensor. */
static gchar *state_json(const gchar *attributes)
{
    return g_strdup_printf(
        "{\"entity_id\":\"sensor.t560_config\",\"state\":\"ok\","
        "\"attributes\":{%s}}", attributes);
}

static gboolean parse(const gchar *attributes, PanelLayout *layout,
                      gchar **failure)
{
    gchar *json = state_json(attributes);
    gboolean parsed = panel_config_parse_json(json, -1, layout, failure);

    g_free(json);
    return parsed;
}

static const gchar *FULL_ATTRIBUTES =
    "\"profile\":\"t560\",\"slot_count\":6,"
    "\"player\":\"media_player.kitchen\","
    "\"queue\":\"sensor.controller_queue\","
    "\"playlists\":\"sensor.controller_playlists\","
    "\"revision\":2098342174,"
    "\"slots\":["
    "{\"slot\":1,\"entity\":\"light.controller_slot_1\","
    "\"label\":\"DESK LAMP\","
    "\"controls\":[\"toggle\",\"brightness\",\"color_temp\"],"
    "\"min_kelvin\":2202,\"max_kelvin\":4000},"
    "{\"slot\":4,\"entity\":\"switch.controller_slot_4\","
    "\"label\":\"FAN\",\"controls\":[\"toggle\"]}]";

static void test_full_payload(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(FULL_ATTRIBUTES, &layout, &failure));
    g_assert_null(failure);
    g_assert_cmpstr(layout.player_entity, ==, "media_player.kitchen");
    g_assert_cmpstr(layout.queue_entity, ==, "sensor.controller_queue");
    g_assert_cmpuint(layout.room_count, ==, 2);
    g_assert_cmpint((gint)layout.revision, ==, 2098342174);

    g_assert_cmpuint(layout.rooms[0].slot, ==, 1);
    g_assert_cmpstr(layout.rooms[0].label, ==, "DESK LAMP");
    g_assert_true(layout.rooms[0].brightness);
    g_assert_true(layout.rooms[0].color_temperature);
    g_assert_cmpint(layout.rooms[0].min_kelvin, ==, 2202);
    g_assert_cmpint(layout.rooms[0].max_kelvin, ==, 4000);

    /* Slot numbers are not positions: slot 4 is the second tile here. */
    g_assert_cmpuint(layout.rooms[1].slot, ==, 4);
    g_assert_false(layout.rooms[1].brightness);
    g_assert_false(layout.rooms[1].color_temperature);

    panel_layout_clear(&layout);
}

/* A control this build does not know must be ignored, so that the
 * integration can add one without breaking a panel already in the field. */
static void test_unknown_control_is_ignored(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\",\"slots\":[{\"slot\":1,"
        "\"entity\":\"light.a\",\"label\":\"A\","
        "\"controls\":[\"toggle\",\"rgb\",\"brightness\"]}]",
        &layout, &failure));
    g_assert_cmpuint(layout.room_count, ==, 1);
    g_assert_true(layout.rooms[0].brightness);
    g_assert_false(layout.rooms[0].color_temperature);

    panel_layout_clear(&layout);
}

static void test_empty_slot_list(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\",\"slots\":[]", &layout, &failure));
    g_assert_cmpuint(layout.room_count, ==, 0);
    g_assert_cmpstr(layout.player_entity, ==, "media_player.a");

    panel_layout_clear(&layout);
}

static void test_missing_controller_entities_fail(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_false(parse("\"slots\":[]", &layout, &failure));
    g_assert_nonnull(failure);
    g_free(failure);
    panel_layout_clear(&layout);
}

static void test_slot_without_entity_is_skipped(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\",\"slots\":[{\"slot\":1},"
        "{\"slot\":2,\"entity\":\"switch.b\",\"label\":\"B\","
        "\"controls\":[\"toggle\"]}]",
        &layout, &failure));
    g_assert_cmpuint(layout.room_count, ==, 1);
    g_assert_cmpstr(layout.rooms[0].entity, ==, "switch.b");

    panel_layout_clear(&layout);
}

/* The panel draws six tiles. A longer list is truncated rather than trusted,
 * because the fixed-size arrays behind it are what keep the tablet fast. */
static void test_more_slots_than_the_panel_draws(void)
{
    GString *slots = g_string_new("");
    PanelLayout layout = {0};
    gchar *failure = NULL;

    for (guint i = 1; i <= PANEL_ROOM_MAX + 3; i++) {
        g_string_append_printf(
            slots,
            "%s{\"slot\":%u,\"entity\":\"switch.s%u\",\"label\":\"S\","
            "\"controls\":[\"toggle\"]}", i > 1 ? "," : "", i, i);
    }
    gchar *attributes = g_strdup_printf(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\",\"slots\":[%s]", slots->str);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(layout.room_count, ==, PANEL_ROOM_MAX);

    panel_layout_clear(&layout);
    g_free(attributes);
    g_string_free(slots, TRUE);
}

static void test_broken_kelvin_bounds_fall_back(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\",\"slots\":[{\"slot\":1,"
        "\"entity\":\"light.a\",\"label\":\"A\","
        "\"controls\":[\"toggle\",\"color_temp\"],"
        "\"min_kelvin\":9000,\"max_kelvin\":3000}]",
        &layout, &failure));
    g_assert_cmpint(layout.rooms[0].min_kelvin, ==, 2000);
    g_assert_cmpint(layout.rooms[0].max_kelvin, ==, 6500);

    panel_layout_clear(&layout);
}

static void test_invalid_json_is_reported(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_false(panel_config_parse_json("not json", -1, &layout, &failure));
    g_assert_nonnull(failure);
    g_free(failure);
    panel_layout_clear(&layout);
}

/* Settings and commands are optional. A payload from an integration that
 * predates them, or one whose blocks are the wrong shape, must leave the
 * panel on its config.ini fallback rather than fail. */
static void test_payload_without_settings_or_commands(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(FULL_ATTRIBUTES, &layout, &failure));
    g_assert_false(layout.settings.present);
    g_assert_cmpint(layout.settings.screen_off_seconds, ==, -1);
    g_assert_false(layout.settings.player_skin_present);
    g_assert_null(layout.commands.display_state);
    g_assert_cmpint((gint)layout.commands.display_at, ==, 0);
    g_assert_cmpint((gint)layout.commands.restart_at, ==, 0);
    g_assert_null(layout.commands.page);

    panel_layout_clear(&layout);
}

static void test_settings_are_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\","
        "\"settings\":{\"poll_interval_ms\":2500,"
        "\"playlist_poll_interval_ms\":120000,"
        "\"screen_off_seconds\":90}",
        &layout, &failure));
    g_assert_true(layout.settings.present);
    g_assert_cmpuint(layout.settings.poll_interval_ms, ==, 2500);
    g_assert_cmpuint(layout.settings.playlist_poll_interval_ms, ==, 120000);
    g_assert_cmpint(layout.settings.screen_off_seconds, ==, 90);
    /* A settings block that names no skin leaves config.ini deciding. */
    g_assert_false(layout.settings.player_skin_present);

    panel_layout_clear(&layout);
}

static void test_player_skin_is_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\","
        "\"settings\":{\"player_skin\":\"cassette\"}",
        &layout, &failure));
    g_assert_true(layout.settings.present);
    g_assert_true(layout.settings.player_skin_present);
    g_assert_cmpint(layout.settings.player_skin, ==,
                    PANEL_PLAYER_SKIN_CASSETTE);

    panel_layout_clear(&layout);
}

/* A skin added to the integration after this build was flashed arrives as a
 * name it has never heard of. Somebody did choose, so it is a choice this
 * build cannot honour: draw the default rather than nothing. */
static void test_unknown_player_skin_falls_back(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\","
        "\"settings\":{\"player_skin\":\"cover_card\"}",
        &layout, &failure));
    g_assert_true(layout.settings.player_skin_present);
    g_assert_cmpint(layout.settings.player_skin, ==,
                    PANEL_PLAYER_SKIN_MODERN);

    panel_layout_clear(&layout);
}

/* An empty name is nobody choosing, not a choice of nothing. */
static void test_empty_player_skin_is_not_a_choice(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\","
        "\"settings\":{\"player_skin\":\"\"}",
        &layout, &failure));
    g_assert_true(layout.settings.present);
    g_assert_false(layout.settings.player_skin_present);

    panel_layout_clear(&layout);
}

/* Home Assistant clamps before it sends, so these bounds only guard against a
 * payload that did not come from it. */
static void test_settings_are_clamped(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\","
        "\"settings\":{\"poll_interval_ms\":1,"
        "\"playlist_poll_interval_ms\":999999999,"
        "\"screen_off_seconds\":0}",
        &layout, &failure));
    g_assert_cmpuint(layout.settings.poll_interval_ms, ==, 500);
    g_assert_cmpuint(layout.settings.playlist_poll_interval_ms, ==, 3600000);
    /* Zero is a value, not a missing setting: it disables the screen off. */
    g_assert_cmpint(layout.settings.screen_off_seconds, ==, 0);

    panel_layout_clear(&layout);
}

static void test_commands_are_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\","
        "\"commands\":{"
        "\"display\":{\"state\":\"off\",\"at\":1756800000000},"
        "\"brightness\":{\"value\":60,\"at\":1756800000100},"
        "\"restart\":{\"at\":1756800000200},"
        "\"page\":{\"value\":\"room\",\"at\":1756800000300}}",
        &layout, &failure));
    g_assert_cmpstr(layout.commands.display_state, ==, "off");
    g_assert_cmpstr(layout.commands.page, ==, "room");
    g_assert_true(layout.commands.page_at ==
                  G_GINT64_CONSTANT(1756800000300));
    g_assert_true(layout.commands.display_at == G_GINT64_CONSTANT(1756800000000));
    g_assert_cmpint(layout.commands.brightness, ==, 60);
    g_assert_true(layout.commands.brightness_at ==
                  G_GINT64_CONSTANT(1756800000100));
    g_assert_true(layout.commands.restart_at ==
                  G_GINT64_CONSTANT(1756800000200));

    panel_layout_clear(&layout);
}

/* A command without a moment cannot be ordered against the last one applied,
 * and one this build does not know must not stop the rest being read. */
static void test_malformed_commands_are_ignored(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\","
        "\"commands\":{"
        "\"display\":{\"state\":\"dim\",\"at\":1756800000000},"
        "\"brightness\":{\"value\":60},"
        "\"reboot\":{\"at\":1756800000200},"
        "\"page\":{\"value\":\"\",\"at\":1756800000400},"
        "\"restart\":{\"at\":1756800000300}}",
        &layout, &failure));
    g_assert_null(layout.commands.display_state);
    g_assert_null(layout.commands.page);
    g_assert_cmpint((gint)layout.commands.page_at, ==, 0);
    g_assert_cmpint((gint)layout.commands.display_at, ==, 0);
    g_assert_cmpint((gint)layout.commands.brightness_at, ==, 0);
    g_assert_true(layout.commands.restart_at ==
                  G_GINT64_CONSTANT(1756800000300));

    panel_layout_clear(&layout);
}

/* The blocks are objects. A producer that sent something else must read as
 * "absent" rather than abort the panel. */
static void test_wrongly_typed_blocks_are_ignored(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\","
        "\"settings\":[1,2],\"commands\":\"none\"",
        &layout, &failure));
    g_assert_false(layout.settings.present);
    g_assert_null(layout.commands.display_state);

    panel_layout_clear(&layout);
}

/* The number the two halves of the contract actually compare. An integration
 * built before the field existed sends nothing at all, so an absent value has
 * to read as 0 rather than as the current version: the application treats 0
 * as older than itself and says so on the status line. */
static void test_contract_version_is_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(
        "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
        "\"playlists\":\"sensor.p\",\"contract_version\":4",
        &layout, &failure));
    g_assert_null(failure);
    g_assert_cmpint(layout.contract_version, ==, 4);

    panel_layout_clear(&layout);
}

static void test_missing_contract_version_is_zero(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(FULL_ATTRIBUTES, &layout, &failure));
    g_assert_cmpint(layout.contract_version, ==, 0);

    panel_layout_clear(&layout);
}

/* A value that is not a positive number says nothing about the other side, so
 * it is read as "named none" rather than believed. */
static void test_unusable_contract_version_is_zero(void)
{
    const gchar *values[] = {"\"four\"", "0", "-3", "null"};

    for (guint i = 0; i < G_N_ELEMENTS(values); i++) {
        PanelLayout layout = {0};
        gchar *failure = NULL;
        gchar *attributes = g_strdup_printf(
            "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
            "\"playlists\":\"sensor.p\",\"contract_version\":%s",
            values[i]);

        g_assert_true(parse(attributes, &layout, &failure));
        g_assert_cmpint(layout.contract_version, ==, 0);
        g_free(attributes);
        panel_layout_clear(&layout);
    }
}

void panel_config_tests_register(void)
{
    g_test_add_func("/config/full-payload", test_full_payload);
    g_test_add_func("/config/unknown-control",
                    test_unknown_control_is_ignored);
    g_test_add_func("/config/empty-slot-list", test_empty_slot_list);
    g_test_add_func("/config/missing-controller-entities",
                    test_missing_controller_entities_fail);
    g_test_add_func("/config/slot-without-entity",
                    test_slot_without_entity_is_skipped);
    g_test_add_func("/config/slot-overflow",
                    test_more_slots_than_the_panel_draws);
    g_test_add_func("/config/kelvin-bounds",
                    test_broken_kelvin_bounds_fall_back);
    g_test_add_func("/config/invalid-json", test_invalid_json_is_reported);
    g_test_add_func("/config/no-settings-or-commands",
                    test_payload_without_settings_or_commands);
    g_test_add_func("/config/settings", test_settings_are_read);
    g_test_add_func("/config/settings-clamped", test_settings_are_clamped);
    g_test_add_func("/config/player-skin", test_player_skin_is_read);
    g_test_add_func("/config/player-skin-unknown",
                    test_unknown_player_skin_falls_back);
    g_test_add_func("/config/player-skin-empty",
                    test_empty_player_skin_is_not_a_choice);
    g_test_add_func("/config/commands", test_commands_are_read);
    g_test_add_func("/config/commands-malformed",
                    test_malformed_commands_are_ignored);
    g_test_add_func("/config/blocks-wrong-type",
                    test_wrongly_typed_blocks_are_ignored);
    g_test_add_func("/config/contract-version", test_contract_version_is_read);
    g_test_add_func("/config/contract-version-missing",
                    test_missing_contract_version_is_zero);
    g_test_add_func("/config/contract-version-unusable",
                    test_unusable_contract_version_is_zero);
}
