#!/usr/bin/env python3
"""
Tek Duzen Hesap Plani (TDHP) bilgi testi
=========================================

Amac: Archive2/jsons icindeki gercek faturalari, icindeki "accounting_entries"
(gercek muhasebe kaydi / ground truth) cikarilmis haliyle birden fazla Ollama
modeline sirayla verip, her modelin SADECE kendi bilgisiyle (hesap plani
listesi verilmeden) dogru 3 haneli TDHP ana hesap kodunu + Borc/Alacak yonunu
uretip uretemedigini olcer.

Neden 3 haneli kod? Ground truth'taki kodlar (orn. 191.01.00020) sirkete ozel
muavin hesap numaralari icerir; bunlari bir modelin bilmesi beklenemez. Sadece
ilk 3 hane (191) TDHP'nin resmi/standart ana hesap kodudur ve modelden de
sadece bu istenir.

Model belirtme sozdizimi (--models, virgulle ayrilmis liste)
--------------------------------------------------------------
  qwen2.5:14b-instruct              -> onek yoksa Ollama modeli sayilir (host: --ollama-host)
  ollama:qwen2.5:14b-instruct       -> ayni sey, acik onekli
  openai:gpt-4.1                    -> OpenAI API (env OPENAI_API_KEY)
  anthropic:claude-sonnet-5         -> Anthropic API (env ANTHROPIC_API_KEY)
  google:gemini-2.5-pro             -> Google Gemini API (env GOOGLE_API_KEY veya GEMINI_API_KEY)
  openai-compat:<base_url>|<model>|<API_KEY_ENV>
                                     -> OpenAI-uyumlu herhangi bir servis (Groq, DeepSeek,
                                        Together, Fireworks, Mistral, vLLM OpenAI server, ...).
                                        API_KEY_ENV opsiyoneldir (belirtilmezse Authorization
                                        header'i gonderilmez, key gerektirmeyen yerel sunucular icin).

Kullanim ornekleri
-------------------
  # Tek local model, tum veri setinde (~1646 fatura)
  python evaluate_models.py --models qwen2.5:14b-instruct

  # Local + bulut modellerini AYNI KOSUDA kiyasla
  python evaluate_models.py --models qwen2.5:14b-instruct,openai:gpt-4.1,anthropic:claude-sonnet-5,google:gemini-2.5-pro

  # Sadece bulut modelleri, hepsini GERCEKTEN AYNI ANDA (paralel) calistir
  python evaluate_models.py --models openai:gpt-4.1,anthropic:claude-sonnet-5,google:gemini-2.5-pro --model-parallelism 3

  # OpenAI-uyumlu 3. parti bir servis (orn. Groq)
  python evaluate_models.py --models "openai-compat:https://api.groq.com/openai/v1|llama-3.3-70b-versatile|GROQ_API_KEY"

  # Once kucuk bir ornekte dene
  python evaluate_models.py --models qwen2.5:14b-instruct --sample-size 100 --seed 42

  # Uzak sunucudaki Ollama'ya baglan
  python evaluate_models.py --models qwen2.5:14b-instruct --ollama-host http://10.34.10.112:11434

  # Kesilen bir kosuyu ayni komutla tekrar calistirmak otomatik devam eder
  # (invoice_id + model zaten sonuc dosyasinda varsa tekrar sorulmaz)

  # Sadece daha once toplanmis sonuclari yeniden ozetle (API cagrisi yapmadan)
  python evaluate_models.py --models qwen2.5:14b-instruct --summarize-only

  # Prompt'un nasil goruntugunu gormek icin (API cagirmadan)
  python evaluate_models.py --models qwen2.5:14b-instruct --dry-run

Onemli: --model-parallelism, modelleri ES ZAMANLI calistirir. Bulut modelleri icin
sorun degil (her biri kendi API'sine gider). Ayni anda birden fazla BUYUK local
Ollama modelini paralel calistirirsaniz, hepsinin VRAM'da AYNI ANDA yer kaplamasi
gerekir (128GB'a sigmiyorsa Ollama modelleri surekli yukleyip bosaltir, bu da
performansi dusurur/hata verebilir) - local modelleri paralel test ederken buna
dikkat edin.

Not: Bu dosyanin gercek uygulamasi core/ paketine bolunmustur (core/constants.py,
core/parsing.py, core/prompting.py, core/scoring.py, core/providers.py,
core/reporting.py, core/runner.py, core/cli.py). Bu dosya sadece geriye donuk
uyumluluk icin ince bir giris noktasidir - "python evaluate_models.py ..."
komutu eskisi gibi calismaya devam eder.
"""

from core.cli import main

if __name__ == "__main__":
    main()
