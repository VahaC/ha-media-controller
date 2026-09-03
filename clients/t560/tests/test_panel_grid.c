#include "test_panel_grid.h"

#include "panel_grid.h"

#include <glib.h>

static PanelGrid *parse(const gchar *json, guint *dropped, gchar **failure)
{
    return panel_grid_parse(json, -1, dropped, failure);
}

static const PanelCard *card_at(const PanelGrid *grid, guint index)
{
    g_assert_cmpuint(index, <, grid->cards->len);
    return g_ptr_array_index(grid->cards, index);
}

static void test_full_layout(void)
{
    gchar *failure = NULL;
    guint dropped = 0;
    PanelGrid *grid = parse(
        "{\"v\":1,\"cols\":10,\"rows\":14,\"cards\":["
        "{\"x\":0,\"y\":0,\"w\":2,\"h\":2,\"rid\":\"a3f1c92d\","
        "\"icon\":\"lightbulb\",\"color\":\"#4DD0E1\"},"
        "{\"x\":2,\"y\":0,\"w\":1,\"h\":1,\"rid\":\"b7e4180a\"}]}",
        &dropped, &failure);

    g_assert_nonnull(grid);
    g_assert_null(failure);
    g_assert_cmpuint(dropped, ==, 0);
    g_assert_cmpuint(grid->columns, ==, 10);
    g_assert_cmpuint(grid->rows, ==, 14);
    g_assert_cmpuint(grid->cards->len, ==, 2);

    const PanelCard *first = card_at(grid, 0);
    g_assert_cmpstr(first->rid, ==, "a3f1c92d");
    g_assert_cmpuint(first->width, ==, 2);
    g_assert_cmpstr(first->icon, ==, "lightbulb");
    /* Stored lower case, so that two spellings of one colour compare equal. */
    g_assert_cmpstr(first->color, ==, "#4dd0e1");

    const PanelCard *second = card_at(grid, 1);
    g_assert_null(second->icon);
    g_assert_null(second->color);

    panel_grid_free(grid);
}

/* The card type is not stored: it follows from the domain of the registry
 * element the rid names, so a round trip must not invent one. */
static void test_round_trip(void)
{
    gchar *failure = NULL;
    PanelGrid *grid = parse(
        "{\"v\":1,\"cols\":10,\"rows\":14,\"cards\":["
        "{\"x\":3,\"y\":4,\"w\":2,\"h\":3,\"rid\":\"a3f1c92d\","
        "\"color\":\"#4dd0e1\"}]}",
        NULL, &failure);
    g_assert_nonnull(grid);

    gchar *json = panel_grid_to_json(grid);
    g_assert_nonnull(g_strstr_len(json, -1, "\"rid\":\"a3f1c92d\""));
    g_assert_null(g_strstr_len(json, -1, "\"type\""));
    g_assert_null(g_strstr_len(json, -1, "\"icon\""));

    guint dropped = 0;
    PanelGrid *again = parse(json, &dropped, &failure);
    g_assert_nonnull(again);
    g_assert_cmpuint(dropped, ==, 0);
    g_assert_cmpuint(again->cards->len, ==, 1);
    g_assert_cmpuint(card_at(again, 0)->x, ==, 3);
    g_assert_cmpuint(card_at(again, 0)->height, ==, 3);
    g_assert_cmpstr(card_at(again, 0)->color, ==, "#4dd0e1");

    g_free(json);
    panel_grid_free(again);
    panel_grid_free(grid);
}

/* A card that does not fit is dropped rather than moved: where it should go
 * instead is a question only the person editing the grid can answer. */
