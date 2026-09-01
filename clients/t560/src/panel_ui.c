#include "panel_ui.h"

/* The ADJUST button sits in the top-right corner of a room card and the
 * header row reserves its height, so both must use the same value. */
#define PANEL_ROOM_ADJUST_HEIGHT 44

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
    GtkWidget *album_art;
    GtkWidget *track_title;
    GtkWidget *artist;
    GtkWidget *progress;
    GtkWidget *position;
    GtkWidget *play;
    GtkWidget *play_icon;
    GtkWidget *shuffle;
    GtkWidget *repeat;
    GtkWidget *repeat_label;
    GtkWidget *volume;
    GtkWidget *queue_list;
    GtkWidget *playlist_list;
    gboolean changing_list_selection;
    GPtrArray *navigation_buttons;
    GtkWidget *room_buttons[PANEL_ROOM_COUNT];
    GtkWidget *room_adjust_buttons[PANEL_ROOM_COUNT];
    GtkWidget *room_icons[PANEL_ROOM_COUNT];
    GtkWidget *room_states[PANEL_ROOM_COUNT];
    gboolean room_active[PANEL_ROOM_COUNT];
    gdouble room_active_mix[PANEL_ROOM_COUNT];
    gdouble room_animation_from[PANEL_ROOM_COUNT];
    gdouble room_animation_to[PANEL_ROOM_COUNT];
    gint64 room_animation_start_us[PANEL_ROOM_COUNT];
    guint room_animation_tick[PANEL_ROOM_COUNT];
    GdkPixbuf *room_icon_off[PANEL_ROOM_COUNT];
    GdkPixbuf *room_icon_on[PANEL_ROOM_COUNT];
    GtkWidget *room_sheet;
    GtkWidget *room_sheet_title;
    GtkWidget *room_brightness_box;
    GtkWidget *room_brightness_scale;
    GtkWidget *room_brightness_value;
    GtkWidget *room_temperature_box;
    GtkWidget *room_temperature_scale;
    GtkWidget *room_temperature_value;
    gint room_adjust_index;
    gint room_brightness[PANEL_ROOM_COUNT];
    gint room_temperature[PANEL_ROOM_COUNT];
    gint room_temperature_min[PANEL_ROOM_COUNT];
    gint room_temperature_max[PANEL_ROOM_COUNT];
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

static GdkPixbuf *tint_icon(GdkPixbuf *source, guchar red, guchar green,
                            guchar blue)
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
            pixel[0] = red;
            pixel[1] = green;
            pixel[2] = blue;
        }
    }
    return result;
}

