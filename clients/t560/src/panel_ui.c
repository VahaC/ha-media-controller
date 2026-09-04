#include "panel_ui.h"

#include "panel_grid.h"

#include <math.h>

/* The ADJUST control sits in the top-right corner of a room card.
 *
 * A card is as small as one cell — about 78 by 76 pixels on this screen — and
 * a labelled pill does not fit in one. The control is therefore the same
 * *hit region* at every size and only its drawing changes: a card with room
 * gets the pill it always had, and a card without one gets a compact glyph of
 * three slider lines in the same corner, the same size as the pill is tall.
 * Nothing about what a tap does changes with the size of the card, which is
 * the part a person has to be able to predict. */
#define PANEL_ROOM_ADJUST_HEIGHT 44
#define PANEL_ROOM_ADJUST_WIDTH 92
#define PANEL_ROOM_ADJUST_GLYPH 36
/* Below these the pill is dropped for the glyph: the pill plus its inset
 * needs this much width, and a card shorter than this has nothing left for a
 * name once the pill has taken the top of it. */
#define PANEL_ROOM_ADJUST_PILL_MIN_WIDTH 132
#define PANEL_ROOM_ADJUST_PILL_MIN_HEIGHT 120

/* The gap between cards, in pixels. The cell size itself is derived from the
 * work area the page is given, so the grid always fits whatever it gets and
 * the bottom row is never cut off. */
#define PANEL_ROOM_CARD_GAP 6

/* The two sizes a card icon is tinted at. The large one is what the room page
 * always drew; the small one exists because a card may be a single cell, and
 * scaling a pixbuf on every frame is not something this tablet can afford. */
/* Used by everything this file draws with Cairo, from the room cards to the
 * header indicators. */
#define PANEL_PI 3.14159265358979323846

#define PANEL_ROOM_ICON_LARGE 62
#define PANEL_ROOM_ICON_SMALL 34

/* How long a card takes to cross between off and on. Unchanged from the
 * fixed six-tile page: the animation is what makes a tap feel answered. */
#define PANEL_ROOM_ANIMATION_US 180000.0

/* The side of the artwork the modern skin draws. Album art is scaled to it
 * once, when it arrives. */
#define PANEL_MODERN_ART_SIZE 510

/* The cassette bay, in the coordinates of its own drawing area. The tablet
 * screen is a fixed 800x1219, so the deck is laid out in pixels the way the
 * rest of this interface already is.
 *
 * The bay is one drawing area rather than a tree of widgets: it is a single
 * machined object, the tape inside it moves, and on an ARMv7 with a software
 * renderer one draw handler that repaints a rectangle is cheaper than a dozen
 * widgets that each invalidate their own. */
#define PANEL_DECK_BAY_WIDTH 752
#define PANEL_DECK_BAY_HEIGHT 420
#define PANEL_DECK_WELL_X 96
#define PANEL_DECK_WELL_Y 18
#define PANEL_DECK_WELL_WIDTH 560
#define PANEL_DECK_WELL_HEIGHT 350
/* The shell, centred in the well, at the proportions of a real cassette. */
#define PANEL_DECK_SHELL_X 111
#define PANEL_DECK_SHELL_Y 28
#define PANEL_DECK_SHELL_WIDTH 530
#define PANEL_DECK_SHELL_HEIGHT 330
#define PANEL_DECK_BAND_HEIGHT 46
/* The window in the shell, and the hubs behind it. Shell-relative. */
#define PANEL_DECK_WINDOW_X 75
#define PANEL_DECK_WINDOW_Y 112
#define PANEL_DECK_WINDOW_WIDTH 380
#define PANEL_DECK_WINDOW_HEIGHT 158
#define PANEL_DECK_HUB_LEFT_X 170
#define PANEL_DECK_HUB_RIGHT_X 360
#define PANEL_DECK_HUB_Y 191
#define PANEL_DECK_HUB_RADIUS 21
#define PANEL_DECK_PACK_RADIUS 62
/* The linear tape-position indicator engraved into the bezel below the well. */
#define PANEL_DECK_TAPE_X 250
#define PANEL_DECK_TAPE_Y 386
#define PANEL_DECK_TAPE_WIDTH 406
#define PANEL_DECK_TAPE_HEIGHT 10
#define PANEL_DECK_METER_SEGMENTS 14
/* One turn of the hubs, and how often the reels are advanced. Eight frames a
 * second is enough for a reel to read as turning and leaves the main loop
 * free; each frame repaints two 48-pixel squares and nothing else. */
#define PANEL_DECK_REEL_PERIOD_MS 3400
#define PANEL_DECK_REEL_INTERVAL_MS 125

/* The stack child the cassette player page lives under. It is never a page
 * name: "player" is what navigation, Home Assistant and the status report all
 * use, and which layout answers to it is decided by the skin. */
#define PANEL_DECK_CHILD "player-deck"

#define PANEL_DECK_AMBER 0xffae3dU
#define PANEL_DECK_AMBER_HI 0xffd79bU
#define PANEL_DECK_TAPE_COLOR 0x38240fU

/* Everything one player layout owns. Both layouts are built at start-up and
 * both are written by every setter, including the one that is hidden, so a
 * skin change shows a page that is already correct instead of a page that
 * catches up on the next poll. A pointer that a layout has no use for stays
 * NULL and every setter checks it: the cassette has no progress bar and the
 * modern skin has no tape. */
typedef struct {
    GtkWidget *page;
    GtkWidget *track_title;
    GtkWidget *artist;
    GtkWidget *play;
    GtkWidget *play_icon;
    gint play_icon_size;
    GtkWidget *shuffle;
    GtkWidget *repeat;
    GtkWidget *shuffle_lamp;
    GtkWidget *repeat_lamp;
    GtkWidget *repeat_label;
    GtkWidget *volume;
    /* Modern only. */
    GtkWidget *album_art;
    GtkWidget *progress;
    GtkWidget *position;
    /* Cassette only. */
    GtkWidget *bay;
    GtkWidget *meter;
    GtkWidget *elapsed;
    GtkWidget *total;
    GtkWidget *index;
    GtkWidget *flag_play;
    GtkWidget *flag_shuffle;
    GtkWidget *flag_repeat;
    /* A deck engraves its legends, so this layout wants REPEAT ALL where the
     * other wants Repeat all. */
    gboolean uppercase_labels;
} PanelPlayerLayout;

struct _PanelUi {
    const AppConfig *config;
    PanelUiEventHandler event_handler;
    gpointer event_user_data;
    GtkWidget *stack;
    GtkWidget *status;
    PanelUiStatus status_state;
    GtkWidget *clock_time;
    GtkWidget *clock_date;
    GtkWidget *battery_box;
    GtkWidget *battery_icon;
    GtkWidget *battery_level;
    gint battery_percent;
    gboolean battery_charging;
    GtkWidget *page_title;
    GtkWidget *root;
    PanelPlayerSkin skin;
    PanelPlayerLayout players[PANEL_PLAYER_SKIN_COUNT];
    gboolean on_player;
    gboolean playing;
    /* The cassette bay is one drawing area, so what it draws lives here and
     * nothing in it is repainted unless one of these actually moved. */
    GdkPixbuf *deck_art;
    gdouble deck_progress;
    gdouble deck_volume;
    gdouble deck_angle;
    gint deck_pack_radius;
    gint deck_tape_filled;
    guint deck_lit_segments;
    guint deck_animation_source;
    GtkWidget *queue_list;
    GtkWidget *playlist_list;
    gboolean changing_list_selection;
    GPtrArray *navigation_buttons;
    /* The room page is one drawing area, not a widget per card.
     *
     * A registry of a hundred elements would otherwise be a hundred GtkButton
     * trees, each with its own style context, its own allocation and its own
     * invalidation, on an ARMv7 running a software renderer. It is the same
     * choice the cassette bay already makes, for the same reason: one draw
     * handler that repaints the rectangles that actually changed. */
    GtkWidget *room_area;
    /* The arrangement, owned. Cards are built from it and from the registry
     * every time either one changes; there is no fixed number of them. */
    PanelGrid *room_grid;
    /* PanelRoomCard*, owned, in the order the grid lists them. */
    GPtrArray *room_cards;
    /* Icon artwork by name, tinted for the current skin and shared by every
     * card that names it. A skin change re-tints one image per distinct icon
     * rather than one per card. */
    GHashTable *room_icon_cache;
    /* One tick callback for the whole page while any card is animating. */
    guint room_animation_tick;
    /* The card a finger is currently down on, and whether it went down on
     * that card's ADJUST corner. -1 for neither. */
    gint room_pressed_index;
    gboolean room_pressed_adjust;
    /* Where the editor can be reached, drawn on an empty page. */
    gchar *room_editor_hint;
    GtkWidget *room_sheet;
    GtkWidget *room_sheet_title;
    GtkWidget *room_brightness_box;
    GtkWidget *room_brightness_scale;
    GtkWidget *room_brightness_value;
    GtkWidget *room_temperature_box;
    GtkWidget *room_temperature_scale;
    GtkWidget *room_temperature_value;
    /* The thermostat setpoint. It is a third control on the same sheet
     * rather than a sheet of its own: a climate card wants exactly what a
     * dimmable light wants — a tap that toggles and one value to drag — and
     * a second sheet would be a second thing to learn for the same gesture. */
    GtkWidget *room_setpoint_box;
    GtkWidget *room_setpoint_scale;
    GtkWidget *room_setpoint_value;
    /* A cover. The percentage is a fourth slider on the same sheet, and STOP
     * is the one button any of this needed: a blind travels for seconds and
     * is stopped half way on purpose, which no slider can express. */
    GtkWidget *room_position_box;
    GtkWidget *room_position_scale;
    GtkWidget *room_position_value;
    GtkWidget *room_stop_button;
    gint room_adjust_index;
    gboolean changing_room_adjustment;
    guint brightness_debounce_source;
    guint temperature_debounce_source;
    guint setpoint_debounce_source;
    guint position_debounce_source;
    gint pending_brightness_index;
    gint pending_brightness;
    gint pending_temperature_index;
    gint pending_temperature;
    gint pending_setpoint_index;
    gdouble pending_setpoint;
    gint pending_position_index;
    gint pending_position;
};

/* One card on the room page. It knows its own identity, where it sits in
 * cells, where that lands in pixels, and everything about the entity behind
 * it that the page draws. Nothing here is indexed by a compile-time constant:
 * the array of these is as long as the grid says. */
typedef struct {
    gchar *rid;
    /* The registry element this card acts on, borrowed from the config
     * layout, or NULL when the registry no longer carries its rid. Such a
     * card is drawn as unassigned rather than dropped: the registry is empty
     * while Home Assistant is unreachable, and a card removed on that basis
     * would be gone for good at the next save. */
    const PanelEntity *entity;
    guint column;
    guint row;
    guint columns;
    guint rows;
    /* Recomputed from the allocation, never stored in the layout file. */
    GdkRectangle bounds;
    gboolean active;
    gboolean state_known;
    gdouble active_mix;
    gdouble animation_from;
    gdouble animation_to;
    gint64 animation_start_us;
    gboolean animating;
    gint brightness;
    gint temperature;
    gint temperature_min;
    gint temperature_max;
    /* A thermostat card. `setpoint` is what it is set to and `ambient` what
     * the room actually is; both are NAN until Home Assistant has answered
     * once, and a card draws only the ones it has. The bounds come from the
     * registry element rather than from the poll, because they are a
     * capability and not a state. */
    gdouble setpoint;
    gdouble ambient;
    /* How far open a cover is, 0 to 100, or -1 while Home Assistant has
     * reported no position — either because it has not answered yet or
     * because this cover has none to report. */
    gint position;
    /* A weather block. The condition is owned and NULL while unknown; the
     * temperature is NAN and the humidity is -1 while unknown. It is a
     * reading rather than a control: a tap on it acts on nothing. */
    gchar *weather_condition;
    gdouble weather_temperature;
    gint weather_humidity;
    /* A sensor block. Both are owned and NULL while unknown. It is a
     * reading rather than a control, exactly like a weather block. */
    gchar *sensor_value;
    gchar *sensor_unit;
    /* The daily forecast, and when it was fetched. Empty until Home Assistant
     * has answered a forecast request once; drawn only where the card is
     * large enough for a row. */
    PanelWeatherDay forecast[PANEL_WEATHER_FORECAST_MAX];
    guint forecast_count;
    gint64 forecast_at;
    /* The colour the user chose for this card, and whether they chose one. */
    guint accent;
    gboolean has_accent;
    /* Interned; points into the icon table or the card's own override. */
    gchar *icon;
} PanelRoomCard;

/* One icon, at the two sizes a card may need. Nothing here is coloured.
 *
 * The artwork is painted through Cairo as a mask, so the colour is chosen at
 * draw time and costs nothing: a skin change re-colours every card without
 * touching a pixbuf, and a card the user gave its own colour is drawn in that
 * colour without a private copy of the image. Two sizes are kept because a
 * card may be a single cell, and scaling a pixbuf on every frame is not
 * something this tablet can afford. */
typedef struct {
    GdkPixbuf *large;
    GdkPixbuf *small;
} PanelIconSet;

static void rounded_rectangle(cairo_t *cr, gdouble x, gdouble y, gdouble width,
                              gdouble height, gdouble radius);
static void set_source_color(cairo_t *cr, guint color, gdouble alpha);
static void refresh_room_icons(PanelUi *ui);
static void room_cards_rebuild(PanelUi *ui);
static void room_cards_allocate(PanelUi *ui);
static void open_room_sheet(PanelUi *ui, gint index);
static void deck_update_animation(PanelUi *ui);
static cairo_pattern_t *skin_texture_pattern(PanelPlayerSkin skin);
static void paint_dithered_gradient(cairo_t *cr, gdouble x, gdouble y,
                                    gdouble width, gdouble height,
                                    gdouble radius, guint start, guint end,
                                    PanelPlayerSkin skin);

/* Every colour the room page and the header draw with Cairo rather than CSS.
 * They are a table rather than constants because the skin owns the whole
 * interface: the room page is repainted in the deck's metal and amber when
 * the cassette skin is chosen, and nothing about it is rebuilt to do it. */
typedef struct {
    guint header;
    guint page_start;
    guint page_end;
    guint sheet_start;
    guint sheet_end;
    guint card_start;
    guint card_end;
    guint card_active_start;
    guint card_active_end;
    guint card_down_start;
    guint card_down_end;
    guint card_down_active_start;
    guint card_down_active_end;
    guint card_hover_start;
    guint card_hover_end;
    guint card_hover_active_start;
    guint card_hover_active_end;
    guint card_off;
    guint border;
    guint border_active;
    guint border_off;
    guint bottom;
    guint bottom_active;
    guint bottom_off;
    guint icon_off;
    guint icon_on;
    /* The two tints the RGB565 texture is built from. */
    guint texture_light;
    guint texture_dark;
} PanelSkinPalette;

static const PanelSkinPalette PANEL_PALETTES[PANEL_PLAYER_SKIN_COUNT] = {
    [PANEL_PLAYER_SKIN_MODERN] = {
        .header = 0x0c1420U,
        .page_start = 0x102039U, .page_end = 0x050a12U,
        .sheet_start = 0x1d3550U, .sheet_end = 0x091521U,
        .card_start = 0x213856U, .card_end = 0x0b1828U,
        .card_active_start = 0x1a595bU, .card_active_end = 0x0a252bU,
        .card_down_start = 0x0c1828U, .card_down_end = 0x1b3550U,
        .card_down_active_start = 0x0d3034U, .card_down_active_end = 0x176066U,
        .card_hover_start = 0x29466aU, .card_hover_end = 0x102138U,
        .card_hover_active_start = 0x247174U,
        .card_hover_active_end = 0x0d3037U,
        .card_off = 0x0c1420U,
        .border = 0x3b5678U, .border_active = 0x42d8cfU,
        .border_off = 0x1c293bU,
        .bottom = 0x050910U, .bottom_active = 0x071617U,
        .bottom_off = 0x060a10U,
        .icon_off = 0x9ab2cfU, .icon_on = 0x062125U,
        .texture_light = 0x8fa9c7U, .texture_dark = 0x000814U
    },
    [PANEL_PLAYER_SKIN_CASSETTE] = {
        .header = 0x15171aU,
        .page_start = 0x2b2e33U, .page_end = 0x141619U,
        .sheet_start = 0x3a3f46U, .sheet_end = 0x1b1e22U,
        .card_start = 0x3a3f46U, .card_end = 0x1f2228U,
        .card_active_start = 0x7d5722U, .card_active_end = 0x33220cU,
        .card_down_start = 0x1f2228U, .card_down_end = 0x3a3f46U,
        .card_down_active_start = 0x33220cU, .card_down_active_end = 0x7d5722U,
        .card_hover_start = 0x474d56U, .card_hover_end = 0x24272dU,
        .card_hover_active_start = 0x8f6528U,
        .card_hover_active_end = 0x3c2810U,
        .card_off = 0x1a1c20U,
        .border = 0x555c66U, .border_active = 0xffae3dU,
        .border_off = 0x2a2e34U,
        .bottom = 0x08090bU, .bottom_active = 0x120c04U,
        .bottom_off = 0x0d0f11U,
        .icon_off = 0xa9b1bbU, .icon_on = 0x241a0dU,
        .texture_light = 0xd8c0a0U, .texture_dark = 0x0a0806U
    }
};

static const PanelSkinPalette *palette(PanelUi *ui)
{
    return &PANEL_PALETTES[ui->skin];
}

enum {
    LIST_COLUMN_INDEX,
    LIST_COLUMN_TEXT,
    LIST_COLUMN_COUNT
};

static void add_css_class(GtkWidget *widget, const gchar *name)
{
    gtk_style_context_add_class(gtk_widget_get_style_context(widget), name);
}

static void toggle_css_class(GtkWidget *widget, const gchar *name,
                             gboolean enabled)
{
    GtkStyleContext *style = gtk_widget_get_style_context(widget);
    if (enabled)
        gtk_style_context_add_class(style, name);
    else
        gtk_style_context_remove_class(style, name);
}

/* A tooltip is a pointer artefact, and this panel is only ever touched: the
 * pointer stays where the finger left it, so the tooltip opens after the tap
 * rather than before it and then stays over the key until the next tap lands
 * elsewhere. On the tablet it paints as a black rectangle across the legend
 * of the key that was just pressed. The text a key would have explained
 * stays with it as its accessible name, which draws nothing. */
static void describe_button(GtkWidget *button, const gchar *text)
{
    AtkObject *accessible = gtk_widget_get_accessible(button);

    if (accessible != NULL)
        atk_object_set_name(accessible, text);
}

static GtkWidget *new_label(const gchar *text, const gchar *css_class)
{
    GtkWidget *label = gtk_label_new(text);
    gtk_label_set_ellipsize(GTK_LABEL(label), PANGO_ELLIPSIZE_END);
    gtk_label_set_justify(GTK_LABEL(label), GTK_JUSTIFY_CENTER);
    if (css_class != NULL)
        add_css_class(label, css_class);
    return label;
}

static GtkWidget *new_button(const gchar *text, const gchar *css_class,
                             gint width, gint height)
{
    GtkWidget *button = gtk_button_new_with_label(text);
    gtk_widget_set_size_request(button, width, height);
    if (css_class != NULL)
        add_css_class(button, css_class);
    return button;
}

static GtkWidget *new_icon(const gchar *name, gint pixel_size)
{
    GtkWidget *icon = gtk_image_new_from_icon_name(name, GTK_ICON_SIZE_BUTTON);
    gtk_image_set_pixel_size(GTK_IMAGE(icon), pixel_size);
    return icon;
}



/* The artwork this build carries, and the name each piece answers to in a
 * layout file. The set is deliberately small: it is what the editor offers,
 * and a card that names something else falls back to its domain's default
 * rather than drawing nothing. */
static const struct {
    const gchar *name;
    const gchar *resource;
} PANEL_ROOM_ICONS[] = {
    {"light-1", "/com/vahac/t560/icons/light-1.png"},
    {"light-2", "/com/vahac/t560/icons/light-2.png"},
    {"desk-lamp", "/com/vahac/t560/icons/desk-lamp.png"},
    {"desk-led-strip", "/com/vahac/t560/icons/desk-led-strip.png"},
    {"fan", "/com/vahac/t560/icons/fan.png"},
    {"ac", "/com/vahac/t560/icons/ac.png"},
    {"blind", "/com/vahac/t560/icons/blind.png"},
    {"weather", "/com/vahac/t560/icons/weather.png"}
};

static const gchar *icon_resource(const gchar *name)
{
    for (guint i = 0; i < G_N_ELEMENTS(PANEL_ROOM_ICONS); i++) {
        if (g_strcmp0(PANEL_ROOM_ICONS[i].name, name) == 0)
            return PANEL_ROOM_ICONS[i].resource;
    }
    return NULL;
}

/* What a card draws when the user has chosen no icon for it. The registry
 * carries the domain precisely so that a client can pick a card without
 * parsing an entity ID. */
static const gchar *icon_for_domain(const gchar *domain)
{
    if (g_strcmp0(domain, "light") == 0)
        return "light-1";
    if (g_strcmp0(domain, "switch") == 0)
        return "fan";
    /* The air-conditioner picture is the closest thing this build carries to
     * a thermostat, and a person can still choose one of the others for a
     * card in the editor. */
    if (g_strcmp0(domain, "climate") == 0)
        return "ac";
    if (g_strcmp0(domain, "cover") == 0)
        return "blind";
    if (g_strcmp0(domain, "weather") == 0)
        return "weather";
    /* A sensor block draws its value as type rather than artwork, so it
     * names no icon: icon_set() finds nothing and the card draws none. */
    if (g_strcmp0(domain, "sensor") == 0)
        return "sensor";
    return "light-2";
}

static void icon_set_free(gpointer data)
{
    PanelIconSet *icons = data;

    g_clear_object(&icons->large);
    g_clear_object(&icons->small);
    g_free(icons);
}

/* Loads one piece of artwork once and keeps it for the life of the process.
 * Cards share the entry, so a page of a hundred cards naming three icons
 * holds three of these and not a hundred. */
static const PanelIconSet *icon_set(PanelUi *ui, const gchar *name)
{
    if (name == NULL)
        return NULL;

    PanelIconSet *icons = g_hash_table_lookup(ui->room_icon_cache, name);
    if (icons != NULL)
        return icons;

    const gchar *resource = icon_resource(name);
    if (resource == NULL)
        return NULL;

    GError *error = NULL;
    GdkPixbuf *large = gdk_pixbuf_new_from_resource_at_scale(
        resource, PANEL_ROOM_ICON_LARGE, PANEL_ROOM_ICON_LARGE, TRUE, &error);
    if (large == NULL) {
        g_warning("Could not load room icon %s: %s", resource,
                  error != NULL ? error->message : "unknown error");
        g_clear_error(&error);
        return NULL;
    }

    icons = g_new0(PanelIconSet, 1);
    icons->large = large;
    icons->small = gdk_pixbuf_scale_simple(large, PANEL_ROOM_ICON_SMALL,
                                           PANEL_ROOM_ICON_SMALL,
                                           GDK_INTERP_BILINEAR);
    g_hash_table_insert(ui->room_icon_cache, g_strdup(name), icons);
    return icons;
}

/* A skin change re-colours the room page without touching the artwork: the
 * colour is decided per draw, so there is nothing to re-tint. */
static void refresh_room_icons(PanelUi *ui)
{
    if (ui->room_area != NULL)
        gtk_widget_queue_draw(ui->room_area);
}

static GtkWidget *new_icon_button(const gchar *icon_name, const gchar *text,
                                  const gchar *css_class, gint width,
                                  gint height, gint icon_size,
                                  GtkOrientation orientation,
                                  GtkWidget **icon_out,
                                  GtkWidget **label_out)
{
    GtkWidget *button = gtk_button_new();
    GtkWidget *content = gtk_box_new(orientation, orientation ==
                                                      GTK_ORIENTATION_HORIZONTAL
                                                  ? 9
                                                  : 3);
    GtkWidget *icon = new_icon(icon_name, icon_size);
    GtkWidget *label = text != NULL ? new_label(text, "button-label") : NULL;

    gtk_widget_set_halign(content, GTK_ALIGN_CENTER);
    gtk_widget_set_valign(content, GTK_ALIGN_CENTER);
    gtk_box_pack_start(GTK_BOX(content), icon, FALSE, FALSE, 0);
    if (label != NULL)
        gtk_box_pack_start(GTK_BOX(content), label, FALSE, FALSE, 0);
    gtk_container_add(GTK_CONTAINER(button), content);
    gtk_widget_set_size_request(button, width, height);
    add_css_class(button, "icon-button");
    if (css_class != NULL)
        add_css_class(button, css_class);
    if (icon_out != NULL)
        *icon_out = icon;
    if (label_out != NULL)
        *label_out = label;
    return button;
}

