#ifndef T560_JSON_HELPERS_H
#define T560_JSON_HELPERS_H

#include <json-glib/json-glib.h>

const gchar *json_object_string(JsonObject *object, const gchar *member,
                                const gchar *fallback);
gboolean json_object_number(JsonObject *object, const gchar *member,
                            gdouble *value);
gboolean json_object_boolean(JsonObject *object, const gchar *member,
                             gboolean fallback);
JsonObject *json_state_attributes(JsonObject *state);
JsonArray *json_optional_array(JsonObject *object, const gchar *member);
gchar *json_builder_to_string(JsonBuilder *builder);
void json_copy_string_array(GPtrArray *target, JsonArray *source);
gboolean json_string_array_matches(GPtrArray *current, JsonArray *incoming);

#endif
