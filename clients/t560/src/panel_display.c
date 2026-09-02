#include "panel_display.h"

#include "app_config.h"

#include <glib/gstdio.h>

#define DISPLAY_STATE_NAME "display-state.ini"
#define DISPLAY_REQUEST_NAME "display-request.ini"

/* A state file older than this means the button handler stopped writing, so
 * whatever it last said about the backlight is no longer worth reporting. It
 * rewrites the file on every change and at least once a minute. */
#define DISPLAY_STATE_MAX_AGE_SECONDS 180

static gboolean state_is_recent(const gchar *path)
{
    GStatBuf info;

    if (g_stat(path, &info) != 0)
        return FALSE;
    return g_get_real_time() / G_USEC_PER_SEC - (gint64)info.st_mtime <
           DISPLAY_STATE_MAX_AGE_SECONDS;
}

void panel_display_read(DisplayStatus *status)
{
    g_return_if_fail(status != NULL);

    status->available = FALSE;
    status->on = FALSE;
    status->brightness = -1;

    gchar *path = app_config_cache_path(DISPLAY_STATE_NAME);
    GKeyFile *file = g_key_file_new();

    if (state_is_recent(path) &&
        g_key_file_load_from_file(file, path, G_KEY_FILE_NONE, NULL)) {
        GError *error = NULL;
        gboolean on = g_key_file_get_boolean(file, "display", "on", &error);

        if (error == NULL) {
            status->available = TRUE;
            status->on = on;
        }
        g_clear_error(&error);

        gint brightness = g_key_file_get_integer(file, "display",
                                                 "brightness", &error);
        if (error == NULL && brightness >= 0)
            status->brightness = CLAMP(brightness, 0, 100);
        g_clear_error(&error);
    }

    g_key_file_unref(file);
    g_free(path);
}

/* One key per request, written whole every time. The handler deletes the file
 * once it has acted, so a request that is still there is one it has not seen
 * yet, and writing a newer one over it is exactly right. */
static gboolean write_request(const gchar *key, const gchar *value)
{
    gchar *path = app_config_cache_path(DISPLAY_REQUEST_NAME);
    GKeyFile *file = g_key_file_new();
    GError *error = NULL;

    /* Whatever is already pending is kept: turning the backlight on and
     * setting its level are two independent requests. */
    g_key_file_load_from_file(file, path, G_KEY_FILE_NONE, NULL);
    g_key_file_set_string(file, "display", key, value);

    gboolean written = g_key_file_save_to_file(file, path, &error);
    if (!written) {
        g_warning("Could not ask the button handler for %s: %s", key,
                  error->message);
        g_clear_error(&error);
    }

    g_key_file_unref(file);
    g_free(path);
    return written;
}

gboolean panel_display_request_state(gboolean on)
{
    return write_request("state", on ? "on" : "off");
}

gboolean panel_display_request_brightness(gint percent)
{
    gchar *value = g_strdup_printf("%d", CLAMP(percent, 1, 100));
    gboolean written = write_request("brightness", value);

    g_free(value);
    return written;
}