static void test_cards_outside_the_grid_are_dropped(void)
{
    const gchar *cards[] = {
        "{\"x\":10,\"y\":0,\"w\":1,\"h\":1,\"rid\":\"a1\"}",
        "{\"x\":0,\"y\":14,\"w\":1,\"h\":1,\"rid\":\"a2\"}",
        "{\"x\":9,\"y\":0,\"w\":2,\"h\":1,\"rid\":\"a3\"}",
        "{\"x\":0,\"y\":13,\"w\":1,\"h\":2,\"rid\":\"a4\"}",
        "{\"x\":0,\"y\":0,\"w\":0,\"h\":2,\"rid\":\"a5\"}",
        "{\"x\":0,\"y\":0,\"w\":2,\"h\":0,\"rid\":\"a6\"}",
        "{\"x\":-1,\"y\":0,\"w\":2,\"h\":2,\"rid\":\"a7\"}"
    };

    for (guint i = 0; i < G_N_ELEMENTS(cards); i++) {
        gchar *failure = NULL;
        guint dropped = 0;
        gchar *json = g_strdup_printf(
            "{\"v\":1,\"cols\":10,\"rows\":14,\"cards\":[%s]}", cards[i]);
        PanelGrid *grid = parse(json, &dropped, &failure);

        g_assert_nonnull(grid);
        g_assert_cmpuint(grid->cards->len, ==, 0);
        g_assert_cmpuint(dropped, ==, 1);

        panel_grid_free(grid);
        g_free(json);
    }
}

/* Two cards on the same cells cannot both be drawn. The first one placed
 * keeps its position and the second is dropped, so reading a file twice gives
 * the same grid both times. */
static void test_overlapping_cards_are_dropped(void)
{
    gchar *failure = NULL;
    guint dropped = 0;
    PanelGrid *grid = parse(
        "{\"v\":1,\"cols\":10,\"rows\":14,\"cards\":["
        "{\"x\":0,\"y\":0,\"w\":3,\"h\":3,\"rid\":\"keep\"},"
        "{\"x\":2,\"y\":2,\"w\":2,\"h\":2,\"rid\":\"corner\"},"
        "{\"x\":0,\"y\":0,\"w\":1,\"h\":1,\"rid\":\"inside\"},"
        "{\"x\":3,\"y\":0,\"w\":2,\"h\":2,\"rid\":\"clear\"}]}",
        &dropped, &failure);

    g_assert_nonnull(grid);
    g_assert_cmpuint(grid->cards->len, ==, 2);
    g_assert_cmpuint(dropped, ==, 2);
    g_assert_cmpstr(card_at(grid, 0)->rid, ==, "keep");
    g_assert_cmpstr(card_at(grid, 1)->rid, ==, "clear");

    panel_grid_free(grid);
}

/* Two cards that only touch do not overlap. Without this the grid would
 * refuse every layout that is actually packed. */
static void test_touching_cards_are_kept(void)
{
    guint dropped = 0;
    gchar *failure = NULL;
    PanelGrid *grid = parse(
        "{\"v\":1,\"cols\":10,\"rows\":14,\"cards\":["
        "{\"x\":0,\"y\":0,\"w\":2,\"h\":2,\"rid\":\"a\"},"
        "{\"x\":2,\"y\":0,\"w\":2,\"h\":2,\"rid\":\"b\"},"
        "{\"x\":0,\"y\":2,\"w\":2,\"h\":2,\"rid\":\"c\"}]}",
        &dropped, &failure);

    g_assert_nonnull(grid);
    g_assert_cmpuint(grid->cards->len, ==, 3);
    g_assert_cmpuint(dropped, ==, 0);

    panel_grid_free(grid);
}

/* A rid the registry does not carry is kept on purpose. The registry is a
 * live payload and is empty while Home Assistant is unreachable; dropping
 * cards against it would let one failed poll erase a layout that the next
 * save then writes back. */
