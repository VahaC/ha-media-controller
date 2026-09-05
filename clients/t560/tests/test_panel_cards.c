#include "test_panel_cards.h"

#include "panel_cards.h"

#include <glib.h>
#include <string.h>

/* The rules a card's display name and icon have to pass on the panel side.
 *
 * The integration checks the same things, because it is the side that owns
 * the registry. These are checked here too so that the editor is told at once
 * rather than after a round trip, and so that nothing unbounded or unexamined
 * is ever put on the wire — which is the whole reason the editor's own server
 * can go without a password. */

static const gchar *CATALOG =
    "{\"revision\":2098342174,\"sizes\":[40],\"esp32_bytes\":6408,"
    "\"icons\":["
    "{\"id\":\"light-1\",\"label\":\"Lamp\"},"
    "{\"id\":\"desk-lamp\",\"label\":\"Desk lamp\"},"
    "{\"id\":\"blind\",\"label\":\"Blind\"}]}";

/* ------------------------------------------------------------------ names */

static void test_name_is_trimmed(void)
{
    gchar *name = NULL;

    g_assert_cmpint(panel_card_name_normalize("  Desk lamp\t ", &name), ==,
                    PANEL_CARD_NAME_OK);
    g_assert_cmpstr(name, ==, "Desk lamp");
    g_free(name);
}

/* An empty name means "use the Home Assistant entity's own name". It is the
 * one value with a meaning of its own, and it is what makes the field
 * clearable without a second control. */
static void test_empty_name_is_allowed(void)
{
    const gchar *inputs[] = {"", "   ", "\t", NULL};

    for (guint i = 0; i < G_N_ELEMENTS(inputs); i++) {
        gchar *name = NULL;
        g_assert_cmpint(panel_card_name_normalize(inputs[i], &name), ==,
                        PANEL_CARD_NAME_OK);
        g_assert_cmpstr(name, ==, "");
        g_free(name);
    }
}

static void test_every_script_is_a_name(void)
{
    const gchar *inputs[] = {"Настільна лампа", "Λάμπα", "デスクランプ",
                             "Lampe 💡"};

    for (guint i = 0; i < G_N_ELEMENTS(inputs); i++) {
        gchar *name = NULL;
        g_assert_cmpint(panel_card_name_normalize(inputs[i], &name), ==,
                        PANEL_CARD_NAME_OK);
        g_assert_cmpstr(name, ==, inputs[i]);
        g_free(name);
    }
}

/* Refused rather than stripped: a newline in a tile label is somebody
 * pasting the wrong thing, and keeping half of what they pasted is worse
 * than telling them. */
static void test_control_characters_are_refused(void)
{
    gchar *name = NULL;

    g_assert_cmpint(panel_card_name_normalize("Desk\nlamp", &name), ==,
                    PANEL_CARD_NAME_UNPRINTABLE);
    g_assert_null(name);
    g_assert_nonnull(panel_card_name_error(PANEL_CARD_NAME_UNPRINTABLE));
}

/* The bound is in characters, so a Cyrillic name may be exactly as long as a
 * Latin one. A limit in bytes would make one script two thirds the length of
 * the other for no reason a person could see. */
static void test_bound_is_in_characters(void)
{
    GString *latin = g_string_new(NULL);
    GString *cyrillic = g_string_new(NULL);

    for (guint i = 0; i < PANEL_CARD_NAME_MAX_CHARS; i++) {
        g_string_append_c(latin, 'a');
        g_string_append(cyrillic, "я");
    }

    gchar *name = NULL;
    g_assert_cmpint(panel_card_name_normalize(latin->str, &name), ==,
                    PANEL_CARD_NAME_OK);
    g_free(name);
    name = NULL;
    g_assert_cmpint(panel_card_name_normalize(cyrillic->str, &name), ==,
                    PANEL_CARD_NAME_OK);
    g_free(name);
    name = NULL;

    g_string_append(cyrillic, "я");
    g_assert_cmpint(panel_card_name_normalize(cyrillic->str, &name), ==,
                    PANEL_CARD_NAME_TOO_LONG);
    g_assert_null(name);
    g_assert_nonnull(panel_card_name_error(PANEL_CARD_NAME_TOO_LONG));

    g_string_free(latin, TRUE);
    g_string_free(cyrillic, TRUE);
}