static void emit_event(PanelUi *ui, PanelUiEvent event, const gchar *value,
                       gint index)
{
    ui->event_handler(event, value, index, ui->event_user_data);
}

static void player_clicked(GtkButton *button, gpointer user_data)
{
    PanelUi *ui = user_data;
    emit_event(ui, PANEL_UI_PLAYER_SERVICE,
               g_object_get_data(G_OBJECT(button), "service"), -1);
}

static void shuffle_clicked(GtkButton *button, gpointer user_data)
{
    (void)button;
    emit_event(user_data, PANEL_UI_TOGGLE_SHUFFLE, NULL, -1);
}

static void repeat_clicked(GtkButton *button, gpointer user_data)
{
    (void)button;
    emit_event(user_data, PANEL_UI_CYCLE_REPEAT, NULL, -1);
}

/* The card at a point, or -1. Cards never overlap — the layout reader drops
 * one that would — so the first hit is the only hit. */
static gint room_card_at(PanelUi *ui, gdouble x, gdouble y)
{
    for (guint i = 0; i < ui->room_cards->len; i++) {
        const PanelRoomCard *card = g_ptr_array_index(ui->room_cards, i);
        if (x >= card->bounds.x && x < card->bounds.x + card->bounds.width &&
            y >= card->bounds.y && y < card->bounds.y + card->bounds.height) {
            return (gint)i;
        }
    }
    return -1;
}

/* Whether the ADJUST corner has anything to open. It is one question for
 * every card type on purpose: a dimmable light, a colour-temperature light
 * and a thermostat all want the same gesture — a tap that toggles and one
 * value to drag — and the sheet shows whichever of the three controls the
 * element actually has. */
static gboolean card_is_adjustable(const PanelRoomCard *card)
{
    return card->entity != NULL &&
           (card->entity->brightness || card->entity->color_temperature ||
            card->entity->target_temperature || card->entity->position ||
            card->entity->stoppable);
}

/* A temperature as a card and a sheet write one: no unit letter, because the
 * payload names none, and one decimal only when there is one to show. */
static gchar *format_temperature(gdouble value)
{
    if (fabs(value - round(value)) < 0.05)
        return g_strdup_printf("%.0f°", round(value));
    return g_strdup_printf("%.1f°", value);
}

/* Whether this card is a weather block rather than a control. It never
 * toggles, never adjusts, and never shows a pressed state: a tap on it acts
 * on nothing. */
static gboolean card_is_weather(const PanelRoomCard *card)
{
    return card->entity != NULL &&
           g_strcmp0(card->entity->domain, "weather") == 0;
}

/* Whether this card is a sensor block rather than a control. Exactly the
 * same contract as a weather block: a reading, never a button. */
static gboolean card_is_sensor(const PanelRoomCard *card)
{
    return card->entity != NULL &&
           g_strcmp0(card->entity->domain, "sensor") == 0;
}

/* Whether this card is any reading rather than a control. */
static gboolean card_is_reading(const PanelRoomCard *card)
{
    return card_is_weather(card) || card_is_sensor(card);
}

/* A Home Assistant weather state ("sunny", "partlycloudy", "clear-night")
 * as a card writes it ("Sunny", "Partlycloudy", "Clear night"). The payload
 * names no vocabulary beyond the state itself, so separators become spaces
 * and each word is capitalised; anything unknown is still drawn rather than
 * dropped. */
static gchar *humanize_weather_condition(const gchar *condition)
{
    if (condition == NULL || *condition == '\0')
        return NULL;

    GString *out = g_string_new(NULL);
    gboolean capitalize = TRUE;
    const gchar *p = condition;
    while (*p != '\0') {
        gunichar c = g_utf8_get_char(p);
        if (c == (gunichar)'_' || c == (gunichar)'-' || c == (gunichar)' ') {
            g_string_append_c(out, ' ');
            capitalize = TRUE;
        } else if (capitalize) {
            g_string_append_unichar(out, g_unichar_toupper(c));
            capitalize = FALSE;
        } else {
            g_string_append_unichar(out, c);
        }
        p = g_utf8_next_char(p);
    }
    return g_string_free(out, FALSE);
}

/* What the panel calls each Home Assistant weather state, and which glyph
 * goes with it. The states are a closed vocabulary ("partlycloudy" is one
 * word), so a table says it right where capitalising the raw state says
 * "Partlycloudy". Anything unlisted falls back to the humanised state with
 * a plain cloud. */
typedef enum {
    WEATHER_SUN,
    WEATHER_MOON,
    WEATHER_PARTLY,
    WEATHER_CLOUD,
    WEATHER_FOG,
    WEATHER_RAIN,
    WEATHER_POUR,
    WEATHER_STORM,
    WEATHER_SNOW,
    WEATHER_SLEET,
    WEATHER_HAIL,
    WEATHER_WIND
} WeatherGlyph;

static const struct {
    const gchar *state;
    const gchar *label;
    WeatherGlyph glyph;
} WEATHER_CONDITIONS[] = {
    {"clear-night", "Clear night", WEATHER_MOON},
    {"cloudy", "Cloudy", WEATHER_CLOUD},
    {"fog", "Fog", WEATHER_FOG},
    {"hail", "Hail", WEATHER_HAIL},
    {"lightning", "Thunderstorm", WEATHER_STORM},
    {"lightning-rainy", "Thunderstorm", WEATHER_STORM},
    {"partlycloudy", "Partly cloudy", WEATHER_PARTLY},
    {"pouring", "Pouring rain", WEATHER_POUR},
    {"rainy", "Rain", WEATHER_RAIN},
    {"snowy", "Snow", WEATHER_SNOW},
    {"snowy-rainy", "Sleet", WEATHER_SLEET},
    {"sunny", "Sunny", WEATHER_SUN},
    {"windy", "Windy", WEATHER_WIND},
    {"windy-variant", "Windy", WEATHER_PARTLY},
    {"exceptional", "Exceptional", WEATHER_CLOUD},
};

/* The label and glyph for a weather state. The label is newly allocated;
 * the glyph answers by value. */
static void weather_condition_info(const gchar *condition, gchar **label,
                                   WeatherGlyph *glyph)
{
    if (condition != NULL) {
        for (guint i = 0; i < G_N_ELEMENTS(WEATHER_CONDITIONS); i++) {
            if (g_strcmp0(condition, WEATHER_CONDITIONS[i].state) == 0) {
                *label = g_strdup(WEATHER_CONDITIONS[i].label);
                *glyph = WEATHER_CONDITIONS[i].glyph;
                return;
            }
        }
    }
    *label = humanize_weather_condition(condition);
    *glyph = WEATHER_CLOUD;
}

static void weather_circle(cairo_t *cr, gdouble cx, gdouble cy, gdouble radius)
{
    cairo_new_sub_path(cr);
    cairo_arc(cr, cx, cy, radius, 0.0, 2.0 * PANEL_PI);
}

static void weather_line(cairo_t *cr, gdouble x1, gdouble y1, gdouble x2,
                         gdouble y2, gdouble width)
{
    cairo_set_line_width(cr, width);
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND);
    cairo_move_to(cr, x1, y1);
    cairo_line_to(cr, x2, y2);
    cairo_stroke(cr);
}

/* A cloud of three puffs on a flat base, centred at (cx, cy) and spanning
 * about s by s*0.7. Filled, in the current source colour. */
static void weather_cloud(cairo_t *cr, gdouble cx, gdouble cy, gdouble s)
{
    gdouble x0 = cx - s / 2.0;
    gdouble y0 = cy - s * 0.35;

    cairo_new_sub_path(cr);
    cairo_rectangle(cr, x0 + s * 0.18, y0 + s * 0.32, s * 0.64, s * 0.30);
    weather_circle(cr, x0 + s * 0.30, y0 + s * 0.32, s * 0.185);
    weather_circle(cr, x0 + s * 0.52, y0 + s * 0.22, s * 0.24);
    weather_circle(cr, x0 + s * 0.72, y0 + s * 0.34, s * 0.17);
    cairo_fill(cr);
}

/* One condition as a vector glyph, centred at (cx, cy) in a box of side s.
 * Drawn, not loaded: a card needs the glyph at whatever size its layout
 * leaves, and a scaled pixbuf is exactly what this tablet cannot afford. */
static void draw_weather_glyph(cairo_t *cr, WeatherGlyph glyph, gdouble cx,
                               gdouble cy, gdouble s, guint color,
                               gdouble alpha)
{
    gdouble sun_r = s * 0.16;

    set_source_color(cr, color, alpha);
    switch (glyph) {
    case WEATHER_SUN:
        weather_circle(cr, cx, cy, sun_r);
        cairo_fill(cr);
        for (gint i = 0; i < 8; i++) {
            gdouble angle = i * PANEL_PI / 4.0;
            gdouble dx = cos(angle);
            gdouble dy = sin(angle);
            weather_line(cr, cx + dx * sun_r * 1.45, cy + dy * sun_r * 1.45,
                         cx + dx * sun_r * 2.0, cy + dy * sun_r * 2.0,
                         MAX(1.5, s * 0.035));
        }
        break;
    case WEATHER_MOON:
        cairo_set_fill_rule(cr, CAIRO_FILL_RULE_EVEN_ODD);
        cairo_new_sub_path(cr);
        cairo_arc(cr, cx, cy, s * 0.22, 0.0, 2.0 * PANEL_PI);
        cairo_new_sub_path(cr);
        cairo_arc(cr, cx + s * 0.10, cy - s * 0.06, s * 0.19, 0.0,
                  2.0 * PANEL_PI);
        cairo_fill(cr);
        cairo_set_fill_rule(cr, CAIRO_FILL_RULE_WINDING);
        break;
    case WEATHER_PARTLY:
        weather_circle(cr, cx - s * 0.14, cy - s * 0.14, sun_r);
        cairo_fill(cr);
        weather_cloud(cr, cx + s * 0.08, cy + s * 0.10, s * 0.72);
        break;
    case WEATHER_CLOUD:
        weather_cloud(cr, cx, cy, s);
        break;
    case WEATHER_FOG:
        weather_cloud(cr, cx, cy - s * 0.10, s * 0.72);
        for (gint i = 0; i < 3; i++) {
            gdouble y = cy + s * (0.12 + i * 0.11);
            weather_line(cr, cx - s * 0.30, y, cx + s * 0.30, y,
                         MAX(1.5, s * 0.035));
        }
        break;
    case WEATHER_RAIN:
    case WEATHER_POUR: {
        gint drops = glyph == WEATHER_RAIN ? 3 : 5;
        weather_cloud(cr, cx, cy - s * 0.12, s * 0.72);
        for (gint i = 0; i < drops; i++) {
            gdouble x = cx - s * 0.26 + i * (s * 0.52 / (drops - 1));
            weather_line(cr, x + s * 0.04, cy + s * 0.12, x - s * 0.04,
                         cy + s * 0.30, MAX(1.5, s * 0.04));
        }
        break;
    }
    case WEATHER_STORM:
        weather_cloud(cr, cx, cy - s * 0.12, s * 0.72);
        cairo_new_sub_path(cr);
        cairo_move_to(cr, cx + s * 0.06, cy - s * 0.02);
        cairo_line_to(cr, cx - s * 0.08, cy + s * 0.20);
        cairo_line_to(cr, cx + s * 0.00, cy + s * 0.20);
        cairo_line_to(cr, cx - s * 0.06, cy + s * 0.36);
        cairo_line_to(cr, cx + s * 0.12, cy + s * 0.10);
        cairo_line_to(cr, cx + s * 0.03, cy + s * 0.10);
        cairo_close_path(cr);
        cairo_fill(cr);
        break;
    case WEATHER_SNOW:
    case WEATHER_SLEET:
    case WEATHER_HAIL: {
        gint flakes = glyph == WEATHER_SNOW ? 3 : 4;
        weather_cloud(cr, cx, cy - s * 0.12, s * 0.72);
        for (gint i = 0; i < flakes; i++) {
            gdouble x = cx - s * 0.22 + i * (s * 0.44 / (flakes - 1));
            gdouble y = cy + s * (0.16 + (i % 2) * 0.09);
            if (glyph == WEATHER_HAIL) {
                weather_circle(cr, x, y, MAX(1.2, s * 0.028));
                cairo_fill(cr);
            } else {
                gdouble r = MAX(1.2, s * 0.045);
                weather_line(cr, x - r, y, x + r, y, MAX(1.2, s * 0.02));
                weather_line(cr, x, y - r, x, y + r, MAX(1.2, s * 0.02));
                if (glyph == WEATHER_SLEET)
                    weather_line(cr, x + s * 0.03, y + s * 0.10,
                                 x - s * 0.01, y + s * 0.20,
                                 MAX(1.2, s * 0.02));
            }
        }
        break;
    }
    case WEATHER_WIND:
        weather_cloud(cr, cx - s * 0.05, cy - s * 0.16, s * 0.60);
        weather_line(cr, cx - s * 0.34, cy + s * 0.08, cx + s * 0.30,
                     cy + s * 0.08, MAX(1.5, s * 0.04));
        weather_line(cr, cx - s * 0.34, cy + s * 0.22, cx + s * 0.16,
                     cy + s * 0.22, MAX(1.5, s * 0.04));
        break;
    }
}

/* The ADJUST hit region: the top-right corner, the same size whatever the
 * card is drawn like. See PANEL_ROOM_ADJUST_HEIGHT above for why the drawing
 * changes with the size and the target does not. */
static void card_adjust_region(const PanelRoomCard *card, GdkRectangle *out)
{
    gboolean pill = card->bounds.width >= PANEL_ROOM_ADJUST_PILL_MIN_WIDTH &&
                    card->bounds.height >= PANEL_ROOM_ADJUST_PILL_MIN_HEIGHT;
    gint width = pill ? PANEL_ROOM_ADJUST_WIDTH : PANEL_ROOM_ADJUST_GLYPH;
    gint height = pill ? PANEL_ROOM_ADJUST_HEIGHT : PANEL_ROOM_ADJUST_GLYPH;
    gint inset = pill ? 14 : 6;

    out->width = MIN(width, card->bounds.width);
    out->height = MIN(height, card->bounds.height);
    out->x = card->bounds.x + card->bounds.width - out->width - inset;
    out->y = card->bounds.y + inset;
    if (out->x < card->bounds.x)
        out->x = card->bounds.x;
}

static gboolean emit_brightness_change(gpointer user_data)
{
    PanelUi *ui = user_data;
    gchar *value = g_strdup_printf("%d", ui->pending_brightness);

    ui->brightness_debounce_source = 0;
    emit_event(ui, PANEL_UI_SET_ROOM_BRIGHTNESS, value,
               ui->pending_brightness_index);
    g_free(value);
    return G_SOURCE_REMOVE;
}

static gboolean emit_temperature_change(gpointer user_data)
{
    PanelUi *ui = user_data;
    gchar *value = g_strdup_printf("%d", ui->pending_temperature);

    ui->temperature_debounce_source = 0;
    emit_event(ui, PANEL_UI_SET_ROOM_COLOR_TEMPERATURE, value,
               ui->pending_temperature_index);
    g_free(value);
    return G_SOURCE_REMOVE;
}

static gboolean emit_setpoint_change(gpointer user_data)
{
    PanelUi *ui = user_data;
    /* Sent with one decimal because a step of 0.5 is ordinary. The locale is
     * deliberately not involved: this becomes a JSON number. */
    gchar value[G_ASCII_DTOSTR_BUF_SIZE];

    g_ascii_formatd(value, sizeof(value), "%.1f", ui->pending_setpoint);
    ui->setpoint_debounce_source = 0;
    emit_event(ui, PANEL_UI_SET_ROOM_TARGET_TEMPERATURE, value,
               ui->pending_setpoint_index);
    return G_SOURCE_REMOVE;
}

static gboolean emit_position_change(gpointer user_data)
{
    PanelUi *ui = user_data;
    gchar *value = g_strdup_printf("%d", ui->pending_position);

    ui->position_debounce_source = 0;
    emit_event(ui, PANEL_UI_SET_ROOM_POSITION, value,
               ui->pending_position_index);
    g_free(value);
    return G_SOURCE_REMOVE;
}

static void room_position_changed(GtkRange *range, gpointer user_data)
{
    PanelUi *ui = user_data;
    gint value = (gint)gtk_range_get_value(range);
    gchar *text = g_strdup_printf("%d%%", value);

    gtk_label_set_text(GTK_LABEL(ui->room_position_value), text);
    g_free(text);
    if (ui->changing_room_adjustment || ui->room_adjust_index < 0)
        return;

    ui->pending_position_index = ui->room_adjust_index;
    ui->pending_position = value;
    if (ui->position_debounce_source != 0)
        g_source_remove(ui->position_debounce_source);
    ui->position_debounce_source = g_timeout_add_full(
        G_PRIORITY_DEFAULT_IDLE, 350, emit_position_change, ui, NULL);
}

/* STOP is not debounced and carries no value: it is the one control on this
 * sheet that has to reach Home Assistant the instant it is pressed, because
 * what it is for is a blind that is moving right now. */
static void room_stop_clicked(GtkButton *button, gpointer user_data)
{
    (void)button;
    PanelUi *ui = user_data;

    if (ui->room_adjust_index < 0)
        return;
    if (ui->position_debounce_source != 0) {
        /* A drag that has not been sent yet is abandoned rather than sent
         * after the stop: the finger has since asked for the opposite. */
        g_source_remove(ui->position_debounce_source);
        ui->position_debounce_source = 0;
    }
    emit_event(ui, PANEL_UI_STOP_ROOM, NULL, ui->room_adjust_index);
}

static void room_setpoint_changed(GtkRange *range, gpointer user_data)
{
    PanelUi *ui = user_data;
    gdouble value = gtk_range_get_value(range);
    gchar *text = format_temperature(value);

    gtk_label_set_text(GTK_LABEL(ui->room_setpoint_value), text);
    g_free(text);
    if (ui->changing_room_adjustment || ui->room_adjust_index < 0)
        return;

    ui->pending_setpoint_index = ui->room_adjust_index;
    ui->pending_setpoint = value;
    if (ui->setpoint_debounce_source != 0)
        g_source_remove(ui->setpoint_debounce_source);
    ui->setpoint_debounce_source = g_timeout_add_full(
        G_PRIORITY_DEFAULT_IDLE, 350, emit_setpoint_change, ui, NULL);
}

static void room_brightness_changed(GtkRange *range, gpointer user_data)
{
    PanelUi *ui = user_data;
    gint value = (gint)(gtk_range_get_value(range) + 0.5);
    gchar *text = g_strdup_printf("%d%%", value);

    gtk_label_set_text(GTK_LABEL(ui->room_brightness_value), text);
    g_free(text);
    if (ui->changing_room_adjustment || ui->room_adjust_index < 0)
        return;

    ui->pending_brightness_index = ui->room_adjust_index;
    ui->pending_brightness = value;
    if (ui->brightness_debounce_source != 0)
        g_source_remove(ui->brightness_debounce_source);
    ui->brightness_debounce_source = g_timeout_add_full(
        G_PRIORITY_DEFAULT_IDLE, 350, emit_brightness_change, ui, NULL);
}

static void room_temperature_changed(GtkRange *range, gpointer user_data)
{
    PanelUi *ui = user_data;
    gint value = (gint)(gtk_range_get_value(range) + 0.5);
    gchar *text = g_strdup_printf("%d K", value);

    gtk_label_set_text(GTK_LABEL(ui->room_temperature_value), text);
    g_free(text);
    if (ui->changing_room_adjustment || ui->room_adjust_index < 0)
        return;

    ui->pending_temperature_index = ui->room_adjust_index;
    ui->pending_temperature = value;
    if (ui->temperature_debounce_source != 0)
        g_source_remove(ui->temperature_debounce_source);
    ui->temperature_debounce_source = g_timeout_add_full(
        G_PRIORITY_DEFAULT_IDLE, 350, emit_temperature_change, ui, NULL);
}

static void close_room_sheet(GtkButton *button, gpointer user_data)
{
    (void)button;
    PanelUi *ui = user_data;
    gtk_revealer_set_reveal_child(GTK_REVEALER(ui->room_sheet), FALSE);
}

/* The sheet shows the controls this element actually has and hides the rest,
 * so one sheet serves a dimmable light, a colour-temperature light and a
 * thermostat without any of them being offered a control that would do
 * nothing. */
static void open_room_sheet(PanelUi *ui, gint index)
{
    PanelRoomCard *card = g_ptr_array_index(ui->room_cards, index);
    const PanelEntity *entity = card->entity;
    gchar *title = g_strdup_printf("%s SETTINGS", entity->name);
    gint brightness = card->brightness >= 0 ? card->brightness : 100;
    gint temperature = card->temperature >= 0
                           ? card->temperature
                           : (card->temperature_min +
                              card->temperature_max) / 2;
    /* A thermostat that has not answered yet opens in the middle of its own
     * range rather than at its minimum, which would read as a setting
     * somebody made. */
    gdouble setpoint = !isnan(card->setpoint)
                           ? card->setpoint
                           : (entity->min_temp + entity->max_temp) / 2.0;

    ui->room_adjust_index = index;
    gtk_label_set_text(GTK_LABEL(ui->room_sheet_title), title);
    g_free(title);
    gtk_widget_set_visible(ui->room_brightness_box, entity->brightness);
    gtk_widget_set_visible(ui->room_temperature_box,
                           entity->color_temperature);
    gtk_widget_set_visible(ui->room_setpoint_box,
                           entity->target_temperature);
    gtk_widget_set_visible(ui->room_position_box, entity->position);
    gtk_widget_set_visible(ui->room_stop_button, entity->stoppable);

    ui->changing_room_adjustment = TRUE;
    gtk_range_set_range(GTK_RANGE(ui->room_temperature_scale),
                        card->temperature_min, card->temperature_max);
    gtk_range_set_value(GTK_RANGE(ui->room_brightness_scale), brightness);
    gtk_range_set_value(GTK_RANGE(ui->room_temperature_scale), temperature);
    if (entity->target_temperature) {
        gtk_range_set_range(GTK_RANGE(ui->room_setpoint_scale),
                            entity->min_temp, entity->max_temp);
        gtk_range_set_increments(GTK_RANGE(ui->room_setpoint_scale),
                                 entity->temp_step, entity->temp_step);
        gtk_range_set_round_digits(GTK_RANGE(ui->room_setpoint_scale),
                                   entity->temp_step < 1.0 ? 1 : 0);
        gtk_range_set_value(GTK_RANGE(ui->room_setpoint_scale), setpoint);
    }
    if (entity->position) {
        /* A cover that has not answered yet opens at closed rather than in
         * the middle: half open is a position somebody chose, and showing it
         * before Home Assistant has said so would invite a drag that moves
         * the blind to where the slider already claimed it was. */
        gtk_range_set_value(GTK_RANGE(ui->room_position_scale),
                            card->position >= 0 ? card->position : 0);
    }
    ui->changing_room_adjustment = FALSE;
    gtk_revealer_set_reveal_child(GTK_REVEALER(ui->room_sheet), TRUE);
}

static void page_clicked(GtkButton *button, gpointer user_data)
{
    PanelUi *ui = user_data;
    const gchar *page = g_object_get_data(G_OBJECT(button), "page");
    const gchar *title = g_object_get_data(G_OBJECT(button), "title");

    if (ui->room_sheet != NULL)
        gtk_revealer_set_reveal_child(GTK_REVEALER(ui->room_sheet), FALSE);
    panel_ui_show_page(ui, page, title);
    emit_event(ui, PANEL_UI_SHOW_PAGE, page, -1);
}

static gint selected_list_index(GtkTreeSelection *selection)
{
    GtkTreeModel *model = NULL;
    GtkTreeIter iter;
    gint index = -1;

    if (gtk_tree_selection_get_selected(selection, &model, &iter))
        gtk_tree_model_get(model, &iter, LIST_COLUMN_INDEX, &index, -1);
    return index;
}

static void queue_selection_changed(GtkTreeSelection *selection,
                                    gpointer user_data)
{
    PanelUi *ui = user_data;
    if (!ui->changing_list_selection)
        emit_event(ui, PANEL_UI_SELECT_QUEUE_ITEM, NULL,
                   selected_list_index(selection));
}

static void playlist_selection_changed(GtkTreeSelection *selection,
                                       gpointer user_data)
{
    PanelUi *ui = user_data;
    if (!ui->changing_list_selection)
        emit_event(ui, PANEL_UI_SELECT_PLAYLIST, NULL,
                   selected_list_index(selection));
}

