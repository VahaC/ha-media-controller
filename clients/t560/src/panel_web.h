#ifndef T560_PANEL_WEB_H
#define T560_PANEL_WEB_H

#include "app_config.h"
#include "panel_cards.h"
#include "panel_grid.h"

#include <glib.h>

/* The layout editor the panel serves on the tablet itself.
 *
 * A tablet has no keyboard and a 800x1219 touch screen, which is a poor place
 * to drag a hundred cards around. So the arrangement is edited from whatever
 * device the person is already holding, over the local network, and the panel
 * serves that page itself rather than depending on anything outside the
 * house.
 *
 * **There is no authentication.** That is a deliberate decision and it is the
 * reason for the shape of everything below:
 *
 * - there are exactly ten routes and not one of them is a general proxy to
 *   Home Assistant. Nothing here can read a state, call an arbitrary service,
 *   or reach an entity the panel does not already draw. The worst an
 *   unauthenticated caller can do is rearrange the room page of one tablet,
 *   rename a card the panel is already drawing, and ask Home Assistant for a
 *   skin this panel already offers;
 * - the two routes for card artwork keep that rule rather than bending it.
 *   The picture route serves what the panel has already downloaded for its
 *   own cards and can reach nothing else; the card route changes the display
 *   name and the icon of an element the panel is already drawing, and every
 *   value in it is checked here and again by the integration that owns the
 *   registry;
 * - the registry is served from the config payload the panel has already
 *   cached, so a request here never becomes a request to Home Assistant;
 * - the panel's Home Assistant token never leaves the panel and is never
 *   readable through any route;
 * - `DELETE /api/layout` puts back the copy Home Assistant holds. That is
 *   what makes the missing password survivable: the worst outcome is undone
 *   by one button.
 *
 * The port is bound on every interface, which is what makes it reachable from
 * a phone. **Do not forward it through a router.** See
 * docs/BUILD_AND_INSTALL.md.
 */

typedef struct _PanelWeb PanelWeb;

/* Answers a restore: NULL and an error, or the stored document. */
typedef void (*PanelWebRestoreReady)(const gchar *layout,
                                     const gchar *error_message,
                                     gpointer request);

/* What the editor needs from the application. They are callbacks rather than
 * direct calls so that this file knows nothing about polling, Home Assistant,
 * or the interface: it turns HTTP into these seven questions and back. */
typedef struct {
    /* The registry this panel was given, for the palette. */
    const PanelLayout *(*layout)(gpointer user_data);
    /* The skin the panel is drawing right now. It is asked for separately
     * because it is not in the payload: Home Assistant sends a skin only once
     * somebody has chosen one, and until then the panel is drawing whatever
     * config.ini said. The editor's picker has to show what is on screen, not
     * what Home Assistant last mentioned. */
    PanelPlayerSkin (*skin)(gpointer user_data);
    /* The arrangement currently on screen. */
    const PanelGrid *(*grid)(gpointer user_data);
    /* Adopt and persist a new arrangement. Takes ownership of `grid` when it
     * returns TRUE. `backed_up` says whether the copy in Home Assistant was
     * written, which is reported to the editor but never fails the save: a
     * layout that is on the panel is saved, whatever Home Assistant did. */
    gboolean (*save_grid)(PanelGrid *grid, gboolean *backed_up,
                          gchar **error_message, gpointer user_data);
    /* Ask Home Assistant for the copy it holds. The answer arrives later, on
     * the main loop, through `ready`. */
    void (*restore)(PanelWebRestoreReady ready, gpointer request,
                    gpointer user_data);
    /* Ask Home Assistant to select a skin. It is written nowhere locally:
     * Home Assistant owns the value and the panel adopts it on its next
     * poll. */
    gboolean (*select_skin)(const gchar *name, gchar **error_message,
                            gpointer user_data);
    /* The card artwork this panel knows about: the catalog the Media
     * Controller integration publishes and the pictures already downloaded
     * from it. It is asked for rather than held here because the fetching
     * needs the HTTP client, which this file has no business knowing about. */
    PanelCards *(*cards)(gpointer user_data);
    /* Public artwork origin only; the caller owns the returned string. */
    gchar *(*icon_preview_base)(gpointer user_data);
    /* Ask Home Assistant to store the display name and the icon of one
     * registry element. Nothing is written locally: Home Assistant owns the
     * registry and the new value arrives back the ordinary way, in the next
     * poll. NULL for either means "leave that one alone", which is the
     * difference between an editor that only renamed a card and one that
     * cleared its icon.
     *
     * The answer arrives later, on the main loop, and the panel reports it
     * through `panel_cards_write_finished`; the editor watches
     * /api/entities for it, exactly as it watches a restore. */
    gboolean (*write_card)(const gchar *rid, const gchar *name,
                           const gchar *icon, gchar **error_message,
                           gpointer user_data);
} PanelWebCallbacks;

/* Starts the server. Returns NULL and sets `error_message` when the port
 * cannot be bound, which is never fatal to the panel: the room page works
 * without an editor. */
PanelWeb *panel_web_new(guint port, const PanelWebCallbacks *callbacks,
                        gpointer user_data, gchar **error_message);
void panel_web_free(PanelWeb *web);
/* Where a person should point a browser, for the hint on an empty page. */
const gchar *panel_web_url(PanelWeb *web);

#endif
