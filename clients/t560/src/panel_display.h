#ifndef T560_PANEL_DISPLAY_H
#define T560_PANEL_DISPLAY_H

#include <glib.h>

/* The panel's view of the backlight.
 *
 * The panel process does not own the display. t560-power-button.py does: it
 * drives DPMS, it holds the pointer grab that stops a wake-up tap from
 * reaching the interface, and it applies the inactivity timeout. Two
 * processes forcing DPMS independently would race over that grab, so this
 * module asks rather than acts.
 *
 * The two sides meet in the cache directory. The panel writes a request file
 * and the handler deletes it once it has acted; the handler writes a state
 * file and the panel reads it. Files rather than signals because the handler
 * already wakes twice a second, and because busybox on the tablet cannot send
 * a real-time signal by name.
 */

typedef struct {
    /* FALSE when t560-power-button.py is not running, or has not written a
     * state file yet. Everything below is then meaningless. */
    gboolean available;
    gboolean on;
    /* Backlight level in percent, or -1 when the kernel exposes no backlight
     * device this session may write. */
    gint brightness;
} DisplayStatus;

void panel_display_read(DisplayStatus *status);

/* Both return FALSE only when the request could not be written at all. A
 * request that the handler never picks up — because it is not running — is
 * not an error here; the state file simply stays as it was. */
gboolean panel_display_request_state(gboolean on);
gboolean panel_display_request_brightness(gint percent);

#endif