static void play_queue_clicked(GtkButton *button, gpointer user_data)
{
    (void)button;
    emit_event(user_data, PANEL_UI_PLAY_QUEUE_ITEM, NULL, -1);
}

static void play_playlist_clicked(GtkButton *button, gpointer user_data)
{
    (void)button;
    emit_event(user_data, PANEL_UI_PLAY_PLAYLIST, NULL, -1);
}

static void select_row(GtkWidget *list, gint selected)
{
    GtkTreeSelection *selection = gtk_tree_view_get_selection(
        GTK_TREE_VIEW(list));
    gtk_tree_selection_unselect_all(selection);
    if (selected >= 0) {
        GtkTreePath *path = gtk_tree_path_new_from_indices(selected, -1);
        gtk_tree_selection_select_path(selection, path);
        gtk_tree_path_free(path);
    }
}

static GtkWidget *new_list(PanelUi *ui, gboolean queue)
{
    GtkListStore *store = gtk_list_store_new(
        LIST_COLUMN_COUNT, G_TYPE_INT, G_TYPE_STRING);
    GtkWidget *list = gtk_tree_view_new_with_model(GTK_TREE_MODEL(store));
    g_object_unref(store);

    gtk_tree_view_set_headers_visible(GTK_TREE_VIEW(list), FALSE);
    gtk_tree_view_set_enable_search(GTK_TREE_VIEW(list), FALSE);
    gtk_tree_view_set_fixed_height_mode(GTK_TREE_VIEW(list), TRUE);
    add_css_class(list, "list-view");

    GtkCellRenderer *renderer = gtk_cell_renderer_text_new();
    g_object_set(renderer, "ellipsize", PANGO_ELLIPSIZE_END, NULL);
    gtk_cell_renderer_set_fixed_size(renderer, -1, queue ? 90 : 82);
    GtkTreeViewColumn *column = gtk_tree_view_column_new_with_attributes(
        "", renderer, "text", LIST_COLUMN_TEXT, NULL);
    gtk_tree_view_column_set_sizing(column, GTK_TREE_VIEW_COLUMN_FIXED);
    gtk_tree_view_append_column(GTK_TREE_VIEW(list), column);

    GtkTreeSelection *selection = gtk_tree_view_get_selection(
        GTK_TREE_VIEW(list));
    gtk_tree_selection_set_mode(selection, GTK_SELECTION_SINGLE);
    g_signal_connect(selection, "changed",
                     G_CALLBACK(queue ? queue_selection_changed
                                      : playlist_selection_changed),
                     ui);
    return list;
}

static gchar *format_time(gdouble seconds)
{
    gint total = MAX(0, (gint)seconds);
    return g_strdup_printf("%d:%02d", total / 60, total % 60);
}

static GtkWidget *navigation_button(PanelUi *ui, const gchar *icon,
                                    const gchar *text, const gchar *page,
                                    const gchar *title)
{
    GtkWidget *button = new_icon_button(
        icon, text, "nav-button", 150, 72, 23, GTK_ORIENTATION_VERTICAL,
        NULL, NULL);
    g_object_set_data(G_OBJECT(button), "page", (gpointer)page);
    g_object_set_data(G_OBJECT(button), "title", (gpointer)title);
    g_signal_connect(button, "clicked", G_CALLBACK(page_clicked), ui);
    g_ptr_array_add(ui->navigation_buttons, button);
    toggle_css_class(button, "active", g_str_equal(page, "player"));
    return button;
}

/* Queue and Playlists belong to the player, so they are reached from the
 * player page instead of the navigation bar shared by every page. */
static GtkWidget *library_button(PanelUi *ui, const gchar *icon,
                                 const gchar *text, const gchar *page,
                                 const gchar *title)
{
    GtkWidget *button = new_icon_button(
        icon, text, "library-button", 150, 74, 23,
        GTK_ORIENTATION_VERTICAL, NULL, NULL);
    g_object_set_data(G_OBJECT(button), "page", (gpointer)page);
    g_object_set_data(G_OBJECT(button), "title", (gpointer)title);
    g_signal_connect(button, "clicked", G_CALLBACK(page_clicked), ui);
    return button;
}

static GtkWidget *navigation(PanelUi *ui)
{
    GtkWidget *navigation_box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_widget_set_halign(navigation_box, GTK_ALIGN_CENTER);
    add_css_class(navigation_box, "navigation-bar");
    gtk_box_pack_start(GTK_BOX(navigation_box),
                       navigation_button(ui, "audio-x-generic-symbolic",
                                         "Player", "player", "NOW PLAYING"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(
        GTK_BOX(navigation_box),
        navigation_button(ui, "computer-symbolic", "Room", "room",
                          "ROOM CONTROLS"),
        FALSE, FALSE, 0);
    return navigation_box;
}

static GtkWidget *player_page(PanelUi *ui)
{
    PanelPlayerLayout *layout = &ui->players[PANEL_PLAYER_SKIN_MODERN];
    GtkWidget *page = gtk_box_new(GTK_ORIENTATION_VERTICAL, 11);
    gtk_widget_set_margin_start(page, 24);
    gtk_widget_set_margin_end(page, 24);
    gtk_widget_set_margin_top(page, 14);
    gtk_widget_set_margin_bottom(page, 10);
    add_css_class(page, "player-page");

    layout->album_art = gtk_image_new_from_icon_name(
        "audio-x-generic-symbolic", GTK_ICON_SIZE_DIALOG);
    gtk_widget_set_size_request(layout->album_art, PANEL_MODERN_ART_SIZE,
                                PANEL_MODERN_ART_SIZE);
    GtkWidget *artwork = gtk_frame_new(NULL);
    gtk_frame_set_shadow_type(GTK_FRAME(artwork), GTK_SHADOW_NONE);
    gtk_widget_set_halign(artwork, GTK_ALIGN_CENTER);
    add_css_class(artwork, "artwork-card");
    gtk_container_add(GTK_CONTAINER(artwork), layout->album_art);

    GtkWidget *track_details = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
    add_css_class(track_details, "track-details");
    layout->track_title = new_label("Nothing playing", "track-title");
    layout->artist = new_label("", "artist");
    gtk_box_pack_start(GTK_BOX(track_details), layout->track_title,
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(track_details), layout->artist,
                       FALSE, FALSE, 0);

    GtkWidget *timeline = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
    gtk_widget_set_margin_start(timeline, 34);
    gtk_widget_set_margin_end(timeline, 34);
    layout->progress = gtk_progress_bar_new();
    gtk_widget_set_size_request(layout->progress, -1, 12);
    layout->position = new_label("0:00  /  0:00", "position");
    gtk_box_pack_start(GTK_BOX(timeline), layout->progress, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(timeline), layout->position, FALSE, FALSE, 0);

    gtk_box_pack_start(GTK_BOX(page), artwork, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(page), track_details, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), timeline, FALSE, FALSE, 0);

    GtkWidget *modes = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_widget_set_halign(modes, GTK_ALIGN_CENTER);
    layout->shuffle = new_icon_button(
        "media-playlist-shuffle-symbolic", "Shuffle", "mode-button",
        190, 58, 23, GTK_ORIENTATION_HORIZONTAL, NULL, NULL);
    layout->repeat = new_icon_button(
        "media-playlist-repeat-symbolic", "Repeat off", "mode-button",
        190, 58, 23, GTK_ORIENTATION_HORIZONTAL, NULL,
        &layout->repeat_label);
    g_signal_connect(layout->shuffle, "clicked",
                     G_CALLBACK(shuffle_clicked), ui);
    g_signal_connect(layout->repeat, "clicked",
                     G_CALLBACK(repeat_clicked), ui);
    gtk_box_pack_start(GTK_BOX(modes), layout->shuffle, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(modes), layout->repeat, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), modes, FALSE, FALSE, 0);

    GtkWidget *controls = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 18);
    gtk_widget_set_halign(controls, GTK_ALIGN_CENTER);
    GtkWidget *previous = new_icon_button(
        "media-skip-backward-symbolic", NULL, "transport-button",
        108, 86, 38, GTK_ORIENTATION_VERTICAL, NULL, NULL);
    layout->play = new_icon_button(
        "media-playback-start-symbolic", NULL, "play-button", 120, 104,
        48, GTK_ORIENTATION_VERTICAL, &layout->play_icon, NULL);
    layout->play_icon_size = 48;
    GtkWidget *next = new_icon_button(
        "media-skip-forward-symbolic", NULL, "transport-button",
        108, 86, 38, GTK_ORIENTATION_VERTICAL, NULL, NULL);
    describe_button(previous, "Previous track");
    describe_button(layout->play, "Play or pause");
    describe_button(next, "Next track");
    g_object_set_data(G_OBJECT(previous), "service", "media_previous_track");
    g_object_set_data(G_OBJECT(layout->play), "service", "media_play_pause");
    g_object_set_data(G_OBJECT(next), "service", "media_next_track");
    g_signal_connect(previous, "clicked", G_CALLBACK(player_clicked), ui);
    g_signal_connect(layout->play, "clicked", G_CALLBACK(player_clicked), ui);
    g_signal_connect(next, "clicked", G_CALLBACK(player_clicked), ui);
    gtk_box_pack_start(GTK_BOX(controls), previous, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(controls), layout->play, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(controls), next, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), controls, FALSE, FALSE, 0);

    GtkWidget *volume_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_widget_set_halign(volume_row, GTK_ALIGN_CENTER);
    GtkWidget *volume_controls = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    add_css_class(volume_controls, "volume-card");
    GtkWidget *down = new_icon_button(
        "audio-volume-low-symbolic", NULL, "volume-button", 86, 62, 28,
        GTK_ORIENTATION_VERTICAL, NULL, NULL);
    GtkWidget *volume_readout = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_size_request(volume_readout, 180, -1);
    gtk_box_pack_start(GTK_BOX(volume_readout),
                       new_label("VOLUME", "volume-caption"),
                       FALSE, FALSE, 0);
    layout->volume = new_label("--", "volume");
    gtk_box_pack_start(GTK_BOX(volume_readout), layout->volume,
                       FALSE, FALSE, 0);
    GtkWidget *up = new_icon_button(
        "audio-volume-high-symbolic", NULL, "volume-button", 86, 62, 28,
        GTK_ORIENTATION_VERTICAL, NULL, NULL);
    describe_button(down, "Volume down");
    describe_button(up, "Volume up");
    g_object_set_data(G_OBJECT(down), "service", "volume_down");
    g_object_set_data(G_OBJECT(up), "service", "volume_up");
    g_signal_connect(down, "clicked", G_CALLBACK(player_clicked), ui);
    g_signal_connect(up, "clicked", G_CALLBACK(player_clicked), ui);
    gtk_box_pack_start(GTK_BOX(volume_controls), down, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(volume_controls), volume_readout,
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(volume_controls), up, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(volume_row),
                       library_button(ui, "view-list-details-symbolic",
                                      "Queue", "queue", "QUEUE"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(volume_row), volume_controls, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(volume_row),
                       library_button(ui, "view-list-icons-symbolic",
                                      "Playlists", "playlists", "PLAYLISTS"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), volume_row, FALSE, FALSE, 0);
    gtk_box_pack_end(GTK_BOX(page), navigation(ui), FALSE, FALSE, 4);
    layout->page = page;
    return page;
}

/* ------------------------------------------------------------ cassette skin
 *
 * The second skin is the faceplate of an early-1980s three-head cassette
 * deck, and it owns the whole interface rather than the player page alone:
 * the navigation bar and the room page are restyled with it, through the
 * .skin-cassette class on the root widget and the palette above.
 *
 * Two properties of this tablet shape how it is drawn. The framebuffer is
 * RGB565, so every large surface goes through paint_dithered_gradient and
 * every small one is a flat fill with hard edges; there is not one CSS
 * gradient in this skin, because a gradient across a key would band. And the
 * CPU is an ARMv7 running a software renderer, so nothing in the bay is
 * repainted unless the pixels it produces actually changed.
 */

/* A tape moves by area, not by radius: the wound length of a pack grows with
 * the square of its radius. Reading the root back is what makes the reels
 * behave like tape rather than like two circles being resized, and it is why
 * the two packs are the same size halfway through a track. */
static void deck_pack_radii(gdouble progress, gdouble *left, gdouble *right)
{
    gdouble hub = PANEL_DECK_HUB_RADIUS;
    gdouble full = PANEL_DECK_PACK_RADIUS;
    gdouble span = full * full - hub * hub;
    gdouble played = CLAMP(progress, 0.0, 1.0);

    *left = sqrt(hub * hub + span * (1.0 - played));
    *right = sqrt(hub * hub + span * played);
}

static void deck_draw_pack(cairo_t *cr, gdouble x, gdouble y, gdouble radius)
{
    cairo_pattern_t *pack = cairo_pattern_create_radial(
        x, y - radius * 0.25, radius * 0.1, x, y, radius);

    cairo_pattern_add_color_stop_rgb(pack, 0.0, 0.482, 0.337, 0.212);
    cairo_pattern_add_color_stop_rgb(pack, 1.0, 0.271, 0.173, 0.098);
    cairo_set_source(cr, pack);
    cairo_arc(cr, x, y, radius, 0.0, 2.0 * G_PI);
    cairo_fill(cr);
    cairo_pattern_destroy(pack);
    set_source_color(cr, 0x8c6540U, 0.65);
    cairo_set_line_width(cr, 1.4);
    cairo_arc(cr, x, y, radius, 0.0, 2.0 * G_PI);
    cairo_stroke(cr);
}

/* Six teeth, as a real shell has. They are the whole point of the animation:
 * a plain disc turning is indistinguishable from a disc standing still. */
static void deck_draw_hub(cairo_t *cr, gdouble x, gdouble y, gdouble angle)
{
    cairo_save(cr);
    cairo_translate(cr, x, y);
    cairo_rotate(cr, angle);
    set_source_color(cr, 0xd6dbe2U, 1.0);
    cairo_arc(cr, 0.0, 0.0, PANEL_DECK_HUB_RADIUS, 0.0, 2.0 * G_PI);
    cairo_fill(cr);
    set_source_color(cr, 0x141619U, 1.0);
    for (guint i = 0; i < 6; i++) {
        cairo_save(cr);
        cairo_rotate(cr, i * G_PI / 3.0);
        cairo_rectangle(cr, -3.0, -PANEL_DECK_HUB_RADIUS + 1.0, 6.0, 8.0);
        cairo_fill(cr);
        cairo_restore(cr);
    }
    cairo_arc(cr, 0.0, 0.0, 10.0, 0.0, 2.0 * G_PI);
    cairo_fill(cr);
    cairo_restore(cr);
}

static gboolean deck_page_draw(GtkWidget *widget, cairo_t *cr,
                               gpointer user_data)
{
    PanelUi *ui = user_data;
    const PanelSkinPalette *colors = palette(ui);

    /* Brushed black aluminium. The grain lives in the texture pattern, so
     * this is one gradient and one tiled fill however tall the page is. */
    paint_dithered_gradient(
        cr, 0.0, 0.0, gtk_widget_get_allocated_width(widget),
        gtk_widget_get_allocated_height(widget), 0.0, colors->page_start,
        colors->page_end, PANEL_PLAYER_SKIN_CASSETTE);
    return FALSE;
}

static gboolean deck_bay_draw(GtkWidget *widget, cairo_t *cr,
                              gpointer user_data)
{
    PanelUi *ui = user_data;
    gdouble width = gtk_widget_get_allocated_width(widget);
    gdouble height = gtk_widget_get_allocated_height(widget);
    gdouble shell_x = PANEL_DECK_SHELL_X;
    gdouble shell_y = PANEL_DECK_SHELL_Y;
    gdouble window_x = shell_x + PANEL_DECK_WINDOW_X;
    gdouble window_y = shell_y + PANEL_DECK_WINDOW_Y;
    gdouble hub_y = shell_y + PANEL_DECK_HUB_Y;
    gdouble hub_left = shell_x + PANEL_DECK_HUB_LEFT_X;
    gdouble hub_right = shell_x + PANEL_DECK_HUB_RIGHT_X;
    gdouble left_radius = 0.0;
    gdouble right_radius = 0.0;
    gdouble filled;
    cairo_pattern_t *sheen;
    const gdouble screws[4][2] = {
        {14.0, 14.0},
        {PANEL_DECK_SHELL_WIDTH - 14.0, 14.0},
        {14.0, PANEL_DECK_SHELL_HEIGHT - 14.0},
        {PANEL_DECK_SHELL_WIDTH - 14.0, PANEL_DECK_SHELL_HEIGHT - 14.0}
    };

    /* The machined bezel, and the chamfer that catches the light along its
     * top edge. */
    paint_dithered_gradient(cr, 0.0, 0.0, width, height, 5.0, 0x4a5058U,
                            0x1e2127U, PANEL_PLAYER_SKIN_CASSETTE);
    set_source_color(cr, 0xffffffU, 0.18);
    cairo_set_line_width(cr, 1.0);
    rounded_rectangle(cr, 0.5, 0.5, width - 1.0, height - 1.0, 5.0);
    cairo_stroke(cr);

    /* The well the cassette is loaded into. */
    set_source_color(cr, 0x070808U, 1.0);
    rounded_rectangle(cr, PANEL_DECK_WELL_X, PANEL_DECK_WELL_Y,
                      PANEL_DECK_WELL_WIDTH, PANEL_DECK_WELL_HEIGHT, 3.0);
    cairo_fill(cr);

    cairo_save(cr);
    rounded_rectangle(cr, shell_x, shell_y, PANEL_DECK_SHELL_WIDTH,
                      PANEL_DECK_SHELL_HEIGHT, 4.0);
    cairo_clip(cr);

    /* The label is the album art, cropped to the shell face when it arrived. */
    if (ui->deck_art != NULL) {
        gdk_cairo_set_source_pixbuf(cr, ui->deck_art, shell_x, shell_y);
        cairo_paint(cr);
    } else {
        paint_dithered_gradient(cr, shell_x, shell_y, PANEL_DECK_SHELL_WIDTH,
                                PANEL_DECK_SHELL_HEIGHT, 0.0, 0x2a2d33U,
                                0x121417U, PANEL_PLAYER_SKIN_CASSETTE);
    }

    /* The sheen of the shell's plastic face. */
    sheen = cairo_pattern_create_linear(
        shell_x, shell_y, shell_x, shell_y + PANEL_DECK_SHELL_HEIGHT);
    cairo_pattern_add_color_stop_rgba(sheen, 0.0, 1.0, 1.0, 1.0, 0.13);
    cairo_pattern_add_color_stop_rgba(sheen, 0.24, 1.0, 1.0, 1.0, 0.0);
    cairo_pattern_add_color_stop_rgba(sheen, 1.0, 0.0, 0.0, 0.0, 0.42);
    cairo_set_source(cr, sheen);
    cairo_paint(cr);
    cairo_pattern_destroy(sheen);
    cairo_set_source(cr, skin_texture_pattern(PANEL_PLAYER_SKIN_CASSETTE));
    cairo_paint(cr);

    /* The paper band the side and the queue position are printed on. Their
     * text is two labels in the overlay above, because Pango belongs in a
     * label and not in a draw handler that runs eight times a second. */
    set_source_color(cr, 0x0a0908U, 0.84);
    cairo_rectangle(cr, shell_x, shell_y, PANEL_DECK_SHELL_WIDTH,
                    PANEL_DECK_BAND_HEIGHT);
    cairo_fill(cr);
    set_source_color(cr, 0xf2e3cbU, 0.2);
    cairo_rectangle(cr, shell_x, shell_y + PANEL_DECK_BAND_HEIGHT,
                    PANEL_DECK_SHELL_WIDTH, 1.0);
    cairo_fill(cr);

    for (guint i = 0; i < G_N_ELEMENTS(screws); i++) {
        set_source_color(cr, 0x4e545dU, 1.0);
        cairo_arc(cr, shell_x + screws[i][0], shell_y + screws[i][1], 4.5,
                  0.0, 2.0 * G_PI);
        cairo_fill(cr);
        set_source_color(cr, 0x14161aU, 1.0);
        cairo_arc(cr, shell_x + screws[i][0], shell_y + screws[i][1], 2.0,
                  0.0, 2.0 * G_PI);
        cairo_fill(cr);
    }
    cairo_restore(cr);

    /* The window, and the tape running behind it. */
    cairo_save(cr);
    rounded_rectangle(cr, window_x, window_y, PANEL_DECK_WINDOW_WIDTH,
                      PANEL_DECK_WINDOW_HEIGHT, 10.0);
    cairo_clip(cr);
    set_source_color(cr, 0x0c0b0aU, 0.88);
    cairo_paint(cr);

    /* Down from each pack, over the guides, across the head block. */
    set_source_color(cr, PANEL_DECK_TAPE_COLOR, 1.0);
    cairo_set_line_width(cr, 8.0);
    cairo_move_to(cr, hub_left - 30.0, hub_y + 12.0);
    cairo_line_to(cr, hub_left - 22.0, hub_y + 61.0);
    cairo_move_to(cr, hub_right + 30.0, hub_y + 12.0);
    cairo_line_to(cr, hub_right + 22.0, hub_y + 61.0);
    cairo_stroke(cr);
    cairo_rectangle(cr, hub_left - 26.0, hub_y + 57.0,
                    (hub_right + 26.0) - (hub_left - 26.0), 7.0);
    cairo_fill(cr);
    /* The two guide rollers the tape turns around. Without them the span
     * across the head block reads as a bracket rather than as tape. */
    for (guint i = 0; i < 2; i++) {
        gdouble x = i == 0 ? hub_left - 24.0 : hub_right + 24.0;

        set_source_color(cr, 0x9aa2adU, 1.0);
        cairo_arc(cr, x, hub_y + 60.0, 8.0, 0.0, 2.0 * G_PI);
        cairo_fill(cr);
        set_source_color(cr, 0x141619U, 1.0);
        cairo_arc(cr, x, hub_y + 60.0, 3.5, 0.0, 2.0 * G_PI);
        cairo_fill(cr);
    }

    deck_pack_radii(ui->deck_progress, &left_radius, &right_radius);
    deck_draw_pack(cr, hub_left, hub_y, left_radius);
    deck_draw_pack(cr, hub_right, hub_y, right_radius);
    deck_draw_hub(cr, hub_left, hub_y, ui->deck_angle);
    deck_draw_hub(cr, hub_right, hub_y, ui->deck_angle);
    cairo_restore(cr);

    set_source_color(cr, 0xf2e3cbU, 0.26);
    cairo_set_line_width(cr, 2.0);
    rounded_rectangle(cr, window_x + 1.0, window_y + 1.0,
                      PANEL_DECK_WINDOW_WIDTH - 2.0,
                      PANEL_DECK_WINDOW_HEIGHT - 2.0, 10.0);
    cairo_stroke(cr);

    /* The linear tape-position indicator. The packs alone are honest but hard
     * to read halfway through a track, where both are the same size. */
    set_source_color(cr, 0x101112U, 1.0);
    rounded_rectangle(cr, PANEL_DECK_TAPE_X, PANEL_DECK_TAPE_Y,
                      PANEL_DECK_TAPE_WIDTH, PANEL_DECK_TAPE_HEIGHT, 5.0);
    cairo_fill(cr);
    filled = PANEL_DECK_TAPE_WIDTH * CLAMP(ui->deck_progress, 0.0, 1.0);
    if (filled >= PANEL_DECK_TAPE_HEIGHT) {
        set_source_color(cr, PANEL_DECK_AMBER, 1.0);
        rounded_rectangle(cr, PANEL_DECK_TAPE_X, PANEL_DECK_TAPE_Y, filled,
                          PANEL_DECK_TAPE_HEIGHT, 5.0);
        cairo_fill(cr);
    }
    return FALSE;
}

static gboolean deck_meter_draw(GtkWidget *widget, cairo_t *cr,
                                gpointer user_data)
{
    PanelUi *ui = user_data;
    gdouble width = gtk_widget_get_allocated_width(widget);
    gdouble height = gtk_widget_get_allocated_height(widget);
    gdouble gap = 4.0;
    gdouble step = (width + gap) / PANEL_DECK_METER_SEGMENTS;

    for (guint i = 0; i < PANEL_DECK_METER_SEGMENTS; i++) {
        guint color = 0x241a0dU;

        if (i < ui->deck_lit_segments) {
            color = i + 1 == ui->deck_lit_segments ? PANEL_DECK_AMBER_HI
                                                   : PANEL_DECK_AMBER;
        }
        set_source_color(cr, color, 1.0);
        cairo_rectangle(cr, i * step, 0.0, step - gap, height);
        cairo_fill(cr);
    }
    return FALSE;
}

