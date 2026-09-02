#ifndef T560_SYSTEM_STATUS_H
#define T560_SYSTEM_STATUS_H

#include <glib.h>

typedef struct {
    gboolean available;
    gint percent;
    gboolean charging;
} BatteryStatus;

/* Diagnostics that say something about the tablet rather than about what it
 * is showing. Both are optional hardware: a panel wired to Ethernet reports
 * no signal, and a kernel that exposes no thermal zone reports no
 * temperature. `available` is what keeps the sensors in Home Assistant
 * unavailable instead of reading zero. */
typedef struct {
    gboolean wifi_available;
    /* Received signal strength in dBm, always negative in practice. */
    gint wifi_dbm;
    gboolean temperature_available;
    gdouble temperature_c;
} SystemDiagnostics;

void system_status_read_battery(BatteryStatus *status);
void system_status_read_diagnostics(SystemDiagnostics *diagnostics);

#endif
