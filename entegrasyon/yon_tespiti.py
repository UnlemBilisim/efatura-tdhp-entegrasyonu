"""Fatura yönü (inbox/outbox) tespiti — Mcp_mimarisi'ni çağırmadan ÖNCE.

Kullanıcı kararı (2026-07-22): dışarıdan gelen (inbox) faturalarda
Mcp_mimarisi'nin KDV/NACE ön filtrelemesi hiç çalışmaz (bkz.
Mcp_mimarisi/project.md §3.9 — sistem "sadece bizim kestiğimiz faturaları
incelemeli" kapsam kararı), fatura doğrudan model_eval'a gider. Bu modül,
`app.py`'nin Mcp_mimarisi'ni çağırıp çağırmayacağına karar vermeden önce
yönü öğrenmesini sağlar.

model_eval'ın kendi ayrıştırma mantığını (`parse_invoice_xml_string`)
kullanır — burada AYRI/tekrar bir XML parser yazılmaz, tek gerçek kaynak
model_eval/core/parsing.py'dir."""

from __future__ import annotations

from model_eval_yolu import model_eval_yolunu_ekle


class FaturaYonuBelirsizHatasi(ValueError):
    """own_vkn ne faturanın satıcı ne alıcı tarafında bulunduğunda fırlatılır
    — parse_invoice_xml_string bu durumda sessizce "inbox" varsayıp
    direction_uncertain=True işaretliyor (bkz. core/parsing.py); entegrasyon
    katmanı bunu sessizce yutmak yerine kullanıcıya açıkça göstermeyi tercih
    eder, çünkü yön burada Mcp_mimarisi'nin çağrılıp çağrılmayacağını
    belirleyen kritik bir dallanma noktası."""


def fatura_yonunu_tespit_et(fatura_xml: str, own_vkn: str) -> str:
    """Faturanın 'outbox' (biz kestik, satıcı=own_vkn) mi yoksa 'inbox'
    (bize kesilmiş, alıcı=own_vkn) mi olduğunu döner."""
    model_eval_yolunu_ekle()

    from core.parsing import parse_invoice_xml_string

    invoice = parse_invoice_xml_string(fatura_xml, own_vkn=own_vkn)
    if invoice.get("direction_uncertain"):
        raise FaturaYonuBelirsizHatasi(
            f"own_vkn ({own_vkn!r}) faturanın ne satıcı ne alıcı tarafında "
            "bulunuyor — bu VKN'nin doğru olduğundan emin olun."
        )
    return invoice["direction"]