/* Only the two hubs move, so only the two hubs are invalidated. Repainting
 * the window would mean repainting the packs and the label behind them
 * eight times a second, which this tablet cannot afford. */
static void deck_damage_reels(PanelUi *ui)
{
    GtkWidget *bay = ui->players[PANEL_PLAYER_SKIN_CASSETTE].bay;
    gint size = 2 * PANEL_DECK_HUB_RADIUS + 4;
    gint y = PANEL_DECK_SHELL_Y + PANEL_DECK_HUB_Y - PANEL_DECK_HUB_RADIUS - 2;

    if (bay == NULL)
        return;
    gtk_widget_queue_draw_area(
        bay, PANEL_DECK_SHELL_X + PANEL_DECK_HUB_LEFT_X -
                 PANEL_DECK_HUB_RADIUS - 2, y, size, size);
    gtk_widget_queue_draw_area(
        bay, PANEL_DECK_SHELL_X + PANEL_DECK_HUB_RIGHT_X -
                 PANEL_DECK_HUB_RADIUS - 2, y, size, size);
}

static gboolean deck_reel_tick(gpointer user_data)
{
    PanelUi *ui = user_data;

    ui->deck_angle += 2.0 * G_PI * PANEL_DECK_REEL_INTERVAL_MS /
                      PANEL_DECK_REEL_PERIOD_MS;
    if (ui->deck_angle > 2.0 * G_PI)
        ui->deck_angle -= 2.0 * G_PI;
    deck_damage_reels(ui);
    return G_SOURCE_CONTINUE;
}

/* The reels turn while the tape runs and while anyone can see them, and not
 * otherwise. A panel sitting on the room page, or paused, costs nothing. */
static void deck_update_animation(PanelUi *ui)
{
    gboolean wanted = ui->skin == PANEL_PLAYER_SKIN_CASSETTE &&
                      ui->playing && ui->on_player &&
                      ui->players[PANEL_PLAYER_SKIN_CASSETTE].bay != NULL;

    if (wanted == (ui->deck_animation_source != 0))
        return;
    if (wanted) {
        ui->deck_animation_source = g_timeout_add_full(
            G_PRIORITY_DEFAULT_IDLE, PANEL_DECK_REEL_INTERVAL_MS,
            deck_reel_tick, ui, NULL);
    } else {
        g_source_remove(ui->deck_animation_source);
        ui->deck_animation_source = 0;
    }
}

static void deck_set_progress(PanelUi *ui, gdouble progress)
{
    PanelPlayerLayout *layout = &ui->players[PANEL_PLAYER_SKIN_CASSETTE];
    gdouble left = 0.0;
    gdouble right = 0.0;
    gint radius;
    gint filled;

    if (layout->bay == NULL)
        return;

    ui->deck_progress = CLAMP(progress, 0.0, 1.0);
    deck_pack_radii(ui->deck_progress, &left, &right);
    radius = (gint)(left + 0.5);
    filled = (gint)(PANEL_DECK_TAPE_WIDTH * ui->deck_progress);

    /* A pack radius moves by a fraction of a pixel a second, so redrawing the
     * window every poll would repaint the label for nothing. */
    if (radius != ui->deck_pack_radius) {
        ui->deck_pack_radius = radius;
        gtk_widget_queue_draw_area(
            layout->bay, PANEL_DECK_SHELL_X + PANEL_DECK_WINDOW_X,
            PANEL_DECK_SHELL_Y + PANEL_DECK_WINDOW_Y,
            PANEL_DECK_WINDOW_WIDTH, PANEL_DECK_WINDOW_HEIGHT);
    }
    if (filled != ui->deck_tape_filled) {
        ui->deck_tape_filled = filled;
        gtk_widget_queue_draw_area(layout->bay, PANEL_DECK_TAPE_X,
                                   PANEL_DECK_TAPE_Y, PANEL_DECK_TAPE_WIDTH,
                                   PANEL_DECK_TAPE_HEIGHT);
    }
}

static void deck_set_volume(PanelUi *ui, gdouble volume)
{
    PanelPlayerLayout *layout = &ui->players[PANEL_PLAYER_SKIN_CASSETTE];
    guint lit;

    if (layout->meter == NULL)
        return;

    ui->deck_volume = CLAMP(volume, 0.0, 1.0);
    lit = (guint)(ui->deck_volume * PANEL_DECK_METER_SEGMENTS + 0.5);
    if (lit == ui->deck_lit_segments)
        return;
    ui->deck_lit_segments = lit;
    gtk_widget_queue_draw(layout->meter);
}

/* A deck key with a pilot lamp where a transport key has its symbol. The lamp
 * is a widget of its own so that lighting it moves nothing. */
static GtkWidget *new_deck_lamp_key(const gchar *text, gint width,
                                    gint height, GtkWidget **label_out,
                                    GtkWidget **lamp_out)
{
    GtkWidget *button = gtk_button_new();
    GtkWidget *content = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
    GtkWidget *lamp = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    GtkWidget *label = new_label(text, "deck-key-label");

    gtk_widget_set_size_request(lamp, 22, 4);
    gtk_widget_set_halign(lamp, GTK_ALIGN_CENTER);
    add_css_class(lamp, "deck-lamp");
    gtk_widget_set_halign(content, GTK_ALIGN_CENTER);
    gtk_widget_set_valign(content, GTK_ALIGN_CENTER);
    gtk_box_pack_start(GTK_BOX(content), lamp, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(content), label, FALSE, FALSE, 0);
    gtk_container_add(GTK_CONTAINER(button), content);
    gtk_widget_set_size_request(button, width, height);
    add_css_class(button, "deck-key");
    if (label_out != NULL)
        *label_out = label;
    if (lamp_out != NULL)
        *lamp_out = lamp;
    return button;
}

static GtkWidget *deck_transport_key(PanelUi *ui, const gchar *icon,
                                     const gchar *text, const gchar *service,
                                     const gchar *description, gint width,
                                     GtkWidget **icon_out)
{
    GtkWidget *button = new_icon_button(icon, text, "deck-key", width, 118,
                                        30, GTK_ORIENTATION_VERTICAL,
                                        icon_out, NULL);
    describe_button(button, description);
    g_object_set_data(G_OBJECT(button), "service", (gpointer)service);
    g_signal_connect(button, "clicked", G_CALLBACK(player_clicked), ui);
    return button;
}

static GtkWidget *deck_page_button(PanelUi *ui, const gchar *icon,
                                   const gchar *text, const gchar *page,
                                   const gchar *title)
{
    GtkWidget *button = new_icon_button(icon, text, "deck-key", -1, 74, 22,
                                        GTK_ORIENTATION_HORIZONTAL, NULL,
                                        NULL);
    g_object_set_data(G_OBJECT(button), "page", (gpointer)page);
    g_object_set_data(G_OBJECT(button), "title", (gpointer)title);
    g_signal_connect(button, "clicked", G_CALLBACK(page_clicked), ui);
    return button;
}

static GtkWidget *deck_scale_mark(const gchar *text, GtkAlign align)
{
    GtkWidget *label = new_label(text, "deck-scale");

    gtk_widget_set_halign(label, align);
    return label;
}

static GtkWidget *deck_page(PanelUi *ui)
{
    PanelPlayerLayout *layout = &ui->players[PANEL_PLAYER_SKIN_CASSETTE];
    GtkWidget *page = gtk_box_new(GTK_ORIENTATION_VERTICAL, 13);

    layout->uppercase_labels = TRUE;
    gtk_widget_set_margin_start(page, 24);
    gtk_widget_set_margin_end(page, 24);
    gtk_widget_set_margin_top(page, 16);
    gtk_widget_set_margin_bottom(page, 10);
    add_css_class(page, "deck-page");
    g_signal_connect(page, "draw", G_CALLBACK(deck_page_draw), ui);

    /* The name strip, engraved into the faceplate. */
    GtkWidget *strip = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 16);
    GtkWidget *maker = new_label("MUSIC ASSISTANT", "deck-brand");
    GtkWidget *kind = new_label("STEREO CASSETTE DECK", "deck-engraved");
    GtkWidget *model = new_label("MA-560", "deck-model");
    gtk_widget_set_size_request(strip, -1, 40);
    add_css_class(strip, "deck-strip");
    gtk_label_set_ellipsize(GTK_LABEL(maker), PANGO_ELLIPSIZE_NONE);
    gtk_label_set_ellipsize(GTK_LABEL(kind), PANGO_ELLIPSIZE_NONE);
    gtk_widget_set_halign(maker, GTK_ALIGN_START);
    gtk_widget_set_valign(kind, GTK_ALIGN_BASELINE);
    gtk_widget_set_valign(model, GTK_ALIGN_BASELINE);
    gtk_box_pack_start(GTK_BOX(strip), maker, TRUE, TRUE, 14);
    gtk_box_pack_end(GTK_BOX(strip), model, FALSE, FALSE, 14);
    gtk_box_pack_end(GTK_BOX(strip), kind, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), strip, FALSE, FALSE, 0);

    /* The bay. One drawing area, with the three engraved legends over it. */
    layout->bay = gtk_drawing_area_new();
    gtk_widget_set_size_request(layout->bay, PANEL_DECK_BAY_WIDTH,
                                PANEL_DECK_BAY_HEIGHT);
    g_signal_connect(layout->bay, "draw", G_CALLBACK(deck_bay_draw), ui);

    GtkWidget *bay = gtk_overlay_new();
    GtkWidget *side = new_label("SIDE A", "deck-band-side");
    GtkWidget *tape_caption = new_label("TAPE POSITION", "deck-engraved");
    layout->index = new_label("", "deck-band-index");
    gtk_container_add(GTK_CONTAINER(bay), layout->bay);

    gtk_label_set_ellipsize(GTK_LABEL(side), PANGO_ELLIPSIZE_NONE);
    gtk_label_set_ellipsize(GTK_LABEL(tape_caption), PANGO_ELLIPSIZE_NONE);
    gtk_widget_set_halign(side, GTK_ALIGN_START);
    gtk_widget_set_valign(side, GTK_ALIGN_START);
    gtk_widget_set_size_request(side, -1, PANEL_DECK_BAND_HEIGHT);
    gtk_widget_set_margin_start(side, PANEL_DECK_SHELL_X + 34);
    gtk_widget_set_margin_top(side, PANEL_DECK_SHELL_Y);
    gtk_widget_set_halign(layout->index, GTK_ALIGN_END);
    gtk_widget_set_valign(layout->index, GTK_ALIGN_START);
    gtk_widget_set_size_request(layout->index, -1, PANEL_DECK_BAND_HEIGHT);
    gtk_widget_set_margin_end(layout->index, PANEL_DECK_SHELL_X + 34);
    gtk_widget_set_margin_top(layout->index, PANEL_DECK_SHELL_Y);
    gtk_widget_set_halign(tape_caption, GTK_ALIGN_START);
    gtk_widget_set_valign(tape_caption, GTK_ALIGN_START);
    gtk_widget_set_size_request(tape_caption, -1, 20);
    gtk_widget_set_margin_start(tape_caption, PANEL_DECK_WELL_X);
    gtk_widget_set_margin_top(tape_caption, PANEL_DECK_TAPE_Y - 5);
    gtk_overlay_add_overlay(GTK_OVERLAY(bay), side);
    gtk_overlay_add_overlay(GTK_OVERLAY(bay), layout->index);
    gtk_overlay_add_overlay(GTK_OVERLAY(bay), tape_caption);
    gtk_box_pack_start(GTK_BOX(page), bay, FALSE, FALSE, 0);

    /* One fluorescent display, as a deck has: everything behind one pane. */
    GtkWidget *display = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_size_request(display, -1, 196);
    add_css_class(display, "deck-display");
    layout->track_title = new_label("Nothing playing", "deck-title");
    layout->artist = new_label("", "deck-artist");
    gtk_widget_set_halign(layout->track_title, GTK_ALIGN_START);
    gtk_widget_set_halign(layout->artist, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(display), layout->track_title, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(display), layout->artist, FALSE, FALSE, 0);

    GtkWidget *flags = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 22);
    layout->flag_shuffle = new_label("SHUFFLE", "deck-flag");
    layout->flag_repeat = new_label("REPEAT", "deck-flag");
    layout->flag_play = new_label("PLAY", "deck-flag");
    add_css_class(flags, "deck-flags");
    gtk_widget_set_size_request(flags, -1, 30);
    gtk_box_pack_start(GTK_BOX(flags), layout->flag_shuffle, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(flags), layout->flag_repeat, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(flags), layout->flag_play, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(display), flags, FALSE, FALSE, 0);

    GtkWidget *bottom = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 26);
    GtkWidget *counter = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 9);
    layout->elapsed = new_label("0:00", "deck-counter");
    layout->total = new_label("/ 0:00", "deck-counter-total");
    gtk_widget_set_valign(counter, GTK_ALIGN_END);
    gtk_widget_set_valign(layout->elapsed, GTK_ALIGN_BASELINE);
    gtk_widget_set_valign(layout->total, GTK_ALIGN_BASELINE);
    gtk_box_pack_start(GTK_BOX(counter), layout->elapsed, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(counter), layout->total, FALSE, FALSE, 0);

    GtkWidget *meter_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 5);
    GtkWidget *meter_head = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *meter_caption = new_label("VOLUME", "deck-meter-caption");
    GtkWidget *scale = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    layout->volume = new_label("--", "deck-meter-value");
    layout->meter = gtk_drawing_area_new();
    gtk_widget_set_size_request(layout->meter, -1, 17);
    g_signal_connect(layout->meter, "draw", G_CALLBACK(deck_meter_draw), ui);
    gtk_label_set_ellipsize(GTK_LABEL(meter_caption), PANGO_ELLIPSIZE_NONE);
    gtk_widget_set_halign(meter_caption, GTK_ALIGN_START);
    gtk_widget_set_halign(layout->volume, GTK_ALIGN_END);
    gtk_box_pack_start(GTK_BOX(meter_head), meter_caption, TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(meter_head), layout->volume, FALSE, FALSE, 0);
    gtk_box_set_homogeneous(GTK_BOX(scale), TRUE);
    gtk_box_pack_start(GTK_BOX(scale), deck_scale_mark("0", GTK_ALIGN_START),
                       TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(scale), deck_scale_mark("25", GTK_ALIGN_CENTER),
                       TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(scale), deck_scale_mark("50", GTK_ALIGN_CENTER),
                       TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(scale), deck_scale_mark("75", GTK_ALIGN_CENTER),
                       TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(scale), deck_scale_mark("100", GTK_ALIGN_END),
                       TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(meter_box), meter_head, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(meter_box), layout->meter, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(meter_box), scale, FALSE, FALSE, 0);
    gtk_widget_set_valign(meter_box, GTK_ALIGN_END);

    gtk_box_pack_start(GTK_BOX(bottom), counter, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(bottom), meter_box, TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(display), bottom, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(page), display, FALSE, FALSE, 0);

    /* Transport keys. Every one is at least as large as the button it
     * replaces on the other skin, so no touch target moves with the skin. */
    GtkWidget *transport = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 16);
    GtkWidget *previous = deck_transport_key(
        ui, "media-skip-backward-symbolic", "PREV", "media_previous_track",
        "Previous track", 200, NULL);
    layout->play = deck_transport_key(
        ui, "media-playback-start-symbolic", "PLAY / PAUSE",
        "media_play_pause", "Play or pause", -1, &layout->play_icon);
    GtkWidget *next = deck_transport_key(
        ui, "media-skip-forward-symbolic", "NEXT", "media_next_track",
        "Next track", 200, NULL);
    layout->play_icon_size = 34;
    add_css_class(layout->play, "deck-key-main");
    gtk_box_pack_start(GTK_BOX(transport), previous, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(transport), layout->play, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(transport), next, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), transport, FALSE, FALSE, 0);

    /* Mode keys and output level. */
    GtkWidget *functions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 14);
    GtkWidget *spacer = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    GtkWidget *down = new_icon_button(
        "audio-volume-low-symbolic", "VOL", "deck-key", 132, 78, 24,
        GTK_ORIENTATION_HORIZONTAL, NULL, NULL);
    GtkWidget *up = new_icon_button(
        "audio-volume-high-symbolic", "VOL", "deck-key", 132, 78, 24,
        GTK_ORIENTATION_HORIZONTAL, NULL, NULL);
    layout->shuffle = new_deck_lamp_key("SHUFFLE", 186, 78, NULL,
                                        &layout->shuffle_lamp);
    layout->repeat = new_deck_lamp_key("REPEAT OFF", 186, 78,
                                       &layout->repeat_label,
                                       &layout->repeat_lamp);
    describe_button(down, "Volume down");
    describe_button(up, "Volume up");
    g_object_set_data(G_OBJECT(down), "service", "volume_down");
    g_object_set_data(G_OBJECT(up), "service", "volume_up");
    g_signal_connect(down, "clicked", G_CALLBACK(player_clicked), ui);
    g_signal_connect(up, "clicked", G_CALLBACK(player_clicked), ui);
    g_signal_connect(layout->shuffle, "clicked",
                     G_CALLBACK(shuffle_clicked), ui);
    g_signal_connect(layout->repeat, "clicked",
                     G_CALLBACK(repeat_clicked), ui);
    gtk_box_pack_start(GTK_BOX(functions), layout->shuffle, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(functions), layout->repeat, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(functions), spacer, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(functions), down, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(functions), up, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), functions, FALSE, FALSE, 0);

    GtkWidget *library = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 16);
    gtk_box_pack_start(GTK_BOX(library),
                       deck_page_button(ui, "view-list-details-symbolic",
                                        "QUEUE", "queue", "QUEUE"),
                       TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(library),
                       deck_page_button(ui, "view-list-icons-symbolic",
                                        "PLAYLISTS", "playlists",
                                        "PLAYLISTS"),
                       TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(page), library, FALSE, FALSE, 0);

    gtk_box_pack_end(GTK_BOX(page), navigation(ui), FALSE, FALSE, 4);
    layout->page = page;
    return page;
}

static GtkWidget *list_page(PanelUi *ui, gboolean queue)
{
    GtkWidget *page = gtk_box_new(GTK_ORIENTATION_VERTICAL, 10);
    gtk_widget_set_margin_start(page, 16);
    gtk_widget_set_margin_end(page, 16);

    GtkWidget *scroll = gtk_scrolled_window_new(NULL, NULL);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll), GTK_POLICY_NEVER,
                                   GTK_POLICY_AUTOMATIC);
    gtk_scrolled_window_set_kinetic_scrolling(GTK_SCROLLED_WINDOW(scroll), TRUE);
    gtk_scrolled_window_set_capture_button_press(GTK_SCROLLED_WINDOW(scroll),
                                                  TRUE);
    GtkWidget *list = new_list(ui, queue);
    gtk_container_add(GTK_CONTAINER(scroll), list);
    GtkWidget *play = new_button(queue ? "PLAY SELECTED TRACK"
                                       : "PLAY SELECTED PLAYLIST",
                                 "play-selected", -1, 80);
    if (queue) {
        ui->queue_list = list;
        g_signal_connect(play, "clicked", G_CALLBACK(play_queue_clicked), ui);
    } else {
        ui->playlist_list = list;
        g_signal_connect(play, "clicked", G_CALLBACK(play_playlist_clicked), ui);
    }
    gtk_box_pack_start(GTK_BOX(page), scroll, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(page), play, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), navigation(ui), FALSE, FALSE, 4);
    return page;
}

/* The tablet framebuffer is RGB565: five bits of red and blue, six of green.
 * A gradient that looks smooth in a 24-bit screenshot therefore collapses
 * into wide colour bands on the actual display, because a hundred shades of a
 * channel land on thirty-two values. Static irregular noise scatters each
 * pixel across the two values it falls between, which reads as the shade that
 * is missing and costs one extra fill. An ordered Bayer matrix would do the
 * same and leave visible diagonals; an animated dither would cost a repaint
 * per frame.
 *
 * The cassette skin folds its brushed grain into the same pattern instead of
 * painting it separately: brushed aluminium is high-frequency by nature, so
 * one surface carries the texture and the dither together, in one operation.
 *
 * One pattern per skin, built on first use and kept for the life of the
 * process. Each is 16 KB. */
static cairo_pattern_t *skin_texture_pattern(PanelPlayerSkin skin)
{
    static cairo_pattern_t *patterns[PANEL_PLAYER_SKIN_COUNT];
    const PanelSkinPalette *colors = &PANEL_PALETTES[skin];
    const guint size = 64;

    if (patterns[skin] == NULL) {
        cairo_surface_t *surface = cairo_image_surface_create(
            CAIRO_FORMAT_ARGB32, size, size);
        guint32 *pixels = (guint32 *)cairo_image_surface_get_data(surface);
        gint stride = cairo_image_surface_get_stride(surface) /
                      (gint)sizeof(*pixels);
        gboolean brushed = skin == PANEL_PLAYER_SKIN_CASSETTE;

        for (guint y = 0; y < size; y++) {
            for (guint x = 0; x < size; x++) {
                guint32 noise = (x + 1U) * 0x9e3779b1U ^
                                (y + 1U) * 0x85ebca6bU;
                gboolean light;
                guint tint;
                guint alpha;

                noise ^= noise >> 16;
                noise *= 0x7feb352dU;
                noise ^= noise >> 15;
                noise *= 0x846ca68bU;
                noise ^= noise >> 16;
                /* Brushed metal is lit and shadowed by the row rather than by
                 * the pixel, so the grain decides the sign and the noise only
                 * decides how far. */
                light = brushed ? (y & 1U) == 0U : (noise & 0xffU) < 128U;
                tint = light ? colors->texture_light : colors->texture_dark;
                alpha = light ? 2U + ((noise >> 8) & 0x07U)
                              : 1U + ((noise >> 11) % 6U);
                /* Cairo image surfaces hold premultiplied colour. */
                pixels[y * stride + x] =
                    (alpha << 24) |
                    ((((tint >> 16) & 0xffU) * alpha / 255U) << 16) |
                    ((((tint >> 8) & 0xffU) * alpha / 255U) << 8) |
                    ((tint & 0xffU) * alpha / 255U);
            }
        }
        cairo_surface_mark_dirty(surface);
        patterns[skin] = cairo_pattern_create_for_surface(surface);
        cairo_pattern_set_extend(patterns[skin], CAIRO_EXTEND_REPEAT);
        cairo_pattern_set_filter(patterns[skin], CAIRO_FILTER_NEAREST);
        cairo_surface_destroy(surface);
    }
    return patterns[skin];
}

static guint mix_color(guint from, guint to, gdouble progress)
{
    guint result = 0;

    for (guint shift = 0; shift <= 16; shift += 8) {
        gdouble start = (from >> shift) & 0xffU;
        gdouble end = (to >> shift) & 0xffU;
        guint channel = (guint)(start + (end - start) * progress + 0.5);
        result |= channel << shift;
    }
    return result;
}

static void add_gradient_stop(cairo_pattern_t *gradient, gdouble offset,
                              guint color)
{
    cairo_pattern_add_color_stop_rgb(
        gradient, offset, ((color >> 16) & 0xffU) / 255.0,
        ((color >> 8) & 0xffU) / 255.0, (color & 0xffU) / 255.0);
}

static void paint_dithered_gradient(cairo_t *cr, gdouble x, gdouble y,
                                    gdouble width, gdouble height,
                                    gdouble radius, guint start, guint end,
                                    PanelPlayerSkin skin)
{
    cairo_pattern_t *gradient = cairo_pattern_create_linear(
        x, y, x, y + height);
    guint middle = mix_color(start, end, 0.48);

    add_gradient_stop(gradient, 0.0, start);
    add_gradient_stop(gradient, 0.48, middle);
    add_gradient_stop(gradient, 1.0, end);
    cairo_save(cr);
    if (radius > 0.0)
        rounded_rectangle(cr, x, y, width, height, radius);
    else
        cairo_rectangle(cr, x, y, width, height);
    cairo_clip(cr);
    cairo_set_source(cr, gradient);
    cairo_paint(cr);
    cairo_set_source(cr, skin_texture_pattern(skin));
    cairo_paint(cr);
    cairo_restore(cr);
    cairo_pattern_destroy(gradient);
}

static gboolean room_page_draw(GtkWidget *widget, cairo_t *cr,
                               gpointer user_data)
{
    PanelUi *ui = user_data;
    const PanelSkinPalette *colors = palette(ui);

    paint_dithered_gradient(
        cr, 0.0, 0.0, gtk_widget_get_allocated_width(widget),
        gtk_widget_get_allocated_height(widget), 0.0, colors->page_start,
        colors->page_end, ui->skin);
    return FALSE;
}

