#include "panel_web.h"

#include "json_helpers.h"

#include <libsoup/soup.h>

#include <string.h>

/* The whole editor is one page compiled into the binary. The tablet is often
 * on a network with no route out of the house, so nothing in it may be
 * fetched from anywhere. */
#define PANEL_WEB_EDITOR_RESOURCE "/com/vahac/t560/editor.html"

/* A layout of a hundred cards is a few kilobytes. This is the ceiling on what
 * the editor may PUT, and it is the same order as the one Home Assistant
 * applies to the copy it stores: a body over it is refused before it is
 * read. */
#define PANEL_WEB_MAX_BODY 16384

struct _PanelWeb {
    SoupServer *server;
    PanelWebCallbacks callbacks;
    gpointer user_data;
    guint port;
    gchar *url;
};

/* One in-flight restore. The HTTP request it answers is paused while Home
 * Assistant is asked, so the main loop keeps running and the interface keeps
 * drawing: nothing here ever blocks the GTK thread. */
typedef struct {
    PanelWeb *web;
    SoupServerMessage *message;
} PanelWebRestore;

static void respond_json(SoupServerMessage *message, guint status,
                         const gchar *json)
{
    soup_server_message_set_status(message, status, NULL);
    soup_server_message_set_response(message, "application/json",
                                     SOUP_MEMORY_COPY, json, strlen(json));
}

static void respond_error(SoupServerMessage *message, guint status,
                          const gchar *text)
{
    JsonBuilder *builder = json_builder_new();

    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "error");
    json_builder_add_string_value(builder, text);
    json_builder_end_object(builder);

    gchar *json = json_builder_to_string(builder);
    respond_json(message, status, json);
    g_free(json);
    g_object_unref(builder);
}

static void respond_ok(SoupServerMessage *message)
{
    respond_json(message, SOUP_STATUS_OK, "{\"status\":\"ok\"}");
}

/* Every route answers exactly one method. Anything else is refused rather
 * than quietly treated as a GET, so that a mistake in a client is visible. */
static gboolean method_is(SoupServerMessage *message, const gchar *method)
{
    return g_strcmp0(soup_server_message_get_method(message), method) == 0;
}

static gchar *read_body(SoupServerMessage *message, gchar **error_message)
{
    SoupMessageBody *body = soup_server_message_get_request_body(message);

    if (body == NULL || body->length == 0) {
        *error_message = g_strdup("The request has no body.");
        return NULL;
    }
    if (body->length > PANEL_WEB_MAX_BODY) {
        *error_message = g_strdup("The layout is too large.");
        return NULL;
    }
    return g_strndup(body->data, (gsize)body->length);
}

/* ------------------------------------------------------------------ routes */

static void handle_editor(PanelWeb *web, SoupServerMessage *message)
{
    GBytes *page = g_resources_lookup_data(PANEL_WEB_EDITOR_RESOURCE,
                                           G_RESOURCE_LOOKUP_FLAGS_NONE, NULL);

    (void)web;
    if (page == NULL) {
        respond_error(message, SOUP_STATUS_INTERNAL_SERVER_ERROR,
                      "The editor is missing from this build.");
        return;
    }

    gsize length = 0;
    const gchar *data = g_bytes_get_data(page, &length);

    soup_server_message_set_status(message, SOUP_STATUS_OK, NULL);
    soup_server_message_set_response(message, "text/html; charset=utf-8",
                                     SOUP_MEMORY_COPY, data, length);
    g_bytes_unref(page);
}

/* The registry, straight out of the payload the panel already holds. The
 * editor never reaches Home Assistant and this route never does either. */
