#include "json_helpers.h"

const gchar *json_object_string(JsonObject *object, const gchar *member,
                                const gchar *fallback)
{
    if (object == NULL || !json_object_has_member(object, member))
        return fallback;

    JsonNode *node = json_object_get_member(object, member);
    return node != NULL && json_node_get_value_type(node) == G_TYPE_STRING
               ? json_node_get_string(node)
               : fallback;
}

gboolean json_object_number(JsonObject *object, const gchar *member,
                            gdouble *value)
{
    if (object == NULL || !json_object_has_member(object, member))
        return FALSE;

    JsonNode *node = json_object_get_member(object, member);
    if (node == NULL || !JSON_NODE_HOLDS_VALUE(node))
        return FALSE;

    GType type = json_node_get_value_type(node);
    if (type != G_TYPE_DOUBLE && type != G_TYPE_INT64 && type != G_TYPE_INT)
        return FALSE;

    *value = json_node_get_double(node);
    return TRUE;
}

gboolean json_object_boolean(JsonObject *object, const gchar *member,
                             gboolean fallback)
{
    if (object == NULL || !json_object_has_member(object, member))
        return fallback;

    JsonNode *node = json_object_get_member(object, member);
    return node != NULL && json_node_get_value_type(node) == G_TYPE_BOOLEAN
               ? json_node_get_boolean(node)
               : fallback;
}

JsonObject *json_state_attributes(JsonObject *state)
{
    return state != NULL && json_object_has_member(state, "attributes")
               ? json_object_get_object_member(state, "attributes")
               : NULL;
}

JsonArray *json_optional_array(JsonObject *object, const gchar *member)
{
    return object != NULL && json_object_has_member(object, member)
               ? json_object_get_array_member(object, member)
               : NULL;
}

gchar *json_builder_to_string(JsonBuilder *builder)
{
    JsonNode *root = json_builder_get_root(builder);
    JsonGenerator *generator = json_generator_new();
    json_generator_set_root(generator, root);
    gchar *json = json_generator_to_data(generator, NULL);

    json_node_free(root);
    g_object_unref(generator);
    return json;
}

void json_copy_string_array(GPtrArray *target, JsonArray *source)
{
    g_ptr_array_set_size(target, 0);
    if (source == NULL)
        return;

    for (guint i = 0; i < json_array_get_length(source); i++) {
        const gchar *value = json_array_get_string_element(source, i);
        g_ptr_array_add(target, g_strdup(value != NULL ? value : ""));
    }
}

gboolean json_string_array_matches(GPtrArray *current, JsonArray *incoming)
{
    if (incoming == NULL)
        return current->len == 0;
    if (current->len != json_array_get_length(incoming))
        return FALSE;

    for (guint i = 0; i < current->len; i++) {
        const gchar *left = g_ptr_array_index(current, i);
        const gchar *right = json_array_get_string_element(incoming, i);
        if (g_strcmp0(left, right) != 0)
            return FALSE;
    }
    return TRUE;
}