static gboolean room_sheet_draw(GtkWidget *widget, cairo_t *cr,
                                gpointer user_data)
{
    PanelUi *ui = user_data;
    const PanelSkinPalette *colors = palette(ui);
    gdouble width = gtk_widget_get_allocated_width(widget);
    gdouble height = gtk_widget_get_allocated_height(widget);

    paint_dithered_gradient(cr, 1.0, 1.0, width - 2.0, height - 6.0, 27.0,
                            colors->sheet_start, colors->sheet_end, ui->skin);
    return FALSE;
}

/* One piece of text on a card. The font is built per call rather than kept
 * per card: a card is redrawn when its state changes, not per frame, and one
 * font description is cheaper than a cache that has to be invalidated with
 * every skin and every size change. */
static gdouble card_text(cairo_t *cr, PangoLayout *layout, const gchar *text,
                         gint size, gboolean bold, guint color, gdouble alpha,
                         gdouble x, gdouble y, gdouble width)
{
    PangoFontDescription *font = pango_font_description_new();
    gint text_height = 0;

    pango_font_description_set_family(font, "Sans");
    pango_font_description_set_weight(
        font, bold ? PANGO_WEIGHT_BOLD : PANGO_WEIGHT_NORMAL);
    pango_font_description_set_absolute_size(font, size * PANGO_SCALE);
    pango_layout_set_font_description(layout, font);
    pango_font_description_free(font);

    pango_layout_set_text(layout, text, -1);
    pango_layout_set_width(layout, (gint)(width * PANGO_SCALE));
    pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);
    pango_layout_set_alignment(layout, PANGO_ALIGN_CENTER);
    pango_layout_get_pixel_size(layout, NULL, &text_height);

    set_source_color(cr, color, alpha);
    cairo_move_to(cr, x, y);
    pango_cairo_show_layout(cr, layout);
    return text_height;
}

static gdouble card_text_height(PangoLayout *layout, const gchar *text,
                                gint size, gboolean bold, gdouble width)
{
    PangoFontDescription *font = pango_font_description_new();
    gint text_height = 0;

    pango_font_description_set_family(font, "Sans");
    pango_font_description_set_weight(
        font, bold ? PANGO_WEIGHT_BOLD : PANGO_WEIGHT_NORMAL);
    pango_font_description_set_absolute_size(font, size * PANGO_SCALE);
    pango_layout_set_font_description(layout, font);
    pango_font_description_free(font);

    pango_layout_set_text(layout, text, -1);
    pango_layout_set_width(layout, (gint)(width * PANGO_SCALE));
    pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);
    pango_layout_get_pixel_size(layout, NULL, &text_height);
    return text_height;
}

/* The ADJUST control. A card with room for it gets the pill the six-tile page
 * always drew; a card without gets the same target drawn as a slider glyph.
 * See PANEL_ROOM_ADJUST_HEIGHT for why only the drawing changes. */
static void draw_room_adjust(PanelUi *ui, cairo_t *cr, PangoLayout *layout,
                             const PanelRoomCard *card, gboolean pressed)
{
    const PanelSkinPalette *colors = palette(ui);
    GdkRectangle region;
    gboolean pill;

    card_adjust_region(card, &region);
    pill = region.width >= PANEL_ROOM_ADJUST_WIDTH;

    guint fill = mix_color(colors->card_end, colors->border_active,
                           pressed ? 0.34 : 0.16);
    gdouble radius = pill ? region.height / 2.0
                          : MIN(12.0, region.width / 3.0);

    cairo_save(cr);
    set_source_color(cr, fill, 1.0);
    rounded_rectangle(cr, region.x, region.y, region.width, region.height,
                      radius);
    cairo_fill(cr);
    set_source_color(cr, colors->border_active, pressed ? 1.0 : 0.72);
    cairo_set_line_width(cr, 1.0);
    rounded_rectangle(cr, region.x + 0.5, region.y + 0.5, region.width - 1.0,
                      region.height - 1.0, radius);
    cairo_stroke(cr);

    if (pill) {
        gdouble height = card_text_height(layout, "ADJUST", 10, TRUE,
                                          region.width);
        card_text(cr, layout, "ADJUST", 10, TRUE, colors->border_active, 1.0,
                  region.x, region.y + (region.height - height) / 2.0,
                  region.width);
    } else {
        /* Three slider lines, each with the knob at a different place: the
         * same picture the sheet behind this control draws. */
        static const gdouble knobs[] = {0.32, 0.62, 0.44};
        gdouble inset = region.width * 0.24;
        gdouble span = region.width - inset * 2.0;
        gdouble step = region.height / 4.0;

        cairo_set_line_width(cr, 1.6);
        for (guint i = 0; i < G_N_ELEMENTS(knobs); i++) {
            gdouble line_y = region.y + step * (i + 1);
            set_source_color(cr, colors->border_active, 0.55);
            cairo_move_to(cr, region.x + inset, line_y);
            cairo_line_to(cr, region.x + inset + span, line_y);
            cairo_stroke(cr);
            set_source_color(cr, colors->border_active, 1.0);
            cairo_arc(cr, region.x + inset + span * knobs[i], line_y, 2.1,
                      0.0, 2.0 * PANEL_PI);
            cairo_fill(cr);
        }
    }
    cairo_restore(cr);
}

/* What a thermostat card says under its name instead of ON or OFF, and NULL
 * for every other card. "ON" tells a person nothing they came to a
 * thermostat for; the temperature the room is at does, with the setpoint
 * after it, which is the order a thermostat is read in.
 *
 * The room temperature is drawn whether the thermostat is running or not,
 * because it is true either way. The **setpoint** is not: a thermostat that
 * is off is heading nowhere, and leaving the number it used to be set to on
 * the card would read as something it is doing. A thermostat that reports
 * no numbers at all falls back to ON and OFF like anything else — a coarse
 * line is better than an empty one — and the card's own gradient says which
 * of the two it is in either case.
 *
 * The size rules above this are unchanged and apply to a thermostat as they
 * do to a lamp: a one-cell card has room for the name and the ADJUST corner
 * and nothing else, and this line appears from about two cells up. */
static gchar *card_reading(const PanelRoomCard *card)
{
    if (card->entity == NULL || !card->state_known)
        return NULL;

    /* A sensor says its value with its unit: the name above says what it
     * is, this line says what it reads. A sensor that has not answered yet
     * falls through to the "--" the caller draws. */
    if (g_strcmp0(card->entity->domain, "sensor") == 0) {
        if (card->sensor_value == NULL || *card->sensor_value == '\0')
            return NULL;
        if (card->sensor_unit != NULL && *card->sensor_unit != '\0')
            return g_strdup_printf("%s %s", card->sensor_value,
                                   card->sensor_unit);
        return g_strdup(card->sensor_value);
    }

    /* A blind says how far open it is, and where it cannot, it says which of
     * the two ends it is at. ON and OFF are the fallback of last resort for
     * everything else on this page and would be the wrong words here. */
    if (g_strcmp0(card->entity->domain, "cover") == 0) {
        if (card->position >= 0)
            return g_strdup_printf("%d%%", card->position);
        return g_strdup(card->active ? "OPEN" : "CLOSED");
    }

    if (!card->entity->target_temperature)
        return NULL;

    gboolean has_ambient = !isnan(card->ambient);
    gboolean has_setpoint = card->active && !isnan(card->setpoint);

    /* The room first and the setpoint after it. The separator is a slash and
     * not an arrow so that the two clients read the same: the Roboto face the
     * ESP32 firmware builds carries no U+2192, and a glyph a font does not
     * have cannot be added to it. */
    if (has_ambient && has_setpoint) {
        gchar *ambient = format_temperature(card->ambient);
        gchar *setpoint = format_temperature(card->setpoint);
        gchar *reading = g_strdup_printf("%s / %s", ambient, setpoint);

        g_free(ambient);
        g_free(setpoint);
        return reading;
    }
    if (has_ambient)
        return format_temperature(card->ambient);
    if (has_setpoint) {
        gchar *setpoint = format_temperature(card->setpoint);
        gchar *reading = g_strdup_printf("set %s", setpoint);

        g_free(setpoint);
        return reading;
    }
    return NULL;
}

/* The day-by-day chart on a weather block: weekday columns with the high
 * above a high/low curve and the low below it, and precipitation bars where
 * any was reported. Returns the height drawn, or 0 when the card has no
 * room for even the compact columns of day, high and low alone. */
static gdouble draw_weather_chart(cairo_t *cr, PangoLayout *layout,
                                  const PanelRoomCard *card, gdouble x,
                                  gdouble y, gdouble width, gdouble height)
{
    guint cols;
    gdouble col_w;
    gdouble tmax;
    gdouble tmin;
    gboolean precipitating = FALSE;
    gboolean full;
    /* Every row answers to the card: a wall-sized block gets wall-sized
     * type, a two-cell one keeps the small type it always had. */
    gdouble cf;
    gint day_size;
    gint high_size;
    gint low_size;
    gint precip_size;
    gdouble day_h;
    gdouble glyph_h;
    gdouble high_h;
    gdouble low_h;
    gdouble value_h;
    gdouble bar_max;
    gdouble precip_h;
    gdouble stroke;
    gdouble dot;
    gdouble top;
    guint i;

    if (card->forecast_count == 0 || width < 80.0)
        return 0.0;
    cols = (guint)(width / 64.0);
    if (cols < 1)
        return 0.0;
    cols = MIN(cols, card->forecast_count);
    cols = MIN(cols, (guint)PANEL_WEATHER_FORECAST_MAX);
    col_w = width / (gdouble)cols;

    cf = CLAMP(MIN(col_w / 5.0, height / 8.0), 8.0, 26.0);
    day_size = (gint)cf;
    high_size = (gint)cf + 1;
    low_size = MAX(8, (gint)cf - 1);
    precip_size = MAX(8, (gint)cf - 3);
    day_h = cf * 1.35;
    glyph_h = cf * 1.8;
    high_h = cf * 1.55;
    low_h = cf * 1.35;
    value_h = cf * 1.1;
    bar_max = cf * 1.1;
    precip_h = value_h + bar_max + 6.0;
    stroke = MAX(2.0, cf * 0.22);
    dot = MAX(2.0, cf * 0.22);

    tmax = card->forecast[0].high;
    tmin = card->forecast[0].has_low ? card->forecast[0].low
                                     : card->forecast[0].high;
    for (i = 1; i < cols; i++) {
        gdouble low = card->forecast[i].has_low ? card->forecast[i].low
                                                : card->forecast[i].high;
        tmax = MAX(tmax, card->forecast[i].high);
        tmin = MIN(tmin, low);
        precipitating = precipitating || card->forecast[i].has_precipitation;
    }
    precipitating =
        precipitating || card->forecast[0].has_precipitation;

    /* Curves and precipitation when they fit; compact day/high/low columns
     * when only they do. */
    full = height >= day_h + glyph_h + high_h + low_h + 4.0 + cf * 2.7 +
           (precipitating ? precip_h : 0.0);
    if (!full && height < day_h + high_h + low_h + 4.0)
        return 0.0;

    top = y;
    for (i = 0; i < cols; i++) {
        card_text(cr, layout, card->forecast[i].day, day_size, TRUE,
                  0xa9c3e0U, 1.0, x + col_w * i, top, col_w);
    }
    top += day_h;

    if (full) {
        WeatherGlyph glyph;

        for (i = 0; i < cols; i++) {
            gchar *label = NULL;

            weather_condition_info(card->forecast[i].condition, &label,
                                   &glyph);
            g_free(label);
            draw_weather_glyph(cr, glyph, x + col_w * i + col_w / 2.0,
                               top + glyph_h / 2.0, glyph_h * 0.95,
                               0xd6e9faU, 1.0);
        }
        top += glyph_h;
    }

    for (i = 0; i < cols; i++) {
        gchar *high = format_temperature(card->forecast[i].high);
        gdouble high_here =
            card_text_height(layout, high, high_size, TRUE, col_w);

        card_text(cr, layout, high, high_size, TRUE, 0xf5a83dU, 1.0,
                  x + col_w * i, top + (high_h - high_here) / 2.0, col_w);
        g_free(high);
    }
    top += high_h;

    if (full) {
        gdouble zone = height - (top - y) - low_h -
                       (precipitating ? precip_h : 0.0);
        gdouble span = tmax - tmin;

        if (span < 0.5)
            span = 0.5;
        cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND);
        cairo_set_line_join(cr, CAIRO_LINE_JOIN_ROUND);
        for (gint pass = 0; pass < 2; pass++) {
            gboolean high_line = pass == 0;

            set_source_color(cr, high_line ? 0xf5a83dU : 0x7fb2f0U, 1.0);
            cairo_set_line_width(cr, stroke);
            for (i = 0; i < cols; i++) {
                gdouble t = high_line ? card->forecast[i].high
                                      : (card->forecast[i].has_low
                                             ? card->forecast[i].low
                                             : card->forecast[i].high);
                gdouble cx = x + col_w * i + col_w / 2.0;
                gdouble cy_dot = top + stroke * 2.0 +
                                 (1.0 - (t - tmin) / span) *
                                     (zone - stroke * 4.0);

                if (i == 0)
                    cairo_move_to(cr, cx, cy_dot);
                else
                    cairo_line_to(cr, cx, cy_dot);
            }
            cairo_stroke(cr);
            for (i = 0; i < cols; i++) {
                gdouble t = high_line ? card->forecast[i].high
                                      : (card->forecast[i].has_low
                                             ? card->forecast[i].low
                                             : card->forecast[i].high);
                gdouble cx = x + col_w * i + col_w / 2.0;
                gdouble cy_dot = top + stroke * 2.0 +
                                 (1.0 - (t - tmin) / span) *
                                     (zone - stroke * 4.0);

                cairo_new_sub_path(cr);
                cairo_arc(cr, cx, cy_dot, dot, 0.0, 2.0 * PANEL_PI);
                cairo_fill(cr);
            }
        }
        top += zone;
        if (precipitating) {
            gdouble pmax = 0.0;

            for (i = 0; i < cols; i++) {
                if (card->forecast[i].has_precipitation)
                    pmax = MAX(pmax, card->forecast[i].precipitation);
            }
            if (pmax < 0.1)
                pmax = 0.1;
            for (i = 0; i < cols; i++) {
                if (!card->forecast[i].has_precipitation)
                    continue;
                {
                    gdouble bar = card->forecast[i].precipitation / pmax *
                                  bar_max;
                    gdouble cx = x + col_w * i + col_w / 2.0;
                    gchar *value = g_strdup_printf(
                        "%.1f mm", card->forecast[i].precipitation);

                    card_text(cr, layout, value, precip_size, FALSE,
                              0x8fc3e8U, 1.0, x + col_w * i, top, col_w);
                    g_free(value);
                    set_source_color(cr, 0x7fc4e8U, 0.75);
                    cairo_rectangle(cr, cx - col_w * 0.16, top + value_h,
                                    col_w * 0.32, bar);
                    cairo_fill(cr);
                }
            }
            top += precip_h;
        }
    }

    for (i = 0; i < cols; i++) {
        if (card->forecast[i].has_low) {
            gchar *low = format_temperature(card->forecast[i].low);

            card_text(cr, layout, low, low_size, FALSE, 0x8fb8e8U, 1.0,
                      x + col_w * i, top, col_w);
            g_free(low);
        } else {
            card_text(cr, layout, "–", low_size, FALSE, 0x8fb8e8U, 1.0,
                      x + col_w * i, top, col_w);
        }
    }
    top += low_h;
    return top - y;
}

/* A weather block draws itself rather than borrowing the button's lines,
 * top down: the current conditions first — glyph, hero temperature and the
 * condition with the humidity — and the day-by-day chart beneath them. The
 * name below is the caller's; everything here must stay above
 * *content_bottom. */
static void draw_weather_body(cairo_t *cr, PangoLayout *layout,
                              const PanelRoomCard *card, gdouble x, gdouble y,
                              gdouble pad, gdouble width,
                              gdouble *content_bottom, gint state_size)
{
    gboolean has_temp = !isnan(card->weather_temperature);
    gboolean has_humidity = card->weather_humidity >= 0;
    gchar *condition = NULL;
    WeatherGlyph glyph = WEATHER_CLOUD;
    gdouble top = y + pad;
    gdouble bottom = *content_bottom;

    weather_condition_info(card->weather_condition, &condition, &glyph);
    if (condition == NULL && !has_temp && !has_humidity) {
        card_text(cr, layout, "--", state_size, TRUE, 0xcfe3f7U, 1.0,
                  x + pad, top, width);
    } else {
        gchar *hero = has_temp ? format_temperature(card->weather_temperature)
                               : NULL;
        gchar *line = NULL;
        gint hero_size = CLAMP(state_size * 3, 22, 46);
        gdouble hero_height = hero != NULL ? card_text_height(
                                                  layout, hero, hero_size,
                                                  TRUE, width)
                                           : 0.0;

        if (condition != NULL && has_humidity)
            line = g_strdup_printf("%s · %d%%", condition,
                                   card->weather_humidity);
        else if (condition != NULL)
            line = g_strdup(condition);
        else
            line = g_strdup_printf("Humidity %d%%", card->weather_humidity);
        {
            gdouble line_height =
                card_text_height(layout, line, state_size, TRUE, width);

            if (width >= 190.0 &&
                top + MAX(hero_height + line_height + 8.0, 84.0) <= bottom) {
                /* Wide enough for a row: the glyph on the left, the numbers
                 * beside it. The hero is sized to its column, not the card:
                 * a 46-point "21.8°" never survived 90 pixels. */
                gdouble box = MIN(hero_height + line_height + 8.0, 96.0);
                gdouble text_top;

                hero_size = MIN(hero_size,
                                MAX(18, (gint)((width - box) / 3.6)));
                hero_height = hero != NULL ? card_text_height(
                                                  layout, hero, hero_size,
                                                  TRUE, width - box)
                                           : 0.0;
                box = MIN(hero_height + line_height + 8.0, 96.0);
                text_top =
                    top + (box - (hero_height + 4.0 + line_height)) / 2.0;

                draw_weather_glyph(cr, glyph, x + pad + box / 2.0,
                                   top + box / 2.0, box * 0.72, 0xd6e9faU,
                                   1.0);
                if (hero != NULL) {
                    card_text(cr, layout, hero, hero_size, TRUE, 0xffffffU,
                              1.0, x + pad + box, text_top,
                              width - box);
                    text_top += hero_height + 4.0;
                }
                card_text(cr, layout, line, state_size, TRUE, 0xcfe3f7U,
                          1.0, x + pad + box, text_top, width - box);
                top += box + 6.0;
            } else {
                /* Narrow: glyph, hero and condition stacked and centred.
                 * The hero answers to the card's own width here as well. */
                gdouble need;
                gdouble glyph_size;

                hero_size = MIN(hero_size,
                                MAX(16, (gint)(width / 3.6)));
                hero_height = hero != NULL ? card_text_height(
                                                  layout, hero, hero_size,
                                                  TRUE, width)
                                           : 0.0;
                need = hero_height + line_height + 8.0;
                glyph_size = MIN(56.0, bottom - top - need - 4.0);

                if (glyph_size >= 30.0) {
                    draw_weather_glyph(cr, glyph, x + pad + width / 2.0,
                                       top + glyph_size / 2.0, glyph_size,
                                       0xd6e9faU, 1.0);
                    top += glyph_size + 4.0;
                }
                if (hero != NULL &&
                    top + hero_height + 4.0 <= bottom) {
                    card_text(cr, layout, hero, hero_size, TRUE, 0xffffffU,
                              1.0, x + pad, top, width);
                    top += hero_height + 4.0;
                }
                if (top + line_height <= bottom) {
                    card_text(cr, layout, line, state_size, TRUE, 0xcfe3f7U,
                              1.0, x + pad, top, width);
                    top += line_height + 6.0;
                }
            }
        }
        g_free(line);
        g_free(hero);
    }
    g_free(condition);

    /* The coming days beneath the current conditions, as much of them as
     * the room between here and the name allows. */
    if (top < bottom)
        draw_weather_chart(cr, layout, card, x + pad, top, width,
                           bottom - top);
}

/* A sensor block draws itself rather than borrowing the button's lines: the
 * name above is the caller's, and the value with its unit is drawn here,
 * large and centred, the way a weather block draws its hero temperature.
 * Everything here must stay above *content_bottom. */
static void draw_sensor_body(cairo_t *cr, PangoLayout *layout,
                             const PanelRoomCard *card, gdouble x, gdouble y,
                             gdouble pad, gdouble width,
                             gdouble *content_bottom, gint state_size)
{
    gdouble top = y + pad;
    gdouble bottom = *content_bottom;
    gchar *hero = NULL;
    gint hero_size;
    gdouble hero_height;

    if (card->sensor_value == NULL || *card->sensor_value == '\0') {
        card_text(cr, layout, "--", state_size, TRUE, 0xcfe3f7U, 1.0,
                  x + pad, top, width);
        return;
    }
    if (card->sensor_unit != NULL && *card->sensor_unit != '\0')
        hero = g_strdup_printf("%s %s", card->sensor_value,
                               card->sensor_unit);
    else
        hero = g_strdup(card->sensor_value);

    /* The value is the content, so its type grows with the card — unlike a
     * button, a sensor block with a wall of empty space around small text
     * is the bug, not the design. */
    hero_size = (gint)CLAMP(MIN((bottom - top) / 2.2, width / 5.0),
                            16.0, 44.0);
    hero_height = card_text_height(layout, hero, hero_size, TRUE, width);
    if (top + hero_height <= bottom) {
        gdouble text_top = top + (bottom - top - hero_height) / 2.0;

        card_text(cr, layout, hero, hero_size, TRUE, 0xffffffU, 1.0,
                  x + pad, text_top, width);
    } else {
        card_text(cr, layout, hero, state_size, TRUE, 0xcfe3f7U, 1.0,
                  x + pad, top, width);
    }
    g_free(hero);
}

