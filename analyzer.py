
import re
from typing import Dict, List

PALAVRAS_CHAVE_INFRACAO = re.compile(
    r"(venda|delivery|entrega|whatsapp|wpp|preço|tabela|catalogo|catálogo|direct|dm|envio)",
    re.IGNORECASE,
)

RISK_KEYWORDS: Dict[str, int] = {
    "venda": 3,
    "delivery": 3,
    "entrega": 2,
    "whatsapp": 2,
    "wpp": 2,
    "preço": 2,
    "tabela": 1,
    "catalogo": 1,
    "catálogo": 1,
    "direct": 1,
    "dm": 1,
    "envio": 2,
    "estoque": 1,
    "promoção": 1,
    "frete": 1,
    "atacado": 2,
    "revenda": 2,
}


def calcular_risco_bio(bio_text: str) -> Dict:
    if not bio_text:
        return {"score": 0, "terms": []}
    texto = bio_text or ""
    termos_detectados: List[str] = []
    total = 0
    lowered = texto.lower()
    for palavra, peso in RISK_KEYWORDS.items():
        occurrences = len(re.findall(rf"\b{re.escape(palavra)}\b", lowered))
        if occurrences > 0:
            termos_detectados.append({"term": palavra, "count": occurrences, "weight": peso})
            total += peso * occurrences
    termos_detectados.sort(key=lambda x: (-x["weight"], -x["count"], x["term"]))
    return {"score": total, "terms": termos_detectados}


def classificar_bio(bio_text: str) -> dict:
    risk = calcular_risco_bio(bio_text)
    if not bio_text:
        return {"status": "OK", "match": None, "risk_score": risk["score"], "risk_terms": risk["terms"]}
    m = PALAVRAS_CHAVE_INFRACAO.search(bio_text or "")
    status = "SUSPEITO" if m else "OK"
    match = m.group(0) if m else None
    return {"status": status, "match": match, "risk_score": risk["score"], "risk_terms": risk["terms"]}
