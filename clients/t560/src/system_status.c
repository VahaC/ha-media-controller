#include "system_status.h"

/* The kernel exposes one directory per power supply. The battery reports
 * "capacity", while chargers report "online". */
#define POWER_SUPPLY_ROOT "/sys/class/power_supply"

typedef struct {
    gchar *battery;
    GPtrArray *chargers;
} PowerSupplies;

static gchar *read_attribute(const gchar *directory, const gchar *attribute)
{
    gchar *path = g_build_filename(directory, attribute, NULL);
    gchar *contents = NULL;

    if (!g_file_get_contents(path, &contents, NULL, NULL)) {
        g_free(path);
        return NULL;
    }

    g_free(path);
    return g_strstrip(contents);
}

static gboolean has_attribute(const gchar *directory, const gchar *attribute)
{
    gchar *path = g_build_filename(directory, attribute, NULL);
    gboolean present = g_file_test(path, G_FILE_TEST_EXISTS);
    g_free(path);
    return present;
}

static gboolean is_charger_type(const gchar *type)
{
    return g_strcmp0(type, "Mains") == 0 || g_strcmp0(type, "Wireless") == 0 ||
           g_str_has_prefix(type, "USB");
}

/* The set of power supplies never changes while the panel runs, so the
 * directories are collected once and reused by every later update. */
static const PowerSupplies *power_supplies(void)
{
    static PowerSupplies supplies;
    static gboolean scanned = FALSE;

    if (scanned)
        return &supplies;

    scanned = TRUE;
    supplies.chargers = g_ptr_array_new_with_free_func(g_free);
    GDir *root = g_dir_open(POWER_SUPPLY_ROOT, 0, NULL);
    if (root == NULL)
        return &supplies;

    const gchar *name = NULL;
    while ((name = g_dir_read_name(root)) != NULL) {
        gchar *candidate = g_build_filename(POWER_SUPPLY_ROOT, name, NULL);
        gchar *type = read_attribute(candidate, "type");

        if (g_strcmp0(type, "Battery") == 0 && supplies.battery == NULL &&
            has_attribute(candidate, "capacity")) {
            supplies.battery = candidate;
        } else if (is_charger_type(type) && has_attribute(candidate, "online")) {
            g_ptr_array_add(supplies.chargers, candidate);
        } else {
            g_free(candidate);
        }
        g_free(type);
    }

    g_dir_close(root);
    return &supplies;
}

static gboolean charger_online(const PowerSupplies *supplies)
{
    for (guint i = 0; i < supplies->chargers->len; i++) {
        gchar *online = read_attribute(
            g_ptr_array_index(supplies->chargers, i), "online");
        gboolean connected = g_strcmp0(online, "1") == 0;
        g_free(online);
        if (connected)
            return TRUE;
    }
    return FALSE;
}

void system_status_read_battery(BatteryStatus *status)
{
    status->available = FALSE;
    status->percent = 0;
    status->charging = FALSE;

    const PowerSupplies *supplies = power_supplies();
    if (supplies->battery == NULL)
        return;

    gchar *capacity = read_attribute(supplies->battery, "capacity");
    if (capacity == NULL)
        return;

    gchar *end = NULL;
    gint64 percent = g_ascii_strtoll(capacity, &end, 10);
    gboolean parsed = end != capacity;
    g_free(capacity);
    if (!parsed)
        return;

    status->available = TRUE;
    status->percent = (gint)CLAMP(percent, 0, 100);

    gchar *charge_status = read_attribute(supplies->battery, "status");
    if (g_strcmp0(charge_status, "Charging") == 0) {
        status->charging = TRUE;
    } else if (g_strcmp0(charge_status, "Discharging") != 0) {
        /* Several drivers report "Full", "Not charging" or "Unknown" while
         * the charger is connected, so the charger supplies decide. */
        status->charging = charger_online(supplies);
    }
    g_free(charge_status);
}