static void draw_room_card(PanelUi *ui, cairo_t *cr, PangoLayout *layout,
                           const PanelRoomCard *card, gint index)
{
    const PanelSkinPalette *colors = palette(ui);
    gdouble x = card->bounds.x;
    gdouble y = card->bounds.y;
    gdouble width = card->bounds.width;
    gdouble height = card->bounds.height;
    gdouble radius = MIN(27.0, MIN(width, height) / 3.2);
    gdouble mix = card->active_mix;
    gboolean unassigned = card->entity == NULL;
    /* A reading is never a button: it never shows a pressed state, because
     * a tap on it acts on nothing. */
    gboolean pressed = index == ui->room_pressed_index &&
                       !ui->room_pressed_adjust && !card_is_reading(card);

    guint start = pressed ? colors->card_down_start : colors->card_start;
    guint end = pressed ? colors->card_down_end : colors->card_end;
    guint active_start = pressed ? colors->card_down_active_start
                                 : colors->card_active_start;
    guint active_end = pressed ? colors->card_down_active_end
                               : colors->card_active_end;
    guint border_active = colors->border_active;
    gdouble shadow_alpha = pressed ? 0.3 : 0.42;

    /* A reading wears its own sky rather than the off gradient: it is
     * information, not a switch left off. The mix is pinned on so the sky
     * and its border actually draw — the card is never "active" on its own.
     * A colour the user chose still wins over it. */
    if (!unassigned && !card->has_accent && card_is_reading(card)) {
        start = 0x2e5d8fU;
        end = 0x122540U;
        active_start = 0x2e5d8fU;
        active_end = 0x122540U;
        border_active = 0x6fb3e8U;
        mix = 1.0;
    }

    /* A colour the user chose replaces the skin's own accent and nothing
     * else, so a card still reads as part of the skin it sits in. */
    if (card->has_accent) {
        border_active = card->accent;
        active_start = mix_color(card->accent, 0x000000U, 0.40);
        active_end = mix_color(card->accent, 0x000000U, 0.76);
        if (pressed) {
            guint swap = active_start;
            active_start = active_end;
            active_end = swap;
        }
    }

    if (unassigned) {
        /* Its registry element is gone from Home Assistant, or has not
         * arrived yet. The card keeps its place and says so rather than
         * disappearing and taking the arrangement with it. */
        start = colors->card_off;
        end = colors->card_off;
        active_start = start;
        active_end = end;
        border_active = colors->border_off;
        shadow_alpha = 0.0;
        mix = 0.0;
    }

    guint border = mix_color(colors->border, border_active, mix);
    guint bottom = mix_color(colors->bottom, colors->bottom_active, mix);

    if (unassigned)
        border = colors->border_off;

    start = mix_color(start, active_start, mix);
    end = mix_color(end, active_end, mix);

    cairo_save(cr);
    set_source_color(cr, 0x000000U, shadow_alpha);
    rounded_rectangle(cr, x + 1.0, y + 6.0, width - 2.0, height - 6.0,
                      radius - 1.0);
    cairo_fill(cr);
    set_source_color(cr, bottom, 1.0);
    rounded_rectangle(cr, x, y, width, height, radius);
    cairo_fill(cr);
    paint_dithered_gradient(cr, x, y, width, height - 4.0, radius - 1.0,
                            start, end, ui->skin);
    set_source_color(cr, border, 1.0);
    cairo_set_line_width(cr, 1.0);
    rounded_rectangle(cr, x + 0.5, y + 0.5, width - 1.0, height - 5.0,
                      radius - 1.0);
    cairo_stroke(cr);
    cairo_restore(cr);

    gdouble pad = CLAMP(width * 0.09, 5.0, 18.0);
    gdouble text_width = width - pad * 2.0;
    gdouble bottom_edge = y + height - pad - 3.0;
    if (text_width < 8.0) {
        return;
    }

    cairo_save(cr);
    rounded_rectangle(cr, x, y, width, height, radius);
    cairo_clip(cr);

    /* The card's own gradient stays dark when it is on — that is what the
     * skin does — so the text and the artwork on it stay light and take the
     * accent rather than the icon-on colour, which belongs to the bright
     * shell this page no longer draws. */
    guint lit = card->has_accent ? card->accent : colors->border_active;

    const gchar *name = unassigned ? "Unassigned" : card->entity->name;
    /* A reading is headed by its name: location first, then the current
     * conditions, then the coming days. Its type grows with the card —
     * unlike a button, a forecast block is the content, so a wall of empty
     * sky around 13-point text is the bug, not the design. */
    gboolean reading_headed =
        !unassigned && height >= 108.0 && card_is_reading(card);
    gint name_size = reading_headed
                         ? (gint)CLAMP(MIN(height / 6.4, width / 12.0), 11.0,
                                        30.0)
                         : (gint)CLAMP(height / 6.4, 11.0, 23.0);
    gdouble name_height = card_text_height(layout, name, name_size, TRUE,
                                           text_width);
    gdouble body_top = y + pad;

    /* Drawn from the bottom up, so that a card too small for everything
     * loses the least important thing first: the state, then the icon. The
     * name is what identifies the card and is never dropped. */
    gdouble content_bottom = bottom_edge - name_height;
    if (reading_headed) {
        card_text(cr, layout, name, name_size, TRUE, 0xf1f6fdU, 1.0,
                  x + pad, y + pad, text_width);
        body_top = y + pad + name_height + 6.0;
        content_bottom = bottom_edge;
    } else {
        card_text(cr, layout, name, name_size, TRUE,
                  unassigned ? 0x52657cU : 0xf1f6fdU, 1.0, x + pad,
                  content_bottom, text_width);
    }

    if (height >= 108.0) {
        /* A reading draws its own body rather than the button's state
         * line: a weather block its hero, condition and chart, a sensor
         * block its value with its unit. */
        if (reading_headed) {
            gint state_size =
                (gint)CLAMP(MIN(height / 11.0, width / 20.0), 9.0, 18.0);
            gdouble body_y = body_top - pad;

            if (card_is_sensor(card))
                draw_sensor_body(cr, layout, card, x, body_y, pad,
                                 text_width, &content_bottom, state_size);
            else
                draw_weather_body(cr, layout, card, x, body_y, pad,
                                  text_width, &content_bottom, state_size);
        } else {
            gchar *reading = unassigned ? NULL : card_reading(card);
            const gchar *state = unassigned ? card->rid
                                 : reading != NULL ? reading
                                 : !card->state_known ? "--"
                                 : card->active ? "ON" : "OFF";
            gint state_size = (gint)CLAMP(height / 11.0, 9.0, 13.0);
            gdouble state_height = card_text_height(layout, state,
                                                    state_size, TRUE,
                                                    text_width);

            content_bottom -= state_height + 4.0;
            card_text(cr, layout, state, state_size, TRUE,
                      unassigned ? 0x52657cU : mix_color(0x8fa9c7U, lit, mix),
                      1.0, x + pad, content_bottom, text_width);
            g_free(reading);
        }
    }

    /* Weather draws vector glyphs of its own in the body above, and a
     * sensor draws its value as type; everything else takes its artwork
     * from the icon table. */
    if (!unassigned && !card_is_reading(card)) {
        const PanelIconSet *icons = icon_set(ui, card->icon);
        gdouble available = content_bottom - (y + pad);

        if (icons != NULL && available >= PANEL_ROOM_ICON_SMALL + 4.0) {
            gboolean large = available >= PANEL_ROOM_ICON_LARGE + 8.0 &&
                             width >= PANEL_ROOM_ICON_LARGE + pad * 2.0;
            GdkPixbuf *pixbuf = large ? icons->large : icons->small;
            gdouble size = large ? PANEL_ROOM_ICON_LARGE
                                 : PANEL_ROOM_ICON_SMALL;
            GdkRectangle artwork_box = {
                (gint)(x + (width - size) / 2.0),
                (gint)(y + pad + (available - size) / 2.0),
                (gint)size, (gint)size
            };

            /* On a card one cell wide the ADJUST corner and the centred
             * artwork want the same pixels, and the control wins: a person
             * can act on a card with no picture on it, and cannot act on a
             * picture. From two cells up they do not meet and both are
             * drawn. The name is below either way, so the card is still
             * identifiable at every size. */
            GdkRectangle adjust_box;
            GdkRectangle collision;
            if (card_is_adjustable(card)) {
                card_adjust_region(card, &adjust_box);
                if (gdk_rectangle_intersect(&adjust_box, &artwork_box,
                                            &collision)) {
                    pixbuf = NULL;
                }
            }

            if (pixbuf != NULL) {
                gdouble left = artwork_box.x;
                gdouble top = artwork_box.y;

                /* The artwork is the mask and the colour is ours, so one
                 * pixbuf serves both states, both skins, and every colour a
                 * user picked for a card. */
                gdk_cairo_set_source_pixbuf(cr, pixbuf, left, top);
                cairo_pattern_t *artwork =
                    cairo_pattern_reference(cairo_get_source(cr));

                set_source_color(cr, mix_color(colors->icon_off, lit, mix),
                                 1.0);
                cairo_mask(cr, artwork);
                cairo_pattern_destroy(artwork);
            }
        }
    }
    cairo_restore(cr);

    if (card_is_adjustable(card)) {
        draw_room_adjust(ui, cr, layout, card,
                         index == ui->room_pressed_index &&
                             ui->room_pressed_adjust);
    }
}

/* The page with nothing on it. A panel that has just been configured in Home
 * Assistant places every element for itself, so this is only reached by a
 * panel whose registry is empty — and then the useful thing to say is where
 * the arrangement is edited. */
static void draw_room_placeholder(PanelUi *ui, cairo_t *cr, gdouble width,
                                  gdouble height)
{
    PangoLayout *layout = pango_cairo_create_layout(cr);
    const gchar *title = "No room controls yet";
    const gchar *body = ui->room_editor_hint != NULL
                            ? ui->room_editor_hint
                            : "Add entities to this panel in Home Assistant.";
    gdouble text_width = MIN(width - 60.0, 520.0);
    gdouble left = (width - text_width) / 2.0;

    gdouble title_height = card_text_height(layout, title, 26, TRUE,
                                            text_width);
    gdouble body_height = card_text_height(layout, body, 16, FALSE,
                                           text_width);
    gdouble top = (height - title_height - body_height - 14.0) / 2.0;

    card_text(cr, layout, title, 26, TRUE, 0xf1f6fdU, 1.0, left, top,
              text_width);
    card_text(cr, layout, body, 16, FALSE, 0x8fa9c7U, 1.0, left,
              top + title_height + 14.0, text_width);
    g_object_unref(layout);
}

static gboolean room_area_draw(GtkWidget *widget, cairo_t *cr,
                               gpointer user_data)
{
    PanelUi *ui = user_data;
    GdkRectangle clip;
    gboolean clipped = gdk_cairo_get_clip_rectangle(cr, &clip);

    if (ui->room_cards->len == 0) {
        draw_room_placeholder(ui, cr, gtk_widget_get_allocated_width(widget),
                              gtk_widget_get_allocated_height(widget));
        return FALSE;
    }

    /* One layout for the whole page. Only the cards the expose actually
     * covers are drawn, which is what makes a state change cost one card
     * rather than a hundred. */
    PangoLayout *layout = pango_cairo_create_layout(cr);
    for (guint i = 0; i < ui->room_cards->len; i++) {
        const PanelRoomCard *card = g_ptr_array_index(ui->room_cards, i);
        GdkRectangle unused;

        if (clipped && !gdk_rectangle_intersect(&clip, &card->bounds, &unused))
            continue;
        draw_room_card(ui, cr, layout, card, (gint)i);
    }
    g_object_unref(layout);
    return FALSE;
}

static void invalidate_card(PanelUi *ui, const PanelRoomCard *card)
{
    if (ui->room_area == NULL)
        return;
    /* A little wider than the card, so the shadow under it is repainted. */
    gtk_widget_queue_draw_area(ui->room_area, card->bounds.x - 2,
                               card->bounds.y - 2, card->bounds.width + 4,
                               card->bounds.height + 8);
}

/* One tick callback for the page, not one per card: a hundred cards changing
 * at once still costs a single frame callback, and it stops as soon as the
 * last card has arrived. */
static gboolean room_animation_frame(GtkWidget *widget,
                                     GdkFrameClock *frame_clock,
                                     gpointer user_data)
{
    PanelUi *ui = user_data;
    gint64 now = gdk_frame_clock_get_frame_time(frame_clock);
    gboolean running = FALSE;

    (void)widget;
    for (guint i = 0; i < ui->room_cards->len; i++) {
        PanelRoomCard *card = g_ptr_array_index(ui->room_cards, i);
        gdouble progress;
        gdouble eased;

        if (!card->animating)
            continue;
        progress = CLAMP((now - card->animation_start_us) /
                             PANEL_ROOM_ANIMATION_US, 0.0, 1.0);
        eased = 1.0 - (1.0 - progress) * (1.0 - progress) * (1.0 - progress);
        card->active_mix = card->animation_from +
            (card->animation_to - card->animation_from) * eased;
        invalidate_card(ui, card);
        if (progress >= 1.0)
            card->animating = FALSE;
        else
            running = TRUE;
    }

    if (!running) {
        ui->room_animation_tick = 0;
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
}

static void start_card_animation(PanelUi *ui, PanelRoomCard *card,
                                 gboolean active)
{
    GdkFrameClock *frame_clock = ui->room_area != NULL
                                     ? gtk_widget_get_frame_clock(ui->room_area)
                                     : NULL;

    card->animation_from = card->active_mix;
    card->animation_to = active ? 1.0 : 0.0;
    card->animation_start_us = frame_clock != NULL
                                   ? gdk_frame_clock_get_frame_time(frame_clock)
                                   : g_get_monotonic_time();
    card->animating = TRUE;
    if (ui->room_animation_tick == 0 && ui->room_area != NULL) {
        ui->room_animation_tick = gtk_widget_add_tick_callback(
            ui->room_area, room_animation_frame, ui, NULL);
    }
}

static gboolean room_area_pressed(GtkWidget *widget, GdkEventButton *event,
                                   gpointer user_data)
{
    PanelUi *ui = user_data;
    gint index = room_card_at(ui, event->x, event->y);

    (void)widget;
    ui->room_pressed_index = index;
    ui->room_pressed_adjust = FALSE;
    if (index >= 0) {
        const PanelRoomCard *card = g_ptr_array_index(ui->room_cards, index);
        GdkRectangle region;

        /* A reading is not a button: a finger down on it leaves no pressed
         * state behind. */
        if (card_is_reading(card)) {
            ui->room_pressed_index = -1;
            return TRUE;
        }
        if (card_is_adjustable(card)) {
            card_adjust_region(card, &region);
            ui->room_pressed_adjust =
                event->x >= region.x && event->x < region.x + region.width &&
                event->y >= region.y && event->y < region.y + region.height;
        }
        invalidate_card(ui, card);
    }
    return TRUE;
}

static gboolean room_area_released(GtkWidget *widget, GdkEventButton *event,
                                   gpointer user_data)
{
    PanelUi *ui = user_data;
    gint pressed = ui->room_pressed_index;
    gboolean on_adjust = ui->room_pressed_adjust;
    gint index = room_card_at(ui, event->x, event->y);

    (void)widget;
    ui->room_pressed_index = -1;
    ui->room_pressed_adjust = FALSE;
    if (pressed < 0)
        return TRUE;

    const PanelRoomCard *card = g_ptr_array_index(ui->room_cards, pressed);
    invalidate_card(ui, card);
    /* A finger that left the card it went down on cancels, the way a button
     * does. */
    if (index != pressed || card->entity == NULL)
        return TRUE;

    /* A reading never acts: it is information, not a button. */
    if (card_is_reading(card))
        return TRUE;
    if (on_adjust && card_is_adjustable(card))
        open_room_sheet(ui, pressed);
    else
        emit_event(ui, PANEL_UI_TOGGLE_ROOM, NULL, pressed);
    return TRUE;
}

static void room_card_free(gpointer data)
{
    PanelRoomCard *card = data;

    g_free(card->rid);
    g_free(card->icon);
    g_free(card->weather_condition);
    g_free(card->sensor_value);
    g_free(card->sensor_unit);
    g_free(card);
}

/* Where each card lands in pixels. The cell size is derived from whatever
 * work area the page was given rather than written down anywhere, so the
 * grid always fits and the bottom row is never cut off. */
static void room_cards_allocate(PanelUi *ui)
{
    gdouble gap = PANEL_ROOM_CARD_GAP;
    gint width;
    gint height;
    gdouble cell_width;
    gdouble cell_height;

    if (ui->room_area == NULL || ui->room_grid == NULL)
        return;
    width = gtk_widget_get_allocated_width(ui->room_area);
    height = gtk_widget_get_allocated_height(ui->room_area);
    if (width <= 1 || height <= 1)
        return;

    cell_width = (width + gap) / (gdouble)ui->room_grid->columns;
    cell_height = (height + gap) / (gdouble)ui->room_grid->rows;

    for (guint i = 0; i < ui->room_cards->len; i++) {
        PanelRoomCard *card = g_ptr_array_index(ui->room_cards, i);
        gdouble left = card->column * cell_width;
        gdouble top = card->row * cell_height;
        gdouble right = left + card->columns * cell_width - gap;
        gdouble foot = top + card->rows * cell_height - gap;

        /* Rounded as edges rather than as an origin and a size, so that two
         * cards that share a boundary still meet exactly. */
        card->bounds.x = (gint)(left + 0.5);
        card->bounds.y = (gint)(top + 0.5);
        card->bounds.width = (gint)(right + 0.5) - card->bounds.x;
        card->bounds.height = (gint)(foot + 0.5) - card->bounds.y;
    }
}

static void room_area_allocated(GtkWidget *widget, GdkRectangle *allocation,
                                gpointer user_data)
{
    (void)widget;
    (void)allocation;
    room_cards_allocate(user_data);
}

/* Builds the card list from the grid and the registry. Both can change while
 * the panel runs — the registry when Home Assistant is edited, the grid when
 * somebody saves in the editor — and this is the one place the two are put
 * together. */
static void room_cards_rebuild(PanelUi *ui)
{
    g_ptr_array_set_size(ui->room_cards, 0);
    ui->room_pressed_index = -1;
    ui->room_pressed_adjust = FALSE;
    ui->room_adjust_index = -1;
    if (ui->room_grid == NULL)
        return;

    for (guint i = 0; i < ui->room_grid->cards->len; i++) {
        const PanelCard *placed = g_ptr_array_index(ui->room_grid->cards, i);
        PanelRoomCard *card = g_new0(PanelRoomCard, 1);
        const PanelEntity *entity = panel_layout_find_entity(
            &ui->config->layout, placed->rid);

        card->rid = g_strdup(placed->rid);
        card->entity = entity;
        card->column = placed->x;
        card->row = placed->y;
        card->columns = placed->width;
        card->rows = placed->height;
        card->brightness = -1;
        card->temperature = -1;
        card->temperature_min = entity != NULL ? entity->min_kelvin : 2000;
        card->temperature_max = entity != NULL ? entity->max_kelvin : 6500;
        card->setpoint = NAN;
        card->ambient = NAN;
        card->position = -1;
        card->weather_condition = NULL;
        card->weather_temperature = NAN;
        card->weather_humidity = -1;
        card->sensor_value = NULL;
        card->sensor_unit = NULL;
        card->forecast_count = 0;
        card->forecast_at = 0;
        card->icon = g_strdup(
            placed->icon != NULL
                ? placed->icon
                : icon_for_domain(entity != NULL ? entity->domain : NULL));
        if (placed->color != NULL) {
            card->accent = (guint)g_ascii_strtoull(placed->color + 1, NULL,
                                                   16);
            card->has_accent = TRUE;
        }
        g_ptr_array_add(ui->room_cards, card);
    }
    room_cards_allocate(ui);
}

static GtkWidget *room_adjust_sheet(PanelUi *ui)
{
    GtkWidget *revealer = gtk_revealer_new();
    GtkWidget *sheet = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    GtkWidget *header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    GtkWidget *close = new_button("CLOSE", "room-sheet-close", 110, 48);
    GtkWidget *subtitle = new_label(
        "Changes are sent automatically", "room-sheet-subtitle");

    gtk_revealer_set_transition_type(
        GTK_REVEALER(revealer), GTK_REVEALER_TRANSITION_TYPE_SLIDE_UP);
    gtk_revealer_set_transition_duration(GTK_REVEALER(revealer), 220);
    gtk_widget_set_halign(revealer, GTK_ALIGN_FILL);
    gtk_widget_set_valign(revealer, GTK_ALIGN_END);
    gtk_widget_set_margin_start(revealer, 18);
    gtk_widget_set_margin_end(revealer, 18);
    gtk_widget_set_margin_bottom(revealer, 18);
    add_css_class(sheet, "room-sheet");
    g_signal_connect(sheet, "draw", G_CALLBACK(room_sheet_draw), ui);

    ui->room_sheet_title = new_label("LIGHT SETTINGS", "room-sheet-title");
    gtk_widget_set_halign(ui->room_sheet_title, GTK_ALIGN_START);
    gtk_widget_set_halign(subtitle, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(header), ui->room_sheet_title, TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(header), close, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(sheet), header, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(sheet), subtitle, FALSE, FALSE, 0);
    g_signal_connect(close, "clicked", G_CALLBACK(close_room_sheet), ui);

    ui->room_brightness_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 5);
    GtkWidget *brightness_header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *brightness_title = new_label("BRIGHTNESS", "room-control-title");
    ui->room_brightness_value = new_label("100%", "room-control-value");
    gtk_widget_set_halign(brightness_title, GTK_ALIGN_START);
    gtk_widget_set_halign(ui->room_brightness_value, GTK_ALIGN_END);
    gtk_box_pack_start(GTK_BOX(brightness_header), brightness_title,
                       TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(brightness_header), ui->room_brightness_value,
                     FALSE, FALSE, 0);
    ui->room_brightness_scale = gtk_scale_new_with_range(
        GTK_ORIENTATION_HORIZONTAL, 1.0, 100.0, 1.0);
    gtk_scale_set_draw_value(GTK_SCALE(ui->room_brightness_scale), FALSE);
    gtk_widget_set_size_request(ui->room_brightness_scale, -1, 58);
    add_css_class(ui->room_brightness_scale, "room-control-scale");
    gtk_box_pack_start(GTK_BOX(ui->room_brightness_box), brightness_header,
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(ui->room_brightness_box),
                       ui->room_brightness_scale, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(sheet), ui->room_brightness_box,
                       FALSE, FALSE, 0);
    g_signal_connect(ui->room_brightness_scale, "value-changed",
                     G_CALLBACK(room_brightness_changed), ui);

    ui->room_temperature_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 5);
    GtkWidget *temperature_header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *temperature_title = new_label(
        "COLOR TEMPERATURE", "room-control-title");
    ui->room_temperature_value = new_label("4500 K", "room-control-value");
    gtk_widget_set_halign(temperature_title, GTK_ALIGN_START);
    gtk_widget_set_halign(ui->room_temperature_value, GTK_ALIGN_END);
    gtk_box_pack_start(GTK_BOX(temperature_header), temperature_title,
                       TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(temperature_header), ui->room_temperature_value,
                     FALSE, FALSE, 0);
    ui->room_temperature_scale = gtk_scale_new_with_range(
        GTK_ORIENTATION_HORIZONTAL, 2000.0, 6500.0, 100.0);
    gtk_scale_set_draw_value(GTK_SCALE(ui->room_temperature_scale), FALSE);
    gtk_widget_set_size_request(ui->room_temperature_scale, -1, 58);
    add_css_class(ui->room_temperature_scale, "room-control-scale");
    GtkWidget *temperature_ends = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *warm = new_label("WARM", "room-temperature-end");
    GtkWidget *cool = new_label("COOL", "room-temperature-end");
    gtk_widget_set_halign(warm, GTK_ALIGN_START);
    gtk_widget_set_halign(cool, GTK_ALIGN_END);
    gtk_box_pack_start(GTK_BOX(temperature_ends), warm, TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(temperature_ends), cool, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(ui->room_temperature_box), temperature_header,
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(ui->room_temperature_box),
                       ui->room_temperature_scale, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(ui->room_temperature_box), temperature_ends,
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(sheet), ui->room_temperature_box,
                       FALSE, FALSE, 0);
    g_signal_connect(ui->room_temperature_scale, "value-changed",
                     G_CALLBACK(room_temperature_changed), ui);

    /* The thermostat setpoint. The range and the step are set per card when
     * the sheet opens, because they come from the registry element rather
     * than from this build: 7 to 35 and 21 are only what an unconfigured
     * scale has to say before a card has been chosen. */
    ui->room_setpoint_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 5);
    GtkWidget *setpoint_header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *setpoint_title = new_label("TARGET", "room-control-title");
    ui->room_setpoint_value = new_label("21°", "room-control-value");
    gtk_widget_set_halign(setpoint_title, GTK_ALIGN_START);
    gtk_widget_set_halign(ui->room_setpoint_value, GTK_ALIGN_END);
    gtk_box_pack_start(GTK_BOX(setpoint_header), setpoint_title,
                       TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(setpoint_header), ui->room_setpoint_value,
                     FALSE, FALSE, 0);
    ui->room_setpoint_scale = gtk_scale_new_with_range(
        GTK_ORIENTATION_HORIZONTAL, 7.0, 35.0, 0.5);
    gtk_scale_set_draw_value(GTK_SCALE(ui->room_setpoint_scale), FALSE);
    gtk_widget_set_size_request(ui->room_setpoint_scale, -1, 58);
    add_css_class(ui->room_setpoint_scale, "room-control-scale");
    gtk_box_pack_start(GTK_BOX(ui->room_setpoint_box), setpoint_header,
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(ui->room_setpoint_box),
                       ui->room_setpoint_scale, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(sheet), ui->room_setpoint_box,
                       FALSE, FALSE, 0);
    g_signal_connect(ui->room_setpoint_scale, "value-changed",
                     G_CALLBACK(room_setpoint_changed), ui);

    /* A cover's percentage. The range is the same for every cover there is,
     * so unlike the setpoint above nothing about it is set per card. */
    ui->room_position_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 5);
    GtkWidget *position_header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *position_title = new_label("OPEN", "room-control-title");
    ui->room_position_value = new_label("0%", "room-control-value");
    gtk_widget_set_halign(position_title, GTK_ALIGN_START);
    gtk_widget_set_halign(ui->room_position_value, GTK_ALIGN_END);
    gtk_box_pack_start(GTK_BOX(position_header), position_title,
                       TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(position_header), ui->room_position_value,
                     FALSE, FALSE, 0);
    ui->room_position_scale = gtk_scale_new_with_range(
        GTK_ORIENTATION_HORIZONTAL, 0.0, 100.0, 1.0);
    gtk_scale_set_draw_value(GTK_SCALE(ui->room_position_scale), FALSE);
    gtk_widget_set_size_request(ui->room_position_scale, -1, 58);
    add_css_class(ui->room_position_scale, "room-control-scale");
    gtk_box_pack_start(GTK_BOX(ui->room_position_box), position_header,
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(ui->room_position_box),
                       ui->room_position_scale, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(sheet), ui->room_position_box,
                       FALSE, FALSE, 0);
    g_signal_connect(ui->room_position_scale, "value-changed",
                     G_CALLBACK(room_position_changed), ui);

    ui->room_stop_button = new_button("STOP", "room-sheet-stop", 160, 62);
    gtk_widget_set_halign(ui->room_stop_button, GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(sheet), ui->room_stop_button, FALSE, FALSE, 0);
    g_signal_connect(ui->room_stop_button, "clicked",
                     G_CALLBACK(room_stop_clicked), ui);

    gtk_container_add(GTK_CONTAINER(revealer), sheet);
    ui->room_sheet = revealer;
    return revealer;
}