static void handle_entities(PanelWeb *web, SoupServerMessage *message)
{
    const PanelLayout *layout = web->callbacks.layout(web->user_data);
    JsonBuilder *builder = json_builder_new();

    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "entities");
    json_builder_begin_array(builder);
    guint count = layout != NULL && layout->entities != NULL
                      ? layout->entities->len
                      : 0;
    for (guint i = 0; i < count; i++) {
        const PanelEntity *entity = g_ptr_array_index(layout->entities, i);

        json_builder_begin_object(builder);
        json_builder_set_member_name(builder, "rid");
        json_builder_add_string_value(builder, entity->rid);
        json_builder_set_member_name(builder, "entity");
        json_builder_add_string_value(builder, entity->entity);
        json_builder_set_member_name(builder, "name");
        json_builder_add_string_value(builder, entity->name);
        json_builder_set_member_name(builder, "domain");
        json_builder_add_string_value(builder, entity->domain);
        json_builder_set_member_name(builder, "brightness");
        json_builder_add_boolean_value(builder, entity->brightness);
        json_builder_set_member_name(builder, "color_temp");
        json_builder_add_boolean_value(builder, entity->color_temperature);
        json_builder_end_object(builder);
    }
    json_builder_end_array(builder);

    /* The artwork this build carries, so the editor offers exactly what the
     * panel can draw rather than a list written down twice. */
    json_builder_set_member_name(builder, "icons");
    json_builder_begin_array(builder);
    static const gchar *ICONS[] = {"light-1", "light-2", "desk-lamp",
                                   "desk-led-strip", "fan", "ac"};
    for (guint i = 0; i < G_N_ELEMENTS(ICONS); i++)
        json_builder_add_string_value(builder, ICONS[i]);
    json_builder_end_array(builder);

    json_builder_set_member_name(builder, "grid");
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "cols");
    json_builder_add_int_value(builder, PANEL_GRID_COLUMNS);
    json_builder_set_member_name(builder, "rows");
    json_builder_add_int_value(builder, PANEL_GRID_ROWS);
    json_builder_end_object(builder);
    json_builder_end_object(builder);

    gchar *json = json_builder_to_string(builder);
    respond_json(message, SOUP_STATUS_OK, json);
    g_free(json);
    g_object_unref(builder);
}

static void handle_get_layout(PanelWeb *web, SoupServerMessage *message)
{
    const PanelGrid *grid = web->callbacks.grid(web->user_data);

    if (grid == NULL) {
        respond_error(message, SOUP_STATUS_SERVICE_UNAVAILABLE,
                      "The panel has not built its room page yet.");
        return;
    }

    gchar *json = panel_grid_to_json(grid);
    respond_json(message, SOUP_STATUS_OK, json);
    g_free(json);
}

static void handle_put_layout(PanelWeb *web, SoupServerMessage *message)
{
    gchar *failure = NULL;
    gchar *body = read_body(message, &failure);

    if (body == NULL) {
        respond_error(message, SOUP_STATUS_BAD_REQUEST, failure);
        g_free(failure);
        return;
    }

    guint dropped = 0;
    PanelGrid *grid = panel_grid_parse(body, -1, &dropped, &failure);
    g_free(body);
    if (grid == NULL) {
        respond_error(message, SOUP_STATUS_BAD_REQUEST, failure);
        g_free(failure);
        return;
    }
    /* A layout that lost cards on the way in is refused rather than saved as
     * something the editor did not ask for. The editor already refuses to
     * place a card that does not fit, so this only catches another client. */
    if (dropped > 0) {
        panel_grid_free(grid);
        gchar *text = g_strdup_printf(
            "%u card(s) are outside the grid or overlap another card.",
            dropped);
        respond_error(message, SOUP_STATUS_BAD_REQUEST, text);
        g_free(text);
        return;
    }

    gboolean backed_up = FALSE;
    if (!web->callbacks.save_grid(grid, &backed_up, &failure,
                                  web->user_data)) {
        panel_grid_free(grid);
        respond_error(message, SOUP_STATUS_INTERNAL_SERVER_ERROR, failure);
        g_free(failure);
        return;
    }

    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "status");
    json_builder_add_string_value(builder, "ok");
    /* Whether the copy reached Home Assistant is reported, never enforced: a
     * layout that is on the panel is saved, whatever Home Assistant did. */
    json_builder_set_member_name(builder, "backup");
    json_builder_add_boolean_value(builder, backed_up);
    json_builder_end_object(builder);

    gchar *json = json_builder_to_string(builder);
    respond_json(message, SOUP_STATUS_OK, json);
    g_free(json);
    g_object_unref(builder);
}

static void restore_ready(const gchar *layout, const gchar *error_message,
                          gpointer request)
{
    PanelWebRestore *restore = request;
    SoupServerMessage *message = restore->message;
    PanelWeb *web = restore->web;

    if (layout == NULL) {
        respond_error(message, SOUP_STATUS_BAD_GATEWAY,
                      error_message != NULL
                          ? error_message
                          : "Home Assistant holds no copy of this layout.");
        goto done;
    }

    gchar *failure = NULL;
    guint dropped = 0;
    PanelGrid *grid = panel_grid_parse(layout, -1, &dropped, &failure);
    if (grid == NULL) {
        respond_error(message, SOUP_STATUS_BAD_GATEWAY, failure);
        g_free(failure);
        goto done;
    }

    gboolean backed_up = FALSE;
    if (!web->callbacks.save_grid(grid, &backed_up, &failure,
                                  web->user_data)) {
        panel_grid_free(grid);
        respond_error(message, SOUP_STATUS_INTERNAL_SERVER_ERROR, failure);
        g_free(failure);
        goto done;
    }
    respond_ok(message);

done:
    soup_server_message_unpause(message);
    g_object_unref(message);
    g_free(restore);
}

