#ifndef T560_PANEL_UI_H
#define T560_PANEL_UI_H

#include "app_config.h"

#include <gtk/gtk.h>

typedef struct _PanelUi PanelUi;

typedef enum {
    PANEL_UI_PLAYER_SERVICE,
    PANEL_UI_TOGGLE_SHUFFLE,
    PANEL_UI_CYCLE_REPEAT,
    PANEL_UI_TOGGLE_ROOM,
    PANEL_UI_SET_ROOM_BRIGHTNESS,
    PANEL_UI_SET_ROOM_COLOR_TEMPERATURE,
    PANEL_UI_SHOW_PAGE,
    PANEL_UI_SELECT_QUEUE_ITEM,
    PANEL_UI_SELECT_PLAYLIST,
    PANEL_UI_PLAY_QUEUE_ITEM,
    PANEL_UI_PLAY_PLAYLIST
} PanelUiEvent;

typedef void (*PanelUiEventHandler)(PanelUiEvent event, const gchar *value,
                                    gint index, gpointer user_data);

/* The connection icon reports whether Home Assistant answers, and nothing
 * else. Any HTTP reply proves the link is up, so a rejected entity ID or a
 * refused token is a warning about the configuration, never a lost
 * connection. Ordered from least to most severe; a poll cycle reports the
 * worst state it observed. */
typedef enum {
    PANEL_UI_STATUS_CONNECTED,
    PANEL_UI_STATUS_CONNECTING,
    PANEL_UI_STATUS_WARNING,
    PANEL_UI_STATUS_OFFLINE
} PanelUiStatus;

PanelUi *panel_ui_new(const AppConfig *config, PanelUiEventHandler handler,
                      gpointer user_data);
void panel_ui_free(PanelUi *ui);
GtkWidget *panel_ui_build(PanelUi *ui);
GtkWidget *panel_ui_build_config_error(const gchar *message);
void panel_ui_install_styles(void);

void panel_ui_set_status(PanelUi *ui, const gchar *text,
                         PanelUiStatus status);
void panel_ui_set_clock(PanelUi *ui, const gchar *time_text,
                        const gchar *date_text);
void panel_ui_set_battery(PanelUi *ui, gboolean available, gint percent,
                          gboolean charging);
void panel_ui_set_player(PanelUi *ui, gboolean playing, const gchar *title,
                         const gchar *artist, gdouble position,
                         gdouble duration, gdouble volume, gboolean shuffle,
                         const gchar *repeat);
void panel_ui_set_modes(PanelUi *ui, gboolean shuffle, const gchar *repeat);
void panel_ui_set_album_art(PanelUi *ui, GdkPixbuf *pixbuf);
void panel_ui_set_queue(PanelUi *ui, GPtrArray *titles, GPtrArray *artists,
                        guint count, gint selected);
void panel_ui_set_playlists(PanelUi *ui, GPtrArray *names, guint count,
                            gint selected);
void panel_ui_select_queue_item(PanelUi *ui, gint selected);
void panel_ui_select_playlist(PanelUi *ui, gint selected);
void panel_ui_set_room(PanelUi *ui, guint index, gboolean active,
                       gint brightness_percent, gint color_temp_kelvin,
                       gint min_color_temp_kelvin,
                       gint max_color_temp_kelvin);
void panel_ui_show_page(PanelUi *ui, const gchar *page, const gchar *title);

#endif
