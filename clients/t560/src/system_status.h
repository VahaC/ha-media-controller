#ifndef T560_SYSTEM_STATUS_H
#define T560_SYSTEM_STATUS_H

#include <glib.h>

typedef struct {
    gboolean available;
    gint percent;
    gboolean charging;
} BatteryStatus;

void system_status_read_battery(BatteryStatus *status);

#endif