/* The one route that has to reach Home Assistant. The request is paused
 * rather than waited on, so the GTK main loop keeps drawing while the answer
 * is in flight. */
static void handle_delete_layout(PanelWeb *web, SoupServerMessage *message)
{
    PanelWebRestore *restore = g_new0(PanelWebRestore, 1);

    restore->web = web;
    restore->message = g_object_ref(message);
    soup_server_message_pause(message);
    web->callbacks.restore(restore_ready, restore, web->user_data);
}

static void handle_skins(PanelWeb *web, SoupServerMessage *message)
{
    const PanelLayout *layout = web->callbacks.layout(web->user_data);
    JsonBuilder *builder = json_builder_new();

    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "skins");
    json_builder_begin_array(builder);
    for (guint i = 0; i < PANEL_PLAYER_SKIN_COUNT; i++)
        json_builder_add_string_value(builder, panel_player_skin_to_string(i));
    json_builder_end_array(builder);

    /* The skin on screen, which is always one of the names above: Home
     * Assistant's choice once somebody has made one, and the config.ini
     * fallback until then. Reporting what Home Assistant last said instead
     * would leave the picker blank on a panel that has never been given a
     * skin, and stale on one that has just been given a new one. */
    json_builder_set_member_name(builder, "current");
    json_builder_add_string_value(
        builder, panel_player_skin_to_string(web->callbacks.skin(
                     web->user_data)));
    /* Whether this panel was told which entity holds the skin. Without one
     * there is nothing to write, and the editor greys the control. */
    json_builder_set_member_name(builder, "writable");
    json_builder_add_boolean_value(
        builder, layout != NULL && layout->skin_select_entity != NULL);
    json_builder_end_object(builder);

    gchar *json = json_builder_to_string(builder);
    respond_json(message, SOUP_STATUS_OK, json);
    g_free(json);
    g_object_unref(builder);
}

/* Calls select.select_option on this panel's own skin select and nothing
 * else. The name is checked against the skins this build draws before it is
 * sent, so this route cannot be used to write an arbitrary value into an
 * arbitrary entity. */
static void handle_put_skin(PanelWeb *web, SoupServerMessage *message)
{
    gchar *failure = NULL;
    gchar *body = read_body(message, &failure);

    if (body == NULL) {
        respond_error(message, SOUP_STATUS_BAD_REQUEST, failure);
        g_free(failure);
        return;
    }

    JsonParser *parser = json_parser_new();
    GError *error = NULL;
    const gchar *requested = NULL;

    if (json_parser_load_from_data(parser, body, -1, &error) &&
        json_parser_get_root(parser) != NULL &&
        JSON_NODE_HOLDS_OBJECT(json_parser_get_root(parser))) {
        requested = json_object_string(
            json_node_get_object(json_parser_get_root(parser)), "skin", NULL);
    }
    g_clear_error(&error);
    g_free(body);

    if (requested == NULL || *requested == '\0') {
        respond_error(message, SOUP_STATUS_BAD_REQUEST,
                      "No skin was named.");
        g_object_unref(parser);
        return;
    }

    /* An unknown name is refused rather than passed on. panel_player_skin_
     * from_string answers with the default for anything it does not know, so
     * comparing the round trip is what tells a real name from a typo. */
    PanelPlayerSkin skin = panel_player_skin_from_string(requested);
    if (g_strcmp0(panel_player_skin_to_string(skin), requested) != 0) {
        respond_error(message, SOUP_STATUS_BAD_REQUEST,
                      "This panel does not draw that skin.");
        g_object_unref(parser);
        return;
    }

    if (!web->callbacks.select_skin(requested, &failure, web->user_data)) {
        respond_error(message, SOUP_STATUS_BAD_GATEWAY, failure);
        g_free(failure);
        g_object_unref(parser);
        return;
    }
    respond_ok(message);
    g_object_unref(parser);
}

/* ----------------------------------------------------------------- routing */

