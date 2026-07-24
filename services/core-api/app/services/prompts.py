from dataclasses import dataclass
from typing import Any

from langfuse import Langfuse

from app.config import Settings
from app.services.tracing import mask_otel_spans

_shared_langfuse: Langfuse | None = None
_shared_langfuse_built = False


def get_shared_langfuse(settings: Settings) -> Langfuse | None:
    """One Langfuse client per process, shared by every PromptRepository.

    Each persona (support answer, triage, commerce insight, monthly report)
    gets its own PromptRepository instance, but they all export traces
    through the same Langfuse background worker instead of one per persona.
    """
    global _shared_langfuse, _shared_langfuse_built
    if not _shared_langfuse_built:
        _shared_langfuse_built = True
        if settings.langfuse_enabled:
            _shared_langfuse = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                base_url=settings.langfuse_base_url,
                environment=settings.app_env,
                release=settings.app_version,
                sample_rate=settings.langfuse_sample_rate,
                mask_otel_spans=mask_otel_spans,
            )
    return _shared_langfuse


@dataclass(slots=True)
class CompiledPrompt:
    text: str
    name: str
    source: str
    version: str | None
    config: dict[str, Any]
    langfuse_prompt: Any | None = None

    @property
    def model(self) -> str:
        return str(self.config["model"])

    @property
    def completion_parameters(self) -> dict[str, Any]:
        allowed = ("temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty")
        return {key: self.config[key] for key in allowed if key in self.config}

    @property
    def routing_parameters(self) -> dict[str, Any]:
        allowed = ("models", "provider")
        return {key: self.config[key] for key in allowed if key in self.config}


class PromptRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._langfuse = get_shared_langfuse(settings)

    def compile(
        self,
        *,
        prompt_name: str,
        fallback_text: str,
        fallback_config: dict[str, Any],
        variables: dict[str, str],
    ) -> CompiledPrompt:
        if self._langfuse is not None:
            try:
                prompt = self._langfuse.get_prompt(
                    prompt_name,
                    type="text",
                    label=self.settings.langfuse_prompt_label,
                    cache_ttl_seconds=self.settings.langfuse_prompt_cache_ttl_seconds,
                    fallback=fallback_text,
                )
                source = "fallback" if getattr(prompt, "is_fallback", False) else "langfuse"
                version = getattr(prompt, "version", None)
                return CompiledPrompt(
                    text=prompt.compile(**variables),
                    name=prompt_name,
                    source=source,
                    version=str(version) if version is not None else None,
                    config=self._runtime_config(fallback_config, getattr(prompt, "config", None)),
                    langfuse_prompt=None if getattr(prompt, "is_fallback", False) else prompt,
                )
            except Exception:
                pass

        text = fallback_text
        for key, value in variables.items():
            text = text.replace("{{" + key + "}}", value)
        return CompiledPrompt(
            text=text,
            name=prompt_name,
            source="fallback",
            version=None,
            config=self._runtime_config(fallback_config, None),
            langfuse_prompt=None,
        )

    def _runtime_config(
        self, fallback_config: dict[str, Any], remote: Any | None
    ) -> dict[str, Any]:
        config = {**fallback_config}
        config["model"] = self.settings.openrouter_default_model
        if isinstance(remote, dict):
            config.update(remote)

        model = config.get("model")
        if not isinstance(model, str) or not model.strip():
            config["model"] = self.settings.openrouter_default_model
        else:
            config["model"] = model.strip()

        if config.get("gateway", "openrouter") != "openrouter":
            raise ValueError("AI Ops Studio currently supports OpenRouter prompt configs only.")
        return config

    @property
    def langfuse(self):
        return self._langfuse