/* ------------------------------------------------------------ identifiers */

static void test_identifier_shape(void)
{
    const gchar *good[] = {"fan", "light-1", "desk-led-strip", "a", "a1"};
    const gchar *bad[] = {"",
                          "-fan",
                          "FAN",
                          "fan.png",
                          "fan ",
                          "../secrets.yaml",
                          "..%2fsecrets",
                          "icons/../fan",
                          "/etc/passwd",
                          ".",
                          "..",
                          "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"};

    for (guint i = 0; i < G_N_ELEMENTS(good); i++)
        g_assert_true(panel_card_icon_id_is_sane(good[i]));
    for (guint i = 0; i < G_N_ELEMENTS(bad); i++)
        g_assert_false(panel_card_icon_id_is_sane(bad[i]));
    g_assert_false(panel_card_icon_id_is_sane(NULL));
}

/* ---------------------------------------------------------------- catalog */

static void test_catalog_is_read(void)
{
    PanelCards *cards = panel_cards_new();

    g_assert_true(panel_cards_set_catalog(cards, CATALOG, -1));
    g_assert_cmpuint(panel_cards_catalog_size(cards), ==, 3);
    g_assert_cmpstr(panel_cards_catalog_id(cards, 0), ==, "light-1");
    g_assert_cmpstr(panel_cards_catalog_label(cards, 1), ==, "Desk lamp");
    g_assert_true(panel_cards_publishes(cards, "blind"));
    g_assert_false(panel_cards_publishes(cards, "kettle"));

    /* The same document twice is not a change, which is what stops the panel
     * refetching every picture on a schedule. */
    g_assert_false(panel_cards_set_catalog(cards, CATALOG, -1));

    panel_cards_free(cards);
}

/* An identifier is a name and never a position: reordering the catalog must
 * not move anybody's icon. It is the whole reason a card stopped storing an
 * index into an array compiled into the client. */
static void test_reordering_moves_nothing(void)
{
    PanelCards *cards = panel_cards_new();
    const gchar *reordered =
        "{\"revision\":7,\"icons\":["
        "{\"id\":\"blind\",\"label\":\"Blind\"},"
        "{\"id\":\"desk-lamp\",\"label\":\"Desk lamp\"},"
        "{\"id\":\"light-1\",\"label\":\"Lamp\"}]}";

    g_assert_true(panel_cards_set_catalog(cards, CATALOG, -1));
    g_assert_true(panel_cards_set_catalog(cards, reordered, -1));
    g_assert_true(panel_cards_publishes(cards, "light-1"));
    g_assert_true(panel_cards_publishes(cards, "desk-lamp"));
    g_assert_true(panel_cards_publishes(cards, "blind"));

    panel_cards_free(cards);
}

static void test_unusable_catalog_is_refused(void)
{
    PanelCards *cards = panel_cards_new();

    g_assert_false(panel_cards_set_catalog(cards, "not json", -1));
    g_assert_false(panel_cards_set_catalog(cards, "[]", -1));
    g_assert_false(panel_cards_set_catalog(cards, "{\"revision\":1}", -1));
    g_assert_cmpuint(panel_cards_catalog_size(cards), ==, 0);

    /* A row whose identifier could not have come from the catalog is dropped
     * rather than carried around and refused later. */
    g_assert_true(panel_cards_set_catalog(
        cards,
        "{\"revision\":2,\"icons\":["
        "{\"id\":\"../secrets\"},{\"id\":\"fan\"}]}",
        -1));
    g_assert_cmpuint(panel_cards_catalog_size(cards), ==, 1);
    g_assert_cmpstr(panel_cards_catalog_id(cards, 0), ==, "fan");
    /* No label in the document, so the identifier is its own label. */
    g_assert_cmpstr(panel_cards_catalog_label(cards, 0), ==, "fan");

    panel_cards_free(cards);
}

