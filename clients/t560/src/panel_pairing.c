#include "panel_pairing.h"

#include "app_config.h"

#include <glib/gstdio.h>

#define DEVICE_ID_FILE "panel-id"
#define PAIRING_CODE_FILE "pairing-code"
#define CONFIG_ENTITY_FILE "config-entity"
#define DEVICE_ID_HEX_LENGTH 8

static gchar *identity_path(const gchar *name)
{
    gchar *directory = app_config_directory_path();
    gchar *path = g_build_filename(directory, name, NULL);

    g_mkdir_with_parents(directory, 0700);
    g_free(directory);
    return path;
}

static gchar *read_trimmed_file(const gchar *path)
{
    gchar *contents = NULL;

    if (!g_file_get_contents(path, &contents, NULL, NULL))
        return NULL;

    g_strstrip(contents);
    if (*contents == '\0') {
        g_free(contents);
        return NULL;
    }
    return contents;
}

static gboolean write_private_file(const gchar *path, const gchar *value,
                                   gchar **error_message)
{
    GError *error = NULL;

    if (!g_file_set_contents(path, value, -1, &error)) {
        if (error_message != NULL)
            *error_message = g_strdup(error->message);
        else
            g_warning("Could not write %s: %s", path, error->message);
        g_clear_error(&error);
        return FALSE;
    }
    g_chmod(path, 0600);
    return TRUE;
}

/* The first hardware address in name order. Any interface will do as long as
 * the choice is repeatable: the value is only ever hashed. */
static gchar *first_hardware_address(void)
{
    GDir *directory = g_dir_open("/sys/class/net", 0, NULL);
    if (directory == NULL)
        return NULL;

    GList *names = NULL;
    const gchar *name;
    while ((name = g_dir_read_name(directory)) != NULL) {
        if (g_str_equal(name, "lo"))
            continue;
        names = g_list_prepend(names, g_strdup(name));
    }
    g_dir_close(directory);
    names = g_list_sort(names, (GCompareFunc)g_strcmp0);

    gchar *address = NULL;
    for (GList *item = names; item != NULL && address == NULL;
         item = item->next) {
        gchar *path = g_build_filename("/sys/class/net", item->data,
                                       "address", NULL);
        gchar *value = read_trimmed_file(path);
        g_free(path);
        if (value == NULL)
            continue;
        if (g_str_equal(value, "00:00:00:00:00:00"))
            g_free(value);
        else
            address = value;
    }

    g_list_free_full(names, g_free);
    return address;
}

static gchar *derive_device_id(void)
{
    gchar *address = first_hardware_address();
    gchar *digest;

    if (address != NULL) {
        digest = g_compute_checksum_for_string(G_CHECKSUM_SHA256, address, -1);
        g_free(address);
    } else {
        /* No usable address: a random ID is still unique, it simply does not
         * survive wiping the tablet. */
        gchar random[33];
        for (guint i = 0; i < sizeof(random) - 1; i++)
            random[i] = "0123456789abcdef"[g_random_int_range(0, 16)];
        random[sizeof(random) - 1] = '\0';
        digest = g_strdup(random);
    }

    /* Underscore, not a dash: the ID becomes part of an entity ID. */
    gchar *identifier = g_strdup_printf("t560_%.*s", DEVICE_ID_HEX_LENGTH,
                                        digest);
    g_free(digest);
    return identifier;
}

gchar *panel_pairing_device_id(void)
{
    gchar *path = identity_path(DEVICE_ID_FILE);
    gchar *identifier = read_trimmed_file(path);

    if (identifier == NULL) {
        identifier = derive_device_id();
        write_private_file(path, identifier, NULL);
    }
    g_free(path);
    return identifier;
}

gchar *panel_pairing_code(void)
{
    gchar *path = app_config_cache_path(PAIRING_CODE_FILE);
    gchar *code = read_trimmed_file(path);

    if (code == NULL) {
        code = g_strdup_printf("%06d", g_random_int_range(0, 1000000));
        write_private_file(path, code, NULL);
    }
    g_free(path);
    return code;
}

void panel_pairing_forget_code(void)
{
    gchar *path = app_config_cache_path(PAIRING_CODE_FILE);

    g_unlink(path);
    g_free(path);
}

void panel_pairing_forget_token(void)
{
    gchar *path = identity_path("token");

    g_unlink(path);
    g_free(path);
    /* A new pairing gets a new code: the one on screen may have been read by
     * whoever revoked the token. */
    panel_pairing_forget_code();
}

gchar *panel_pairing_config_entity(void)
{
    gchar *path = app_config_cache_path(CONFIG_ENTITY_FILE);
    gchar *entity = read_trimmed_file(path);

    g_free(path);
    return entity;
}

gboolean panel_pairing_store_token(const gchar *token,
                                   const gchar *config_entity,
                                   gchar **error_message)
{
    g_return_val_if_fail(token != NULL && *token != '\0', FALSE);

    gchar *path = identity_path("token");
    gboolean stored = write_private_file(path, token, error_message);

    g_free(path);
    if (!stored)
        return FALSE;

    /* Home Assistant derives the config sensor's entity ID from the device
     * name, so it is told rather than guessed. */
    if (config_entity != NULL && *config_entity != '\0') {
        gchar *entity_path = app_config_cache_path(CONFIG_ENTITY_FILE);
        write_private_file(entity_path, config_entity, NULL);
        g_free(entity_path);
    }

    panel_pairing_forget_code();
    return TRUE;
}
