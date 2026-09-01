#ifndef T560_TEST_PANEL_CONFIG_H
#define T560_TEST_PANEL_CONFIG_H

/* Registered from the single test binary's main, so that the payload the
 * panel depends on is covered by the same `make test` run. */
void panel_config_tests_register(void);

#endif
