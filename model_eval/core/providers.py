"""Model saglayici katmani: model spec ayristirma ve Ollama icin API cagrilari.

2026-07-29: OpenAI/Anthropic/Google/openai-compat destegi kaldirildi (kullanici
karari - "biz sadece Ollama kullanacagiz"). Sistem zaten sadece Ollama
(gemma4:31b-cloud, uzak GPU'da) kullaniyordu; entegrasyon/model_eval_koprusu.py
hic bir zaman baska bir provider'a gecmiyordu. Coklu-provider destegi
model_eval'in kendi karsilastirma/degerlendirme araci (evaluate_models.py) icin
eklenmisti, uretim akisinda kullanilmiyordu."""

import time

import requests

KNOWN_PROVIDERS = {"ollama"}


def parse_model_spec(spec, default_ollama_host):
    """'--models' listesindeki tek bir girdiyi provider/model/base_url'e ayirir.

    Onek varsa ('ollama:model-adi') acikca soyulur; onek yoksa/farkli bir
    onekse (geriye donuk uyumluluk) duz Ollama model adi sayilir."""
    prefix, sep, rest = spec.partition(":")
    if sep and prefix.lower() == "ollama":
        return {"provider": "ollama", "model": rest, "base_url": default_ollama_host, "label": spec}

    return {"provider": "ollama", "model": spec, "base_url": default_ollama_host, "label": spec}


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


def call_model(spec, system_prompt, user_prompt, temperature, timeout, retries=3):
    provider = spec["provider"]
    if provider != "ollama":
        raise ValueError(f"Bilinmeyen provider: {provider} (sadece 'ollama' destekleniyor)")
    return call_ollama(spec["base_url"], spec["model"], system_prompt, user_prompt, temperature, timeout, retries)
