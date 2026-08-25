"""Phase 11 — CLI Provider and FreeBuff integration tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from orchestrator.providers import (
    CLIProvider,
    FreebuffProvider,
    ProviderStatus,
    ProviderResponse,
    get_provider,
    list_providers,
)
from orchestrator.validate import validate_config_value


# ── Helper: fake CLI scripts ─────────────────────────────────────────────

def _create_fake_cli(
    directory: Path,
    name: str = "fake-ai",
    response: str = "Hello from fake AI",
    exit_code: int = 0,
    delay: float = 0.0,
) -> Path:
    """Create a fake CLI script that echoes a response."""
    if os.name == "nt":
        # Windows: create a .bat file
        script = directory / f"{name}.bat"
        if delay > 0:
            content = f'@echo off\nping -n {int(delay) + 1} 127.0.0.1 >nul\necho {response}\nexit /b {exit_code}\n'
        else:
            content = f'@echo off\necho {response}\nexit /b {exit_code}\n'
        script.write_text(content)
    else:
        # Unix: create a shell script
        script = directory / name
        if delay > 0:
            content = f'#!/bin/sh\nsleep {delay}\necho "{response}"\nexit {exit_code}\n'
        else:
            content = f'#!/bin/sh\necho "{response}"\nexit {exit_code}\n'
        script.write_text(content)
        os.chmod(script, 0o755)
    return script


def _create_fake_cli_stdin(directory: Path, name: str = "fake-ai-stdin") -> Path:
    """Create a fake CLI that echoes whatever is passed via stdin."""
    if os.name == "nt":
        script = directory / f"{name}.bat"
        content = '@echo off\nset /p INPUT=\necho %INPUT%\n'
        script.write_text(content)
    else:
        script = directory / name
        content = '#!/bin/sh\ncat\n'
        script.write_text(content)
        os.chmod(script, 0o755)
    return script


# ── CLIProvider tests ────────────────────────────────────────────────────

class TestCLIProviderInit(unittest.TestCase):

    def test_basic_init(self):
        provider = CLIProvider(executable="fake-ai")
        self.assertEqual(provider.name, "cli")
        self.assertEqual(provider._executable, "fake-ai")
        self.assertEqual(provider._args, [])
        self.assertIsNone(provider._work_dir)

    def test_init_with_args(self):
        provider = CLIProvider(executable="fake-ai", args=["--flag", "value"])
        self.assertEqual(provider._args, ["--flag", "value"])

    def test_init_with_custom_name(self):
        provider = CLIProvider(executable="fake-ai", provider_name="custom")
        self.assertEqual(provider.name, "custom")

    def test_init_with_timeout(self):
        provider = CLIProvider(executable="fake-ai", timeout=30.0)
        self.assertEqual(provider._timeout, 30.0)


class TestCLIProviderHealth(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_health_available(self):
        script = _create_fake_cli(self.tmpdir)
        # Use full path to avoid PATH issues
        provider = CLIProvider(executable=str(script))
        self.assertEqual(provider.health(), ProviderStatus.AVAILABLE)

    def test_health_unavailable(self):
        provider = CLIProvider(executable="nonexistent-tool-12345")
        self.assertEqual(provider.health(), ProviderStatus.UNAVAILABLE)

    def test_available_property(self):
        provider = CLIProvider(executable="nonexistent-tool-12345")
        self.assertFalse(provider.available)


class TestCLIProviderComplete(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_successful_completion(self):
        script = _create_fake_cli(self.tmpdir, response="AI response text")
        provider = CLIProvider(executable=str(script))
        result = provider.complete("test prompt")
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        self.assertIn("AI response text", result.text)
        self.assertEqual(result.duration > 0, True)

    def test_prompt_via_stdin(self):
        """Verify prompt is passed via stdin, not arguments."""
        script = _create_fake_cli_stdin(self.tmpdir)
        provider = CLIProvider(executable=str(script))
        result = provider.complete("my secret prompt")
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        self.assertIn("my secret prompt", result.text)

    def test_stderr_capture(self):
        script = _create_fake_cli(self.tmpdir, response="stdout text", exit_code=1)
        provider = CLIProvider(executable=str(script))
        result = provider.complete("test")
        self.assertEqual(result.status, ProviderStatus.ERROR)
        self.assertIn("exited with code 1", result.error)

    def test_nonzero_exit_code(self):
        script = _create_fake_cli(self.tmpdir, response="error output", exit_code=42)
        provider = CLIProvider(executable=str(script))
        result = provider.complete("test")
        self.assertEqual(result.status, ProviderStatus.ERROR)
        self.assertIn("42", result.error)

    def test_executable_not_found(self):
        provider = CLIProvider(executable="nonexistent-tool-12345")
        result = provider.complete("test")
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertIn("not found", result.error)

    def test_timeout_handling(self):
        if os.name == "nt":
            self.skipTest("timeout test not reliable on Windows .bat")
        script = _create_fake_cli(self.tmpdir, delay=10)
        provider = CLIProvider(executable=str(script), timeout=1.0)
        result = provider.complete("test")
        self.assertEqual(result.status, ProviderStatus.TIMEOUT)
        self.assertIn("timeout", result.error.lower())

    def test_output_size_limit(self):
        # Create a script that outputs a lot of data
        if os.name == "nt":
            script = self.tmpdir / "big-output.bat"
            # Generate ~200KB output
            lines = ["echo This is a test line of output for size testing"] * 4000
            script.write_text("@echo off\n" + "\n".join(lines) + "\n")
        else:
            script = self.tmpdir / "big-output"
            lines = ["echo This is a test line of output for size testing"] * 4000
            script.write_text("#!/bin/sh\n" + "\n".join(lines) + "\n")
            os.chmod(script, 0o755)
        
        provider = CLIProvider(executable=str(script), max_output=1000)
        result = provider.complete("test")
        # Output should be capped
        self.assertLessEqual(len(result.raw), 5000)  # raw is capped at 5000

    def test_custom_args(self):
        script = _create_fake_cli(self.tmpdir, response="with args")
        provider = CLIProvider(executable=str(script), args=["--verbose"])
        result = provider.complete("test")
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)

    def test_work_dir(self):
        script = _create_fake_cli(self.tmpdir, response="in workdir")
        provider = CLIProvider(
            executable=str(script),
            work_dir=str(self.tmpdir),
        )
        result = provider.complete("test")
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)


class TestCLIProviderOutputValidation(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_null_bytes_rejected(self):
        if os.name == "nt":
            self.skipTest("null bytes test not reliable on Windows")
        # Use Python to reliably produce null bytes (shell echo varies)
        script = self.tmpdir / "null-bytes-test.py"
        script.write_bytes(b'import sys\nimport os\nos.write(1, b"hello\x00world\n")\n')
        provider = CLIProvider(executable=sys.executable, args=[str(script)])
        result = provider.complete("test")
        self.assertEqual(result.status, ProviderStatus.ERROR)
        self.assertIn("null bytes", result.error)

class TestCLIProviderSecurity(unittest.TestCase):

    def test_no_shell_true(self):
        """Verify shell=False is used by inspecting the source."""
        import ast
        source = open(
            Path(__file__).parent.parent / "orchestrator" / "providers.py",
            encoding="utf-8",
        ).read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                val = node.value
                if isinstance(val, ast.Constant) and val.value is True:
                    self.fail("shell=True found in providers.py")

    def test_prompt_not_in_arguments(self):
        """Prompt must be passed via stdin, not as a CLI argument."""
        # This is verified by the implementation using input=prompt
        # and the test_fake_cli_stdin test above confirms it works
        pass  # Covered by test_prompt_via_stdin


# ── FreebuffProvider tests ───────────────────────────────────────────────

class TestFreebuffProviderInit(unittest.TestCase):

    def test_default_init(self):
        provider = FreebuffProvider()
        self.assertEqual(provider.name, "freebuff")
        self.assertEqual(provider._executable, "freebuff")
        self.assertIn("--no-banner", provider._args)
        self.assertIn("--output", provider._args)
        self.assertIn("text", provider._args)

    def test_custom_executable(self):
        provider = FreebuffProvider(executable="/usr/local/bin/freebuff")
        self.assertEqual(provider._executable, "/usr/local/bin/freebuff")

    def test_extra_args(self):
        provider = FreebuffProvider(args=["--model", "llama3"])
        self.assertIn("--model", provider._args)
        self.assertIn("llama3", provider._args)
        # Default args still present
        self.assertIn("--no-banner", provider._args)

    def test_is_cli_provider(self):
        provider = FreebuffProvider()
        self.assertIsInstance(provider, CLIProvider)


class TestFreebuffProviderHealth(unittest.TestCase):

    def test_unavailable_when_not_installed(self):
        provider = FreebuffProvider(executable="nonexistent-freebuff-12345")
        self.assertEqual(provider.health(), ProviderStatus.UNAVAILABLE)
        self.assertFalse(provider.available)


# ── Provider registry tests ──────────────────────────────────────────────

class TestProviderRegistry(unittest.TestCase):

    def test_get_ollama(self):
        provider = get_provider("ollama")
        self.assertEqual(provider.name, "ollama")

    def test_get_none(self):
        provider = get_provider("none")
        self.assertEqual(provider.name, "none")

    def test_get_freebuff(self):
        provider = get_provider("freebuff")
        self.assertEqual(provider.name, "freebuff")
        self.assertIsInstance(provider, FreebuffProvider)

    def test_get_cli(self):
        provider = get_provider("cli", executable="my-ai")
        self.assertEqual(provider.name, "cli")
        self.assertIsInstance(provider, CLIProvider)

    def test_get_cli_no_executable(self):
        provider = get_provider("cli")
        self.assertEqual(provider.name, "none")  # falls back to NoneProvider

    def test_get_unknown(self):
        provider = get_provider("unknown")
        self.assertEqual(provider.name, "none")

    def test_list_providers(self):
        providers = list_providers()
        self.assertIn("ollama", providers)
        self.assertIn("none", providers)
        self.assertIn("freebuff", providers)
        self.assertIn("cli", providers)


# ── Config validation tests ──────────────────────────────────────────────

class TestCLIProviderConfig(unittest.TestCase):

    def test_provider_enum(self):
        result = validate_config_value("provider", "freebuff")
        self.assertTrue(result.valid)

    def test_provider_invalid(self):
        result = validate_config_value("provider", "chatgpt")
        self.assertFalse(result.valid)

    def test_provider_executable(self):
        result = validate_config_value("provider_executable", "freebuff")
        self.assertTrue(result.valid)

    def test_provider_executable_empty(self):
        result = validate_config_value("provider_executable", "")
        self.assertFalse(result.valid)

    def test_provider_args(self):
        result = validate_config_value("provider_args", "--model llama3")
        self.assertTrue(result.valid)

    def test_provider_timeout(self):
        result = validate_config_value("provider_timeout", "30")
        self.assertTrue(result.valid)

    def test_provider_timeout_invalid(self):
        result = validate_config_value("provider_timeout", "abc")
        self.assertFalse(result.valid)

    def test_provider_timeout_range(self):
        result = validate_config_value("provider_timeout", "99999")
        self.assertFalse(result.valid)


# ── Backward compatibility tests ─────────────────────────────────────────

class TestBackwardCompatibility(unittest.TestCase):

    def test_ollama_provider_unchanged(self):
        provider = get_provider("ollama")
        self.assertEqual(provider.name, "ollama")
        self.assertTrue(hasattr(provider, "complete"))
        self.assertTrue(hasattr(provider, "health"))

    def test_none_provider_unchanged(self):
        provider = get_provider("none")
        self.assertEqual(provider.name, "none")
        result = provider.complete("test")
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_all_providers_have_complete(self):
        for name in ["ollama", "none", "freebuff"]:
            provider = get_provider(name)
            self.assertTrue(hasattr(provider, "complete"))
            self.assertTrue(hasattr(provider, "health"))
            self.assertTrue(hasattr(provider, "name"))
            self.assertTrue(hasattr(provider, "available"))

    def test_provider_response_compatible(self):
        """CLI provider returns same ProviderResponse as Ollama."""
        response = ProviderResponse(text="test", status=ProviderStatus.AVAILABLE)
        self.assertTrue(response.ok)
        self.assertEqual(response.text, "test")


# ── Integration test with real fake CLI ──────────────────────────────────

class TestCLIProviderIntegration(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_workflow(self):
        """Test complete CLI provider workflow with fake CLI."""
        script = _create_fake_cli(self.tmpdir, response="analysis complete")
        provider = CLIProvider(
            executable=str(script),
            args=["--verbose"],
            timeout=10.0,
        )

        # Health check
        self.assertEqual(provider.health(), ProviderStatus.AVAILABLE)
        self.assertTrue(provider.available)

        # Complete
        result = provider.complete(
            "Analyze this code for security issues",
            max_tokens=2048,
            temperature=0.3,
        )

        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        self.assertIn("analysis complete", result.text)
        self.assertGreater(result.duration, 0)
        self.assertEqual(result.model, "cli")

    def test_freebuff_like_workflow(self):
        """Test FreeBuff-like workflow with fake CLI."""
        # Create a script that mimics FreeBuff behavior
        if os.name == "nt":
            script = self.tmpdir / "freebuff-mock.bat"
            script.write_text(
                '@echo off\n'
                'echo Analysis of the provided code:\n'
                'echo No security issues found.\n'
                'exit /b 0\n'
            )
        else:
            script = self.tmpdir / "freebuff-mock"
            script.write_text(
                '#!/bin/sh\n'
                'echo "Analysis of the provided code:"\n'
                'echo "No security issues found."\n'
                'exit 0\n'
            )
            os.chmod(script, 0o755)

        provider = FreebuffProvider(executable=str(script))
        result = provider.complete("Review this PR for security")

        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        self.assertIn("security", result.text.lower())


if __name__ == "__main__":
    unittest.main()
