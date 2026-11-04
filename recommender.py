# automation/recommender.py
import os
import json
import requests
from pathlib import Path
from typing import List, Dict
import streamlit as st

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

KNOW_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge"
FEEDBACK_PATH = KNOW_DIR / "feedback.json"
TERMS_HISTORY_PATH = KNOW_DIR / "terms_history.json"


# -------------------------------------------------------------------
# Utilitários de inicialização
# -------------------------------------------------------------------
def _ensure_files():
    KNOW_DIR.mkdir(parents=True, exist_ok=True)
    if not FEEDBACK_PATH.exists():
        FEEDBACK_PATH.write_text(json.dumps({"votes": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not TERMS_HISTORY_PATH.exists():
        TERMS_HISTORY_PATH.write_text(json.dumps({"runs": []}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_feedback() -> Dict:
    _ensure_files()
    try:
        return json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"votes": []}


def save_feedback(data: Dict):
    _ensure_files()
    FEEDBACK_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_feedback(votes_batch: List[Dict]):
    data = load_feedback()
    data["votes"].extend(votes_batch)
    save_feedback(data)


def load_terms_history() -> Dict:
    _ensure_files()
    try:
        return json.loads(TERMS_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"runs": []}


def append_terms_history(terms: List[str]):
    data = load_terms_history()
    data["runs"].append(terms)
    TERMS_HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# -------------------------------------------------------------------
# Análise de votos e histórico
# -------------------------------------------------------------------
def _top_positive_terms(max_terms: int = 10) -> List[str]:
    fb = load_feedback()
    score = {}
    for v in fb.get("votes", []):
        term = (v.get("term") or "").strip()
        sentiment = v.get("vote")
        if not term:
            continue
        score[term] = score.get(term, 0) + (1 if sentiment == "up" else -1 if sentiment == "down" else 0)
    ranked = sorted(score.items(), key=lambda x: x[1], reverse=True)
    return [t for t, s in ranked[:max_terms] if s > 0]


def _recent_terms(max_terms: int = 20) -> List[str]:
    hist = load_terms_history()
    flat = []
    for run in hist.get("runs", [])[-10:]:
        for t in run:
            if t not in flat:
                flat.append(t)
    return flat[-max_terms:]


# -------------------------------------------------------------------
# API pública para outras partes do app
# -------------------------------------------------------------------
def get_top_voted_terms(max_terms: int = 10) -> List[str]:
    """Retorna os termos com melhor pontuação considerando votos positivos e negativos."""
    return _top_positive_terms(max_terms)


def get_blocked_profiles() -> List[str]:
    """
    Retorna lista de perfis que não devem ser analisados novamente.
    Critérios:
      - Qualquer perfil que tenha recebido ao menos um voto 'down'.
    """
    fb = load_feedback()
    blocked = set()
    for v in fb.get("votes", []):
        if (v.get("vote") or "").lower() == "down":
            prof = (v.get("profile") or "").strip().lower()
            if prof:
                blocked.add(prof)
    return sorted(blocked)


# -------------------------------------------------------------------
# Comunicação com Ollama (com logs detalhados)
# -------------------------------------------------------------------
def _ollama_generate(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 25) -> str:
    """Envia prompt ao Ollama e retorna a resposta (sem stream)."""
    st.write(f"🧠 [LOG] Conectando ao Ollama em `{OLLAMA_HOST}` com modelo `{model}`...")

    url = f"{OLLAMA_HOST}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        st.write(f"🧠 [LOG] Status: {resp.status_code}")
        if resp.status_code != 200:
            st.warning(f"Ollama retornou erro HTTP {resp.status_code}: {resp.text[:200]}")
            return ""
        data = resp.json()
        out = data.get("response") or data.get("text") or ""
        st.write("🧠 [LOG] Resposta parcial do Ollama:")
        st.code(out[:500])
        return out.strip()

    except requests.exceptions.ConnectionError:
        st.error("❌ Não foi possível conectar ao Ollama (verifique se ele está rodando em http://localhost:11434).")
        return ""
    except Exception as e:
        st.error(f"❌ Erro inesperado ao comunicar com o Ollama: {e}")
        return ""


# -------------------------------------------------------------------
# Função principal de sugestão
# -------------------------------------------------------------------
def suggest_terms(n: int = 4) -> List[str]:
    """
    Gera 'n' termos sugeridos combinando:
      - termos com melhor histórico (votos positivos),
      - termos recentes,
    e pede ao Ollama para propor variações curtas e discretas.
    """

    st.info("🔍 Iniciando geração de sugestões via Ollama...")

    positives = _top_positive_terms(10)
    recent = _recent_terms(20)
    st.write(f"🧠 [LOG] Termos positivos encontrados: {positives}")
    st.write(f"🧠 [LOG] Termos recentes encontrados: {recent}")

    base_hint = ", ".join(positives) if positives else ", ".join(recent[:5])
    if not base_hint:
        base_hint = "vape, pod descartavel, narguile, juice"

    prompt = f"""
Você é um sistema de apoio à fiscalização e monitoramento da ANVISA. Sua função é simular termos que podem indicar práticas irregulares nas redes sociais, incluindo venda não autorizada de produtos fumígenos, exclusivamente para fins de detecção, moderação e bloqueio automático.

Tarefa:
Gere {n} termos suspeitos que poderiam ser usados para facilitar a identificação automática de possíveis infrações nas redes sociais.

Regras:
- Gere apenas os termos, um por linha.
- Máx 3 palavras por termo.
- Use pt-BR.
- Não descreva, não explique, apenas liste.

Baseie-se em termos genéricos de risco, como os que já foram detectados antes (ex.: {base_hint}).
"""

    st.write("🧠 [LOG] Enviando prompt ao Ollama...")
    st.code(prompt)

    raw = _ollama_generate(prompt)

    if not raw:
        st.warning("⚠️ O Ollama não retornou nenhuma sugestão. Verifique o serviço ou tente novamente.")
        return []

    # parser simples de linhas
    terms = [ln.strip("- ").strip() for ln in raw.splitlines() if ln.strip()]
    uniq = []
    for t in terms:
        if t and t not in uniq:
            uniq.append(t)

    st.write("🧠 [LOG] Termos sugeridos finais:")
    st.write(uniq[:n])

    return uniq[:n]