/* The room page: one drawing area for the whole grid, and the navigation bar
 * under it.
 *
 * The intro row the six-tile page carried — a kicker, a hint and a count of
 * tiles — is gone. Fourteen rows have to fit between the header and the
 * navigation bar without the bottom one being cut off, and a count of cards
 * is not a fact worth a row of the screen once the user has arranged them
 * themselves. */
static GtkWidget *room_page(PanelUi *ui)
{
    GtkWidget *page = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
    GtkWidget *area = gtk_drawing_area_new();

    gtk_widget_set_margin_start(page, 14);
    gtk_widget_set_margin_end(page, 14);
    gtk_widget_set_margin_top(page, 10);
    gtk_widget_set_margin_bottom(page, 6);
    add_css_class(page, "room-page");
    g_signal_connect(page, "draw", G_CALLBACK(room_page_draw), ui);

    add_css_class(area, "room-grid");
    gtk_widget_set_hexpand(area, TRUE);
    gtk_widget_set_vexpand(area, TRUE);
    /* Touch arrives as button events on this tablet; both masks are asked
     * for so that a mouse in a development session behaves the same way. */
    gtk_widget_add_events(area, GDK_BUTTON_PRESS_MASK |
                                    GDK_BUTTON_RELEASE_MASK |
                                    GDK_TOUCH_MASK);
    g_signal_connect(area, "draw", G_CALLBACK(room_area_draw), ui);
    g_signal_connect(area, "button-press-event",
                     G_CALLBACK(room_area_pressed), ui);
    g_signal_connect(area, "button-release-event",
                     G_CALLBACK(room_area_released), ui);
    g_signal_connect(area, "size-allocate",
                     G_CALLBACK(room_area_allocated), ui);
    ui->room_area = area;

    /* The grid is read here rather than in the constructor, because reading
     * it needs the registry the config sensor delivered, and that has
     * arrived by the time the interface is built. */
    if (ui->room_grid == NULL)
        ui->room_grid = panel_grid_load(&ui->config->layout);
    room_cards_rebuild(ui);

    gtk_box_pack_start(GTK_BOX(page), area, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(page), navigation(ui), FALSE, FALSE, 4);
    return page;
}

guint panel_ui_card_count(PanelUi *ui)
{
    return ui->room_cards != NULL ? ui->room_cards->len : 0;
}

const PanelEntity *panel_ui_card_entity(PanelUi *ui, guint index)
{
    if (ui->room_cards == NULL || index >= ui->room_cards->len)
        return NULL;
    return ((const PanelRoomCard *)g_ptr_array_index(ui->room_cards,
                                                     index))->entity;
}

/* A saved arrangement replaces the one on screen without rebuilding a single
 * widget: the page is one drawing area, so a new grid is a new card list and
 * a redraw. This is what the editor calls once it has written the file. */
void panel_ui_set_grid(PanelUi *ui, PanelGrid *grid)
{
    g_return_if_fail(grid != NULL);

    if (ui->room_sheet != NULL)
        gtk_revealer_set_reveal_child(GTK_REVEALER(ui->room_sheet), FALSE);
    if (ui->room_grid != grid) {
        g_clear_pointer(&ui->room_grid, panel_grid_free);
        ui->room_grid = grid;
    }
    room_cards_rebuild(ui);
    if (ui->room_area != NULL)
        gtk_widget_queue_draw(ui->room_area);
}

const PanelGrid *panel_ui_grid(PanelUi *ui)
{
    return ui->room_grid;
}

void panel_ui_set_editor_url(PanelUi *ui, const gchar *url)
{
    g_free(ui->room_editor_hint);
    ui->room_editor_hint = url != NULL && *url != 0
        ? g_strdup_printf("Open %s in a browser on this network to arrange "
                          "the room page.", url)
        : NULL;
    if (ui->room_area != NULL && panel_ui_card_count(ui) == 0)
        gtk_widget_queue_draw(ui->room_area);
}

PanelUi *panel_ui_new(const AppConfig *config, PanelUiEventHandler handler,
                      gpointer user_data)
{
    g_return_val_if_fail(config != NULL, NULL);
    g_return_val_if_fail(handler != NULL, NULL);

    PanelUi *ui = g_new0(PanelUi, 1);
    ui->config = config;
    ui->event_handler = handler;
    ui->event_user_data = user_data;
    ui->navigation_buttons = g_ptr_array_new();
    ui->room_adjust_index = -1;
    /* config.ini decides only until Home Assistant has been read once, but it
     * decides now, so the first frame is already in the right skin. */
    ui->skin = config->player_skin;
    ui->deck_pack_radius = -1;
    ui->deck_tape_filled = -1;
    ui->room_pressed_index = -1;
    ui->room_cards = g_ptr_array_new_with_free_func(room_card_free);
    ui->room_icon_cache = g_hash_table_new_full(g_str_hash, g_str_equal,
                                                g_free, icon_set_free);
    return ui;
}

void panel_ui_free(PanelUi *ui)
{
    if (ui->brightness_debounce_source != 0)
        g_source_remove(ui->brightness_debounce_source);
    if (ui->temperature_debounce_source != 0)
        g_source_remove(ui->temperature_debounce_source);
    if (ui->setpoint_debounce_source != 0)
        g_source_remove(ui->setpoint_debounce_source);
    if (ui->position_debounce_source != 0)
        g_source_remove(ui->position_debounce_source);
    if (ui->room_animation_tick != 0 && ui->room_area != NULL)
        gtk_widget_remove_tick_callback(ui->room_area,
                                        ui->room_animation_tick);
    g_clear_pointer(&ui->room_cards, g_ptr_array_unref);
    g_clear_pointer(&ui->room_icon_cache, g_hash_table_unref);
    g_clear_pointer(&ui->room_grid, panel_grid_free);
    g_free(ui->room_editor_hint);
    if (ui->deck_animation_source != 0)
        g_source_remove(ui->deck_animation_source);
    g_clear_object(&ui->deck_art);
    g_ptr_array_unref(ui->navigation_buttons);
    g_free(ui);
}

/* The header indicators are drawn with Cairo so that they do not depend on
 * the icon theme installed on the tablet and can be tinted per state. */
#define PANEL_COLOR_ACCENT 0x56e5dcU
#define PANEL_COLOR_CHARGING 0x5ce48aU
#define PANEL_COLOR_WARNING 0xffc36bU
#define PANEL_COLOR_ALERT 0xff8a94U
#define PANEL_COLOR_OUTLINE 0x6d86a5U
#define PANEL_COLOR_BOLT 0xf7faffU

static void set_source_color(cairo_t *cr, guint color, gdouble alpha)
{
    cairo_set_source_rgba(cr, ((color >> 16) & 0xffU) / 255.0,
                          ((color >> 8) & 0xffU) / 255.0,
                          (color & 0xffU) / 255.0, alpha);
}

static void rounded_rectangle(cairo_t *cr, gdouble x, gdouble y, gdouble width,
                              gdouble height, gdouble radius)
{
    cairo_new_sub_path(cr);
    cairo_arc(cr, x + width - radius, y + radius, radius, -0.5 * PANEL_PI, 0.0);
    cairo_arc(cr, x + width - radius, y + height - radius, radius, 0.0,
              0.5 * PANEL_PI);
    cairo_arc(cr, x + radius, y + height - radius, radius, 0.5 * PANEL_PI,
              PANEL_PI);
    cairo_arc(cr, x + radius, y + radius, radius, PANEL_PI, 1.5 * PANEL_PI);
    cairo_close_path(cr);
}

/* A chain link, not a signal strength icon: the state describes the Home
 * Assistant connection and must not be mistaken for the Wi-Fi indicator.
 * Only an unreachable Home Assistant breaks the link. A misconfigured entity
 * keeps the link whole and turns it amber, because the panel did reach the
 * server. */
static gboolean status_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data)
{
    PanelUi *ui = user_data;
    gdouble center_x = gtk_widget_get_allocated_width(widget) / 2.0;
    gdouble center_y = gtk_widget_get_allocated_height(widget) / 2.0;
    gboolean broken = ui->status_state == PANEL_UI_STATUS_OFFLINE;
    gdouble gap = broken ? 3.5 : 0.0;
    guint color = PANEL_COLOR_ACCENT;

    if (ui->status_state == PANEL_UI_STATUS_CONNECTING)
        color = PANEL_COLOR_OUTLINE;
    else if (ui->status_state == PANEL_UI_STATUS_WARNING)
        color = PANEL_COLOR_WARNING;
    else if (broken)
        color = PANEL_COLOR_ALERT;

    set_source_color(cr, color, 1.0);
    cairo_set_line_width(cr, 2.4);
    cairo_save(cr);
    cairo_translate(cr, center_x, center_y);
    cairo_rotate(cr, -0.25 * PANEL_PI);
    rounded_rectangle(cr, -12.0 - gap, -5.0, 13.5, 10.0, 5.0);
    cairo_stroke(cr);
    rounded_rectangle(cr, -1.5 + gap, -5.0, 13.5, 10.0, 5.0);
    cairo_stroke(cr);
    cairo_restore(cr);
    return FALSE;
}

static gboolean battery_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data)
{
    static const gdouble bolt[][2] = {
        {2.5, -7.0}, {-3.0, 0.5}, {0.0, 0.5},
        {-2.5, 7.0}, {3.5, -0.5}, {0.5, -0.5}
    };
    PanelUi *ui = user_data;
    gdouble width = gtk_widget_get_allocated_width(widget);
    gdouble height = gtk_widget_get_allocated_height(widget);
    gdouble center_x = width / 2.0;
    gdouble body_top = 4.0;
    gdouble body_height = height - body_top - 1.0;
    gdouble body_width = width - 3.0;
    gdouble body_left = center_x - body_width / 2.0;
    gdouble track_top = body_top + 3.0;
    gdouble track_height = body_height - 6.0;
    guint color = PANEL_COLOR_ACCENT;

    if (ui->battery_charging) {
        color = PANEL_COLOR_CHARGING;
    } else if (ui->battery_percent <= 15) {
        color = PANEL_COLOR_ALERT;
    } else if (ui->battery_percent <= 35) {
        color = PANEL_COLOR_WARNING;
    }

    /* The outline follows the charge state as well, so the indicator differs
     * even where the fill is short. */
    set_source_color(cr, ui->battery_charging ? color : PANEL_COLOR_OUTLINE,
                     1.0);
    cairo_set_line_width(cr, 1.6);
    rounded_rectangle(cr, body_left, body_top, body_width, body_height, 4.5);
    cairo_stroke(cr);
    rounded_rectangle(cr, center_x - 4.0, 0.8, 8.0, 3.4, 1.4);
    cairo_fill(cr);

    if (ui->battery_percent > 0) {
        gdouble fill = MAX(track_height * ui->battery_percent / 100.0, 3.0);
        set_source_color(cr, color, 1.0);
        rounded_rectangle(cr, body_left + 3.0, track_top + track_height - fill,
                          body_width - 6.0, fill, 2.0);
        cairo_fill(cr);
    }

    if (ui->battery_charging) {
        gdouble bolt_y = body_top + body_height / 2.0;

        cairo_move_to(cr, center_x + bolt[0][0], bolt_y + bolt[0][1]);
        for (guint i = 1; i < G_N_ELEMENTS(bolt); i++)
            cairo_line_to(cr, center_x + bolt[i][0], bolt_y + bolt[i][1]);
        cairo_close_path(cr);
        set_source_color(cr, PANEL_COLOR_BOLT, 1.0);
        cairo_fill_preserve(cr);
        set_source_color(cr, palette(ui)->header, 1.0);
        cairo_set_line_width(cr, 1.2);
        cairo_stroke(cr);
    }
    return FALSE;
}

static GtkWidget *build_clock(PanelUi *ui)
{
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_valign(box, GTK_ALIGN_CENTER);
    ui->clock_time = new_label("--:--", "clock-time");
    ui->clock_date = new_label("", "clock-date");
    gtk_box_pack_start(GTK_BOX(box), ui->clock_time, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box), ui->clock_date, FALSE, FALSE, 0);
    return box;
}

static GtkWidget *build_status(PanelUi *ui)
{
    ui->status_state = PANEL_UI_STATUS_CONNECTING;
    ui->status = gtk_drawing_area_new();
    gtk_widget_set_size_request(ui->status, 30, 30);
    gtk_widget_set_valign(ui->status, GTK_ALIGN_CENTER);
    gtk_widget_set_tooltip_text(ui->status, "Connecting");
    g_signal_connect(ui->status, "draw", G_CALLBACK(status_draw), ui);
    return ui->status;
}

static GtkWidget *build_battery(PanelUi *ui)
{
    ui->battery_box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 7);
    gtk_widget_set_valign(ui->battery_box, GTK_ALIGN_CENTER);
    gtk_widget_set_no_show_all(ui->battery_box, TRUE);
    ui->battery_icon = gtk_drawing_area_new();
    gtk_widget_set_size_request(ui->battery_icon, 18, 30);
    gtk_widget_set_valign(ui->battery_icon, GTK_ALIGN_CENTER);
    g_signal_connect(ui->battery_icon, "draw", G_CALLBACK(battery_draw), ui);
    ui->battery_level = new_label("--%", "battery-level");
    gtk_box_pack_start(GTK_BOX(ui->battery_box), ui->battery_icon, FALSE, FALSE,
                       0);
    gtk_box_pack_start(GTK_BOX(ui->battery_box), ui->battery_level, FALSE,
                       FALSE, 0);
    /* The children are shown once here because the box itself opts out of the
     * recursive show, which keeps its visibility driven by the battery state
     * alone. */
    gtk_widget_show(ui->battery_icon);
    gtk_widget_show(ui->battery_level);
    return ui->battery_box;
}

GtkWidget *panel_ui_build(PanelUi *ui)
{
    GtkWidget *outer = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkWidget *header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    add_css_class(header, "header");
    gtk_widget_set_size_request(header, -1, 70);

    ui->page_title = new_label("NOW PLAYING", "header-title");
    gtk_widget_set_halign(ui->page_title, GTK_ALIGN_START);
    gtk_widget_set_valign(ui->page_title, GTK_ALIGN_CENTER);
    gtk_box_pack_start(GTK_BOX(header), ui->page_title, FALSE, FALSE, 18);
    gtk_box_set_center_widget(GTK_BOX(header), build_clock(ui));
    /* The battery indicator stays at the far right and the connection icon
     * sits directly to its left. Grouping both keeps the right margin intact
     * when the tablet reports no battery. */
    GtkWidget *indicators = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_widget_set_valign(indicators, GTK_ALIGN_CENTER);
    gtk_box_pack_start(GTK_BOX(indicators), build_status(ui), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(indicators), build_battery(ui), FALSE, FALSE, 0);
    gtk_box_pack_end(GTK_BOX(header), indicators, FALSE, FALSE, 18);

    ui->stack = gtk_stack_new();
    gtk_stack_set_transition_type(GTK_STACK(ui->stack),
                                  GTK_STACK_TRANSITION_TYPE_CROSSFADE);
    gtk_stack_set_transition_duration(GTK_STACK(ui->stack), 180);
    /* Both player layouts exist from here on, and both are written by every
     * setter. Switching skins therefore shows a page that is already right
     * rather than one that catches up on the next poll. */
    gtk_stack_add_named(GTK_STACK(ui->stack), player_page(ui), "player");
    gtk_stack_add_named(GTK_STACK(ui->stack), deck_page(ui), PANEL_DECK_CHILD);
    gtk_stack_add_named(GTK_STACK(ui->stack), list_page(ui, TRUE), "queue");
    gtk_stack_add_named(GTK_STACK(ui->stack), list_page(ui, FALSE), "playlists");
    gtk_stack_add_named(GTK_STACK(ui->stack), room_page(ui), "room");
    GtkWidget *content = gtk_overlay_new();
    gtk_container_add(GTK_CONTAINER(content), ui->stack);
    gtk_overlay_add_overlay(GTK_OVERLAY(content), room_adjust_sheet(ui));
    gtk_box_pack_start(GTK_BOX(outer), header, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(outer), content, TRUE, TRUE, 0);
    ui->root = outer;
    toggle_css_class(outer, "skin-cassette",
                     ui->skin == PANEL_PLAYER_SKIN_CASSETTE);
    panel_ui_show_page(ui, "player", "NOW PLAYING");
    return outer;
}

GtkWidget *panel_ui_build_config_error(const gchar *message)
{
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 20);
    gtk_widget_set_valign(box, GTK_ALIGN_CENTER);
    gtk_widget_set_margin_start(box, 60);
    gtk_widget_set_margin_end(box, 60);
    GtkWidget *error = new_label(message, "config-error");
    gtk_label_set_line_wrap(GTK_LABEL(error), TRUE);
    gtk_box_pack_start(GTK_BOX(box),
                       new_label("T560 Music Panel", "setup-title"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box), error, FALSE, FALSE, 0);
    return box;
}

GtkWidget *panel_ui_build_pairing(const gchar *code, const gchar *message)
{
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 24);
    gtk_widget_set_valign(box, GTK_ALIGN_CENTER);
    gtk_widget_set_margin_start(box, 60);
    gtk_widget_set_margin_end(box, 60);

    GtkWidget *digits = new_label(code, "pairing-code");
    GtkWidget *status = new_label(message, "config-error");
    gtk_label_set_line_wrap(GTK_LABEL(status), TRUE);
    gtk_label_set_justify(GTK_LABEL(status), GTK_JUSTIFY_CENTER);
    gtk_widget_set_halign(digits, GTK_ALIGN_CENTER);
    gtk_widget_set_size_request(digits, 600, -1);  // Adjust 600 to fit your 6 digit code

    gtk_box_pack_start(GTK_BOX(box),
                       new_label("T560 Music Panel", "setup-title"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box),
                       new_label("PAIRING CODE", "room-kicker"),
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box), digits, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box), status, FALSE, FALSE, 0);
    return box;
}

