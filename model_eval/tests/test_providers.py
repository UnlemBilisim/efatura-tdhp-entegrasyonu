"""core.providers icin birim testleri.

Calistirmak icin:
    cd model_eval
    python3 -m pytest tests/ -v
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.providers as providers


# ---------------------------------------------------------------------------
# parse_model_spec — provider/model/base_url ayristirma (Ollama + bulut)
# ---------------------------------------------------------------------------

class TestParseModelSpec:
    HOST = "http://localhost:11434"

    def test_bare_ollama_model_backward_compat(self):
        spec = providers.parse_model_spec("qwen2.5:14b-instruct", self.HOST)
        assert spec == {
            "provider": "ollama",
            "model": "qwen2.5:14b-instruct",
            "base_url": self.HOST,
            "api_key_env": None,
            "label": "qwen2.5:14b-instruct",
        }

    def test_explicit_ollama_prefix(self):
        spec = providers.parse_model_spec("ollama:qwen2.5:14b-instruct", self.HOST)
        assert spec["provider"] == "ollama"
        assert spec["model"] == "qwen2.5:14b-instruct"

    def test_openai_prefix(self):
        spec = providers.parse_model_spec("openai:gpt-4.1", self.HOST)
        assert spec["provider"] == "openai"
        assert spec["model"] == "gpt-4.1"
        assert spec["base_url"] is None

    def test_anthropic_prefix(self):
        spec = providers.parse_model_spec("anthropic:claude-sonnet-5", self.HOST)
        assert spec["provider"] == "anthropic"
        assert spec["model"] == "claude-sonnet-5"

    def test_google_prefix(self):
        spec = providers.parse_model_spec("google:gemini-2.5-pro", self.HOST)
        assert spec["provider"] == "google"
        assert spec["model"] == "gemini-2.5-pro"

    def test_openai_compat_with_api_key_env(self):
        spec = providers.parse_model_spec(
            "openai-compat:https://api.groq.com/openai/v1|llama-3.3-70b-versatile|GROQ_API_KEY", self.HOST
        )
        assert spec["provider"] == "openai-compat"
        assert spec["base_url"] == "https://api.groq.com/openai/v1"
        assert spec["model"] == "llama-3.3-70b-versatile"
        assert spec["api_key_env"] == "GROQ_API_KEY"

    def test_openai_compat_without_api_key_env(self):
        spec = providers.parse_model_spec("openai-compat:http://localhost:8000/v1|my-model", self.HOST)
        assert spec["api_key_env"] is None

    def test_openai_compat_missing_model_raises(self):
        with pytest.raises(ValueError):
            providers.parse_model_spec("openai-compat:http://localhost:8000/v1", self.HOST)

    def test_unknown_prefix_falls_back_to_ollama(self):
        # "mistral-large" gibi ":" icermeyen ya da bilinmeyen bir onek tasiyan
        # modeller geriye donuk uyumluluk icin Ollama sayilmali.
        spec = providers.parse_model_spec("mistral-large", self.HOST)
        assert spec["provider"] == "ollama"
        assert spec["model"] == "mistral-large"


# ---------------------------------------------------------------------------
# call_* fonksiyonlari — gercek ag cagrisi yapmadan (requests.post mock'lanir)
# ---------------------------------------------------------------------------

def _fake_response(status_code=200, json_body=None, raise_on=None, headers=None):
    resp = SimpleNamespace()
    resp.status_code = status_code
    resp.json = lambda: json_body
    resp.headers = headers or {}

    def raise_for_status():
        if raise_on:
            raise raise_on
    resp.raise_for_status = raise_for_status
    return resp


class TestCallOllama:
    def test_success_returns_content_and_latency(self):
        fake = _fake_response(200, {"message": {"content": '{"entries": []}'}})
        with patch.object(providers.requests, "post", return_value=fake) as mock_post:
            content, latency, err = providers.call_ollama("http://localhost:11434", "qwen2.5", "sys", "usr", 0.0, 30)
        assert content == '{"entries": []}'
        assert err is None
        assert latency is not None
        called_url = mock_post.call_args.args[0]
        assert called_url == "http://localhost:11434/api/chat"

    def test_404_reports_model_not_found_without_retrying(self):
        fake = _fake_response(404)
        with patch.object(providers.requests, "post", return_value=fake) as mock_post:
            content, latency, err = providers.call_ollama("http://localhost:11434", "ghost-model", "sys", "usr", 0.0, 30, retries=3)
        assert content is None
        assert "bulunamadi" in err
        assert mock_post.call_count == 1  # 404 icin tekrar denenmemeli

    def test_network_error_retries_then_fails(self):
        with patch.object(providers.requests, "post", side_effect=ConnectionError("bagalanti yok")) as mock_post, \
             patch.object(providers.time, "sleep", return_value=None):
            content, latency, err = providers.call_ollama("http://localhost:11434", "qwen2.5", "sys", "usr", 0.0, 30, retries=3)
        assert content is None
        assert mock_post.call_count == 3

    @pytest.mark.parametrize("status,keyword", [(403, "Yetki"), (401, "Kimlik")])
    def test_permanent_auth_errors_fail_fast_without_retrying(self, status, keyword):
        """403/401 kalici hatalardir (rate limit degil, yetki/plan sorunu) -
        tekrar denemek zaman kaybettirir, hemen donmeli."""
        fake = _fake_response(status)
        with patch.object(providers.requests, "post", return_value=fake) as mock_post, \
             patch.object(providers.time, "sleep") as mock_sleep:
            content, latency, err = providers.call_ollama("http://localhost:11434", "glm-5:cloud", "sys", "usr", 0.0, 30, retries=3)
        assert content is None
        assert keyword in err
        assert mock_post.call_count == 1  # tekrar denenmemeli
        mock_sleep.assert_not_called()

    def test_429_retries_with_backoff_then_fails_after_exhausting_retries(self):
        fake = _fake_response(429)
        with patch.object(providers.requests, "post", return_value=fake) as mock_post, \
             patch.object(providers.time, "sleep", return_value=None) as mock_sleep:
            content, latency, err = providers.call_ollama("http://localhost:11434", "glm-5:cloud", "sys", "usr", 0.0, 30, retries=3)
        assert content is None
        assert "429" in err
        assert mock_post.call_count == 3  # retries tukenene kadar denenir
        assert mock_sleep.call_count == 2  # denemeler arasinda bekleme yapilir

    def test_429_honors_retry_after_header(self):
        fake = _fake_response(429, headers={"Retry-After": "7"})
        success = _fake_response(200, {"message": {"content": "ok"}})
        with patch.object(providers.requests, "post", side_effect=[fake, success]), \
             patch.object(providers.time, "sleep", return_value=None) as mock_sleep:
            content, latency, err = providers.call_ollama("http://localhost:11434", "glm-5:cloud", "sys", "usr", 0.0, 30, retries=3)
        assert content == "ok"
        assert err is None
        mock_sleep.assert_called_once_with(7.0)

    def test_429_eventual_success_on_retry_returns_content(self):
        fake = _fake_response(429)
        success = _fake_response(200, {"message": {"content": '{"entries": []}'}})
        with patch.object(providers.requests, "post", side_effect=[fake, success]), \
             patch.object(providers.time, "sleep", return_value=None):
            content, latency, err = providers.call_ollama("http://localhost:11434", "glm-5:cloud", "sys", "usr", 0.0, 30, retries=3)
        assert content == '{"entries": []}'
        assert err is None


class TestCallOpenaiStyle:
    def test_success(self):
        fake = _fake_response(200, {"choices": [{"message": {"content": '{"entries": []}'}}]})
        with patch.object(providers.requests, "post", return_value=fake):
            content, latency, err = providers.call_openai_style(
                "https://api.openai.com/v1/chat/completions", {"Authorization": "Bearer x"},
                "gpt-4.1", "sys", "usr", 0.0, 30,
            )
        assert content == '{"entries": []}'
        assert err is None

    def test_400_retries_without_json_mode(self):
        bad = _fake_response(400)
        good = _fake_response(200, {"choices": [{"message": {"content": "ok"}}]})
        with patch.object(providers.requests, "post", side_effect=[bad, good]) as mock_post:
            content, latency, err = providers.call_openai_style(
                "https://example.com/v1/chat/completions", {}, "some-model", "sys", "usr", 0.0, 30, retries=3,
            )
        assert content == "ok"
        assert err is None
        assert mock_post.call_count == 2
        # ikinci cagrida response_format artik gonderilmemis olmali
        second_call_payload = mock_post.call_args_list[1].kwargs["json"]
        assert "response_format" not in second_call_payload


class TestCallOpenaiMissingKey:
    def test_missing_api_key_short_circuits_without_network_call(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch.object(providers.requests, "post") as mock_post:
            content, latency, err = providers.call_openai("gpt-4.1", "sys", "usr", 0.0, 30)
        assert content is None
        assert "OPENAI_API_KEY" in err
        mock_post.assert_not_called()


class TestCallAnthropic:
    def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        content, latency, err = providers.call_anthropic("claude-sonnet-5", "sys", "usr", 0.0, 30)
        assert content is None
        assert "ANTHROPIC_API_KEY" in err

    def test_success_concatenates_text_blocks(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        fake = _fake_response(200, {"content": [{"type": "text", "text": '{"entries"'}, {"type": "text", "text": ": []}"}]})
        with patch.object(providers.requests, "post", return_value=fake):
            content, latency, err = providers.call_anthropic("claude-sonnet-5", "sys", "usr", 0.0, 30)
        assert content == '{"entries": []}'
        assert err is None


class TestCallGoogle:
    def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        content, latency, err = providers.call_google("gemini-2.5-pro", "sys", "usr", 0.0, 30)
        assert content is None
        assert "API_KEY" in err

    def test_success_extracts_first_candidate_text(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
        fake = _fake_response(200, {"candidates": [{"content": {"parts": [{"text": '{"entries": []}'}]}}]})
        with patch.object(providers.requests, "post", return_value=fake):
            content, latency, err = providers.call_google("gemini-2.5-pro", "sys", "usr", 0.0, 30)
        assert content == '{"entries": []}'
        assert err is None


class TestCallModelDispatch:
    def test_dispatches_to_correct_provider(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake")
        spec = providers.parse_model_spec("openai:gpt-4.1", "http://localhost:11434")
        with patch.object(providers, "call_openai", return_value=("ok", 1.0, None)) as mock_call:
            content, latency, err = providers.call_model(spec, "sys", "usr", 0.0, 30)
        assert content == "ok"
        mock_call.assert_called_once()

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            providers.call_model({"provider": "bilinmeyen", "model": "x"}, "sys", "usr", 0.0, 30)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
