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

static const PanelEntity *entity_at(const PanelLayout *layout, guint index)
{
    g_assert_nonnull(layout->entities);
    g_assert_cmpuint(index, <, layout->entities->len);
    return g_ptr_array_index(layout->entities, index);
}

static guint entity_count(const PanelLayout *layout)
{
    return layout->entities != NULL ? layout->entities->len : 0;
}

static const gchar *CONTROLLER_ENTITIES =
    "\"player\":\"media_player.a\",\"queue\":\"sensor.q\","
    "\"playlists\":\"sensor.p\"";

static const gchar *FULL_ATTRIBUTES =
    "\"profile\":\"t560\",\"entity_limit\":100,"
    "\"player\":\"media_player.kitchen\","
    "\"queue\":\"sensor.controller_queue\","
    "\"playlists\":\"sensor.controller_playlists\","
    "\"revision\":2098342174,"
    "\"entities\":["
    "{\"rid\":\"a3f1c92d\",\"entity\":\"light.desk_lamp\","
    "\"name\":\"Desk lamp\",\"domain\":\"light\","
    "\"controls\":[\"toggle\",\"brightness\",\"color_temp\"],"
    "\"min_kelvin\":2202,\"max_kelvin\":4000},"
    "{\"rid\":\"b7e4180a\",\"entity\":\"switch.fan\","
    "\"name\":\"Fan\",\"domain\":\"switch\",\"controls\":[\"toggle\"]}]";

static void test_full_payload(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(FULL_ATTRIBUTES, &layout, &failure));
    g_assert_null(failure);
    g_assert_cmpstr(layout.player_entity, ==, "media_player.kitchen");
    g_assert_cmpstr(layout.queue_entity, ==, "sensor.controller_queue");
    g_assert_cmpuint(entity_count(&layout), ==, 2);
    g_assert_cmpint((gint)layout.revision, ==, 2098342174);

    /* The rid is the identity a card is keyed on, not the entity ID. */
    g_assert_cmpstr(entity_at(&layout, 0)->rid, ==, "a3f1c92d");
    g_assert_cmpstr(entity_at(&layout, 0)->entity, ==, "light.desk_lamp");
    g_assert_cmpstr(entity_at(&layout, 0)->name, ==, "Desk lamp");
    g_assert_cmpstr(entity_at(&layout, 0)->domain, ==, "light");
    g_assert_true(entity_at(&layout, 0)->brightness);
    g_assert_true(entity_at(&layout, 0)->color_temperature);
    g_assert_cmpint(entity_at(&layout, 0)->min_kelvin, ==, 2202);
    g_assert_cmpint(entity_at(&layout, 0)->max_kelvin, ==, 4000);

    g_assert_cmpstr(entity_at(&layout, 1)->domain, ==, "switch");
    g_assert_false(entity_at(&layout, 1)->brightness);
    g_assert_false(entity_at(&layout, 1)->color_temperature);

    /* The element with this rid is what a card resolves against. */
    g_assert_nonnull(panel_layout_find_entity(&layout, "b7e4180a"));
    g_assert_cmpstr(panel_layout_find_entity(&layout, "b7e4180a")->entity, ==,
                    "switch.fan");
    g_assert_null(panel_layout_find_entity(&layout, "deadbeef"));

    panel_layout_clear(&layout);
}

/* The name is UTF-8 and is whatever the user typed. Cyrillic and every other
 * script has to survive the payload intact. */
