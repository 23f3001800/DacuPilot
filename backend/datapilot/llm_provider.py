import logging
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx2
from langchain_openai import ChatOpenAI
from openai import OpenAI

from .config import AppConfig, Config, get_config

logger = logging.getLogger("datapilot.providers")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
AZURE_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureCliBearerAuth(httpx2.Auth):
    def __init__(self, credential=None):
        if credential is None:
            from azure.identity import AzureCliCredential

            credential = AzureCliCredential()
        self._credential = credential
        self._lock = threading.Lock()
        self._token = ""
        self._expires_on = 0

    def _access_token(self) -> str:
        with self._lock:
            if self._token and self._expires_on > time.time() + 120:
                return self._token
            token = self._credential.get_token(AZURE_TOKEN_SCOPE)
            self._token = token.token
            self._expires_on = token.expires_on
            return self._token

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self._access_token()}"
        yield request

    async def async_auth_flow(self, request):
        import asyncio

        request.headers["Authorization"] = (
            f"Bearer {await asyncio.to_thread(self._access_token)}"
        )
        yield request


@lru_cache(maxsize=1)
def _azure_cli_http_clients():
    auth = AzureCliBearerAuth()
    return httpx2.Client(auth=auth), httpx2.AsyncClient(auth=auth)


def _client_auth_options(provider: "ModelProvider") -> dict[str, Any]:
    if provider.auth_mode == "azure-cli":
        http_client, http_async_client = _azure_cli_http_clients()
        return {
            "api_key": "azure-cli",
            "http_client": http_client,
            "http_async_client": http_async_client,
        }
    return {"api_key": provider.api_key}


def _azure_openai_base_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint.rstrip("/"))
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]

    normalized_path = path.lower()
    if normalized_path.endswith("/openai"):
        path += "/v1"
    elif not normalized_path.endswith(("/openai/v1", "/v1")):
        path += "/openai/v1"

    return urlunsplit(parsed._replace(path=path, fragment=""))


@dataclass(frozen=True)
class ModelProvider:
    name: str
    base_url: str
    api_key: str = field(repr=False)
    model: str
    auth_mode: str = "api-key"


def configured_providers(config: AppConfig | None = None) -> list[ModelProvider]:
    settings = config or get_config()
    if settings.azure_auth_mode not in {"api-key", "azure-cli"}:
        raise RuntimeError(
            "AZURE_OPENAI_AUTH_MODE must be 'api-key' or 'azure-cli'."
        )

    azure_endpoint_configured = bool(settings.azure_base_url or settings.azure_model)
    azure_ready = bool(settings.azure_base_url and settings.azure_model)
    if settings.azure_auth_mode == "api-key":
        azure_endpoint_configured = azure_endpoint_configured or bool(
            settings.azure_api_key
        )
        azure_ready = azure_ready and bool(settings.azure_api_key)
        if azure_endpoint_configured and not azure_ready:
            raise RuntimeError(
                "Configure the Azure endpoint, API key, and model together "
                "(AZURE_OPENAI_* or AZURE_FOUNDRY_*)."
            )
    elif azure_endpoint_configured and not azure_ready:
        raise RuntimeError(
            "Configure the Azure endpoint and model together when using "
            "AZURE_OPENAI_AUTH_MODE=azure-cli."
        )

    openai_ready = bool(
        settings.openai_api_key
        or (settings.openai_base_url and settings.openai_base_url.rstrip("/") != "https://api.openai.com/v1")
    )

    providers = {
        "openai": (
            ModelProvider(
                name="OpenAI",
                base_url=settings.openai_base_url or "https://api.openai.com/v1",
                api_key=settings.openai_api_key or "local",
                model=settings.openai_model or "gpt-4o",
            )
            if openai_ready
            else None
        ),
        "gemini": (
            ModelProvider(
                name="Gemini",
                base_url=GEMINI_BASE_URL,
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
            )
            if settings.gemini_api_key
            else None
        ),
        "azure": (
            ModelProvider(
                name="Azure OpenAI-compatible provider",
                base_url=_azure_openai_base_url(settings.azure_base_url),
                api_key=settings.azure_api_key,
                model=settings.azure_model,
                auth_mode=settings.azure_auth_mode,
            )
            if azure_ready
            else None
        ),
    }
    if settings.ai_primary_provider not in providers:
        raise RuntimeError(
            "AI_PRIMARY_PROVIDER must be 'openai', 'gemini', or 'azure'; "
            "TRACEROOT_PROVIDER is also accepted."
        )

    order = [settings.ai_primary_provider] + [
        k for k in ["gemini", "azure", "openai"] if k != settings.ai_primary_provider
    ]
    configured = [providers[k] for k in order if providers.get(k) is not None]
    if not configured:
        raise RuntimeError(
            "Configure GEMINI_API_KEY or OPENAI_API_KEY or the Azure OpenAI-compatible provider "
            "settings to use AI features."
        )
    return configured


