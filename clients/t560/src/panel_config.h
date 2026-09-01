#ifndef T560_PANEL_CONFIG_H
#define T560_PANEL_CONFIG_H

#include "app_config.h"

#include <json-glib/json-glib.h>

/* Reads the layout the Media Controller integration publishes on
 * sensor.<panel_id>_config. The panel renders what it receives and never
 * inspects Home Assistant capabilities itself. */

gboolean panel_config_parse_state(JsonObject *state, PanelLayout *layout,
                                  gchar **error_message);
gboolean panel_config_parse_json(const gchar *data, gssize length,
                                 PanelLayout *layout, gchar **error_message);

/* The cache is what makes the panel start while Home Assistant is down. It
 * holds the last state document that parsed successfully. */
gboolean panel_config_load_cache(PanelLayout *layout, gchar **error_message);
void panel_config_store_cache(const gchar *data, gsize length);

#endif