static void test_names_survive_unicode(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"a1b2c3d4\",\"entity\":\"light.a\","
        "\"name\":\"\\u041d\\u0430\\u0441\\u0442\\u0456\\u043b\\u044c\\u043d"
        "\\u0430 \\u043b\\u0430\\u043c\\u043f\\u0430\",\"domain\":\"light\","
        "\"controls\":[\"toggle\"]}]", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpstr(entity_at(&layout, 0)->name, ==, "Настільна лампа");
    g_assert_true(g_utf8_validate(entity_at(&layout, 0)->name, -1, NULL));

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A control this build does not know must be ignored, so that the
 * integration can add one without breaking a panel already in the field. */
static void test_unknown_control_is_ignored(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"a1b2c3d4\",\"entity\":\"light.a\","
        "\"name\":\"A\",\"domain\":\"light\","
        "\"controls\":[\"toggle\",\"rgb\",\"brightness\"]}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_true(entity_at(&layout, 0)->togglable);
    g_assert_true(entity_at(&layout, 0)->brightness);
    g_assert_false(entity_at(&layout, 0)->color_temperature);
    g_assert_false(entity_at(&layout, 0)->target_temperature);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* The same rule from the other side, and the one that lets a card type ship
 * on its own: a payload from an integration newer than this build carries
 * control names this build has never heard of, and the controls it does know
 * still arrive. Nothing here may fail, and nothing may be dropped. */
static void test_a_future_control_does_not_disturb_the_known_ones(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"a1b2c3d4\",\"entity\":\"cover.blind\","
        "\"name\":\"Blind\",\"domain\":\"cover\","
        "\"controls\":[\"toggle\",\"position\",\"tilt\"]},"
        "{\"rid\":\"b2c3d4e5\",\"entity\":\"climate.hall\","
        "\"name\":\"Hall\",\"domain\":\"climate\","
        "\"controls\":[\"toggle\",\"target_temperature\",\"humidity\"],"
        "\"min_temp\":16,\"max_temp\":30,\"target_temp_step\":0.5}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 2);
    /* `tilt` is the unknown one here; `position` this build knows, and
     * neither costs the other anything. */
    g_assert_cmpstr(entity_at(&layout, 0)->domain, ==, "cover");
    g_assert_true(entity_at(&layout, 0)->position);
    g_assert_false(entity_at(&layout, 0)->stoppable);
    g_assert_false(entity_at(&layout, 0)->target_temperature);
    /* And an unknown name beside a known one costs the known one nothing. */
    g_assert_true(entity_at(&layout, 1)->target_temperature);
    g_assert_cmpfloat(entity_at(&layout, 1)->max_temp, ==, 30.0);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* Contract version 7: the climate card. The setpoint bounds arrive with the
 * control and are read as sent — the payload names no unit, so there is no
 * plausible range to check them against. */
static void test_climate_element_is_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"7c41b8e0\",\"entity\":\"climate.hall\","
        "\"name\":\"Hall\",\"domain\":\"climate\","
        "\"controls\":[\"toggle\",\"target_temperature\"],"
        "\"min_temp\":16.5,\"max_temp\":30,\"target_temp_step\":0.5}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_cmpstr(entity_at(&layout, 0)->domain, ==, "climate");
    g_assert_true(entity_at(&layout, 0)->target_temperature);
    g_assert_false(entity_at(&layout, 0)->brightness);
    g_assert_false(entity_at(&layout, 0)->color_temperature);
    g_assert_cmpfloat(entity_at(&layout, 0)->min_temp, ==, 16.5);
    g_assert_cmpfloat(entity_at(&layout, 0)->max_temp, ==, 30.0);
    g_assert_cmpfloat(entity_at(&layout, 0)->temp_step, ==, 0.5);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* Contract version 7: the cover card. A cover carries no bounds of its own
 * — a position is a percentage — so the controls are the whole of it. */
static void test_cover_element_is_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"3f9a01cd\",\"entity\":\"cover.blind\","
        "\"name\":\"Blind\",\"domain\":\"cover\","
        "\"controls\":[\"toggle\",\"position\",\"stop\"]}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_cmpstr(entity_at(&layout, 0)->domain, ==, "cover");
    g_assert_true(entity_at(&layout, 0)->togglable);
    g_assert_true(entity_at(&layout, 0)->position);
    g_assert_true(entity_at(&layout, 0)->stoppable);
    g_assert_false(entity_at(&layout, 0)->brightness);
    g_assert_false(entity_at(&layout, 0)->target_temperature);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A blind that opens and closes and reports nothing in between. Its card
 * toggles, and the sheet it opens carries the stop button alone. */
static void test_cover_without_a_position(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"3f9a01cd\",\"entity\":\"cover.blind\","
        "\"name\":\"Blind\",\"domain\":\"cover\","
        "\"controls\":[\"toggle\",\"stop\"]}]", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_true(entity_at(&layout, 0)->togglable);
    g_assert_false(entity_at(&layout, 0)->position);
    g_assert_true(entity_at(&layout, 0)->stoppable);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A sensor block. It carries an empty control list, because there is
 * nothing to act on: the value is the entity state and the unit arrives
 * with the poll, never in the payload. */
static void test_sensor_element_is_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"b71f0c2e\","
        "\"entity\":\"sensor.kitchen_temperature\",\"name\":\"Kitchen\","
        "\"domain\":\"sensor\",\"controls\":[]}]", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_cmpstr(entity_at(&layout, 0)->domain, ==, "sensor");
    g_assert_false(entity_at(&layout, 0)->togglable);
    g_assert_false(entity_at(&layout, 0)->brightness);
    g_assert_false(entity_at(&layout, 0)->target_temperature);
    g_assert_false(entity_at(&layout, 0)->position);
    g_assert_false(entity_at(&layout, 0)->stoppable);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* The closed control list holds for the new group too: a name this build
 * has never heard of is ignored rather than acted on, so a sensor stays a
 * reading however new the integration on the other end is. */
static void test_sensor_with_unknown_control_is_still_a_reading(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"b71f0c2e\","
        "\"entity\":\"sensor.kitchen_temperature\",\"name\":\"Kitchen\","
        "\"domain\":\"sensor\",\"controls\":[\"frobnicator\"]}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_cmpstr(entity_at(&layout, 0)->domain, ==, "sensor");
    g_assert_false(entity_at(&layout, 0)->togglable);
    g_assert_false(entity_at(&layout, 0)->brightness);
    g_assert_false(entity_at(&layout, 0)->color_temperature);
    g_assert_false(entity_at(&layout, 0)->target_temperature);
    g_assert_false(entity_at(&layout, 0)->position);
    g_assert_false(entity_at(&layout, 0)->stoppable);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A thermostat that can be turned off and nothing else. The card still
 * draws and still toggles; it simply has no setpoint to open. */
static void test_climate_without_a_setpoint(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"7c41b8e0\",\"entity\":\"climate.hall\","
        "\"name\":\"Hall\",\"domain\":\"climate\","
        "\"controls\":[\"toggle\"]}]", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_true(entity_at(&layout, 0)->togglable);
    g_assert_false(entity_at(&layout, 0)->target_temperature);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* And one that can be neither turned off nor set. It is still carried and
 * still drawn; what it must not do is act on a tap, because Home Assistant
 * offered no action for it. */
static void test_climate_with_no_controls_at_all(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"7c41b8e0\",\"entity\":\"climate.hall\","
        "\"name\":\"Hall\",\"domain\":\"climate\","
        "\"controls\":[]}]", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_false(entity_at(&layout, 0)->togglable);
    g_assert_false(entity_at(&layout, 0)->target_temperature);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* Bounds that could not be drawn as a slider, and a step of nothing. Home
 * Assistant's own Celsius defaults are what the integration would have sent
 * had the entity reported nothing, so they are what this falls back to. */
static void test_broken_temperature_bounds_fall_back(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"7c41b8e0\",\"entity\":\"climate.hall\","
        "\"name\":\"Hall\",\"domain\":\"climate\","
        "\"controls\":[\"toggle\",\"target_temperature\"],"
        "\"min_temp\":30,\"max_temp\":16,\"target_temp_step\":0}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpfloat(entity_at(&layout, 0)->min_temp, ==, 7.0);
    g_assert_cmpfloat(entity_at(&layout, 0)->max_temp, ==, 35.0);
    g_assert_cmpfloat(entity_at(&layout, 0)->temp_step, ==, 0.5);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A house configured in Fahrenheit. The payload carries no unit and the
 * panel invents none: 45 to 95 travels intact. */
static void test_temperature_bounds_carry_no_unit(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"7c41b8e0\",\"entity\":\"climate.hall\","
        "\"name\":\"Hall\",\"domain\":\"climate\","
        "\"controls\":[\"toggle\",\"target_temperature\"],"
        "\"min_temp\":45,\"max_temp\":95,\"target_temp_step\":1}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpfloat(entity_at(&layout, 0)->min_temp, ==, 45.0);
    g_assert_cmpfloat(entity_at(&layout, 0)->max_temp, ==, 95.0);
    g_assert_cmpfloat(entity_at(&layout, 0)->temp_step, ==, 1.0);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A group whose cards this build does not draw still arrives. It is carried
 * through rather than dropped here: which domains can be drawn is the room
 * page's business, not the payload reader's. */
static void test_unknown_domain_is_carried(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"a1b2c3d4\",\"entity\":\"climate.hall\","
        "\"name\":\"Hall\",\"domain\":\"climate\",\"controls\":[]}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_cmpstr(entity_at(&layout, 0)->domain, ==, "climate");
    g_assert_false(entity_at(&layout, 0)->brightness);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* The domain is repeated in the payload so that a client need not parse the
 * entity ID. A payload that omits it is still readable. */
static void test_missing_domain_is_derived(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"a1b2c3d4\",\"entity\":\"switch.pump\","
        "\"name\":\"Pump\",\"controls\":[\"toggle\"]}]", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpstr(entity_at(&layout, 0)->domain, ==, "switch");

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A name the user never typed falls back to the entity ID rather than being
 * empty, so a tile always says something. */
static void test_missing_name_falls_back_to_the_entity(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"a1b2c3d4\",\"entity\":\"light.a\","
        "\"domain\":\"light\",\"controls\":[\"toggle\"]}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpstr(entity_at(&layout, 0)->name, ==, "light.a");

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A panel with no room controls configured is not an error: the room page
 * draws itself empty and says where to add some. */
static void test_empty_entity_list(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf("%s,\"entities\":[]",
                                        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 0);
    g_assert_cmpstr(layout.player_entity, ==, "media_player.a");

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A payload with no registry block at all reads as an empty registry, not as
 * a failure. That is what an integration older than version 6 sends a panel. */
static void test_payload_without_entities(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup(CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_null(failure);
    g_assert_cmpuint(entity_count(&layout), ==, 0);

    g_free(attributes);
    panel_layout_clear(&layout);
}

static void test_missing_controller_entities_fail(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_false(parse("\"entities\":[]", &layout, &failure));
    g_assert_nonnull(failure);
    g_free(failure);
    panel_layout_clear(&layout);
}

/* An element with no entity, and one with no rid, are both unusable: a card
 * is keyed on the rid and acts on the entity, so neither could be drawn. */
static void test_unusable_elements_are_skipped(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":["
        "{\"rid\":\"a1b2c3d4\",\"name\":\"No entity\"},"
        "{\"entity\":\"light.b\",\"name\":\"No rid\"},"
        "{\"rid\":\"\",\"entity\":\"light.c\",\"name\":\"Empty rid\"},"
        "{\"rid\":\"e5f6a7b8\",\"entity\":\"switch.b\",\"name\":\"B\","
        "\"domain\":\"switch\",\"controls\":[\"toggle\"]}]",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 1);
    g_assert_cmpstr(entity_at(&layout, 0)->entity, ==, "switch.b");

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* The registry is unbounded only as far as the profile allows. A longer list
 * is truncated rather than trusted: the payload comes over HTTP, and reading
 * an arbitrary number of elements into memory on a tablet is not something a
 * panel should agree to on the producer's word. */
static void test_more_entities_than_the_limit(void)
{
    GString *entities = g_string_new("");
    PanelLayout layout = {0};
    gchar *failure = NULL;

    for (guint i = 0; i < PANEL_ENTITY_LIMIT + 5; i++) {
        g_string_append_printf(
            entities,
            "%s{\"rid\":\"%08x\",\"entity\":\"switch.s%u\",\"name\":\"S\","
            "\"domain\":\"switch\",\"controls\":[\"toggle\"]}",
            i > 0 ? "," : "", i, i);
    }
    gchar *attributes = g_strdup_printf("%s,\"entities\":[%s]",
                                        CONTROLLER_ENTITIES, entities->str);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, PANEL_ENTITY_LIMIT);

    panel_layout_clear(&layout);
    g_free(attributes);
    g_string_free(entities, TRUE);
}

/* The whole registry the T560 profile allows has to arrive intact: a hundred
 * elements is the supported case, not the edge of one. */
static void test_a_full_registry_is_read(void)
{
    GString *entities = g_string_new("");
    PanelLayout layout = {0};
    gchar *failure = NULL;

    for (guint i = 0; i < 100; i++) {
        g_string_append_printf(
            entities,
            "%s{\"rid\":\"%08x\",\"entity\":\"light.l%u\",\"name\":\"L\","
            "\"domain\":\"light\",\"controls\":[\"toggle\",\"brightness\"]}",
            i > 0 ? "," : "", i, i);
    }
    gchar *attributes = g_strdup_printf(
        "%s,\"entity_limit\":100,\"entities\":[%s]", CONTROLLER_ENTITIES,
        entities->str);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 100);
    g_assert_cmpstr(entity_at(&layout, 99)->entity, ==, "light.l99");
    g_assert_nonnull(panel_layout_find_entity(&layout, "00000063"));

    panel_layout_clear(&layout);
    g_free(attributes);
    g_string_free(entities, TRUE);
}

/* The integration sends its own ceiling, and a smaller one is honoured. */
static void test_entity_limit_from_the_payload(void)
{
    GString *entities = g_string_new("");
    PanelLayout layout = {0};
    gchar *failure = NULL;

    for (guint i = 0; i < 12; i++) {
        g_string_append_printf(
            entities,
            "%s{\"rid\":\"%08x\",\"entity\":\"switch.s%u\",\"name\":\"S\","
            "\"domain\":\"switch\",\"controls\":[\"toggle\"]}",
            i > 0 ? "," : "", i, i);
    }
    gchar *attributes = g_strdup_printf(
        "%s,\"entity_limit\":8,\"entities\":[%s]", CONTROLLER_ENTITIES,
        entities->str);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(entity_count(&layout), ==, 8);

    panel_layout_clear(&layout);
    g_free(attributes);
    g_string_free(entities, TRUE);
}

static void test_broken_kelvin_bounds_fall_back(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"entities\":[{\"rid\":\"a1b2c3d4\",\"entity\":\"light.a\","
        "\"name\":\"A\",\"domain\":\"light\","
        "\"controls\":[\"toggle\",\"color_temp\"],"
        "\"min_kelvin\":9000,\"max_kelvin\":3000}]", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpint(entity_at(&layout, 0)->min_kelvin, ==, 2000);
    g_assert_cmpint(entity_at(&layout, 0)->max_kelvin, ==, 6500);

    g_free(attributes);
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

/* The select Home Assistant holds this panel's skin in. The panel writes it
 * and stores no skin of its own, so it has to be told which entity to write:
 * deriving it from the config sensor's entity ID would break the first time
 * either of them was renamed. */
static void test_skin_select_is_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"skin_select\":\"select.kitchen_tablet_player_skin\"",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpstr(layout.skin_select_entity, ==,
                    "select.kitchen_tablet_player_skin");

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* An integration that names none leaves the panel with no local skin picker
 * to offer, which is a missing control rather than a failure. */
static void test_missing_skin_select_is_null(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;

    g_assert_true(parse(FULL_ATTRIBUTES, &layout, &failure));
    g_assert_null(layout.skin_select_entity);

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
    gchar *attributes = g_strdup_printf(
        "%s,\"settings\":{\"poll_interval_ms\":2500,"
        "\"playlist_poll_interval_ms\":120000,"
        "\"screen_off_seconds\":90}", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_true(layout.settings.present);
    g_assert_cmpuint(layout.settings.poll_interval_ms, ==, 2500);
    g_assert_cmpuint(layout.settings.playlist_poll_interval_ms, ==, 120000);
    g_assert_cmpint(layout.settings.screen_off_seconds, ==, 90);
    /* A settings block that names no skin leaves config.ini deciding. */
    g_assert_false(layout.settings.player_skin_present);

    g_free(attributes);
    panel_layout_clear(&layout);
}

static void test_player_skin_is_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"settings\":{\"player_skin\":\"cassette\"}", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_true(layout.settings.present);
    g_assert_true(layout.settings.player_skin_present);
    g_assert_cmpint(layout.settings.player_skin, ==,
                    PANEL_PLAYER_SKIN_CASSETTE);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A skin added to the integration after this build was flashed arrives as a
 * name it has never heard of. Somebody did choose, so it is a choice this
 * build cannot honour: draw the default rather than nothing. */
static void test_unknown_player_skin_falls_back(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"settings\":{\"player_skin\":\"cover_card\"}",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_true(layout.settings.player_skin_present);
    g_assert_cmpint(layout.settings.player_skin, ==,
                    PANEL_PLAYER_SKIN_MODERN);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* An empty name is nobody choosing, not a choice of nothing. */
static void test_empty_player_skin_is_not_a_choice(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"settings\":{\"player_skin\":\"\"}", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_true(layout.settings.present);
    g_assert_false(layout.settings.player_skin_present);

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* Home Assistant clamps before it sends, so these bounds only guard against a
 * payload that did not come from it. */
static void test_settings_are_clamped(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"settings\":{\"poll_interval_ms\":1,"
        "\"playlist_poll_interval_ms\":999999999,"
        "\"screen_off_seconds\":0}", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpuint(layout.settings.poll_interval_ms, ==, 500);
    g_assert_cmpuint(layout.settings.playlist_poll_interval_ms, ==, 3600000);
    /* Zero is a value, not a missing setting: it disables the screen off. */
    g_assert_cmpint(layout.settings.screen_off_seconds, ==, 0);

    g_free(attributes);
    panel_layout_clear(&layout);
}

static void test_commands_are_read(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"commands\":{"
        "\"display\":{\"state\":\"off\",\"at\":1756800000000},"
        "\"brightness\":{\"value\":60,\"at\":1756800000100},"
        "\"restart\":{\"at\":1756800000200},"
        "\"page\":{\"value\":\"room\",\"at\":1756800000300}}",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_cmpstr(layout.commands.display_state, ==, "off");
    g_assert_cmpstr(layout.commands.page, ==, "room");
    g_assert_true(layout.commands.page_at ==
                  G_GINT64_CONSTANT(1756800000300));
    g_assert_true(layout.commands.display_at ==
                  G_GINT64_CONSTANT(1756800000000));
    g_assert_cmpint(layout.commands.brightness, ==, 60);
    g_assert_true(layout.commands.brightness_at ==
                  G_GINT64_CONSTANT(1756800000100));
    g_assert_true(layout.commands.restart_at ==
                  G_GINT64_CONSTANT(1756800000200));

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* A command without a moment cannot be ordered against the last one applied,
 * and one this build does not know must not stop the rest being read. */
static void test_malformed_commands_are_ignored(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"commands\":{"
        "\"display\":{\"state\":\"dim\",\"at\":1756800000000},"
        "\"brightness\":{\"value\":60},"
        "\"reboot\":{\"at\":1756800000200},"
        "\"page\":{\"value\":\"\",\"at\":1756800000400},"
        "\"restart\":{\"at\":1756800000300}}", CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_null(layout.commands.display_state);
    g_assert_null(layout.commands.page);
    g_assert_cmpint((gint)layout.commands.page_at, ==, 0);
    g_assert_cmpint((gint)layout.commands.display_at, ==, 0);
    g_assert_cmpint((gint)layout.commands.brightness_at, ==, 0);
    g_assert_true(layout.commands.restart_at ==
                  G_GINT64_CONSTANT(1756800000300));

    g_free(attributes);
    panel_layout_clear(&layout);
}

/* The blocks are objects. A producer that sent something else must read as
 * "absent" rather than abort the panel. */
static void test_wrongly_typed_blocks_are_ignored(void)
{
    PanelLayout layout = {0};
    gchar *failure = NULL;
    gchar *attributes = g_strdup_printf(
        "%s,\"settings\":[1,2],\"commands\":\"none\",\"entities\":\"all\"",
        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_false(layout.settings.present);
    g_assert_null(layout.commands.display_state);
    g_assert_cmpuint(entity_count(&layout), ==, 0);

    g_free(attributes);
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
    gchar *attributes = g_strdup_printf("%s,\"contract_version\":4",
                                        CONTROLLER_ENTITIES);

    g_assert_true(parse(attributes, &layout, &failure));
    g_assert_null(failure);
    g_assert_cmpint(layout.contract_version, ==, 4);

    g_free(attributes);
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
        gchar *attributes = g_strdup_printf("%s,\"contract_version\":%s",
                                            CONTROLLER_ENTITIES, values[i]);

        g_assert_true(parse(attributes, &layout, &failure));
        g_assert_cmpint(layout.contract_version, ==, 0);
        g_free(attributes);
        panel_layout_clear(&layout);
    }
}

void panel_config_tests_register(void)
{
    g_test_add_func("/config/full-payload", test_full_payload);
    g_test_add_func("/config/unicode-names", test_names_survive_unicode);
    g_test_add_func("/config/unknown-control",
                    test_unknown_control_is_ignored);
    g_test_add_func("/config/future-control",
                    test_a_future_control_does_not_disturb_the_known_ones);
    g_test_add_func("/config/climate", test_climate_element_is_read);
    g_test_add_func("/config/cover", test_cover_element_is_read);
    g_test_add_func("/config/sensor", test_sensor_element_is_read);
    g_test_add_func("/config/sensor-unknown-control",
                    test_sensor_with_unknown_control_is_still_a_reading);
    g_test_add_func("/config/cover-no-position",
                    test_cover_without_a_position);
    g_test_add_func("/config/climate-toggle-only",
                    test_climate_without_a_setpoint);
    g_test_add_func("/config/climate-no-controls",
                    test_climate_with_no_controls_at_all);
    g_test_add_func("/config/climate-bounds",
                    test_broken_temperature_bounds_fall_back);
    g_test_add_func("/config/climate-bounds-unitless",
                    test_temperature_bounds_carry_no_unit);
    g_test_add_func("/config/unknown-domain", test_unknown_domain_is_carried);
    g_test_add_func("/config/missing-domain", test_missing_domain_is_derived);
    g_test_add_func("/config/missing-name",
                    test_missing_name_falls_back_to_the_entity);
    g_test_add_func("/config/empty-entity-list", test_empty_entity_list);
    g_test_add_func("/config/no-entities", test_payload_without_entities);
    g_test_add_func("/config/missing-controller-entities",
                    test_missing_controller_entities_fail);
    g_test_add_func("/config/unusable-elements",
                    test_unusable_elements_are_skipped);
    g_test_add_func("/config/entity-overflow",
                    test_more_entities_than_the_limit);
    g_test_add_func("/config/full-registry", test_a_full_registry_is_read);
    g_test_add_func("/config/entity-limit",
                    test_entity_limit_from_the_payload);
    g_test_add_func("/config/kelvin-bounds",
                    test_broken_kelvin_bounds_fall_back);
    g_test_add_func("/config/invalid-json", test_invalid_json_is_reported);
    g_test_add_func("/config/skin-select", test_skin_select_is_read);
    g_test_add_func("/config/skin-select-missing",
                    test_missing_skin_select_is_null);
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