static void test_unknown_rid_is_kept(void)
{
    PanelLayout layout = {0};
    guint dropped = 0;
    gchar *failure = NULL;
    PanelGrid *grid = parse(
        "{\"v\":1,\"cols\":10,\"rows\":14,\"cards\":["
        "{\"x\":0,\"y\":0,\"w\":2,\"h\":2,\"rid\":\"deadbeef\"}]}",
        &dropped, &failure);

    g_assert_nonnull(grid);
    g_assert_cmpuint(grid->cards->len, ==, 1);
    g_assert_cmpuint(dropped, ==, 0);
    /* Nothing in an empty registry answers to it, and the card survives. */
    g_assert_null(panel_layout_find_entity(&layout, "deadbeef"));

    panel_grid_free(grid);
    panel_layout_clear(&layout);
}

/* A card with no rid could never be placed: the rid is what a card is keyed
 * on, so there would be nothing to draw. */
static void test_card_without_rid_is_dropped(void)
{
    guint dropped = 0;
    gchar *failure = NULL;
    PanelGrid *grid = parse(
        "{\"v\":1,\"cards\":["
        "{\"x\":0,\"y\":0,\"w\":2,\"h\":2},"
        "{\"x\":2,\"y\":0,\"w\":2,\"h\":2,\"rid\":\"\"},"
        "{\"x\":4,\"y\":0,\"w\":2,\"h\":2,\"rid\":\"ok\"},"
        "\"not an object\"]}",
        &dropped, &failure);

    g_assert_nonnull(grid);
    g_assert_cmpuint(grid->cards->len, ==, 1);
    g_assert_cmpuint(dropped, ==, 3);
    g_assert_cmpstr(card_at(grid, 0)->rid, ==, "ok");

    panel_grid_free(grid);
}

/* A card with no geometry is dropped rather than defaulted: a card silently
 * placed at 0,0 would land on top of whatever is really there. */
static void test_card_without_geometry_is_dropped(void)
{
    guint dropped = 0;
    gchar *failure = NULL;
    PanelGrid *grid = parse(
        "{\"v\":1,\"cards\":[{\"rid\":\"a\"},"
        "{\"x\":0,\"y\":0,\"w\":2,\"rid\":\"b\"},"
        "{\"x\":0,\"y\":\"two\",\"w\":2,\"h\":2,\"rid\":\"c\"}]}",
        &dropped, &failure);

    g_assert_nonnull(grid);
    g_assert_cmpuint(grid->cards->len, ==, 0);
    g_assert_cmpuint(dropped, ==, 3);

    panel_grid_free(grid);
}

static void test_broken_json_is_reported(void)
{
    const gchar *documents[] = {
        "",
        "   ",
        "not json",
        "[]",
        "{\"cards\":[]}",
        "{\"v\":2,\"cards\":[]}",
        "{\"v\":\"1\",\"cards\":[]}"
    };

    for (guint i = 0; i < G_N_ELEMENTS(documents); i++) {
        gchar *failure = NULL;
        guint dropped = 0;
        PanelGrid *grid = parse(documents[i], &dropped, &failure);

        g_assert_null(grid);
        g_assert_nonnull(failure);
        g_free(failure);
    }
}

/* An empty file is a broken file, not an empty grid. The two are told apart
 * so that a truncated write falls back to the default arrangement instead of
 * leaving a blank room page nobody can explain. */
static void test_empty_card_list_is_a_valid_grid(void)
{
    gchar *failure = NULL;
    PanelGrid *grid = parse("{\"v\":1,\"cols\":10,\"rows\":14,\"cards\":[]}",
                            NULL, &failure);

    g_assert_nonnull(grid);
    g_assert_null(failure);
    g_assert_cmpuint(grid->cards->len, ==, 0);

    panel_grid_free(grid);
}

/* A file naming another grid size is honoured rather than reshaped: the cell
 * size follows from the work area, so nothing about the renderer assumes ten
 * by fourteen. */