static GtkWidget *new_room_icon(PanelUi *ui, guint index,
                                const gchar *resource_path)
{
    GError *error = NULL;
    GdkPixbuf *source = gdk_pixbuf_new_from_resource_at_scale(
        resource_path, 62, 62, TRUE, &error);

    if (source == NULL) {
        g_warning("Could not load room icon %s: %s", resource_path,
                  error != NULL ? error->message : "unknown error");
        g_clear_error(&error);
        return new_icon("image-missing-symbolic", 48);
    }

    ui->room_icon_off[index] = tint_icon(source, 0x9a, 0xb2, 0xcf);
    ui->room_icon_on[index] = tint_icon(source, 0x06, 0x21, 0x25);
    g_object_unref(source);
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
    gchar *title = g_strdup_printf("%s SETTINGS",
                                   ui->config->room_labels[index]);
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
    gtk_widget_set_visible(ui->room_brightness_box,
                           ui->config->room_brightness[index]);
    gtk_widget_set_visible(
        ui->room_temperature_box,
        ui->config->room_color_temperature[index]);

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
    GtkWidget *page = gtk_box_new(GTK_ORIENTATION_VERTICAL, 11);
    gtk_widget_set_margin_start(page, 24);
    gtk_widget_set_margin_end(page, 24);
    gtk_widget_set_margin_top(page, 14);
    gtk_widget_set_margin_bottom(page, 10);
    add_css_class(page, "player-page");

    ui->album_art = gtk_image_new_from_icon_name(
        "audio-x-generic-symbolic", GTK_ICON_SIZE_DIALOG);
    gtk_widget_set_size_request(ui->album_art, 510, 510);
    GtkWidget *artwork = gtk_frame_new(NULL);
    gtk_frame_set_shadow_type(GTK_FRAME(artwork), GTK_SHADOW_NONE);
    gtk_widget_set_halign(artwork, GTK_ALIGN_CENTER);
    add_css_class(artwork, "artwork-card");
    gtk_container_add(GTK_CONTAINER(artwork), ui->album_art);

    GtkWidget *track_details = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
    add_css_class(track_details, "track-details");
    ui->track_title = new_label("Nothing playing", "track-title");
    ui->artist = new_label("", "artist");
    gtk_box_pack_start(GTK_BOX(track_details), ui->track_title,
                       FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(track_details), ui->artist,
                       FALSE, FALSE, 0);

    GtkWidget *timeline = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
    gtk_widget_set_margin_start(timeline, 34);
    gtk_widget_set_margin_end(timeline, 34);
    ui->progress = gtk_progress_bar_new();
    gtk_widget_set_size_request(ui->progress, -1, 12);
    ui->position = new_label("0:00  /  0:00", "position");
    gtk_box_pack_start(GTK_BOX(timeline), ui->progress, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(timeline), ui->position, FALSE, FALSE, 0);

    gtk_box_pack_start(GTK_BOX(page), artwork, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(page), track_details, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), timeline, FALSE, FALSE, 0);

    GtkWidget *modes = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_widget_set_halign(modes, GTK_ALIGN_CENTER);
    ui->shuffle = new_icon_button(
        "media-playlist-shuffle-symbolic", "Shuffle", "mode-button",
        190, 58, 23, GTK_ORIENTATION_HORIZONTAL, NULL, NULL);
    ui->repeat = new_icon_button(
        "media-playlist-repeat-symbolic", "Repeat off", "mode-button",
        190, 58, 23, GTK_ORIENTATION_HORIZONTAL, NULL, &ui->repeat_label);
    g_signal_connect(ui->shuffle, "clicked", G_CALLBACK(shuffle_clicked), ui);
    g_signal_connect(ui->repeat, "clicked", G_CALLBACK(repeat_clicked), ui);
    gtk_box_pack_start(GTK_BOX(modes), ui->shuffle, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(modes), ui->repeat, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(page), modes, FALSE, FALSE, 0);

    GtkWidget *controls = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 18);
    gtk_widget_set_halign(controls, GTK_ALIGN_CENTER);
    GtkWidget *previous = new_icon_button(
        "media-skip-backward-symbolic", NULL, "transport-button",
        108, 86, 38, GTK_ORIENTATION_VERTICAL, NULL, NULL);
    ui->play = new_icon_button(
        "media-playback-start-symbolic", NULL, "play-button", 120, 104,
        48, GTK_ORIENTATION_VERTICAL, &ui->play_icon, NULL);
    GtkWidget *next = new_icon_button(
        "media-skip-forward-symbolic", NULL, "transport-button",
        108, 86, 38, GTK_ORIENTATION_VERTICAL, NULL, NULL);
    gtk_widget_set_tooltip_text(previous, "Previous track");
    gtk_widget_set_tooltip_text(ui->play, "Play or pause");
    gtk_widget_set_tooltip_text(next, "Next track");
    g_object_set_data(G_OBJECT(previous), "service", "media_previous_track");
    g_object_set_data(G_OBJECT(ui->play), "service", "media_play_pause");
    g_object_set_data(G_OBJECT(next), "service", "media_next_track");
    g_signal_connect(previous, "clicked", G_CALLBACK(player_clicked), ui);
    g_signal_connect(ui->play, "clicked", G_CALLBACK(player_clicked), ui);
    g_signal_connect(next, "clicked", G_CALLBACK(player_clicked), ui);
    gtk_box_pack_start(GTK_BOX(controls), previous, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(controls), ui->play, FALSE, FALSE, 0);
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
    ui->volume = new_label("--", "volume");
    gtk_box_pack_start(GTK_BOX(volume_readout), ui->volume,
                       FALSE, FALSE, 0);
    GtkWidget *up = new_icon_button(
        "audio-volume-high-symbolic", NULL, "volume-button", 86, 62, 28,
        GTK_ORIENTATION_VERTICAL, NULL, NULL);
    gtk_widget_set_tooltip_text(down, "Volume down");
    gtk_widget_set_tooltip_text(up, "Volume up");
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

/* The tablet framebuffer is RGB565. Subtle CSS gradients therefore collapse
 * into wide color bands even though they look smooth in a 24-bit screenshot.
 * Static irregular noise breaks up those bands without the diagonal artifacts
 * of an ordered Bayer matrix and without adding animation work. */
