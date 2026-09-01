#include "home_assistant_client.h"

#include <libsoup/soup.h>
#include <string.h>

typedef struct {
    HomeAssistantClient *client;
    SoupMessage *message;
    HomeAssistantResponse callback;
    gpointer user_data;
    GDestroyNotify user_data_destroy;
} PendingRequest;

struct _HomeAssistantClient {
    SoupSession *session;
    gchar *base_url;
    gchar *token;
    GList *pending_requests;
};

static void add_headers(HomeAssistantClient *client, SoupMessage *message)
{
    gchar *authorization = g_strdup_printf("Bearer %s", client->token);
    SoupMessageHeaders *headers = soup_message_get_request_headers(message);

    soup_message_headers_append(headers, "Authorization", authorization);
    soup_message_headers_append(headers, "Accept", "application/json");
    g_free(authorization);
}

static void request_finished(GObject *source, GAsyncResult *result,
                             gpointer user_data)
{
    PendingRequest *request = user_data;
    GError *error = NULL;
    GBytes *body = soup_session_send_and_read_finish(
        SOUP_SESSION(source), result, &error);
    guint status = soup_message_get_status(request->message);

    if (request->client != NULL) {
        request->client->pending_requests = g_list_remove(
            request->client->pending_requests, request);
    }
    if (request->callback != NULL)
        request->callback(status, body, error, request->user_data);

    g_clear_error(&error);
    g_clear_pointer(&body, g_bytes_unref);
    if (request->user_data_destroy != NULL)
        request->user_data_destroy(request->user_data);
    g_object_unref(request->message);
    g_free(request);
}

static gboolean send_request(HomeAssistantClient *client, const gchar *method,
                             const gchar *url, const gchar *json, gint priority,
                             HomeAssistantResponse callback, gpointer user_data,
                             GDestroyNotify user_data_destroy)
{
    SoupMessage *message = soup_message_new(method, url);
    if (message == NULL)
        return FALSE;

    add_headers(client, message);
    if (json != NULL) {
        GBytes *bytes = g_bytes_new(json, strlen(json));
        soup_message_set_request_body_from_bytes(
            message, "application/json", bytes);
        g_bytes_unref(bytes);
    }

    PendingRequest *request = g_new0(PendingRequest, 1);
    request->client = client;
    request->message = g_object_ref(message);
    request->callback = callback;
    request->user_data = user_data;
    request->user_data_destroy = user_data_destroy;
    client->pending_requests = g_list_prepend(client->pending_requests, request);
    soup_session_send_and_read_async(client->session, message, priority, NULL,
                                     request_finished, request);
    g_object_unref(message);
    return TRUE;
}

HomeAssistantClient *home_assistant_client_new(const gchar *base_url,
                                               const gchar *token)
{
    HomeAssistantClient *client = g_new0(HomeAssistantClient, 1);
    client->base_url = g_strdup(base_url);
    client->token = g_strdup(token);
    client->session = soup_session_new_with_options(
        "timeout", 8, "user-agent", "t560-music-panel/0.2", NULL);
    return client;
}

void home_assistant_client_free(HomeAssistantClient *client)
{
    if (client == NULL)
        return;

    GList *requests = client->pending_requests;
    client->pending_requests = NULL;
    for (GList *item = requests; item != NULL; item = item->next) {
        PendingRequest *request = item->data;
        request->client = NULL;
        request->callback = NULL;
    }
    g_list_free(requests);
    soup_session_abort(client->session);
    g_object_unref(client->session);
    g_free(client->base_url);
    g_free(client->token);
    g_free(client);
}

gboolean home_assistant_client_get_state(HomeAssistantClient *client,
                                         const gchar *entity,
                                         HomeAssistantResponse callback,
                                         gpointer user_data,
                                         GDestroyNotify user_data_destroy)
{
    gchar *escaped_entity = g_uri_escape_string(entity, NULL, TRUE);
    gchar *url = g_strdup_printf("%s/api/states/%s", client->base_url,
                                 escaped_entity);
    gboolean started = send_request(client, "GET", url, NULL,
                                    G_PRIORITY_LOW, callback, user_data,
                                    user_data_destroy);
    g_free(escaped_entity);
    g_free(url);
    return started;
}

gboolean home_assistant_client_call_service(HomeAssistantClient *client,
                                            const gchar *domain,
                                            const gchar *service,
                                            const gchar *json,
                                            HomeAssistantResponse callback,
                                            gpointer user_data)
{
    gchar *url = g_strdup_printf("%s/api/services/%s/%s", client->base_url,
                                 domain, service);
    gboolean started = send_request(client, "POST", url, json,
                                    G_PRIORITY_DEFAULT, callback, user_data,
                                    NULL);
    g_free(url);
    return started;
}

gboolean home_assistant_client_get_url(HomeAssistantClient *client,
                                       const gchar *url, gint priority,
                                       HomeAssistantResponse callback,
                                       gpointer user_data,
                                       GDestroyNotify user_data_destroy)
{
    return send_request(client, "GET", url, NULL, priority, callback, user_data,
                        user_data_destroy);
}

gchar *home_assistant_client_resolve_url(HomeAssistantClient *client,
                                         const gchar *path_or_url)
{
    if (g_str_has_prefix(path_or_url, "http://") ||
        g_str_has_prefix(path_or_url, "https://")) {
        return g_strdup(path_or_url);
    }
    return g_strdup_printf("%s%s", client->base_url, path_or_url);
}