static void test_other_grid_sizes_are_honoured(void)
{
    gchar *failure = NULL;
    PanelGrid *grid = parse(
        "{\"v\":1,\"cols\":6,\"rows\":8,\"cards\":["
        "{\"x\":5,\"y\":7,\"w\":1,\"h\":1,\"rid\":\"a\"},"
        "{\"x\":6,\"y\":0,\"w\":1,\"h\":1,\"rid\":\"b\"}]}",
        NULL, &failure);

    g_assert_nonnull(grid);
    g_assert_cmpuint(grid->columns, ==, 6);
    g_assert_cmpuint(grid->rows, ==, 8);
    /* The second card is outside a six-column grid even though it would fit
     * a ten-column one. */
    g_assert_cmpuint(grid->cards->len, ==, 1);

    panel_grid_free(grid);
}

static PanelLayout registry_of(guint count)
{
    PanelLayout layout = {0};

    layout.entities = g_ptr_array_new_with_free_func(
        (GDestroyNotify)panel_entity_free);
    for (guint i = 0; i < count; i++) {
        PanelEntity *entity = g_new0(PanelEntity, 1);
        entity->rid = g_strdup_printf("%08x", i);
        entity->entity = g_strdup_printf("light.entity_%u", i);
        entity->name = g_strdup("Entity");
        entity->domain = g_strdup("light");
        g_ptr_array_add(layout.entities, entity);
    }
    return layout;
}

/* Nobody has opened the editor yet, so every registry element is placed for
 * them: two cells square, in registry order, left to right and top to bottom.
 * A panel is useful the moment it is configured in Home Assistant. */
static void test_default_grid_places_every_element(void)
{
    PanelLayout layout = registry_of(7);
    PanelGrid *grid = panel_grid_default(&layout);

    g_assert_cmpuint(grid->columns, ==, PANEL_GRID_COLUMNS);
    g_assert_cmpuint(grid->rows, ==, PANEL_GRID_ROWS);
    g_assert_cmpuint(grid->cards->len, ==, 7);

    /* Five two-cell cards fit across ten columns, so the sixth starts a row. */
    g_assert_cmpuint(card_at(grid, 0)->x, ==, 0);
    g_assert_cmpuint(card_at(grid, 0)->y, ==, 0);
    g_assert_cmpuint(card_at(grid, 4)->x, ==, 8);
    g_assert_cmpuint(card_at(grid, 4)->y, ==, 0);
    g_assert_cmpuint(card_at(grid, 5)->x, ==, 0);
    g_assert_cmpuint(card_at(grid, 5)->y, ==, 2);
    for (guint i = 0; i < grid->cards->len; i++) {
        g_assert_cmpuint(card_at(grid, i)->width, ==, 2);
        g_assert_cmpuint(card_at(grid, i)->height, ==, 2);
    }

    panel_grid_free(grid);
    panel_layout_clear(&layout);
}

static void test_empty_registry_gives_an_empty_grid(void)
{
    PanelLayout layout = registry_of(0);
    PanelGrid *grid = panel_grid_default(&layout);

    g_assert_cmpuint(grid->cards->len, ==, 0);

    panel_grid_free(grid);
    panel_layout_clear(&layout);
}

/* The profile allows a hundred elements and a ten-by-fourteen grid holds
 * thirty-five two-cell cards. The rest are simply not placed: the default is
 * a starting point, not a promise that everything fits at that size. */
static void test_default_grid_stops_at_the_last_row(void)
{
    PanelLayout layout = registry_of(100);
    PanelGrid *grid = panel_grid_default(&layout);

    g_assert_cmpuint(grid->cards->len, ==, 35);
    for (guint i = 0; i < grid->cards->len; i++) {
        const PanelCard *card = card_at(grid, i);
        g_assert_cmpuint(card->x + card->width, <=, grid->columns);
        g_assert_cmpuint(card->y + card->height, <=, grid->rows);
    }

    /* And what it produced has to be readable again, unchanged. */
    gchar *json = panel_grid_to_json(grid);
    guint dropped = 0;
    gchar *failure = NULL;
    PanelGrid *again = panel_grid_parse(json, -1, &dropped, &failure);
    g_assert_nonnull(again);
    g_assert_cmpuint(dropped, ==, 0);
    g_assert_cmpuint(again->cards->len, ==, 35);

    g_free(json);
    panel_grid_free(again);
    panel_grid_free(grid);
    panel_layout_clear(&layout);
}

