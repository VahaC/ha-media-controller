"""Public previews expose bundled PNGs only, without changing asset auth."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web


class IconPreviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = Path(__file__).parents[1] / "custom_components/media_controller"
        package = types.ModuleType("preview_test_integration")
        package.__path__ = [str(root)]
        http = types.ModuleType("homeassistant.components.http")

        class View:
            requires_auth = True

            def json(self, data, status_code=200):
                return web.json_response(data, status=status_code)

        http.HomeAssistantView = View
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        modules = {
            package.__name__: package,
            "homeassistant": types.ModuleType("homeassistant"),
            "homeassistant.components": types.ModuleType("homeassistant.components"),
            "homeassistant.components.http": http,
            "homeassistant.core": core,
        }
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location(
                "preview_test_integration.icons", root / "icons.py"
            )
            self.icons = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.icons)
        self.executor = AsyncMock(side_effect=lambda callback: callback())
        self.hass = types.SimpleNamespace(async_add_executor_job=self.executor)

    async def test_preview_is_public_but_existing_routes_require_auth(self):
        self.assertFalse(self.icons.IconPreviewView.requires_auth)
        self.assertTrue(self.icons.IconAssetView.requires_auth)
        self.assertTrue(self.icons.IconCatalogView.requires_auth)

    async def test_preview_returns_png_for_late_catalog_icon(self):
        response = await self.icons.IconPreviewView(self.hass).get(None, "sun-umbrella")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "image/png")
        self.assertTrue(response.body.startswith(b"\x89PNG\r\n\x1a\n"))
        self.executor.assert_awaited_once()

    async def test_unknown_or_path_identifiers_never_read_files(self):
        view = self.icons.IconPreviewView(self.hass)
        for icon in ("../secrets.yaml", "..%2fsecrets.yaml", "unknown-icon", "fan/40"):
            response = await view.get(None, icon)
            self.assertEqual(response.status, 404)
        self.executor.assert_not_awaited()

    async def test_missing_asset_returns_404(self):
        self.executor.side_effect = FileNotFoundError
        response = await self.icons.IconPreviewView(self.hass).get(None, "fan")
        self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
