#ifndef T560_PANEL_PAIRING_H
#define T560_PANEL_PAIRING_H

#include <glib.h>

/* Identity and first-run pairing.
 *
 * The panel identifies itself to Home Assistant by a per-device ID. It is
 * deliberately not the hostname: two tablets flashed from the same image
 * share one, and they would then claim the same Home Assistant device and
 * overwrite each other's configuration. */

/* Stable for the life of the device. Derived once from the first hardware
 * address and cached, so reinstalling the application keeps it, and a wiped
 * tablet derives the same value again. */
gchar *panel_pairing_device_id(void);

/* The six digits shown on screen while the panel has no token. Generated
 * once and cached, so a watchdog restart does not change the code the person
 * is currently reading. */
gchar *panel_pairing_code(void);

/* Stores what Home Assistant handed over. The token file is the only file
 * this application refuses to run without. */
gboolean panel_pairing_store_token(const gchar *token,
                                   const gchar *config_entity,
                                   gchar **error_message);

/* The entity Home Assistant named during pairing, or NULL when the panel has
 * never been paired on this installation. */
gchar *panel_pairing_config_entity(void);

void panel_pairing_forget_code(void);

/* Drops a token Home Assistant no longer accepts, so that the next start
 * shows a pairing code instead of failing every request. */
void panel_pairing_forget_token(void);

#endif
