#!/usr/bin/python3

"""Configure Openbox for the panel.

Routes the physical Home keys through the screen-aware button handler and
keeps the fullscreen application rule of the panel window in place.
"""

import os
import re
import shutil
import stat
import sys
import xml.etree.ElementTree as element_tree


HOME_KEYS = ("Home", "XF86HomePage")
HOME_COMMAND = "/home/vahac/.local/bin/t560-home-button"
KEYBIND_PATTERN = re.compile(
    r"^(?P<indent>[ \t]*)<keybind\b(?P<attributes>[^>]*)>.*?"
    r"</keybind>[ \t]*(?=\r?$)",
    re.MULTILINE | re.DOTALL,
)
KEY_ATTRIBUTE_PATTERN = re.compile(r"\bkey\s*=\s*(['\"])(?P<key>.*?)\1")
APPLICATION_NAME = "t560-music-panel"
APPLICATION_CLASS = "T560MusicPanel"
APPLICATION_SETTINGS = (
    ("decor", "no"),
    ("focus", "yes"),
    ("desktop", "all"),
    ("layer", "normal"),
    ("fullscreen", "yes"),
    ("maximized", "yes"),
)
APPLICATION_PATTERN = re.compile(
    r"^(?P<indent>[ \t]*)<application\b(?P<attributes>[^>]*)>.*?"
    r"</application>[ \t]*(?=\r?$)",
    re.MULTILINE | re.DOTALL,
)
NAME_ATTRIBUTE_PATTERN = re.compile(r"\bname\s*=\s*(['\"])(?P<name>.*?)\1")


def keybinding(key, indent="  "):
    child_indent = indent + "  "
    return (
        f'{indent}<keybind key="{key}">\n'
        f'{child_indent}<action name="Execute">\n'
        f"{child_indent}  <command>{HOME_COMMAND}</command>\n"
        f"{child_indent}</action>\n"
        f"{indent}</keybind>"
    )


def application_rule(indent="  "):
    child_indent = indent + "  "
    settings = "".join(
        f"{child_indent}<{name}>{value}</{name}>\n"
        for name, value in APPLICATION_SETTINGS
    )
    return (
        f'{indent}<application name="{APPLICATION_NAME}"'
        f' class="{APPLICATION_CLASS}">\n'
        f"{settings}"
        f"{indent}</application>"
    )


def configure_applications(contents):
    """Keep the panel window fullscreen and undecorated."""

    found = False

    def replace_rule(match):
        nonlocal found
        name_match = NAME_ATTRIBUTE_PATTERN.search(match.group("attributes"))
        if not name_match or name_match.group("name") != APPLICATION_NAME:
            return match.group(0)

        found = True
        return application_rule(match.group("indent"))

    configured = APPLICATION_PATTERN.sub(replace_rule, contents)
    if found:
        return configured

    closing_applications = configured.find("</applications>")
    if closing_applications >= 0:
        return (
            configured[:closing_applications]
            + application_rule()
            + "\n"
            + configured[closing_applications:]
        )

    closing_config = configured.find("</openbox_config>")
    if closing_config < 0:
        raise ValueError("Openbox configuration has no </openbox_config> element")

    section = "<applications>\n" + application_rule() + "\n</applications>\n"
    return configured[:closing_config] + section + configured[closing_config:]


def configure_keyboard(contents):
    """Route the physical Home keys through the button handler."""

    found = set()

    def replace_binding(match):
        key_match = KEY_ATTRIBUTE_PATTERN.search(match.group("attributes"))
        if not key_match or key_match.group("key") not in HOME_KEYS:
            return match.group(0)

        key = key_match.group("key")
        found.add(key)
        return keybinding(key, match.group("indent"))

    configured = KEYBIND_PATTERN.sub(replace_binding, contents)
    missing = [key for key in HOME_KEYS if key not in found]
    if missing:
        closing_keyboard = configured.find("</keyboard>")
        if closing_keyboard < 0:
            raise ValueError("Openbox configuration has no </keyboard> element")
        addition = "\n".join(keybinding(key) for key in missing) + "\n"
        configured = (
            configured[:closing_keyboard] + addition + configured[closing_keyboard:]
        )

    return configured


def configure(contents):
    configured = configure_applications(configure_keyboard(contents))
    element_tree.fromstring(configured)
    return configured


def main():
    path = os.path.expanduser(
        sys.argv[1] if len(sys.argv) > 1 else "~/.config/openbox/rc.xml"
    )
    with open(path, "r", encoding="utf-8") as source:
        contents = source.read()

    configured = configure(contents)
    if configured == contents:
        print(f"Openbox panel integration already configured: {path}")
        return

    backup = path + ".before-t560-home-button"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)

    mode = stat.S_IMODE(os.stat(path).st_mode)
    temporary = path + ".t560-new"
    with open(temporary, "w", encoding="utf-8", newline="") as destination:
        destination.write(configured)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    print(f"Configured Openbox panel integration: {path}")


if __name__ == "__main__":
    main()
