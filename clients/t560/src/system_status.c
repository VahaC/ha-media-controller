#include "system_status.h"

#include <string.h>

/* The kernel exposes one directory per power supply. The battery reports
 * "capacity", while chargers report "online". */
#define POWER_SUPPLY_ROOT "/sys/class/power_supply"

/* One line per interface, after two header lines that are told apart by the
 * "|" they contain. After the interface name and its colon come status, link
 * and level; the level is the signal strength in dBm, written with a
 * trailing dot. */
#define WIRELESS_PATH "/proc/net/wireless"
#define THERMAL_ROOT "/sys/class/thermal"

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


/* Only the first wireless interface is reported. A panel has one radio, and
 * a tablet with none simply reports nothing. */
static gboolean read_wifi_dbm(gint *dbm)
{
    gchar *contents = NULL;

    if (!g_file_get_contents(WIRELESS_PATH, &contents, NULL, NULL))
        return FALSE;

    gchar **lines = g_strsplit(contents, "\n", -1);
    gboolean found = FALSE;

    for (guint i = 0; lines[i] != NULL && !found; i++) {
        /* Both header lines carry a "|", and no data line does before its
         * interface name, which ends in a colon. */
        gchar *colon = strchr(lines[i], ':');
        if (colon == NULL || strchr(lines[i], '|') != NULL)
            continue;

        gchar **fields = g_strsplit_set(colon + 1, " \t", -1);
        guint column = 0;
        for (guint f = 0; fields[f] != NULL; f++) {
            if (*fields[f] == '\0')
                continue;
            /* status, link, level: the level is the third value. */
            if (++column < 3)
                continue;

            gchar *end = NULL;
            gdouble value = g_ascii_strtod(fields[f], &end);
            if (end != fields[f] && value < 0.0 && value >= -200.0) {
                *dbm = (gint)value;
                found = TRUE;
            }
            break;
        }
        g_strfreev(fields);
    }

    g_strfreev(lines);
    g_free(contents);
    return found;
}

static gboolean read_zone_temperature(const gchar *directory, gdouble *celsius)
{
    gchar *raw = read_attribute(directory, "temp");
    if (raw == NULL)
        return FALSE;

    gchar *end = NULL;
    gint64 millidegrees = g_ascii_strtoll(raw, &end, 10);
    gboolean parsed = end != raw;
    g_free(raw);
    if (!parsed)
        return FALSE;

    /* Zones report millidegrees, but not all of them: a few drivers report
     * whole degrees. Anything outside a plausible range is a zone this panel
     * should not be reading. */
    gdouble value = millidegrees >= 1000 ? millidegrees / 1000.0
                                         : (gdouble)millidegrees;
    if (value < -50.0 || value > 150.0)
        return FALSE;

    *celsius = value;
    return TRUE;
}

/* The zone that best describes how warm the tablet is. A CPU zone is
 * preferred where one is named; otherwise the first readable zone is taken,
 * because any of them is a better answer than none. */
static gboolean read_temperature(gdouble *celsius)
{
    GDir *root = g_dir_open(THERMAL_ROOT, 0, NULL);
    if (root == NULL)
        return FALSE;

    gboolean found = FALSE;
    gboolean preferred = FALSE;
    const gchar *name = NULL;

    while ((name = g_dir_read_name(root)) != NULL && !preferred) {
        if (!g_str_has_prefix(name, "thermal_zone"))
            continue;

        gchar *directory = g_build_filename(THERMAL_ROOT, name, NULL);
        gdouble value = 0.0;

        if (read_zone_temperature(directory, &value)) {
            gchar *type = read_attribute(directory, "type");
            gboolean is_cpu = type != NULL &&
                              (strstr(type, "cpu") != NULL ||
                               strstr(type, "CPU") != NULL);
            g_free(type);

            if (is_cpu || !found) {
                *celsius = value;
                found = TRUE;
                preferred = is_cpu;
            }
        }
        g_free(directory);
    }

    g_dir_close(root);
    return found;
}

void system_status_read_diagnostics(SystemDiagnostics *diagnostics)
{
    g_return_if_fail(diagnostics != NULL);

    diagnostics->wifi_available = FALSE;
    diagnostics->wifi_dbm = 0;
    diagnostics->temperature_available = FALSE;
    diagnostics->temperature_c = 0.0;

    diagnostics->wifi_available = read_wifi_dbm(&diagnostics->wifi_dbm);
    diagnostics->temperature_available =
        read_temperature(&diagnostics->temperature_c);
}
