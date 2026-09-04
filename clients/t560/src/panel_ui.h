#ifndef T560_PANEL_UI_H
#define T560_PANEL_UI_H

#include "app_config.h"
#include "panel_grid.h"

#include <gtk/gtk.h>

typedef struct _PanelUi PanelUi;

typedef enum {
    PANEL_UI_PLAYER_SERVICE,
    PANEL_UI_TOGGLE_SHUFFLE,
    PANEL_UI_CYCLE_REPEAT,
    PANEL_UI_TOGGLE_ROOM,
    PANEL_UI_SET_ROOM_BRIGHTNESS,
    PANEL_UI_SET_ROOM_COLOR_TEMPERATURE,
    PANEL_UI_SET_ROOM_TARGET_TEMPERATURE,
    PANEL_UI_SET_ROOM_POSITION,
    PANEL_UI_STOP_ROOM,
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
/* Shown while the panel has no token: the code the person reads out to Home
 * Assistant, and what the panel is currently waiting for. */
GtkWidget *panel_ui_build_pairing(const gchar *code, const gchar *message);
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
/* The room page is a grid of cards the user arranged, so the panel addresses
 * a card by its position in that arrangement rather than by a slot number.
 * A card whose registry element has gone reports NULL and acts on nothing. */
guint panel_ui_card_count(PanelUi *ui);
const PanelEntity *panel_ui_card_entity(PanelUi *ui, guint index);
/* Replaces the arrangement on screen; takes ownership of the grid. The page
 * is one drawing area, so this rebuilds a card list and redraws rather than
 * rebuilding a widget tree. */
void panel_ui_set_grid(PanelUi *ui, PanelGrid *grid);
/* The arrangement on screen, borrowed. */
const PanelGrid *panel_ui_grid(PanelUi *ui);
/* Where the layout editor answers, shown on a page with no cards on it. */
void panel_ui_set_editor_url(PanelUi *ui, const gchar *url);

/* One poll's answer about one card: everything a room card draws that comes
 * from Home Assistant. It is a record rather than a parameter list because
 * the list grows by a field every time a card type is added, and it was
 * already seven parameters long when the second one arrived.
 *
 * Every field carries its own "not answered" value, so a card keeps what it
 * last knew rather than being blanked by an attribute the entity does not
 * have: -1 for the two integers, 0 for the Kelvin bounds, NAN for the two
 * temperatures. */
/* One daily forecast row a weather block draws when the card is large
 * enough for it: the weekday and the high, with the low where one was
 * reported. */
#define PANEL_WEATHER_FORECAST_MAX 5
typedef struct {
    gchar day[8];
    gdouble high;
    gdouble low;
    gboolean has_low;
} PanelWeatherDay;

typedef struct {
    gboolean active;
    gint brightness_percent;
    gint color_temp_kelvin;
    gint min_color_temp_kelvin;
    gint max_color_temp_kelvin;
    /* A thermostat's setpoint and the temperature the room actually is.
     * Unitless, as the payload is: the card draws a degree sign and no
     * letter. */
    gdouble setpoint;
    gdouble ambient;
    /* How far open a cover is, 0 to 100, or -1 when the entity reported no
     * position. A cover that reports none is not half anything: it is open
     * or closed, and the card says so in words. */
    gint position;
    /* A weather block. The condition is the entity state itself ("sunny",
     * "partlycloudy", ...) and NULL while unknown; the temperature is NAN
     * while unknown and the humidity is -1 while unknown. A weather card is
     * a reading rather than a control: it never toggles and never adjusts. */
    const gchar *weather_condition;
    gdouble weather_temperature;
    gint weather_humidity;
} PanelRoomState;

void panel_ui_set_room(PanelUi *ui, guint index, const PanelRoomState *state);
/* The daily forecast behind one weather block, and when it was fetched. A
 * fetch is slow-moving data, so the application asks at most this often and
 * the card draws as many rows as it has room for. */
void panel_ui_set_room_forecast(PanelUi *ui, guint index,
                                const PanelWeatherDay *days, guint count);
gint64 panel_ui_room_forecast_at(PanelUi *ui, guint index);
void panel_ui_show_page(PanelUi *ui, const gchar *page, const gchar *title);
/* Chooses how the whole interface is drawn, not only the player page: the
 * navigation bar and the room page follow the skin too. Safe to call before
 * the widget tree exists, and safe to call with the skin already in use. */
void panel_ui_set_skin(PanelUi *ui, PanelPlayerSkin skin);

#endif