/* --------------------------------------------------------------- pictures */

static void test_pictures_are_shared_and_guarded(void)
{
    PanelCards *cards = panel_cards_new();
    GBytes *png = g_bytes_new_static("\x89PNG", 4);

    g_assert_true(panel_cards_set_catalog(cards, CATALOG, -1));

    /* Only what the catalog publishes. Without this the cache would be a
     * place anything could be put by asking for it. */
    panel_cards_store_image(cards, "kettle", png);
    g_assert_null(panel_cards_image(cards, "kettle"));

    panel_cards_store_image(cards, "blind", png);
    GBytes *held = panel_cards_image(cards, "blind");
    g_assert_nonnull(held);
    /* Cards naming the same picture are handed the same bytes: one decoded
     * copy per identifier, never one per card. */
    g_assert_true(held == panel_cards_image(cards, "blind"));

    g_bytes_unref(png);
    panel_cards_free(cards);
}

static void test_wanted_list_skips_what_is_held(void)
{
    PanelCards *cards = panel_cards_new();
    GBytes *png = g_bytes_new_static("\x89PNG", 4);

    g_assert_null(panel_cards_next_wanted(cards));
    g_assert_true(panel_cards_set_catalog(cards, CATALOG, -1));
    g_assert_cmpstr(panel_cards_next_wanted(cards), ==, "light-1");

    panel_cards_store_image(cards, "light-1", png);
    g_assert_cmpstr(panel_cards_next_wanted(cards), ==, "desk-lamp");

    /* A picture that did not arrive is left alone for a while rather than
     * asked for again on every tick: Home Assistant being down must not
     * become a request per poll. */
    panel_cards_mark_missing(cards, "desk-lamp");
    g_assert_cmpstr(panel_cards_next_wanted(cards), ==, "blind");

    panel_cards_store_image(cards, "blind", png);
    g_assert_null(panel_cards_next_wanted(cards));

    g_bytes_unref(png);
    panel_cards_free(cards);
}

/* ------------------------------------------------------------ the outcome */

static void test_write_outcome_is_reported(void)
{
    PanelCards *cards = panel_cards_new();

    g_assert_cmpint(panel_cards_write_state(cards), ==,
                    PANEL_CARD_WRITE_IDLE);
    panel_cards_write_started(cards);
    g_assert_cmpint(panel_cards_write_state(cards), ==,
                    PANEL_CARD_WRITE_PENDING);
    panel_cards_write_finished(cards, FALSE, "Home Assistant refused it.");
    g_assert_cmpint(panel_cards_write_state(cards), ==,
                    PANEL_CARD_WRITE_FAILED);
    g_assert_cmpstr(panel_cards_write_message(cards), ==,
                    "Home Assistant refused it.");
    panel_cards_write_finished(cards, TRUE, NULL);
    g_assert_cmpint(panel_cards_write_state(cards), ==, PANEL_CARD_WRITE_OK);
    g_assert_cmpstr(panel_cards_write_message(cards), ==, "");

    panel_cards_free(cards);
}

void panel_cards_tests_register(void)
{
    g_test_add_func("/cards/name-trimmed", test_name_is_trimmed);
    g_test_add_func("/cards/name-empty", test_empty_name_is_allowed);
    g_test_add_func("/cards/name-unicode", test_every_script_is_a_name);
    g_test_add_func("/cards/name-control-characters",
                    test_control_characters_are_refused);
    g_test_add_func("/cards/name-bound", test_bound_is_in_characters);
    g_test_add_func("/cards/icon-identifier", test_identifier_shape);
    g_test_add_func("/cards/catalog", test_catalog_is_read);
    g_test_add_func("/cards/catalog-reordered", test_reordering_moves_nothing);
    g_test_add_func("/cards/catalog-unusable", test_unusable_catalog_is_refused);
    g_test_add_func("/cards/pictures", test_pictures_are_shared_and_guarded);
    g_test_add_func("/cards/pictures-wanted",
                    test_wanted_list_skips_what_is_held);
    g_test_add_func("/cards/write-outcome", test_write_outcome_is_reported);
}
