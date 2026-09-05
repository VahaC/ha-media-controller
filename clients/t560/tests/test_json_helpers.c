#include "json_helpers.h"

#include "test_panel_cards.h"
#include "test_panel_config.h"
#include "test_panel_grid.h"

#include <glib.h>

static void test_scalar_accessors(void)
{
    JsonObject *object = json_object_new();
    json_object_set_string_member(object, "title", "Track");
    json_object_set_int_member(object, "position", 42);
    json_object_set_boolean_member(object, "playing", TRUE);

    g_assert_cmpstr(json_object_string(object, "title", "fallback"), ==,
                    "Track");
    g_assert_cmpstr(json_object_string(object, "missing", "fallback"), ==,
                    "fallback");
    gdouble value = 0.0;
    g_assert_true(json_object_number(object, "position", &value));
    g_assert_cmpfloat(value, ==, 42.0);
    g_assert_false(json_object_number(object, "missing", &value));
    g_assert_true(json_object_boolean(object, "playing", FALSE));
    g_assert_true(json_object_boolean(object, "missing", TRUE));

    json_object_unref(object);
}

static void test_string_arrays(void)
{
    JsonArray *source = json_array_new();
    json_array_add_string_element(source, "one");
    json_array_add_string_element(source, "two");
    GPtrArray *copy = g_ptr_array_new_with_free_func(g_free);

    json_copy_string_array(copy, source);
    g_assert_cmpuint(copy->len, ==, 2);
    g_assert_cmpstr(g_ptr_array_index(copy, 0), ==, "one");
    g_assert_true(json_string_array_matches(copy, source));
    json_array_add_string_element(source, "three");
    g_assert_false(json_string_array_matches(copy, source));

    g_ptr_array_unref(copy);
    json_array_unref(source);
}

static void test_large_string_array(void)
{
    JsonArray *source = json_array_new();
    GPtrArray *copy = g_ptr_array_new_with_free_func(g_free);

    for (guint i = 0; i < 500; i++) {
        gchar *value = g_strdup_printf("Playlist %u", i);
        json_array_add_string_element(source, value);
        g_free(value);
    }

    json_copy_string_array(copy, source);
    g_assert_cmpuint(copy->len, ==, 500);
    g_assert_true(json_string_array_matches(copy, source));
    g_assert_cmpstr(g_ptr_array_index(copy, 499), ==, "Playlist 499");

    g_ptr_array_unref(copy);
    json_array_unref(source);
}

/* A member holding the wrong type reads as absent. Both accessors are given
 * remote input: a config sensor that carried a string where an array belongs
 * must leave the panel with nothing to draw, not abort it. */
static void test_optional_accessors_check_the_type(void)
{
    JsonObject *object = json_object_new();
    json_object_set_string_member(object, "entities", "all");
    json_object_set_string_member(object, "settings", "none");
    json_object_set_null_member(object, "commands");

    g_assert_null(json_optional_array(object, "entities"));
    g_assert_null(json_optional_object(object, "settings"));
    g_assert_null(json_optional_array(object, "missing"));
    g_assert_null(json_optional_object(object, "commands"));

    json_object_set_array_member(object, "controls", json_array_new());
    g_assert_nonnull(json_optional_array(object, "controls"));

    json_object_unref(object);
}

static void test_builder_serialization(void)
{
    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "name");
    json_builder_add_string_value(builder, "value");
    json_builder_end_object(builder);

    gchar *json = json_builder_to_string(builder);
    g_assert_cmpstr(json, ==, "{\"name\":\"value\"}");

    g_free(json);
    g_object_unref(builder);
}

int main(int argc, char **argv)
{
    g_test_init(&argc, &argv, NULL);
    g_test_add_func("/json/scalar-accessors", test_scalar_accessors);
    g_test_add_func("/json/string-arrays", test_string_arrays);
    g_test_add_func("/json/large-string-array", test_large_string_array);
    g_test_add_func("/json/optional-accessor-types",
                    test_optional_accessors_check_the_type);
    g_test_add_func("/json/builder-serialization", test_builder_serialization);
    panel_cards_tests_register();
    panel_config_tests_register();
    panel_grid_tests_register();
    return g_test_run();
}
