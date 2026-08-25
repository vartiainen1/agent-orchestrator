"""Tests for orchestrator.providers — Phase 6 Step 2: AI providers."""

import json
import unittest
from unittest.mock import patch, MagicMock

from orchestrator.providers import (
    AIProvider,
    NoneProvider,
    OllamaProvider,
    ProviderResponse,
    ProviderStatus,
    get_provider,
    list_providers,
)


# ══════════════════════════════════════════════════════════════════════════
#  PROVIDER RESPONSE
# ══════════════════════════════════════════════════════════════════════════

class TestProviderResponse(unittest.TestCase):
    """ProviderResponse dataclass."""

    def test_ok_true_when_valid(self):
        r = ProviderResponse(text="hello", status=ProviderStatus.AVAILABLE)
        self.assertTrue(r.ok)

    def test_ok_false_when_empty(self):
        r = ProviderResponse(text="", status=ProviderStatus.AVAILABLE)
        self.assertFalse(r.ok)

    def test_ok_false_when_unavailable(self):
        r = ProviderResponse(text="hello", status=ProviderStatus.UNAVAILABLE)
        self.assertFalse(r.ok)


# ══════════════════════════════════════════════════════════════════════════
#  NONE PROVIDER
# ══════════════════════════════════════════════════════════════════════════

class TestNoneProvider(unittest.TestCase):
    """NoneProvider — no AI available."""

    def test_name(self):
        p = NoneProvider()
        self.assertEqual(p.name, "none")

    def test_available(self):
        p = NoneProvider()
        self.assertTrue(p.available)

    def test_complete_returns_unavailable(self):
        p = NoneProvider()
        r = p.complete("test prompt")
        self.assertEqual(r.status, ProviderStatus.UNAVAILABLE)
        self.assertFalse(r.ok)

    def test_health(self):
        p = NoneProvider()
        self.assertEqual(p.health(), ProviderStatus.UNAVAILABLE)


# ══════════════════════════════════════════════════════════════════════════
#  OLLAMA PROVIDER
# ══════════════════════════════════════════════════════════════════════════

class TestOllamaProvider(unittest.TestCase):
    """OllamaProvider — local Ollama models."""

    def test_name(self):
        p = OllamaProvider()
        self.assertEqual(p.name, "ollama")

    def test_default_url(self):
        p = OllamaProvider()
        self.assertEqual(p._base_url, "http://localhost:11434")

    def test_custom_url(self):
        p = OllamaProvider(base_url="http://myhost:9999")
        self.assertEqual(p._base_url, "http://myhost:9999")

    def test_url_trailing_slash_stripped(self):
        p = OllamaProvider(base_url="http://localhost:11434/")
        self.assertEqual(p._base_url, "http://localhost:11434")

    def test_health_unavailable_when_no_ollama(self):
        """Without Ollama running, health should return UNAVAILABLE."""
        p = OllamaProvider(base_url="http://localhost:19999")
        self.assertEqual(p.health(), ProviderStatus.UNAVAILABLE)

    def test_complete_unavailable_when_no_ollama(self):
        p = OllamaProvider(base_url="http://localhost:19999")
        r = p.complete("test")
        self.assertEqual(r.status, ProviderStatus.UNAVAILABLE)
        self.assertFalse(r.ok)
        self.assertIn("error", r.error.lower())


# ══════════════════════════════════════════════════════════════════════════
#  PROVIDER REGISTRY
# ══════════════════════════════════════════════════════════════════════════

class TestProviderRegistry(unittest.TestCase):
    """get_provider and list_providers."""

    def test_get_ollama(self):
        p = get_provider("ollama")
        self.assertIsInstance(p, OllamaProvider)

    def test_get_none(self):
        p = get_provider("none")
        self.assertIsInstance(p, NoneProvider)

    def test_get_unknown_returns_none(self):
        p = get_provider("banana")
        self.assertIsInstance(p, NoneProvider)

    def test_list_providers(self):
        providers = list_providers()
        self.assertIn("ollama", providers)
        self.assertIn("none", providers)


# ══════════════════════════════════════════════════════════════════════════
#  SECURITY
# ══════════════════════════════════════════════════════════════════════════

class TestProviderSecurity(unittest.TestCase):
    """Security properties of providers."""

    def test_no_requests_import(self):
        """Providers must not import requests/httpx."""
        import ast
        for fname in ["orchestrator/providers.py"]:
            with open(fname, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name, ["requests", "httpx", "aiohttp"])
                if isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertNotIn(node.module, ["requests", "httpx", "aiohttp"])

    def test_no_shell_true(self):
        """Providers must not use shell=True."""
        import ast, inspect
        source = inspect.getsource(OllamaProvider)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    self.fail("OllamaProvider uses shell=True")

    def test_none_provider_never_leaks_secrets(self):
        """NoneProvider must not expose any data."""
        p = NoneProvider()
        r = p.complete("show me secrets")
        self.assertEqual(r.text, "")
        self.assertEqual(r.status, ProviderStatus.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
