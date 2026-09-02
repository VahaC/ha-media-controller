#include "panel_ui.h"

#include <math.h>

/* The ADJUST button sits in the top-right corner of a room card and the
 * header row reserves its height, so both must use the same value. */
#define PANEL_ROOM_ADJUST_HEIGHT 44

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
    GtkWidget *room_buttons[PANEL_ROOM_MAX];
    GtkWidget *room_adjust_buttons[PANEL_ROOM_MAX];
    GtkWidget *room_icons[PANEL_ROOM_MAX];
    GtkWidget *room_states[PANEL_ROOM_MAX];
    gboolean room_active[PANEL_ROOM_MAX];
    gdouble room_active_mix[PANEL_ROOM_MAX];
    gdouble room_animation_from[PANEL_ROOM_MAX];
    gdouble room_animation_to[PANEL_ROOM_MAX];
    gint64 room_animation_start_us[PANEL_ROOM_MAX];
    guint room_animation_tick[PANEL_ROOM_MAX];
    GdkPixbuf *room_icon_source[PANEL_ROOM_MAX];
    GdkPixbuf *room_icon_off[PANEL_ROOM_MAX];
    GdkPixbuf *room_icon_on[PANEL_ROOM_MAX];
    GtkWidget *room_sheet;
    GtkWidget *room_sheet_title;
    GtkWidget *room_brightness_box;
    GtkWidget *room_brightness_scale;
    GtkWidget *room_brightness_value;
    GtkWidget *room_temperature_box;
    GtkWidget *room_temperature_scale;
    GtkWidget *room_temperature_value;
    gint room_adjust_index;
    gint room_brightness[PANEL_ROOM_MAX];
    gint room_temperature[PANEL_ROOM_MAX];
    gint room_temperature_min[PANEL_ROOM_MAX];
    gint room_temperature_max[PANEL_ROOM_MAX];
    gboolean changing_room_adjustment;
    guint brightness_debounce_source;
    guint temperature_debounce_source;
    gint pending_brightness_index;
    gint pending_brightness;
    gint pending_temperature_index;
    gint pending_temperature;
};

static void rounded_rectangle(cairo_t *cr, gdouble x, gdouble y, gdouble width,
                              gdouble height, gdouble radius);
static void set_source_color(cairo_t *cr, guint color, gdouble alpha);
static void refresh_room_icons(PanelUi *ui);
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

static GdkPixbuf *tint_icon(GdkPixbuf *source, guint color)
{
    GdkPixbuf *result = gdk_pixbuf_copy(source);
    guchar *pixels = gdk_pixbuf_get_pixels(result);
    gint width = gdk_pixbuf_get_width(result);
    gint height = gdk_pixbuf_get_height(result);
    gint rowstride = gdk_pixbuf_get_rowstride(result);
    gint channels = gdk_pixbuf_get_n_channels(result);

    for (gint y = 0; y < height; y++) {
        guchar *row = pixels + y * rowstride;
        for (gint x = 0; x < width; x++) {
            guchar *pixel = row + x * channels;
            pixel[0] = (guchar)((color >> 16) & 0xffU);
            pixel[1] = (guchar)((color >> 8) & 0xffU);
            pixel[2] = (guchar)(color & 0xffU);
        }
    }
    return result;
}

/* A tile icon is the same artwork in two colours, and the skin decides which
 * two. Re-tinting is a pass over six 62x62 images, so it is done when the skin
 * changes rather than kept as four pixbufs per tile for the life of the
 * process. */
static void refresh_room_icons(PanelUi *ui)
{
    const PanelSkinPalette *colors = palette(ui);

    for (guint i = 0; i < PANEL_ROOM_MAX; i++) {
        if (ui->room_icon_source[i] == NULL)
            continue;
        g_clear_object(&ui->room_icon_off[i]);
        g_clear_object(&ui->room_icon_on[i]);
        ui->room_icon_off[i] = tint_icon(ui->room_icon_source[i],
                                         colors->icon_off);
        ui->room_icon_on[i] = tint_icon(ui->room_icon_source[i],
                                        colors->icon_on);
        if (ui->room_icons[i] != NULL) {
            gtk_image_set_from_pixbuf(
                GTK_IMAGE(ui->room_icons[i]),
                ui->room_active[i] ? ui->room_icon_on[i]
                                   : ui->room_icon_off[i]);
        }
    }
}

