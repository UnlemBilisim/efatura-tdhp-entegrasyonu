"""Model saglayici katmani: model spec ayristirma ve 6 farkli saglayici
(Ollama/OpenAI/Anthropic/Google/OpenAI-uyumlu) icin API cagrilari."""

import os
import time

import requests

KNOWN_PROVIDERS = {"ollama", "openai", "anthropic", "google"}


def parse_model_spec(spec, default_ollama_host):
    """'--models' listesindeki tek bir girdiyi provider/model/base_url/api_key_env'e ayirir."""
    if spec.startswith("openai-compat:"):
        rest = spec[len("openai-compat:"):]
        parts = rest.split("|")
        if len(parts) < 2:
            raise ValueError(f"openai-compat spec formati hatali: '{spec}' (bekleniyor: openai-compat:<base_url>|<model>[|<API_KEY_ENV>])")
        base_url = parts[0]
        model = parts[1]
        api_key_env = parts[2] if len(parts) > 2 else None
        return {"provider": "openai-compat", "model": model, "base_url": base_url, "api_key_env": api_key_env, "label": spec}

    prefix, sep, rest = spec.partition(":")
    if sep and prefix.lower() in KNOWN_PROVIDERS:
        provider = prefix.lower()
        base_url = default_ollama_host if provider == "ollama" else None
        return {"provider": provider, "model": rest, "base_url": base_url, "api_key_env": None, "label": spec}

    # onek yok / taninmayan onek -> geriye donuk uyumluluk icin duz Ollama model adi say
    return {"provider": "ollama", "model": spec, "base_url": default_ollama_host, "api_key_env": None, "label": spec}


PERMANENT_HTTP_ERRORS = {
    404: "Model '{model}' bulunamadi (404). Once 'ollama pull {model}' calistirin.",
    403: "Yetki hatasi (403) - bu model hesabinizda/planinizda erisilebilir olmayabilir. Tekrar denemek yardimci olmaz.",
    401: "Kimlik dogrulama hatasi (401) - API key gecersiz ya da eksik.",
}


def call_ollama_messages(host, model, messages, temperature, timeout, retries=3):
    """Genel amacli, tam mesaj listesi kabul eden versiyon - cok turlu
    (multi-turn) konusmalar icin (orn. self-correction takip mesaji)."""
    url = host.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "format": "json",
        "stream": False,
        "options": {"temperature": temperature},
    }
    last_err = None
    for attempt in range(1, retries + 1):
        start = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            latency = time.time() - start
            if resp.status_code in PERMANENT_HTTP_ERRORS:
                # kalici hata: retry zaman kaybi, hemen don
                return None, None, PERMANENT_HTTP_ERRORS[resp.status_code].format(model=model)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else min(5 * (2 ** attempt), 60)
                last_err = RuntimeError(f"429 Too Many Requests (Retry-After={retry_after})")
                if attempt < retries:
                    time.sleep(wait)
                    continue
                return None, None, "429 Too Many Requests - rate limit asildi, retries tukendi"
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            return content, latency, None
        except Exception as exc:  # noqa: BLE001 - network/timeouts vary by backend
            last_err = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 10))
                continue
    return None, None, str(last_err)


def call_ollama(host, model, system_prompt, user_prompt, temperature, timeout, retries=3):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return call_ollama_messages(host, model, messages, temperature, timeout, retries)


def build_balance_correction_request(metrics):
    """Dengesiz (Borc != Alacak) bir cevap icin duzeltme istegi metni."""
    return (
        f"Onceki cevabin cift-tarafli (double-entry) olarak DENGESIZ: "
        f"Borc toplami {metrics['borc_total']:.2f}, Alacak toplami {metrics['alacak_total']:.2f} "
        f"- esit degil. Ayni faturayi tekrar incele (ozellikle tevkifatli KDV varsa "
        f"tutarlarin dogru bolustugunden emin ol) ve SADECE duzeltilmis JSON'u tekrar "
        f"don, baska hicbir metin ekleme."
    )


