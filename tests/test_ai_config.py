import os
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2
from datapilot.config import AppConfig
from datapilot.llm_provider import (
    AZURE_TOKEN_SCOPE,
    AzureCliBearerAuth,
    configured_providers,
    create_chat_model,
    create_completion_with_fallback,
    create_openai_clients,
)
from openai import OpenAI


class ProviderConfigurationTests(unittest.TestCase):
    def test_google_document_ai_settings_are_centralized_without_repr_secrets(self):
        env = {
            "GCP_PROJECT_ID": "project-test",
            "GCP_LOCATION": "asia-south1",
            "DOCAI_PROCESSOR_ID": "processor-test",
            "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/service-account.json",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = AppConfig.from_environment()

        self.assertEqual(settings.gcp_project_id, "project-test")
        self.assertEqual(settings.gcp_location, "asia-south1")
        self.assertEqual(settings.docai_processor_id, "processor-test")
        self.assertNotIn("service-account.json", repr(settings))

    def test_azure_cli_auth_mode_is_loaded_from_environment(self):
        with patch.dict(
            os.environ,
            {"AZURE_OPENAI_AUTH_MODE": "azure-cli"},
            clear=True,
        ):
            settings = AppConfig.from_environment()

        self.assertEqual(settings.azure_auth_mode, "azure-cli")

    def test_azure_proxy_follows_gemini_as_the_configured_fallback(self):
        env = {
            "AI_PRIMARY_PROVIDER": "gemini",
            "GEMINI_API_KEY": "gemini-test",
            "GEMINI_MODEL": "gemini-test-model",
            "AZURE_OPENAI_BASE_URL": "https://proxy.example/v1",
            "AZURE_OPENAI_API_KEY": "azure-test",
            "AZURE_OPENAI_MODEL": "azure-test-deployment",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = configured_providers()

        self.assertEqual([provider.name for provider in providers], [
            "Gemini",
            "Azure OpenAI-compatible provider",
        ])
        self.assertEqual(providers[0].model, "gemini-test-model")
        self.assertEqual(providers[1].base_url, "https://proxy.example/v1")
        self.assertEqual(providers[1].model, "azure-test-deployment")

    def test_missing_gemini_uses_configured_azure_provider(self):
        env = {
            "AI_PRIMARY_PROVIDER": "gemini",
            "GEMINI_API_KEY": "",
            "AZURE_OPENAI_BASE_URL": "https://proxy.example/v1",
            "AZURE_OPENAI_API_KEY": "azure-test",
            "AZURE_OPENAI_MODEL": "azure-test-deployment",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = configured_providers()

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].name, "Azure OpenAI-compatible provider")

    def test_azure_foundry_environment_and_provider_alias_are_supported(self):
        env = {
            "TRACEROOT_PROVIDER": "azure",
            "AZURE_FOUNDRY_ENDPOINT": (
                "https://foundry.example/openai/v1/chat/completions"
            ),
            "AZURE_FOUNDRY_API_KEY": "foundry-test",
            "AZURE_FOUNDRY_MODEL": "foundry-deployment",
            "GEMINI_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = configured_providers()

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].name, "Azure OpenAI-compatible provider")
        self.assertEqual(providers[0].base_url, "https://foundry.example/openai/v1")
        self.assertEqual(providers[0].model, "foundry-deployment")

    def test_azure_resource_endpoint_uses_openai_v1_route(self):
        env = {
            "AI_PRIMARY_PROVIDER": "azure",
            "AZURE_OPENAI_BASE_URL": "https://resource.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "azure-test",
            "AZURE_OPENAI_MODEL": "azure-deployment",
            "GEMINI_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = configured_providers()

        self.assertEqual(
            providers[0].base_url,
            "https://resource.openai.azure.com/openai/v1",
        )

    def test_azure_cli_auth_works_without_an_api_key(self):
        env = {
            "AI_PRIMARY_PROVIDER": "azure",
            "AZURE_OPENAI_AUTH_MODE": "azure-cli",
            "AZURE_OPENAI_BASE_URL": "https://resource.openai.azure.com",
            "AZURE_OPENAI_MODEL": "azure-deployment",
            "AZURE_OPENAI_API_KEY": "",
            "GEMINI_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = configured_providers()

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].auth_mode, "azure-cli")
        self.assertEqual(
            providers[0].base_url,
            "https://resource.openai.azure.com/openai/v1",
        )

    def test_azure_cli_auth_overrides_the_openai_api_key_header(self):
        credential = SimpleNamespace(
            get_token=MagicMock(
                return_value=SimpleNamespace(
                    token="cli-access-token",
                    expires_on=4_000_000_000,
                )
            )
        )
        auth = AzureCliBearerAuth(credential=credential)
        requests = []

        with httpx2.Client(
            auth=auth,
            transport=httpx2.MockTransport(
                lambda request: (
                    requests.append(request)
                    or httpx2.Response(200, request=request)
                )
            ),
        ) as client:
            client.get("https://resource.openai.azure.com/openai/v1/models")

        self.assertEqual(
            requests[0].headers["Authorization"],
            "Bearer cli-access-token",
        )
        credential.get_token.assert_called_once_with(AZURE_TOKEN_SCOPE)

    def test_openai_completion_uses_cli_bearer_on_the_v1_chat_route(self):
        credential = SimpleNamespace(
            get_token=MagicMock(
                return_value=SimpleNamespace(
                    token="cli-access-token",
                    expires_on=4_000_000_000,
                )
            )
        )
        requests = []

        def respond(request):
            requests.append(request)
            return httpx2.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "azure-deployment",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Hello"},
                            "finish_reason": "stop",
                        }
                    ],
                },
                request=request,
            )

        with httpx2.Client(
            auth=AzureCliBearerAuth(credential=credential),
            transport=httpx2.MockTransport(respond),
        ) as http_client:
            with OpenAI(
                api_key="azure-cli",
                base_url="https://resource.openai.azure.com/openai/v1",
                http_client=http_client,
                max_retries=0,
            ) as client:
                completion = client.chat.completions.create(
                    model="azure-deployment",
                    messages=[{"role": "user", "content": "Hi"}],
                )

        self.assertEqual(completion.choices[0].message.content, "Hello")
        self.assertEqual(
            requests[0].url.path,
            "/openai/v1/chat/completions",
        )
        self.assertEqual(
            requests[0].headers["Authorization"],
            "Bearer cli-access-token",
        )

    def test_azure_cli_auth_is_applied_to_async_requests(self):
        credential = SimpleNamespace(
            get_token=MagicMock(
                return_value=SimpleNamespace(
                    token="cli-access-token",
                    expires_on=4_000_000_000,
                )
            )
        )
        auth = AzureCliBearerAuth(credential=credential)
        requests = []

        async def send_request():
            async with httpx2.AsyncClient(
                auth=auth,
                transport=httpx2.MockTransport(
                    lambda request: (
                        requests.append(request)
                        or httpx2.Response(200, request=request)
                    )
                ),
            ) as client:
                await client.get("https://resource.openai.azure.com/openai/v1/models")

        asyncio.run(send_request())

        self.assertEqual(
            requests[0].headers["Authorization"],
            "Bearer cli-access-token",
        )
        credential.get_token.assert_called_once_with(AZURE_TOKEN_SCOPE)

    def test_azure_cli_auth_is_shared_by_chat_and_completion_clients(self):
        env = {
            "AI_PRIMARY_PROVIDER": "azure",
            "AZURE_OPENAI_AUTH_MODE": "azure-cli",
            "AZURE_OPENAI_BASE_URL": "https://resource.openai.azure.com",
            "AZURE_OPENAI_MODEL": "azure-deployment",
            "GEMINI_API_KEY": "",
        }
        sync_client = MagicMock()
        async_client = MagicMock()
        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "datapilot.llm_provider._azure_cli_http_clients",
                return_value=(sync_client, async_client),
            ),
            patch("datapilot.llm_provider.ChatOpenAI") as chat_openai,
            patch("datapilot.llm_provider.OpenAI") as openai,
        ):
            create_chat_model(streaming=True)
            clients = create_openai_clients()

        chat_openai.assert_called_once_with(
            model="azure-deployment",
            api_key="azure-cli",
            http_client=sync_client,
            http_async_client=async_client,
            base_url="https://resource.openai.azure.com/openai/v1",
            streaming=True,
        )
        openai.assert_called_once_with(
            api_key="azure-cli",
            http_client=sync_client,
            http_async_client=async_client,
            base_url="https://resource.openai.azure.com/openai/v1",
        )
        self.assertEqual(len(clients), 1)

    def test_azure_v1_proxy_url_is_preserved(self):
        env = {
            "AI_PRIMARY_PROVIDER": "azure",
            "AZURE_OPENAI_BASE_URL": "https://proxy.example/v1",
            "AZURE_OPENAI_API_KEY": "azure-test",
            "AZURE_OPENAI_MODEL": "azure-deployment",
            "GEMINI_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = configured_providers()

        self.assertEqual(providers[0].base_url, "https://proxy.example/v1")

    def test_gemini_uses_its_separate_openai_compatible_endpoint(self):
        env = {
            "AI_PRIMARY_PROVIDER": "gemini",
            "GEMINI_API_KEY": "gemini-test",
            "GEMINI_MODEL": "gemini-test-model",
            "AZURE_OPENAI_BASE_URL": "",
            "AZURE_OPENAI_API_KEY": "",
            "AZURE_OPENAI_MODEL": "",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = configured_providers()

        self.assertEqual(
            providers[0].base_url,
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    def test_incomplete_azure_configuration_fails_explicitly(self):
        env = {
            "GEMINI_API_KEY": "gemini-test",
            "AZURE_OPENAI_BASE_URL": "https://proxy.example/v1",
            "AZURE_OPENAI_API_KEY": "",
            "AZURE_OPENAI_MODEL": "",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Configure the Azure endpoint"):
                configured_providers()

    def test_chat_model_wraps_secondary_provider_as_runtime_fallback(self):
        primary = MagicMock()
        fallback = MagicMock()
        primary.with_fallbacks.return_value = "model-with-fallback"
        env = {
            "AI_PRIMARY_PROVIDER": "gemini",
            "GEMINI_API_KEY": "gemini-test",
            "GEMINI_MODEL": "gemini-test-model",
            "AZURE_OPENAI_BASE_URL": "https://proxy.example/v1",
            "AZURE_OPENAI_API_KEY": "azure-test",
            "AZURE_OPENAI_MODEL": "azure-model",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "datapilot.llm_provider.ChatOpenAI",
                side_effect=[primary, fallback],
            ) as chat_openai,
        ):
            model = create_chat_model(temperature=0.1, streaming=True)

        self.assertEqual(model, "model-with-fallback")
        self.assertEqual(chat_openai.call_count, 2)
        self.assertEqual(chat_openai.call_args_list[0].kwargs["model"], "gemini-test-model")
        self.assertEqual(chat_openai.call_args_list[1].kwargs["model"], "azure-model")
        primary.with_fallbacks.assert_called_once_with([fallback])

    def test_openai_compatible_request_falls_back_after_primary_error(self):
        first_create = MagicMock(side_effect=ConnectionError("primary unavailable"))
        second_create = MagicMock(return_value="azure response")
        clients = [
            (
                SimpleNamespace(name="Gemini", model="gemini-model"),
                SimpleNamespace(
                    chat=SimpleNamespace(
                        completions=SimpleNamespace(create=first_create)
                    )
                ),
            ),
            (
                SimpleNamespace(name="Azure proxy", model="azure-model"),
                SimpleNamespace(
                    chat=SimpleNamespace(
                        completions=SimpleNamespace(create=second_create)
                    )
                ),
            ),
        ]

        result = create_completion_with_fallback(clients, messages=[])

        self.assertEqual(result, "azure response")
        first_create.assert_called_once_with(model="gemini-model", messages=[])
        second_create.assert_called_once_with(model="azure-model", messages=[])

    def test_all_provider_failures_surface_the_last_error(self):
        failure = ConnectionError("fallback unavailable")
        clients = [
            (
                SimpleNamespace(name="Azure proxy", model="azure-model"),
                SimpleNamespace(
                    chat=SimpleNamespace(
                        completions=SimpleNamespace(
                            create=MagicMock(side_effect=failure)
                        )
                    )
                ),
            )
        ]
        with self.assertRaisesRegex(ConnectionError, "fallback unavailable"):
            create_completion_with_fallback(clients, messages=[])


if __name__ == "__main__":
    unittest.main()