static GtkWidget *new_room_icon(PanelUi *ui, guint index,
                                const gchar *resource_path)
{
    GError *error = NULL;
    const PanelSkinPalette *colors = palette(ui);
    GdkPixbuf *source = gdk_pixbuf_new_from_resource_at_scale(
        resource_path, 62, 62, TRUE, &error);

    if (source == NULL) {
        g_warning("Could not load room icon %s: %s", resource_path,
                  error != NULL ? error->message : "unknown error");
        g_clear_error(&error);
        return new_icon("image-missing-symbolic", 48);
    }

    ui->room_icon_source[index] = source;
    ui->room_icon_off[index] = tint_icon(source, colors->icon_off);
    ui->room_icon_on[index] = tint_icon(source, colors->icon_on);
    return gtk_image_new_from_pixbuf(ui->room_icon_off[index]);
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

static void room_clicked(GtkButton *button, gpointer user_data)
{
    emit_event(user_data, PANEL_UI_TOGGLE_ROOM, NULL,
               GPOINTER_TO_INT(g_object_get_data(G_OBJECT(button),
                                                 "room-index")));
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

static void room_adjust_clicked(GtkButton *button, gpointer user_data)
{
    PanelUi *ui = user_data;
    gint index = GPOINTER_TO_INT(
        g_object_get_data(G_OBJECT(button), "room-index"));
    const PanelRoom *room = &ui->config->layout.rooms[index];
    gchar *title = g_strdup_printf("%s SETTINGS", room->label);
    gint brightness = ui->room_brightness[index] >= 0
                          ? ui->room_brightness[index]
                          : 100;
    gint temperature = ui->room_temperature[index] >= 0
                           ? ui->room_temperature[index]
                           : (ui->room_temperature_min[index] +
                              ui->room_temperature_max[index]) / 2;

    ui->room_adjust_index = index;
    gtk_label_set_text(GTK_LABEL(ui->room_sheet_title), title);
    g_free(title);
    gtk_widget_set_visible(ui->room_brightness_box, room->brightness);
    gtk_widget_set_visible(ui->room_temperature_box,
                           room->color_temperature);

    ui->changing_room_adjustment = TRUE;
    gtk_range_set_range(GTK_RANGE(ui->room_temperature_scale),
                        ui->room_temperature_min[index],
                        ui->room_temperature_max[index]);
    gtk_range_set_value(GTK_RANGE(ui->room_brightness_scale), brightness);
    gtk_range_set_value(GTK_RANGE(ui->room_temperature_scale), temperature);
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

static gboolean room_card_draw(GtkWidget *widget, cairo_t *cr,
                               gpointer user_data)
{
    PanelUi *ui = user_data;
    guint index = (guint)GPOINTER_TO_INT(
        g_object_get_data(G_OBJECT(widget), "room-index"));
    GtkStateFlags flags = gtk_widget_get_state_flags(widget);
    gdouble width = gtk_widget_get_allocated_width(widget);
    gdouble height = gtk_widget_get_allocated_height(widget);
    const PanelSkinPalette *colors = palette(ui);
    gdouble mix = ui->room_active_mix[index];
    guint start = colors->card_start;
    guint end = colors->card_end;
    guint active_start = colors->card_active_start;
    guint active_end = colors->card_active_end;
    guint border = mix_color(colors->border, colors->border_active, mix);
    guint bottom = mix_color(colors->bottom, colors->bottom_active, mix);
    gdouble shadow_alpha = 0.42;

    if ((flags & GTK_STATE_FLAG_INSENSITIVE) != 0) {
        start = colors->card_off;
        end = colors->card_off;
        active_start = start;
        active_end = end;
        border = colors->border_off;
        bottom = colors->bottom_off;
        shadow_alpha = 0.0;
    } else if ((flags & GTK_STATE_FLAG_ACTIVE) != 0) {
        start = colors->card_down_start;
        end = colors->card_down_end;
        active_start = colors->card_down_active_start;
        active_end = colors->card_down_active_end;
        shadow_alpha = 0.3;
    } else if ((flags & GTK_STATE_FLAG_PRELIGHT) != 0) {
        start = colors->card_hover_start;
        end = colors->card_hover_end;
        active_start = colors->card_hover_active_start;
        active_end = colors->card_hover_active_end;
    }

    start = mix_color(start, active_start, mix);
    end = mix_color(end, active_end, mix);
    cairo_save(cr);
    set_source_color(cr, 0x000000U, shadow_alpha);
    rounded_rectangle(cr, 2.0, 7.0, width - 4.0, height - 8.0, 26.0);
    cairo_fill(cr);
    set_source_color(cr, bottom, 1.0);
    rounded_rectangle(cr, 1.0, 1.0, width - 2.0, height - 2.0, 27.0);
    cairo_fill(cr);
    paint_dithered_gradient(cr, 1.0, 1.0, width - 2.0, height - 6.0, 26.0,
                            start, end, ui->skin);
    set_source_color(cr, border, 1.0);
    cairo_set_line_width(cr, 1.0);
    rounded_rectangle(cr, 1.5, 1.5, width - 3.0, height - 7.0, 26.0);
    cairo_stroke(cr);
    cairo_restore(cr);
    return FALSE;
}

static gboolean room_card_animation_tick(GtkWidget *widget,
                                         GdkFrameClock *frame_clock,
                                         gpointer user_data)
{
    PanelUi *ui = user_data;
    guint index = (guint)GPOINTER_TO_INT(
        g_object_get_data(G_OBJECT(widget), "room-index"));
    gint64 elapsed = gdk_frame_clock_get_frame_time(frame_clock) -
                     ui->room_animation_start_us[index];
    gdouble progress = CLAMP(elapsed / 180000.0, 0.0, 1.0);
    gdouble eased = 1.0 - (1.0 - progress) * (1.0 - progress) *
                              (1.0 - progress);

    ui->room_active_mix[index] = ui->room_animation_from[index] +
        (ui->room_animation_to[index] - ui->room_animation_from[index]) * eased;
    gtk_widget_queue_draw(widget);
    if (progress >= 1.0) {
        ui->room_animation_tick[index] = 0;
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
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

    gtk_container_add(GTK_CONTAINER(revealer), sheet);
    ui->room_sheet = revealer;
    return revealer;
}

/* Icons follow the slot number, so a tile keeps its icon when the entity
 * behind it is changed in Home Assistant. */
static const gchar *slot_icon_resource(guint slot, guint fallback_index)
{
    static const gchar *icons[PANEL_ROOM_MAX] = {
        "/com/vahac/t560/icons/light-1.png",
        "/com/vahac/t560/icons/light-2.png",
        "/com/vahac/t560/icons/fan.png",
        "/com/vahac/t560/icons/ac.png",
        "/com/vahac/t560/icons/desk-lamp.png",
        "/com/vahac/t560/icons/desk-led-strip.png"
    };
    guint index = slot >= 1 && slot <= PANEL_ROOM_MAX ? slot - 1
                                                      : fallback_index;
    return icons[MIN(index, (guint)PANEL_ROOM_MAX - 1)];
}

/* A slot is generic now, so the kicker above a tile comes from the proxy
 * domain rather than from a hardcoded list of tile names. */
static const gchar *room_control_type(const PanelRoom *room)
{
    return g_str_has_prefix(room->entity, "light.") ? "LIGHTING" : "POWER";
}

static GtkWidget *room_page(PanelUi *ui)
{
    const PanelLayout *layout = &ui->config->layout;

    GtkWidget *page = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    gtk_widget_set_margin_start(page, 20);
    gtk_widget_set_margin_end(page, 20);
    gtk_widget_set_margin_top(page, 14);
    gtk_widget_set_margin_bottom(page, 10);
    add_css_class(page, "room-page");
    g_signal_connect(page, "draw", G_CALLBACK(room_page_draw), ui);

    GtkWidget *intro = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    GtkWidget *intro_text = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
    GtkWidget *kicker = new_label("AMBIENT CONTROL", "room-kicker");
    GtkWidget *help = new_label("Tap a device to switch it", "room-help");
    gchar *count_text = g_strdup_printf("%u CONTROLS", layout->room_count);
    GtkWidget *count = new_label(count_text, "room-count");
    g_free(count_text);
    gtk_label_set_ellipsize(GTK_LABEL(kicker), PANGO_ELLIPSIZE_NONE);
    gtk_widget_set_halign(kicker, GTK_ALIGN_START);
    gtk_widget_set_halign(help, GTK_ALIGN_START);
    gtk_widget_set_halign(count, GTK_ALIGN_END);
    gtk_widget_set_valign(count, GTK_ALIGN_CENTER);
    gtk_box_pack_start(GTK_BOX(intro_text), kicker, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(intro_text), help, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(intro), intro_text, TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(intro), count, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), intro, FALSE, FALSE, 0);

    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 16);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 20);
    gtk_widget_set_vexpand(grid, TRUE);
    for (guint i = 0; i < layout->room_count; i++) {
        const PanelRoom *room = &layout->rooms[i];
        GtkWidget *tile = gtk_overlay_new();
        GtkWidget *button = gtk_button_new();
        gtk_widget_set_hexpand(tile, TRUE);
        gtk_widget_set_vexpand(tile, TRUE);
        gtk_widget_set_hexpand(button, TRUE);
        gtk_widget_set_vexpand(button, TRUE);
        gtk_widget_set_size_request(button, 350, 250);
        add_css_class(button, "room-card");
        g_signal_connect(button, "draw", G_CALLBACK(room_card_draw), ui);

        GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
        add_css_class(box, "room-card-content");

        GtkWidget *header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
        GtkWidget *type = new_label(room_control_type(room), "room-type");
        gtk_label_set_ellipsize(GTK_LABEL(type), PANGO_ELLIPSIZE_NONE);
        gtk_widget_set_halign(type, GTK_ALIGN_START);
        gtk_widget_set_valign(type, GTK_ALIGN_CENTER);
        gtk_widget_set_size_request(header, -1, PANEL_ROOM_ADJUST_HEIGHT);
        gtk_box_pack_start(GTK_BOX(header), type, TRUE, TRUE, 0);

        GtkWidget *icon_shell = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
        GtkWidget *icon = new_room_icon(
            ui, i, slot_icon_resource(room->slot, i));
        gtk_widget_set_size_request(icon_shell, 88, 88);
        gtk_widget_set_halign(icon_shell, GTK_ALIGN_CENTER);
        gtk_widget_set_valign(icon_shell, GTK_ALIGN_CENTER);
        gtk_widget_set_halign(icon, GTK_ALIGN_CENTER);
        gtk_widget_set_valign(icon, GTK_ALIGN_CENTER);
        add_css_class(icon_shell, "room-icon-shell");
        add_css_class(icon, "room-icon");
        ui->room_icons[i] = icon;
        gtk_box_pack_start(GTK_BOX(icon_shell), icon, TRUE, TRUE, 0);

        GtkWidget *name = new_label(room->label, "room-name");
        ui->room_states[i] = new_label("--", "room-state");
        gtk_widget_set_halign(ui->room_states[i], GTK_ALIGN_CENTER);
        gtk_box_pack_start(GTK_BOX(box), header, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(box), icon_shell, TRUE, TRUE, 0);
        gtk_box_pack_start(GTK_BOX(box), name, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(box), ui->room_states[i], FALSE, FALSE, 0);
        gtk_container_add(GTK_CONTAINER(button), box);
        g_object_set_data(G_OBJECT(button), "room-index", GINT_TO_POINTER(i));
        g_signal_connect(button, "clicked", G_CALLBACK(room_clicked), ui);
        ui->room_buttons[i] = button;
        gtk_container_add(GTK_CONTAINER(tile), button);

        if (room->brightness || room->color_temperature) {
            GtkWidget *adjust = new_button("ADJUST", "room-adjust-button",
                                           92, PANEL_ROOM_ADJUST_HEIGHT);
            gtk_widget_set_halign(adjust, GTK_ALIGN_END);
            gtk_widget_set_valign(adjust, GTK_ALIGN_START);
            /* Matches the .room-card-content padding, so the button lands on
             * the header row instead of floating over the icon. */
            gtk_widget_set_margin_end(adjust, 20);
            gtk_widget_set_margin_top(adjust, 14);
            g_object_set_data(G_OBJECT(adjust), "room-index",
                              GINT_TO_POINTER(i));
            g_signal_connect(adjust, "clicked",
                             G_CALLBACK(room_adjust_clicked), ui);
            gtk_overlay_add_overlay(GTK_OVERLAY(tile), adjust);
            ui->room_adjust_buttons[i] = adjust;
        }
        gtk_grid_attach(GTK_GRID(grid), tile, i % 2, i / 2, 1, 1);
    }
    if (layout->room_count == 0) {
        GtkWidget *empty = new_label(
            "No room controls are configured for this panel.\n"
            "Add them to the panel in Home Assistant.", "room-help");
        gtk_label_set_line_wrap(GTK_LABEL(empty), TRUE);
        gtk_widget_set_valign(empty, GTK_ALIGN_CENTER);
        gtk_grid_attach(GTK_GRID(grid), empty, 0, 0, 2, 1);
    }
    gtk_box_pack_start(GTK_BOX(page), grid, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(page), navigation(ui), FALSE, FALSE, 4);
    return page;
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
    for (guint i = 0; i < PANEL_ROOM_MAX; i++) {
        ui->room_brightness[i] = -1;
        ui->room_temperature[i] = -1;
        ui->room_temperature_min[i] = 2000;
        ui->room_temperature_max[i] = 6500;
    }
    return ui;
}

void panel_ui_free(PanelUi *ui)
{
    if (ui->brightness_debounce_source != 0)
        g_source_remove(ui->brightness_debounce_source);
    if (ui->temperature_debounce_source != 0)
        g_source_remove(ui->temperature_debounce_source);
    for (guint i = 0; i < PANEL_ROOM_MAX; i++) {
        if (ui->room_animation_tick[i] != 0 &&
            ui->room_buttons[i] != NULL) {
            gtk_widget_remove_tick_callback(ui->room_buttons[i],
                                            ui->room_animation_tick[i]);
        }
    }
    for (guint i = 0; i < PANEL_ROOM_MAX; i++) {
        g_clear_object(&ui->room_icon_source[i]);
        g_clear_object(&ui->room_icon_off[i]);
        g_clear_object(&ui->room_icon_on[i]);
    }
    if (ui->deck_animation_source != 0)
        g_source_remove(ui->deck_animation_source);
    g_clear_object(&ui->deck_art);
    g_ptr_array_unref(ui->navigation_buttons);
    g_free(ui);
}

/* The header indicators are drawn with Cairo so that they do not depend on
 * the icon theme installed on the tablet and can be tinted per state. */
#define PANEL_PI 3.14159265358979323846
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
        ".room-card{background:transparent;background-image:none;border:0;border-radius:27px;box-shadow:none;padding:0;transition:180ms ease-out}"
        ".room-card:hover{background:transparent;background-image:none;border:0;box-shadow:none}"
        ".room-card:active{background:transparent;background-image:none;border:0;box-shadow:none}"
        ".room-card.active{background:transparent;background-image:none;border:0;box-shadow:none;color:#78f1e9}"
        ".room-card:disabled{background:transparent;background-image:none;border:0;box-shadow:none;color:#52657c}"
        ".room-card-content{padding:14px 20px 13px 20px}"
        ".room-type{font-size:12px;font-weight:700;letter-spacing:1px;color:#7189a7}"
        ".room-icon-shell{background-image:linear-gradient(to bottom,#203550,#0d1828);border:1px solid #3c5574;border-bottom:4px solid #07101a;border-radius:44px;box-shadow:0 7px 15px rgba(0,0,0,.4);transition:180ms ease-out}"
        ".room-icon{color:#9ab2cf;-gtk-icon-shadow:0 2px 3px rgba(0,0,0,.35)}"
        ".room-card.active .room-icon-shell{background-image:linear-gradient(to bottom,#65eee4,#2bc3ce);border-color:#8ff8f1;border-bottom-color:#147680;box-shadow:0 9px 22px rgba(45,208,205,.32)}"
        ".room-card.active .room-icon{color:#062125;-gtk-icon-shadow:none}"
        ".room-name{font-size:23px;font-weight:700;color:#f1f6fd}"
        ".room-state{font-size:12px;font-weight:700;color:#8fa9c7;background:#0a121d;border:1px solid #263951;border-radius:14px;padding:5px 12px;transition:180ms ease-out}"
        ".room-card.active .room-state{color:#062125;background:#5ce4dc;border-color:#8cf6ef}"
        ".room-card:disabled .room-icon,.room-card:disabled .room-name,.room-card:disabled .room-type{color:#52657c}";
    static const gchar room_sheet_css[] =
        ".room-adjust-button{font-size:10px;font-weight:700;color:#63e5dd;background:#132c39;border:1px solid #34757b;border-radius:15px;box-shadow:0 4px 10px rgba(0,0,0,.3);padding:0}"
        ".room-adjust-button:hover{background:#173a46;border-color:#56dcd4}"
        ".room-adjust-button:active{background:#24515a;color:#efffff}"
        ".room-sheet{background:transparent;background-image:none;border:1px solid #3a526e;border-bottom:5px solid #050a11;border-radius:28px;padding:22px 28px;box-shadow:0 0 34px rgba(0,0,0,.62)}"
        ".room-sheet-title{font-size:25px;font-weight:700;color:#f5f9ff}"
        ".room-sheet-subtitle{font-size:14px;color:#7f98b6}"
        ".room-sheet-close{font-size:12px;font-weight:700;color:#6fe7df;background:#122a37;border-color:#337078;border-radius:16px;box-shadow:none}"
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

void panel_ui_set_room(PanelUi *ui, guint index, gboolean active,
                       gint brightness_percent, gint color_temp_kelvin,
                       gint min_color_temp_kelvin,
                       gint max_color_temp_kelvin)
{
    g_return_if_fail(index < PANEL_ROOM_MAX);
    if (brightness_percent >= 0)
        ui->room_brightness[index] = CLAMP(brightness_percent, 1, 100);
    if (min_color_temp_kelvin > 0 && max_color_temp_kelvin > 0 &&
        min_color_temp_kelvin < max_color_temp_kelvin) {
        ui->room_temperature_min[index] = min_color_temp_kelvin;
        ui->room_temperature_max[index] = max_color_temp_kelvin;
    }
    if (color_temp_kelvin > 0) {
        ui->room_temperature[index] = CLAMP(
            color_temp_kelvin, ui->room_temperature_min[index],
            ui->room_temperature_max[index]);
    }
    gtk_label_set_text(GTK_LABEL(ui->room_states[index]), active ? "ON" : "OFF");
    if (ui->room_icon_off[index] != NULL &&
        ui->room_icon_on[index] != NULL) {
        gtk_image_set_from_pixbuf(
            GTK_IMAGE(ui->room_icons[index]),
            active ? ui->room_icon_on[index] : ui->room_icon_off[index]);
    }
    if (ui->room_active[index] != active) {
        ui->room_active[index] = active;
        ui->room_animation_from[index] = ui->room_active_mix[index];
        ui->room_animation_to[index] = active ? 1.0 : 0.0;
        GdkFrameClock *frame_clock = gtk_widget_get_frame_clock(
            ui->room_buttons[index]);
        ui->room_animation_start_us[index] = frame_clock != NULL
            ? gdk_frame_clock_get_frame_time(frame_clock)
            : g_get_monotonic_time();
        if (ui->room_animation_tick[index] == 0) {
            ui->room_animation_tick[index] = gtk_widget_add_tick_callback(
                ui->room_buttons[index], room_card_animation_tick, ui, NULL);
        }
    }
    toggle_css_class(ui->room_buttons[index], "active", active);

    if (ui->room_adjust_index == (gint)index) {
        ui->changing_room_adjustment = TRUE;
        if (ui->brightness_debounce_source == 0 &&
            ui->room_brightness[index] >= 0) {
            gtk_range_set_value(GTK_RANGE(ui->room_brightness_scale),
                                ui->room_brightness[index]);
        }
        gtk_range_set_range(GTK_RANGE(ui->room_temperature_scale),
                            ui->room_temperature_min[index],
                            ui->room_temperature_max[index]);
        if (ui->temperature_debounce_source == 0 &&
            ui->room_temperature[index] >= 0) {
            gtk_range_set_value(GTK_RANGE(ui->room_temperature_scale),
                                ui->room_temperature[index]);
        }
        ui->changing_room_adjustment = FALSE;
    }
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