def build_correction_messages(system_prompt, user_prompt, raw_response, correction_request):
    """Onceki bir cevaptan sonra modele ikinci bir sans vermek icin cok turlu
    mesaj listesi olusturur. correction_request, tetikleyen sebebe gore
    hazirlanir - dengesizlik icin build_balance_correction_request, RAG
    emsaline uymama icin rag_common.build_precedent_correction_request."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": raw_response},
        {"role": "user", "content": correction_request},
    ]


def self_correct_ollama(host, model, system_prompt, user_prompt, raw_response, correction_request, temperature, timeout, retries=3):
    messages = build_correction_messages(system_prompt, user_prompt, raw_response, correction_request)
    return call_ollama_messages(host, model, messages, temperature, timeout, retries)


def call_openai_style(url, headers, model, system_prompt, user_prompt, temperature, timeout, retries=3, use_json_mode=True):
    """OpenAI Chat Completions semasini konusan her servis icin ortak cagri (OpenAI, Groq,
    DeepSeek, Together, Fireworks, Mistral, vLLM OpenAI server, ...)."""
    base_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    last_err = None
    json_mode = use_json_mode
    for attempt in range(1, retries + 1):
        payload = dict(base_payload)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        start = time.time()
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            latency = time.time() - start
            if resp.status_code == 400 and json_mode:
                # bazi 3. parti servisler response_format'i desteklemiyor; onsuz tekrar dene
                json_mode = False
                continue
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content, latency, None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 10))
                continue
    return None, None, str(last_err)


def call_openai(model, system_prompt, user_prompt, temperature, timeout, retries=3):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, None, "OPENAI_API_KEY ortam degiskeni tanimli degil"
    headers = {"Authorization": f"Bearer {api_key}"}
    url = "https://api.openai.com/v1/chat/completions"
    return call_openai_style(url, headers, model, system_prompt, user_prompt, temperature, timeout, retries)


def call_openai_compat(base_url, api_key_env, model, system_prompt, user_prompt, temperature, timeout, retries=3):
    headers = {}
    if api_key_env:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            return None, None, f"{api_key_env} ortam degiskeni tanimli degil"
        headers["Authorization"] = f"Bearer {api_key}"
    url = base_url.rstrip("/") + "/chat/completions"
    return call_openai_style(url, headers, model, system_prompt, user_prompt, temperature, timeout, retries)


def call_anthropic(model, system_prompt, user_prompt, temperature, timeout, retries=3):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, None, "ANTHROPIC_API_KEY ortam degiskeni tanimli degil"
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    last_err = None
    for attempt in range(1, retries + 1):
        start = time.time()
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            latency = time.time() - start
            resp.raise_for_status()
            data = resp.json()
            content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return content, latency, None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 10))
                continue
    return None, None, str(last_err)


def call_google(model, system_prompt, user_prompt, temperature, timeout, retries=3):
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, None, "GOOGLE_API_KEY / GEMINI_API_KEY ortam degiskeni tanimli degil"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    last_err = None
    for attempt in range(1, retries + 1):
        start = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            latency = time.time() - start
            resp.raise_for_status()
            data = resp.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return content, latency, None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 10))
                continue
    return None, None, str(last_err)


def call_model(spec, system_prompt, user_prompt, temperature, timeout, retries=3):
    provider = spec["provider"]
    model = spec["model"]
    if provider == "ollama":
        return call_ollama(spec["base_url"], model, system_prompt, user_prompt, temperature, timeout, retries)
    if provider == "openai":
        return call_openai(model, system_prompt, user_prompt, temperature, timeout, retries)
    if provider == "anthropic":
        return call_anthropic(model, system_prompt, user_prompt, temperature, timeout, retries)
    if provider == "google":
        return call_google(model, system_prompt, user_prompt, temperature, timeout, retries)
    if provider == "openai-compat":
        return call_openai_compat(spec["base_url"], spec["api_key_env"], model, system_prompt, user_prompt, temperature, timeout, retries)
    raise ValueError(f"Bilinmeyen provider: {provider}")
