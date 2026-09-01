import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as element_tree


SCRIPT = Path(__file__).parents[1] / "scripts" / "t560-configure-openbox.py"
SPEC = importlib.util.spec_from_file_location("configure_openbox", SCRIPT)
CONFIGURE_OPENBOX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIGURE_OPENBOX)


class ConfigureOpenboxTest(unittest.TestCase):
    def test_replaces_existing_home_bindings(self):
        source = """<?xml version="1.0"?>
<openbox_config>
<keyboard>
  <keybind key="Home">
    <action name="ToggleShowDesktop" />
  </keybind>
  <keybind key="XF86HomePage">
    <action name="Execute"><command>old-command</command></action>
  </keybind>
</keyboard>
</openbox_config>
"""

        configured = CONFIGURE_OPENBOX.configure(source)

        self.assertEqual(configured.count(CONFIGURE_OPENBOX.HOME_COMMAND), 2)
        self.assertNotIn("ToggleShowDesktop", configured)
        self.assertNotIn("old-command", configured)
        element_tree.fromstring(configured)

    def test_adds_missing_home_bindings_and_is_idempotent(self):
        source = """<openbox_config>
<keyboard>
  <keybind key="A-F4"><action name="Close" /></keybind>
</keyboard>
</openbox_config>
"""

        configured = CONFIGURE_OPENBOX.configure(source)

        self.assertEqual(configured.count(CONFIGURE_OPENBOX.HOME_COMMAND), 2)
        self.assertIn('keybind key="A-F4"', configured)
        self.assertEqual(CONFIGURE_OPENBOX.configure(configured), configured)

    def test_replaces_existing_panel_application_rule(self):
        source = """<openbox_config>
<keyboard>
</keyboard>
<applications>
  <application name="other-app">
    <fullscreen>no</fullscreen>
  </application>
  <application name="t560-music-panel" class="T560MusicPanel">
    <fullscreen>no</fullscreen>
    <maximized>yes</maximized>
  </application>
</applications>
</openbox_config>
"""

        configured = CONFIGURE_OPENBOX.configure(source)
        root = element_tree.fromstring(configured)
        rules = {
            application.get("name"): application
            for application in root.iter("application")
        }

        self.assertEqual(rules["other-app"].find("fullscreen").text, "no")
        panel = rules["t560-music-panel"]
        self.assertEqual(panel.find("fullscreen").text, "yes")
        self.assertEqual(panel.find("decor").text, "no")
        self.assertEqual(configured.count('name="t560-music-panel"'), 1)

    def test_adds_applications_section_when_missing(self):
        source = """<openbox_config>
<keyboard>
</keyboard>
</openbox_config>
"""

        configured = CONFIGURE_OPENBOX.configure(source)
        root = element_tree.fromstring(configured)
        panel = root.find("./applications/application")

        self.assertEqual(panel.get("name"), "t560-music-panel")
        self.assertEqual(panel.get("class"), "T560MusicPanel")
        self.assertEqual(panel.find("fullscreen").text, "yes")
        self.assertEqual(CONFIGURE_OPENBOX.configure(configured), configured)


if __name__ == "__main__":
    unittest.main()