static cairo_pattern_t *room_dither_pattern(void)
{
    static cairo_pattern_t *pattern;
    const guint size = 64;

    if (pattern == NULL) {
        cairo_surface_t *surface = cairo_image_surface_create(
            CAIRO_FORMAT_ARGB32, size, size);
        guint32 *pixels = (guint32 *)cairo_image_surface_get_data(surface);
        gint stride = cairo_image_surface_get_stride(surface) /
                      (gint)sizeof(*pixels);

        for (guint y = 0; y < size; y++) {
            for (guint x = 0; x < size; x++) {
                guint32 noise = (x + 1U) * 0x9e3779b1U ^
                                (y + 1U) * 0x85ebca6bU;
                guint8 alpha;
                guint8 red;
                guint8 green;
                guint8 blue;

                noise ^= noise >> 16;
                noise *= 0x7feb352dU;
                noise ^= noise >> 15;
                noise *= 0x846ca68bU;
                noise ^= noise >> 16;
                if ((noise & 0xffU) < 128U) {
                    alpha = (guint8)(2U + ((noise >> 8) & 0x07U));
                    red = (guint8)(0x8fU * alpha / 255U);
                    green = (guint8)(0xa9U * alpha / 255U);
                    blue = (guint8)(0xc7U * alpha / 255U);
                } else {
                    alpha = (guint8)(1U + ((noise >> 11) % 6U));
                    red = 0;
                    green = (guint8)(0x08U * alpha / 255U);
                    blue = (guint8)(0x14U * alpha / 255U);
                }
                pixels[y * stride + x] = ((guint32)alpha << 24) |
                                         ((guint32)red << 16) |
                                         ((guint32)green << 8) | blue;
            }
        }
        cairo_surface_mark_dirty(surface);
        pattern = cairo_pattern_create_for_surface(surface);
        cairo_pattern_set_extend(pattern, CAIRO_EXTEND_REPEAT);
        cairo_pattern_set_filter(pattern, CAIRO_FILTER_NEAREST);
        cairo_surface_destroy(surface);
    }
    return pattern;
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
                                    gdouble radius, guint start, guint end)
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
    cairo_set_source(cr, room_dither_pattern());
    cairo_paint(cr);
    cairo_restore(cr);
    cairo_pattern_destroy(gradient);
}

static gboolean room_page_draw(GtkWidget *widget, cairo_t *cr,
                               gpointer user_data)
{
    (void)user_data;
    paint_dithered_gradient(
        cr, 0.0, 0.0, gtk_widget_get_allocated_width(widget),
        gtk_widget_get_allocated_height(widget), 0.0, 0x102039U, 0x050a12U);
    return FALSE;
}

