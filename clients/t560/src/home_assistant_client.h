#ifndef T560_HOME_ASSISTANT_CLIENT_H
#define T560_HOME_ASSISTANT_CLIENT_H

#include <gio/gio.h>

typedef struct _HomeAssistantClient HomeAssistantClient;

typedef void (*HomeAssistantResponse)(guint status_code, GBytes *body,
                                      const GError *error, gpointer user_data);

HomeAssistantClient *home_assistant_client_new(const gchar *base_url,
                                               const gchar *token);
void home_assistant_client_free(HomeAssistantClient *client);

gboolean home_assistant_client_get_state(HomeAssistantClient *client,
                                         const gchar *entity,
                                         HomeAssistantResponse callback,
                                         gpointer user_data,
                                         GDestroyNotify user_data_destroy);
gboolean home_assistant_client_call_service(HomeAssistantClient *client,
                                            const gchar *domain,
                                            const gchar *service,
                                            const gchar *json,
                                            HomeAssistantResponse callback,
                                            gpointer user_data);
/* The pairing request is the only one a panel makes before it has a token,
 * so a NULL token is valid and simply omits the Authorization header. */
gboolean home_assistant_client_post_path(HomeAssistantClient *client,
                                         const gchar *path,
                                         const gchar *json,
                                         HomeAssistantResponse callback,
                                         gpointer user_data,
                                         GDestroyNotify user_data_destroy);
/* The layout backup: a document Home Assistant stores and hands back without
 * ever parsing it. See the panel layout endpoint in docs/CONTRACT.md. */
gboolean home_assistant_client_put_path(HomeAssistantClient *client,
                                        const gchar *path,
                                        const gchar *body,
                                        const gchar *content_type,
                                        HomeAssistantResponse callback,
                                        gpointer user_data,
                                        GDestroyNotify user_data_destroy);
gboolean home_assistant_client_get_path(HomeAssistantClient *client,
                                        const gchar *path,
                                        HomeAssistantResponse callback,
                                        gpointer user_data,
                                        GDestroyNotify user_data_destroy);
gboolean home_assistant_client_get_url(HomeAssistantClient *client,
                                       const gchar *url,
                                       gint priority,
                                       HomeAssistantResponse callback,
                                       gpointer user_data,
                                       GDestroyNotify user_data_destroy);
gchar *home_assistant_client_resolve_url(HomeAssistantClient *client,
                                         const gchar *path_or_url);

#endif