def configured_provider_names() -> list[str]:
    return [provider.name for provider in configured_providers()]


def create_chat_model(**kwargs: Any) -> ChatOpenAI:
    providers = configured_providers()
    models = [
        ChatOpenAI(
            model=provider.model,
            **_client_auth_options(provider),
            base_url=provider.base_url,
            **kwargs,
        )
        for provider in providers
    ]
    if len(models) == 1:
        return models[0]
    return models[0].with_fallbacks(models[1:])


def create_openai_clients() -> list[tuple[ModelProvider, OpenAI]]:
    return [
        (
            provider,
            OpenAI(
                **_client_auth_options(provider),
                base_url=provider.base_url,
            ),
        )
        for provider in configured_providers()
    ]


def _uses_max_completion_tokens(model_name: str) -> bool:
    """Return True for models that require max_completion_tokens instead of max_tokens."""
    name = model_name.lower()
    return any(
        keyword in name
        for keyword in ("o1", "o3", "o4", "gpt-5", "gpt5")
    )


def create_completion_with_fallback(clients, **kwargs):
    """Try configured OpenAI-compatible services in priority order."""
    last_error = None
    for provider, client in clients:
        call_kwargs = dict(kwargs)
        # Normalize max_tokens → max_completion_tokens for reasoning models
        if "max_tokens" in call_kwargs and _uses_max_completion_tokens(provider.model):
            call_kwargs["max_completion_tokens"] = call_kwargs.pop("max_tokens")
        try:
            return client.chat.completions.create(
                model=provider.model,
                **call_kwargs,
            )
        except Exception as error:
            last_error = error
            logger.warning(
                "Provider %s failed; trying the next configured provider (%s).",
                provider.name,
                type(error).__name__,
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError("No AI providers are configured.")


def public_settings() -> dict[str, object]:
    try:
        provider_list = configured_providers()
        providers = [p.name for p in provider_list]
        active_model = provider_list[0].model if provider_list else "N/A"
        active_endpoint = provider_list[0].base_url if provider_list else "N/A"
    except RuntimeError:
        providers = []
        active_model = "N/A"
        active_endpoint = "N/A"
    settings = get_config()
    google_ocr_active = bool(settings.gcp_project_id and settings.docai_processor_id)
    azure_ocr_active = bool(
        settings.azure_document_intelligence_endpoint
        and settings.azure_document_intelligence_key
    )
    return {
        "primary_provider": (
            providers[0] if providers else settings.ai_primary_provider.title()
        ),
        "available_providers": providers,
        "active_model": active_model,
        "active_endpoint": active_endpoint,
        "confidence_threshold": Config.FIELD_CONFIDENCE_THRESHOLD,
        "handwriting_penalty": Config.HANDWRITTEN_PENALTY,
        "google_ocr_configured": google_ocr_active,
        "azure_ocr_configured": azure_ocr_active,
        "ocr_priority": "Azure Document Intelligence (Primary) → Google Cloud Document AI (Secondary) → Vision LLM (Fallback)",
    }