static gboolean room_sheet_draw(GtkWidget *widget, cairo_t *cr,
                                gpointer user_data)
{
    (void)user_data;
    gdouble width = gtk_widget_get_allocated_width(widget);
    gdouble height = gtk_widget_get_allocated_height(widget);

    paint_dithered_gradient(cr, 1.0, 1.0, width - 2.0, height - 6.0, 27.0,
                            0x1d3550U, 0x091521U);
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
    gdouble mix = ui->room_active_mix[index];
    guint start = 0x213856U;
    guint end = 0x0b1828U;
    guint active_start = 0x1a595bU;
    guint active_end = 0x0a252bU;
    guint border = mix_color(0x3b5678U, 0x42d8cfU, mix);
    guint bottom = mix_color(0x050910U, 0x071617U, mix);
    gdouble shadow_alpha = 0.42;

    if ((flags & GTK_STATE_FLAG_INSENSITIVE) != 0) {
        start = 0x0c1420U;
        end = 0x0c1420U;
        active_start = start;
        active_end = end;
        border = 0x1c293bU;
        bottom = 0x060a10U;
        shadow_alpha = 0.0;
    } else if ((flags & GTK_STATE_FLAG_ACTIVE) != 0) {
        start = 0x0c1828U;
        end = 0x1b3550U;
        active_start = 0x0d3034U;
        active_end = 0x176066U;
        shadow_alpha = 0.3;
    } else if ((flags & GTK_STATE_FLAG_PRELIGHT) != 0) {
        start = 0x29466aU;
        end = 0x102138U;
        active_start = 0x247174U;
        active_end = 0x0d3037U;
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
                            start, end);
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

static GtkWidget *room_page(PanelUi *ui)
{
    static const gchar *icon_resources[PANEL_ROOM_COUNT] = {
        "/com/vahac/t560/icons/light-1.png",
        "/com/vahac/t560/icons/light-2.png",
        "/com/vahac/t560/icons/fan.png",
        "/com/vahac/t560/icons/ac.png",
        "/com/vahac/t560/icons/desk-lamp.png",
        "/com/vahac/t560/icons/desk-led-strip.png"
    };
    static const gchar *control_types[PANEL_ROOM_COUNT] = {
        "LIGHTING", "LIGHTING", "AIRFLOW", "CLIMATE", "TASK LIGHT",
        "ACCENT LIGHT"
    };

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
    gchar *count_text = g_strdup_printf("%u CONTROLS", PANEL_ROOM_COUNT);
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
    for (guint i = 0; i < PANEL_ROOM_COUNT; i++) {
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
        GtkWidget *type = new_label(control_types[i], "room-type");
        gtk_label_set_ellipsize(GTK_LABEL(type), PANGO_ELLIPSIZE_NONE);
        gtk_widget_set_halign(type, GTK_ALIGN_START);
        gtk_widget_set_valign(type, GTK_ALIGN_CENTER);
        gtk_widget_set_size_request(header, -1, PANEL_ROOM_ADJUST_HEIGHT);
        gtk_box_pack_start(GTK_BOX(header), type, TRUE, TRUE, 0);

        GtkWidget *icon_shell = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
        GtkWidget *icon = new_room_icon(ui, i, icon_resources[i]);
        gtk_widget_set_size_request(icon_shell, 88, 88);
        gtk_widget_set_halign(icon_shell, GTK_ALIGN_CENTER);
        gtk_widget_set_valign(icon_shell, GTK_ALIGN_CENTER);
        gtk_widget_set_halign(icon, GTK_ALIGN_CENTER);
        gtk_widget_set_valign(icon, GTK_ALIGN_CENTER);
        add_css_class(icon_shell, "room-icon-shell");
        add_css_class(icon, "room-icon");
        gtk_widget_set_opacity(
            icon, ui->config->room_entities[i] != NULL ? 1.0 : 0.35);
        ui->room_icons[i] = icon;
        gtk_box_pack_start(GTK_BOX(icon_shell), icon, TRUE, TRUE, 0);

        GtkWidget *name = new_label(ui->config->room_labels[i], "room-name");
        ui->room_states[i] = new_label(
            ui->config->room_entities[i] != NULL ? "--" : "NOT CONFIGURED",
            "room-state");
        gtk_widget_set_halign(ui->room_states[i], GTK_ALIGN_CENTER);
        gtk_box_pack_start(GTK_BOX(box), header, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(box), icon_shell, TRUE, TRUE, 0);
        gtk_box_pack_start(GTK_BOX(box), name, FALSE, FALSE, 0);
        gtk_box_pack_start(GTK_BOX(box), ui->room_states[i], FALSE, FALSE, 0);
        gtk_container_add(GTK_CONTAINER(button), box);
        g_object_set_data(G_OBJECT(button), "room-index", GINT_TO_POINTER(i));
        g_signal_connect(button, "clicked", G_CALLBACK(room_clicked), ui);
        gtk_widget_set_sensitive(button, ui->config->room_entities[i] != NULL);
        ui->room_buttons[i] = button;
        gtk_container_add(GTK_CONTAINER(tile), button);

        if (ui->config->room_brightness[i] ||
            ui->config->room_color_temperature[i]) {
            GtkWidget *adjust = new_button("ADJUST", "room-adjust-button",
                                           92, PANEL_ROOM_ADJUST_HEIGHT);
            gtk_widget_set_halign(adjust, GTK_ALIGN_END);
            gtk_widget_set_valign(adjust, GTK_ALIGN_START);
            /* Matches the .room-card-content padding, so the button lands on
             * the header row instead of floating over the icon. */
            gtk_widget_set_margin_end(adjust, 20);
            gtk_widget_set_margin_top(adjust, 14);
            gtk_widget_set_sensitive(
                adjust, ui->config->room_entities[i] != NULL);
            g_object_set_data(G_OBJECT(adjust), "room-index",
                              GINT_TO_POINTER(i));
            g_signal_connect(adjust, "clicked",
                             G_CALLBACK(room_adjust_clicked), ui);
            gtk_overlay_add_overlay(GTK_OVERLAY(tile), adjust);
            ui->room_adjust_buttons[i] = adjust;
        }
        gtk_grid_attach(GTK_GRID(grid), tile, i % 2, i / 2, 1, 1);
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
    for (guint i = 0; i < PANEL_ROOM_COUNT; i++) {
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
    for (guint i = 0; i < PANEL_ROOM_COUNT; i++) {
        if (ui->room_animation_tick[i] != 0 &&
            ui->room_buttons[i] != NULL) {
            gtk_widget_remove_tick_callback(ui->room_buttons[i],
                                            ui->room_animation_tick[i]);
        }
    }
    for (guint i = 0; i < PANEL_ROOM_COUNT; i++) {
        g_clear_object(&ui->room_icon_off[i]);
        g_clear_object(&ui->room_icon_on[i]);
    }
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
#define PANEL_COLOR_HEADER 0x0c1420U

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
        set_source_color(cr, PANEL_COLOR_HEADER, 1.0);
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
    gtk_stack_add_named(GTK_STACK(ui->stack), player_page(ui), "player");
    gtk_stack_add_named(GTK_STACK(ui->stack), list_page(ui, TRUE), "queue");
    gtk_stack_add_named(GTK_STACK(ui->stack), list_page(ui, FALSE), "playlists");
    gtk_stack_add_named(GTK_STACK(ui->stack), room_page(ui), "room");
    GtkWidget *content = gtk_overlay_new();
    gtk_container_add(GTK_CONTAINER(content), ui->stack);
    gtk_overlay_add_overlay(GTK_OVERLAY(content), room_adjust_sheet(ui));
    gtk_box_pack_start(GTK_BOX(outer), header, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(outer), content, TRUE, TRUE, 0);
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
        ".config-error{font-size:21px}";
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

    install_css(css);
    install_css(room_css);
    install_css(room_sheet_css);
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
    gtk_image_set_from_icon_name(
        GTK_IMAGE(ui->play_icon),
        playing ? "media-playback-pause-symbolic"
                : "media-playback-start-symbolic",
        GTK_ICON_SIZE_BUTTON);
    gtk_image_set_pixel_size(GTK_IMAGE(ui->play_icon), 48);
    gtk_label_set_text(GTK_LABEL(ui->track_title), title);
    gtk_label_set_text(GTK_LABEL(ui->artist), artist);
    gtk_progress_bar_set_fraction(
        GTK_PROGRESS_BAR(ui->progress),
        duration > 0.0 ? CLAMP(position / duration, 0.0, 1.0) : 0.0);

    gchar *position_text = format_time(position);
    gchar *duration_text = format_time(duration);
    gchar *timeline = g_strdup_printf("%s  /  %s", position_text, duration_text);
    gtk_label_set_text(GTK_LABEL(ui->position), timeline);
    g_free(position_text);
    g_free(duration_text);
    g_free(timeline);

    gchar *volume_text = g_strdup_printf("%.0f%%", volume * 100.0);
    gtk_label_set_text(GTK_LABEL(ui->volume), volume_text);
    g_free(volume_text);

    panel_ui_set_modes(ui, shuffle, repeat);
}

void panel_ui_set_modes(PanelUi *ui, gboolean shuffle, const gchar *repeat)
{
    toggle_css_class(ui->shuffle, "active", shuffle);
    const gchar *repeat_state = g_str_equal(repeat, "all") ? "all"
                                : g_str_equal(repeat, "one") ? "one"
                                                               : "off";
    gchar *repeat_text = g_strdup_printf("Repeat %s", repeat_state);
    gtk_label_set_text(GTK_LABEL(ui->repeat_label), repeat_text);
    toggle_css_class(ui->repeat, "active", !g_str_equal(repeat, "off"));
    g_free(repeat_text);
}

void panel_ui_set_album_art(PanelUi *ui, GdkPixbuf *pixbuf)
{
    gtk_image_set_from_pixbuf(GTK_IMAGE(ui->album_art), pixbuf);
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
    g_return_if_fail(index < PANEL_ROOM_COUNT);
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

void panel_ui_show_page(PanelUi *ui, const gchar *page, const gchar *title)
{
    gtk_stack_set_visible_child_name(GTK_STACK(ui->stack), page);
    gtk_label_set_text(GTK_LABEL(ui->page_title), title);
    for (guint i = 0; i < ui->navigation_buttons->len; i++) {
        GtkWidget *button = g_ptr_array_index(ui->navigation_buttons, i);
        const gchar *button_page = g_object_get_data(
            G_OBJECT(button), "page");
        toggle_css_class(button, "active", g_str_equal(button_page, page));
    }
}