/* A registry of a hundred is what the T560 profile allows, and a grid may
 * hold one card per element. Reading that back must cost nothing surprising. */
static void test_a_full_registry_lays_out(void)
{
    GString *cards = g_string_new("");
    guint placed = 0;

    for (guint y = 0; y < PANEL_GRID_ROWS && placed < 100; y++) {
        for (guint x = 0; x < PANEL_GRID_COLUMNS && placed < 100; x++) {
            g_string_append_printf(
                cards, "%s{\"x\":%u,\"y\":%u,\"w\":1,\"h\":1,\"rid\":\"%08x\"}",
                placed > 0 ? "," : "", x, y, placed);
            placed++;
        }
    }
    gchar *json = g_strdup_printf(
        "{\"v\":1,\"cols\":10,\"rows\":14,\"cards\":[%s]}", cards->str);

    guint dropped = 0;
    gchar *failure = NULL;
    PanelGrid *grid = panel_grid_parse(json, -1, &dropped, &failure);

    g_assert_nonnull(grid);
    g_assert_cmpuint(grid->cards->len, ==, 100);
    g_assert_cmpuint(dropped, ==, 0);

    panel_grid_free(grid);
    g_free(json);
    g_string_free(cards, TRUE);
}

/* A half-written colour is dropped rather than repaired: the card then draws
 * in the skin's own colours, which is always a defensible picture. */
static void test_unusable_colors_are_ignored(void)
{
    const gchar *colors[] = {"red", "#abc", "#12345g", "#1234567", ""};

    for (guint i = 0; i < G_N_ELEMENTS(colors); i++) {
        gchar *failure = NULL;
        gchar *json = g_strdup_printf(
            "{\"v\":1,\"cards\":[{\"x\":0,\"y\":0,\"w\":1,\"h\":1,"
            "\"rid\":\"a\",\"color\":\"%s\"}]}", colors[i]);
        PanelGrid *grid = panel_grid_parse(json, -1, NULL, &failure);

        g_assert_nonnull(grid);
        g_assert_cmpuint(grid->cards->len, ==, 1);
        g_assert_null(card_at(grid, 0)->color);

        panel_grid_free(grid);
        g_free(json);
    }
}

void panel_grid_tests_register(void)
{
    g_test_add_func("/grid/full-layout", test_full_layout);
    g_test_add_func("/grid/round-trip", test_round_trip);
    g_test_add_func("/grid/cards-outside",
                    test_cards_outside_the_grid_are_dropped);
    g_test_add_func("/grid/overlapping", test_overlapping_cards_are_dropped);
    g_test_add_func("/grid/touching", test_touching_cards_are_kept);
    g_test_add_func("/grid/unknown-rid", test_unknown_rid_is_kept);
    g_test_add_func("/grid/card-without-rid",
                    test_card_without_rid_is_dropped);
    g_test_add_func("/grid/card-without-geometry",
                    test_card_without_geometry_is_dropped);
    g_test_add_func("/grid/broken-json", test_broken_json_is_reported);
    g_test_add_func("/grid/empty-card-list",
                    test_empty_card_list_is_a_valid_grid);
    g_test_add_func("/grid/other-sizes", test_other_grid_sizes_are_honoured);
    g_test_add_func("/grid/default", test_default_grid_places_every_element);
    g_test_add_func("/grid/default-empty",
                    test_empty_registry_gives_an_empty_grid);
    g_test_add_func("/grid/default-overflow",
                    test_default_grid_stops_at_the_last_row);
    g_test_add_func("/grid/full-registry", test_a_full_registry_lays_out);
    g_test_add_func("/grid/unusable-color", test_unusable_colors_are_ignored);
}
