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
}
