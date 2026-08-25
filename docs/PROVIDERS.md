# AI Providers

The orchestrator is **provider-agnostic**. It coordinates tools and workflows
without depending on any specific AI model or service.

## Architecture

```
Agent -> AIProvider -> Provider Implementation -> AI System
```

The `AIProvider` protocol defines the interface that all providers must implement.

## Built-in Providers

### NoneProvider

No AI. Agents produce deterministic output.

### OllamaProvider

Local Ollama models via HTTP. No API key required.

### CLIProvider

Generic CLI-based AI tool. Executes an external program via subprocess.
Prompts are delivered through stdin. No API key required.

### FreebuffProvider

FreeBuff CLI -- a specific implementation of CLIProvider.
FreeBuff is **one supported provider**, not the project's identity.

## Implementing a Custom Provider

```python
from orchestrator.providers import AIProvider, ProviderResponse, ProviderStatus

class MyProvider:
    @property
    def name(self) -> str:
        return "my-provider"

    @property
    def available(self) -> bool:
        return True

    def complete(self, prompt, *, model="", max_tokens=4096,
                 temperature=0.7, timeout=60.0) -> ProviderResponse:
        return ProviderResponse(text="response", status=ProviderStatus.AVAILABLE)

    def health(self) -> ProviderStatus:
        return ProviderStatus.AVAILABLE
```

Register in `providers.py` `get_provider()` and add to `validate.py` config schema.