static void handle_request(SoupServer *server, SoupServerMessage *message,
                           const char *path, GHashTable *query,
                           gpointer user_data)
{
    PanelWeb *web = user_data;

    (void)server;
    (void)query;

    /* Seven routes, and the table below is all of them. There is deliberately
     * no catch-all and no path that takes an entity, a service or a URL from
     * the caller: this server has no password, so what it cannot express is
     * the security model. */
    if (g_strcmp0(path, "/") == 0) {
        if (!method_is(message, "GET")) {
            soup_server_message_set_status(
                message, SOUP_STATUS_METHOD_NOT_ALLOWED, NULL);
            return;
        }
        handle_editor(web, message);
        return;
    }

    if (g_strcmp0(path, "/api/entities") == 0) {
        if (method_is(message, "GET"))
            handle_entities(web, message);
        else
            soup_server_message_set_status(
                message, SOUP_STATUS_METHOD_NOT_ALLOWED, NULL);
        return;
    }

    if (g_strcmp0(path, "/api/layout") == 0) {
        if (method_is(message, "GET"))
            handle_get_layout(web, message);
        else if (method_is(message, "PUT"))
            handle_put_layout(web, message);
        else if (method_is(message, "DELETE"))
            handle_delete_layout(web, message);
        else
            soup_server_message_set_status(
                message, SOUP_STATUS_METHOD_NOT_ALLOWED, NULL);
        return;
    }

    if (g_strcmp0(path, "/api/skins") == 0) {
        if (method_is(message, "GET"))
            handle_skins(web, message);
        else
            soup_server_message_set_status(
                message, SOUP_STATUS_METHOD_NOT_ALLOWED, NULL);
        return;
    }

    if (g_strcmp0(path, "/api/skin") == 0) {
        if (method_is(message, "PUT"))
            handle_put_skin(web, message);
        else
            soup_server_message_set_status(
                message, SOUP_STATUS_METHOD_NOT_ALLOWED, NULL);
        return;
    }

    soup_server_message_set_status(message, SOUP_STATUS_NOT_FOUND, NULL);
}

/* ------------------------------------------------------------- lifecycle */

/* The address a phone on the same network should use. The listener binds
 * every interface, so this only has to name one of them that is routable;
 * the hostname is the fallback when none can be read. */
static gchar *first_local_address(guint port)
{
    GSocketAddress *local = NULL;
    GSocket *socket = g_socket_new(G_SOCKET_FAMILY_IPV4,
                                   G_SOCKET_TYPE_DATAGRAM,
                                   G_SOCKET_PROTOCOL_UDP, NULL);
    gchar *url = NULL;

    if (socket != NULL) {
        /* Connecting a datagram socket sends nothing. It only asks the
         * kernel which of this machine's addresses it would route from,
         * which is the address a phone on that network can reach. */
        GInetAddress *probe = g_inet_address_new_from_string("192.168.1.1");
        GSocketAddress *target = g_inet_socket_address_new(probe, 53);

        if (g_socket_connect(socket, target, NULL, NULL))
            local = g_socket_get_local_address(socket, NULL);
        g_object_unref(target);
        g_object_unref(probe);
        g_object_unref(socket);
    }

    if (local != NULL) {
        GInetAddress *address = g_inet_socket_address_get_address(
            G_INET_SOCKET_ADDRESS(local));
        gchar *text = g_inet_address_to_string(address);

        if (text != NULL && !g_str_equal(text, "0.0.0.0"))
            url = g_strdup_printf("http://%s:%u/", text, port);
        g_free(text);
        g_object_unref(local);
    }

    if (url == NULL)
        url = g_strdup_printf("http://%s:%u/", g_get_host_name(), port);
    return url;
}

PanelWeb *panel_web_new(guint port, const PanelWebCallbacks *callbacks,
                        gpointer user_data, gchar **error_message)
{
    g_return_val_if_fail(callbacks != NULL, NULL);
    g_return_val_if_fail(error_message != NULL, NULL);

    PanelWeb *web = g_new0(PanelWeb, 1);
    GError *error = NULL;

    web->callbacks = *callbacks;
    web->user_data = user_data;
    web->port = port;
    web->server = soup_server_new("server-header", "t560-panel", NULL);
    soup_server_add_handler(web->server, "/", handle_request, web, NULL);

    if (!soup_server_listen_all(web->server, port, 0, &error)) {
        *error_message = g_strdup(error != NULL ? error->message
                                                : "unknown error");
        g_clear_error(&error);
        panel_web_free(web);
        return NULL;
    }

    web->url = first_local_address(port);
    return web;
}

void panel_web_free(PanelWeb *web)
{
    if (web == NULL)
        return;

    if (web->server != NULL) {
        soup_server_disconnect(web->server);
        g_object_unref(web->server);
    }
    g_free(web->url);
    g_free(web);
}

const gchar *panel_web_url(PanelWeb *web)
{
    return web != NULL ? web->url : NULL;
}
