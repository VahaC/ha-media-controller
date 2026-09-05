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

/* Whether two registries differ in display name and icon alone. The revision
 * the integration sends covers the whole registry, so renaming a card looks
 * exactly like rearranging the room; this is how the application tells the
 * two apart and applies a rename while it keeps running instead of
 * restarting for it. Identity, capabilities and bounds must match element
 * for element, in order; only `name` and `icon` may differ. Settings,
 * commands, the skin select and the contract version are not layout and are
 * never part of this comparison. */
gboolean panel_layout_is_appearance_only(const PanelLayout *current,
                                         const PanelLayout *candidate);
/* Adopts the candidate's display names, icons and revision into the running
 * layout. The caller must have asked panel_layout_is_appearance_only first:
 * anything else still needs a restart. The candidate keeps its own strings;
 * what is adopted is copied. */
void panel_layout_apply_appearance(PanelLayout *layout,
                                   const PanelLayout *appearance);

/* The cache is what makes the panel start while Home Assistant is down. It
 * holds the last state document that parsed successfully. */
gboolean panel_config_load_cache(PanelLayout *layout, gchar **error_message);
void panel_config_store_cache(const gchar *data, gsize length);

#endif