static void install_css(const gchar *css)
{
    GtkCssProvider *provider = gtk_css_provider_new();
    GError *error = NULL;

    if (gtk_css_provider_load_from_data(provider, css, -1, &error)) {
        gtk_style_context_add_provider_for_screen(
            gdk_screen_get_default(), GTK_STYLE_PROVIDER(provider),
            GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    } else {
        g_warning("Could not load UI styles: %s", error->message);
        g_clear_error(&error);
    }
    g_object_unref(provider);
}

void panel_ui_install_styles(void)
{
    static const gchar css[] =
        "*{font-family:Sans;color:#edf4ff}"
        "window{background:#070c14;color:#edf4ff}"
        ".header{background:#0c1420;border-bottom:1px solid #1d2b3f;box-shadow:0 5px 18px rgba(0,0,0,.28)}"
        ".header-title{font-size:24px;font-weight:700;color:#f7faff}"
        ".clock-time{font-size:23px;font-weight:700;color:#f7faff}"
        ".clock-date{font-size:12px;font-weight:600;color:#7f97b5}"
        ".battery-level{font-size:15px;font-weight:700;color:#dceaff}"
        "button{background-image:linear-gradient(to bottom,#182438,#111a29);color:#e8f0fb;border:1px solid #2b3c55;border-radius:18px;box-shadow:0 5px 14px rgba(0,0,0,.24)}"
        "button:hover{background-image:linear-gradient(to bottom,#1d2c43,#152138);border-color:#3b526f}"
        "button:active{background:#20334d;box-shadow:none}"
        "button.active{background:#12373c;border-color:#43d8d0;color:#75f1e9;box-shadow:0 0 0 1px rgba(67,216,208,.18)}"
        ".icon-button image{-gtk-icon-shadow:none}"
        ".player-page{background-image:linear-gradient(to bottom,#0a111c,#070c14)}"
        ".artwork-card{background:#101a29;border:1px solid #25364e;border-radius:28px;padding:10px;box-shadow:0 14px 34px rgba(0,0,0,.42)}"
        ".track-details{padding:2px 12px}"
        ".track-title{font-size:30px;font-weight:700;color:#f8fbff}"
        ".artist{font-size:20px;color:#8fa9c7}"
        ".position{font-size:14px;font-weight:600;color:#778ba5}"
        "progressbar trough{min-height:8px;background:#172235;border-radius:6px}"
        "progressbar progress{min-height:8px;background-image:linear-gradient(to right,#31c8da,#55e4c5);border-radius:6px;box-shadow:0 0 8px rgba(49,200,218,.35)}"
        ".mode-button{font-size:16px;font-weight:700;border-radius:20px;box-shadow:none}"
        ".library-button{font-size:15px;font-weight:700;border-radius:25px;box-shadow:none;border-color:#2f5a63;color:#8fe6df}"
        ".library-button:hover{border-color:#43d8d0}"
        ".transport-button{background:#121d2d;border-color:#2a3c55;border-radius:28px;box-shadow:0 7px 18px rgba(0,0,0,.28)}"
        ".play-button{background-image:linear-gradient(to bottom,#5ce4d7,#2fc8d6);color:#061418;border:0;border-radius:36px;box-shadow:0 10px 28px rgba(47,200,214,.32)}"
        ".play-button:hover{background-image:linear-gradient(to bottom,#72eee3,#43d7e2)}"
        ".play-button:active{background:#27b3c1;box-shadow:0 4px 10px rgba(47,200,214,.24)}"
        ".volume-card{background:#0e1826;border:1px solid #22334a;border-radius:25px;padding:6px 12px}"
        ".volume-button{background:transparent;border:0;box-shadow:none;color:#91aac8}"
        ".volume-button:active{background:#192b41;color:#56e5dc}"
        ".volume-caption{font-size:11px;font-weight:700;color:#647a96}"
        ".volume{font-size:22px;font-weight:700;color:#dceaff}"
        ".navigation-bar{background:#0d1623;border:1px solid #1e2d42;border-radius:25px;padding:5px;box-shadow:0 8px 22px rgba(0,0,0,.3)}"
        ".nav-button{font-size:13px;font-weight:700;background:transparent;border:0;border-radius:19px;box-shadow:none;color:#7188a5}"
        ".nav-button.active{background:#152e3a;border:0;color:#5ee1d8;box-shadow:none}"
        ".list-view{font-size:20px;background:#070c14;color:#edf4ff}"
        ".list-view:selected{background:#12373c;color:#75f1e9}"
        ".play-selected{font-size:20px;font-weight:700;border-color:#43d8d0}"
        ".setup-title{font-size:38px;font-weight:700;color:#56e5dc}"
        ".config-error{font-size:21px}"
        /* Read out loud from across the room, so it is the largest text the
         * panel ever draws. */
        ".pairing-code{font-size:86px;font-weight:700;letter-spacing:14px;"
        "color:#f2f6ff}";
    static const gchar room_css[] =
        ".room-page{background:transparent}"
        ".room-kicker{font-size:12px;font-weight:700;letter-spacing:2px;color:#54ded6}"
        ".room-help{font-size:17px;color:#778ba5}"
        ".room-count{font-size:12px;font-weight:700;color:#8fa9c7;background:#111d2d;border:1px solid #263952;border-radius:16px;padding:8px 14px}"
        /* The cards themselves are drawn with Cairo in one drawing area,
         * so the only rule they need is that GTK paints nothing behind
         * them. */
        ".room-grid{background:transparent}";
    static const gchar room_sheet_css[] =
        ".room-sheet{background:transparent;background-image:none;border:1px solid #3a526e;border-bottom:5px solid #050a11;border-radius:28px;padding:22px 28px;box-shadow:0 0 34px rgba(0,0,0,.62)}"
        ".room-sheet-title{font-size:25px;font-weight:700;color:#f5f9ff}"
        ".room-sheet-subtitle{font-size:14px;color:#7f98b6}"
        ".room-sheet-close{font-size:12px;font-weight:700;color:#6fe7df;background:#122a37;border-color:#337078;border-radius:16px;box-shadow:none}"
        ".room-sheet-stop{font-size:15px;font-weight:700;color:#ffd9d0;background:#3a1a17;border-color:#7a3128;border-radius:16px;box-shadow:none}"
        ".room-control-title{font-size:13px;font-weight:700;color:#8fa9c7}"
        ".room-control-value{font-size:18px;font-weight:700;color:#67e6de}"
        ".room-temperature-end{font-size:11px;font-weight:700;color:#647d9a}"
        ".room-control-scale trough{min-height:14px;background:#09121d;border:1px solid #2a3d55;border-radius:8px}"
        ".room-control-scale highlight{min-height:14px;background-image:linear-gradient(to right,#2fc8d6,#5ce4d7);border-radius:8px}"
        ".room-control-scale slider{min-width:34px;min-height:34px;margin:-11px;background-image:linear-gradient(to bottom,#f3ffff,#8ceee8);border:2px solid #236e75;border-radius:18px;box-shadow:0 4px 10px rgba(0,0,0,.38)}";

    /* The cassette skin. Not one gradient in it: the tablet framebuffer is
     * RGB565, a gradient down a key would band into three or four visible
     * steps, and a machined faceplate is flat metal with hard edges anyway.
     * Every gradient this skin does draw goes through Cairo, where the
     * texture pattern dithers it. */
    static const gchar deck_css[] =
        /* The page paints itself, so the default background must not cover
         * the brushed metal underneath it. */
        ".deck-page{background:transparent}"
        ".deck-strip{border-bottom:1px solid #0a0b0d}"
        ".deck-brand{font-size:20px;font-weight:700;color:#c6ccd4}"
        ".deck-model{font-size:19px;font-weight:700;color:#d7dde4}"
        ".deck-engraved{font-size:12px;font-weight:700;color:#a9b1bb}"
        ".deck-band-side{font-size:17px;font-weight:700;color:#f2e3cb}"
        ".deck-band-index{font-size:14px;font-weight:700;color:#cbb99e}"
        /* The display glass: one flat warm black, lit only by its contents. */
        ".deck-display{background:#0a0704;border:1px solid #0b0c0d;"
        "border-radius:3px;padding:14px 22px}"
        ".deck-title{font-size:30px;font-weight:600;color:#ffd79b}"
        ".deck-artist{font-size:19px;color:#c08b47}"
        ".deck-flags{border-top:1px solid #33230f;margin-top:4px}"
        ".deck-flag{font-size:14px;font-weight:700;color:#6d4a1c}"
        ".deck-flag.on{color:#ffae3d}"
        ".deck-counter{font-size:44px;font-weight:700;color:#ffae3d}"
        ".deck-counter-total{font-size:22px;font-weight:700;color:#9c6f34}"
        ".deck-meter-caption{font-size:13px;font-weight:700;color:#9c6f34}"
        ".deck-meter-value{font-size:20px;font-weight:700;color:#ffae3d}"
        ".deck-scale{font-size:10px;font-weight:700;color:#7d5a2b}"
        /* A machined key: flat cap, bright top chamfer, deep bottom lip. */
        ".deck-key{background-image:none;background:#31353b;border-radius:3px;"
        "border-top:1px solid #626973;border-left:1px solid #3f444c;"
        "border-right:1px solid #23272c;border-bottom:5px solid #08090b;"
        "color:#eaeef3;box-shadow:none}"
        ".deck-key:hover{background:#3a3f46;border-top-color:#727a85}"
        /* Pressed: the cap travels, so the lip loses three pixels and the
         * content takes them, which moves the legend down by the same
         * distance a real key would. */
        ".deck-key:active{background:#24282e;border-bottom-width:2px;"
        "padding-top:3px}"
        ".deck-key .button-label,.deck-key-label{font-size:13px;"
        "font-weight:700;color:#98a0aa}"
        ".deck-key-main .button-label{font-size:14px}"
        ".deck-lamp{background:#2a231a;border-radius:2px}"
        ".deck-lamp.active{background:#ffae3d}";

    /* The skin owns the whole interface, not the player page alone. One class
     * on the root widget carries it to the navigation bar, the two lists and
     * the room page, so a skin change restyles them without rebuilding a
     * single widget. Everything drawn with Cairo follows the palette instead;
     * these are only the parts GTK draws from the stylesheet. */
    static const gchar cassette_css[] =
        ".skin-cassette .header{background:#15171a;border-bottom-color:#2a2e34}"
        ".skin-cassette .navigation-bar{background:#191b1f;"
        "border-color:#383d45}"
        ".skin-cassette .nav-button{color:#8a919b}"
        ".skin-cassette .nav-button.active{background:#3d2b10;color:#ffd79b}"
        ".skin-cassette .list-view{background:#141619;color:#e6e9ee}"
        ".skin-cassette .list-view:selected{background:#553a14;color:#ffd79b}"
        ".skin-cassette .play-selected{background-image:none;background:#31353b;"
        "border-color:#8a6427;color:#ffd79b}"
        ".skin-cassette .room-kicker{color:#ffae3d}"
        ".skin-cassette .room-help{color:#8f979f}"
        ".skin-cassette .room-count{background:#1f2228;border-color:#3a3f46;"
        "color:#b7bec7}"
        ".skin-cassette .room-icon-shell{background-image:none;"
        "background:#2c3036;border-color:#565d67;border-bottom-color:#0a0b0d}"
        ".skin-cassette .room-card.active .room-icon-shell{"
        "background-image:none;background:#ffae3d;border-color:#ffd79b;"
        "border-bottom-color:#6d4a1c}"
        ".skin-cassette .room-icon{color:#a9b1bb}"
        ".skin-cassette .room-card.active .room-icon{color:#241a0d}"
        ".skin-cassette .room-state{background:#15171a;border-color:#3a3f46;"
        "color:#b7bec7}"
        ".skin-cassette .room-card.active .room-state{background:#ffae3d;"
        "border-color:#ffd79b;color:#241a0d}"
        ".skin-cassette .room-type{color:#8f979f}"
        ".skin-cassette .room-adjust-button{background:#31353b;"
        "border-color:#626973;color:#eaeef3}"
        ".skin-cassette .room-adjust-button:hover{background:#3a3f46;"
        "border-color:#727a85}"
        ".skin-cassette .room-adjust-button:active{background:#24282e;"
        "border-color:#626973;color:#eaeef3}"
        ".skin-cassette .room-sheet{border-color:#4a5058;"
        "border-bottom-color:#08090b}"
        ".skin-cassette .room-sheet-close{background:#3d2b10;"
        "border-color:#8a6427;color:#ffc978}"
        ".skin-cassette .room-control-title{color:#a9b1bb}"
        ".skin-cassette .room-control-value{color:#ffae3d}"
        ".skin-cassette .room-temperature-end{color:#8a7150}"
        ".skin-cassette .room-control-scale trough{background:#121417;"
        "border-color:#3a3f46}"
        ".skin-cassette .room-control-scale highlight{background-image:none;"
        "background:#ffae3d}"
        ".skin-cassette .room-control-scale slider{background-image:none;"
        "background:#ffd79b;border-color:#6d4a1c}";

    install_css(css);
    install_css(room_css);
    install_css(room_sheet_css);
    install_css(deck_css);
    install_css(cassette_css);
}

void panel_ui_set_status(PanelUi *ui, const gchar *text,
                         PanelUiStatus status)
{
    gboolean changed = ui->status_state != status;

    ui->status_state = status;
    /* The icon replaces the former status text, so the message is preserved
     * as a tooltip for diagnostics. It names the rejected entity when the
     * configuration is at fault. */
    gtk_widget_set_tooltip_text(ui->status, text);
    if (changed)
        gtk_widget_queue_draw(ui->status);
}

void panel_ui_set_clock(PanelUi *ui, const gchar *time_text,
                        const gchar *date_text)
{
    gtk_label_set_text(GTK_LABEL(ui->clock_time), time_text);
    gtk_label_set_text(GTK_LABEL(ui->clock_date), date_text);
}

void panel_ui_set_battery(PanelUi *ui, gboolean available, gint percent,
                          gboolean charging)
{
    if (!available) {
        gtk_widget_hide(ui->battery_box);
        return;
    }

    ui->battery_percent = CLAMP(percent, 0, 100);
    ui->battery_charging = charging;

    gchar *text = g_strdup_printf("%d%%", ui->battery_percent);
    gtk_label_set_text(GTK_LABEL(ui->battery_level), text);
    g_free(text);

    gtk_widget_queue_draw(ui->battery_icon);
    gtk_widget_show(ui->battery_box);
}

void panel_ui_set_player(PanelUi *ui, gboolean playing, const gchar *title,
                         const gchar *artist, gdouble position,
                         gdouble duration, gdouble volume, gboolean shuffle,
                         const gchar *repeat)
{
    gdouble fraction = duration > 0.0 ? CLAMP(position / duration, 0.0, 1.0)
                                      : 0.0;
    gchar *position_text = format_time(position);
    gchar *duration_text = format_time(duration);
    gchar *timeline = g_strdup_printf("%s  /  %s", position_text,
                                      duration_text);
    gchar *total_text = g_strdup_printf("/ %s", duration_text);
    gchar *volume_text = g_strdup_printf("%.0f%%", volume * 100.0);

    /* Every layout is written, the hidden one included. */
    for (guint i = 0; i < PANEL_PLAYER_SKIN_COUNT; i++) {
        PanelPlayerLayout *layout = &ui->players[i];

        if (layout->page == NULL)
            continue;
        gtk_label_set_text(GTK_LABEL(layout->track_title), title);
        gtk_label_set_text(GTK_LABEL(layout->artist), artist);
        gtk_image_set_from_icon_name(
            GTK_IMAGE(layout->play_icon),
            playing ? "media-playback-pause-symbolic"
                    : "media-playback-start-symbolic",
            GTK_ICON_SIZE_BUTTON);
        gtk_image_set_pixel_size(GTK_IMAGE(layout->play_icon),
                                 layout->play_icon_size);
        gtk_label_set_text(GTK_LABEL(layout->volume), volume_text);
        if (layout->progress != NULL) {
            gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(layout->progress),
                                          fraction);
        }
        if (layout->position != NULL)
            gtk_label_set_text(GTK_LABEL(layout->position), timeline);
        if (layout->elapsed != NULL)
            gtk_label_set_text(GTK_LABEL(layout->elapsed), position_text);
        if (layout->total != NULL)
            gtk_label_set_text(GTK_LABEL(layout->total), total_text);
        if (layout->flag_play != NULL)
            toggle_css_class(layout->flag_play, "on", playing);
    }
    g_free(position_text);
    g_free(duration_text);
    g_free(timeline);
    g_free(total_text);
    g_free(volume_text);

    deck_set_progress(ui, fraction);
    deck_set_volume(ui, volume);
    if (ui->playing != playing) {
        ui->playing = playing;
        deck_update_animation(ui);
    }
    panel_ui_set_modes(ui, shuffle, repeat);
}

void panel_ui_set_modes(PanelUi *ui, gboolean shuffle, const gchar *repeat)
{
    const gchar *repeat_state = g_str_equal(repeat, "all") ? "all"
                                : g_str_equal(repeat, "one") ? "one"
                                                               : "off";
    gboolean repeating = !g_str_equal(repeat_state, "off");
    /* A deck engraves its legends, so one layout wants REPEAT ALL where the
     * other wants Repeat all. GTK CSS has no text-transform. */
    gchar *sentence_case = g_strdup_printf("Repeat %s", repeat_state);
    gchar *upper_case = g_ascii_strup(sentence_case, -1);

    for (guint i = 0; i < PANEL_PLAYER_SKIN_COUNT; i++) {
        PanelPlayerLayout *layout = &ui->players[i];

        if (layout->page == NULL)
            continue;
        toggle_css_class(layout->shuffle_lamp != NULL ? layout->shuffle_lamp
                                   : layout->shuffle,
                 "active", shuffle);
        toggle_css_class(layout->repeat_lamp != NULL ? layout->repeat_lamp
                                  : layout->repeat,
                 "active", repeating);
        gtk_label_set_text(GTK_LABEL(layout->repeat_label),
                           layout->uppercase_labels ? upper_case
                                                    : sentence_case);
        if (layout->flag_shuffle != NULL)
            toggle_css_class(layout->flag_shuffle, "on", shuffle);
        if (layout->flag_repeat != NULL)
            toggle_css_class(layout->flag_repeat, "on", repeating);
    }
    g_free(sentence_case);
    g_free(upper_case);
}

/* The album art is fitted to the modern artwork card and cropped to the
 * cassette label, both exactly once, here, when it arrives. Nothing is scaled
 * while drawing: the bay repaints eight times a second while the tape runs,
 * and this tablet has a software renderer. */
static GdkPixbuf *scale_to_fit(GdkPixbuf *source, gint width, gint height)
{
    gint source_width = gdk_pixbuf_get_width(source);
    gint source_height = gdk_pixbuf_get_height(source);
    gdouble ratio = MIN((gdouble)width / source_width,
                        (gdouble)height / source_height);

    if (ratio >= 1.0)
        return g_object_ref(source);
    return gdk_pixbuf_scale_simple(
        source, MAX(1, (gint)(source_width * ratio + 0.5)),
        MAX(1, (gint)(source_height * ratio + 0.5)), GDK_INTERP_BILINEAR);
}

static GdkPixbuf *scale_to_cover(GdkPixbuf *source, gint width, gint height)
{
    gint source_width = gdk_pixbuf_get_width(source);
    gint source_height = gdk_pixbuf_get_height(source);
    gdouble ratio = MAX((gdouble)width / source_width,
                        (gdouble)height / source_height);
    gint scaled_width = MAX(width, (gint)(source_width * ratio + 0.5));
    gint scaled_height = MAX(height, (gint)(source_height * ratio + 0.5));
    GdkPixbuf *scaled = gdk_pixbuf_scale_simple(source, scaled_width,
                                                scaled_height,
                                                GDK_INTERP_BILINEAR);
    GdkPixbuf *cropped;

    if (scaled == NULL)
        return NULL;
    cropped = gdk_pixbuf_new_subpixbuf(scaled, (scaled_width - width) / 2,
                                       (scaled_height - height) / 2, width,
                                       height);
    g_object_unref(scaled);
    return cropped;
}

void panel_ui_set_album_art(PanelUi *ui, GdkPixbuf *pixbuf)
{
    PanelPlayerLayout *modern = &ui->players[PANEL_PLAYER_SKIN_MODERN];
    PanelPlayerLayout *deck = &ui->players[PANEL_PLAYER_SKIN_CASSETTE];

    if (modern->album_art != NULL) {
        GdkPixbuf *fitted = scale_to_fit(pixbuf, PANEL_MODERN_ART_SIZE,
                                         PANEL_MODERN_ART_SIZE);
        gtk_image_set_from_pixbuf(GTK_IMAGE(modern->album_art), fitted);
        g_clear_object(&fitted);
    }
    g_clear_object(&ui->deck_art);
    ui->deck_art = scale_to_cover(pixbuf, PANEL_DECK_SHELL_WIDTH,
                                  PANEL_DECK_SHELL_HEIGHT);
    if (deck->bay != NULL)
        gtk_widget_queue_draw(deck->bay);
}

/* The band across the cassette label carries the position in the queue, which
 * is the one number a deck would have printed on the paper. */
static void deck_set_index(PanelUi *ui, guint count, gint selected)
{
    PanelPlayerLayout *layout = &ui->players[PANEL_PLAYER_SKIN_CASSETTE];
    gchar *text;

    if (layout->index == NULL)
        return;
    text = count > 0 && selected >= 0
               ? g_strdup_printf("TRACK %02d / %02u", selected + 1, count)
               : g_strdup("");
    gtk_label_set_text(GTK_LABEL(layout->index), text);
    g_free(text);
}

void panel_ui_set_queue(PanelUi *ui, GPtrArray *titles, GPtrArray *artists,
                        guint count, gint selected)
{
    GtkListStore *store = GTK_LIST_STORE(gtk_tree_view_get_model(
        GTK_TREE_VIEW(ui->queue_list)));
    ui->changing_list_selection = TRUE;
    gtk_list_store_clear(store);
    for (guint i = 0; i < count; i++) {
        const gchar *title = g_ptr_array_index(titles, i);
        const gchar *artist = g_ptr_array_index(artists, i);
        gchar *text = *artist != '\0' ? g_strdup_printf("%s\n%s", title, artist)
                                      : g_strdup(title);
        GtkTreeIter iter;
        gtk_list_store_append(store, &iter);
        gtk_list_store_set(store, &iter,
                           LIST_COLUMN_INDEX, (gint)i,
                           LIST_COLUMN_TEXT, text, -1);
        g_free(text);
    }
    select_row(ui->queue_list, selected);
    ui->changing_list_selection = FALSE;
    deck_set_index(ui, count, selected);
}

void panel_ui_set_playlists(PanelUi *ui, GPtrArray *names, guint count,
                            gint selected)
{
    GtkListStore *store = GTK_LIST_STORE(gtk_tree_view_get_model(
        GTK_TREE_VIEW(ui->playlist_list)));
    ui->changing_list_selection = TRUE;
    gtk_list_store_clear(store);
    for (guint i = 0; i < count; i++) {
        GtkTreeIter iter;
        gtk_list_store_append(store, &iter);
        gtk_list_store_set(store, &iter,
                           LIST_COLUMN_INDEX, (gint)i,
                           LIST_COLUMN_TEXT, g_ptr_array_index(names, i), -1);
    }
    select_row(ui->playlist_list, selected);
    ui->changing_list_selection = FALSE;
}

void panel_ui_select_queue_item(PanelUi *ui, gint selected)
{
    ui->changing_list_selection = TRUE;
    select_row(ui->queue_list, selected);
    ui->changing_list_selection = FALSE;
}

void panel_ui_select_playlist(PanelUi *ui, gint selected)
{
    ui->changing_list_selection = TRUE;
    select_row(ui->playlist_list, selected);
    ui->changing_list_selection = FALSE;
}

void panel_ui_set_room(PanelUi *ui, guint index, const PanelRoomState *state)
{
    g_return_if_fail(ui->room_cards != NULL);
    g_return_if_fail(state != NULL);
    g_return_if_fail(index < ui->room_cards->len);

    PanelRoomCard *card = g_ptr_array_index(ui->room_cards, index);

    if (state->brightness_percent >= 0)
        card->brightness = CLAMP(state->brightness_percent, 1, 100);
    if (state->min_color_temp_kelvin > 0 && state->max_color_temp_kelvin > 0 &&
        state->min_color_temp_kelvin < state->max_color_temp_kelvin) {
        card->temperature_min = state->min_color_temp_kelvin;
        card->temperature_max = state->max_color_temp_kelvin;
    }
    if (state->color_temp_kelvin > 0) {
        card->temperature = CLAMP(state->color_temp_kelvin,
                                  card->temperature_min,
                                  card->temperature_max);
    }
    /* Taken as reported and not clamped to the registry's bounds: they are
     * what a card may *ask* for, and a room that is colder than a
     * thermostat's minimum is a fact worth drawing rather than an error. */
    if (!isnan(state->setpoint))
        card->setpoint = state->setpoint;
    if (!isnan(state->ambient))
        card->ambient = state->ambient;
    if (state->position >= 0)
        card->position = CLAMP(state->position, 0, 100);
    /* A weather block keeps its own reading. An absent condition clears the
     * last one rather than leaving a stale sky on the card. */
    if (card_is_weather(card)) {
        g_free(card->weather_condition);
        card->weather_condition = state->weather_condition != NULL
                                      ? g_strdup(state->weather_condition)
                                      : NULL;
        card->weather_temperature = state->weather_temperature;
        card->weather_humidity = state->weather_humidity;
    }
    /* A sensor block keeps its own reading. An absent value clears the last
     * one rather than leaving a stale number on the card. */
    if (card_is_sensor(card)) {
        g_free(card->sensor_value);
        g_free(card->sensor_unit);
        card->sensor_value = state->sensor_value != NULL
                                 ? g_strdup(state->sensor_value)
                                 : NULL;
        card->sensor_unit = state->sensor_unit != NULL
                                ? g_strdup(state->sensor_unit)
                                : NULL;
    }

    if (card->active != state->active || !card->state_known) {
        card->active = state->active;
        start_card_animation(ui, card, state->active);
    }
    card->state_known = TRUE;
    invalidate_card(ui, card);

    if (ui->room_adjust_index == (gint)index) {
        ui->changing_room_adjustment = TRUE;
        if (ui->brightness_debounce_source == 0 && card->brightness >= 0) {
            gtk_range_set_value(GTK_RANGE(ui->room_brightness_scale),
                                card->brightness);
        }
        gtk_range_set_range(GTK_RANGE(ui->room_temperature_scale),
                            card->temperature_min, card->temperature_max);
        if (ui->temperature_debounce_source == 0 && card->temperature >= 0) {
            gtk_range_set_value(GTK_RANGE(ui->room_temperature_scale),
                                card->temperature);
        }
        /* Never while a drag is still settling: the slider is where the
         * finger left it, and Home Assistant is still reporting the value
         * from before the change. */
        if (ui->setpoint_debounce_source == 0 && !isnan(card->setpoint)) {
            gtk_range_set_value(GTK_RANGE(ui->room_setpoint_scale),
                                card->setpoint);
        }
        if (ui->position_debounce_source == 0 && card->position >= 0) {
            gtk_range_set_value(GTK_RANGE(ui->room_position_scale),
                                card->position);
        }
        ui->changing_room_adjustment = FALSE;
    }
}

void panel_ui_set_room_forecast(PanelUi *ui, guint index,
                                const PanelWeatherDay *days, guint count)
{
    g_return_if_fail(ui->room_cards != NULL);
    g_return_if_fail(days != NULL || count == 0);
    g_return_if_fail(index < ui->room_cards->len);

    PanelRoomCard *card = g_ptr_array_index(ui->room_cards, index);

    /* A rebuild drops the cards and with them the forecast: only a card
     * that still names the same registry element may keep one. */
    if (card->entity == NULL ||
        g_strcmp0(card->entity->domain, "weather") != 0)
        return;
    card->forecast_count = MIN(count, (guint)PANEL_WEATHER_FORECAST_MAX);
    for (guint i = 0; i < card->forecast_count; i++)
        card->forecast[i] = days[i];
    card->forecast_at = g_get_monotonic_time();
    invalidate_card(ui, card);
}

gint64 panel_ui_room_forecast_at(PanelUi *ui, guint index)
{
    g_return_val_if_fail(ui->room_cards != NULL, 0);
    g_return_val_if_fail(index < ui->room_cards->len, 0);

    return ((const PanelRoomCard *)g_ptr_array_index(ui->room_cards,
                                                     index))->forecast_at;
}

void panel_ui_touch_room_forecast(PanelUi *ui, guint index)
{
    g_return_if_fail(ui->room_cards != NULL);
    g_return_if_fail(index < ui->room_cards->len);

    ((PanelRoomCard *)g_ptr_array_index(ui->room_cards, index))->forecast_at =
        g_get_monotonic_time();
}

/* Two stack children answer to one page name. "player" is what navigation
 * emits, what Home Assistant sends, and what the panel reports; which of the
 * two is shown is the skin's business and nobody else's. */
static const gchar *player_child_name(PanelUi *ui)
{
    return ui->skin == PANEL_PLAYER_SKIN_CASSETTE ? PANEL_DECK_CHILD
                                                  : "player";
}

void panel_ui_show_page(PanelUi *ui, const gchar *page, const gchar *title)
{
    ui->on_player = g_str_equal(page, "player");
    gtk_stack_set_visible_child_name(
        GTK_STACK(ui->stack), ui->on_player ? player_child_name(ui) : page);
    gtk_label_set_text(GTK_LABEL(ui->page_title), title);
    for (guint i = 0; i < ui->navigation_buttons->len; i++) {
        GtkWidget *button = g_ptr_array_index(ui->navigation_buttons, i);
        const gchar *button_page = g_object_get_data(
            G_OBJECT(button), "page");
        toggle_css_class(button, "active", g_str_equal(button_page, page));
    }
    deck_update_animation(ui);
}

void panel_ui_set_skin(PanelUi *ui, PanelPlayerSkin skin)
{
    if (skin >= PANEL_PLAYER_SKIN_COUNT)
        return;

    ui->skin = skin;
    if (ui->root == NULL)
        return;

    /* One class on the root restyles every shared widget through the
     * stylesheet, and the palette repaints everything drawn with Cairo. No
     * widget is rebuilt, so nothing loses its state. */
    toggle_css_class(ui->root, "skin-cassette",
                     skin == PANEL_PLAYER_SKIN_CASSETTE);
    refresh_room_icons(ui);
    if (ui->on_player) {
        gtk_stack_set_visible_child_name(GTK_STACK(ui->stack),
                                         player_child_name(ui));
    }
    gtk_widget_queue_draw(ui->root);
    deck_update_animation(ui);
}
