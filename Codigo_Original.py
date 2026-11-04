"""
================================================================================
GGTAB – Plataforma de Monitoramento de Redes Sociais
================================================================================
Versão  : 11
Autor   : GGTAB / ANVISA
Descrição:
    Automação de busca e análise de perfis/publicações em redes sociais
    (Instagram, TikTok, Threads, Facebook e Pinterest) usando Playwright.
    Interface construída com Streamlit.

Estrutura do arquivo:
    1. Imports e configurações globais
    2. Constantes e caminhos
    3. Utilitários gerais (deduplicação, votos, sidebar, homepage)
    4. Módulo Instagram
    5. Módulo TikTok
    6. Módulo Threads
    7. Módulo Facebook
    8. Módulo Pinterest
    9. Função genérica de visita (Threads / Facebook / Pinterest)
   10. Roteador de páginas (ponto de entrada do Streamlit)
================================================================================
"""

# ==============================================================================
# 1. IMPORTS
# ==============================================================================

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import asyncio
import json
import logging
import os
import platform
import re
import time
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

# Módulos auxiliares do projeto
from analyzer import classificar_bio
from recommender import (
    append_feedback,
    append_terms_history,
    get_blocked_profiles,
    get_top_voted_terms,
    suggest_terms,
)
from report_pdf import build_pdf, criar_volume_evidencias

# ==============================================================================
# 2. CONFIGURAÇÕES DO SISTEMA OPERACIONAL
# ==============================================================================

# No Windows, o Playwright precisa de um event loop diferente do padrão.
if platform.system() == "Windows":
    try:
        import asyncio.windows_events  # noqa: F401
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass  # Ignora silenciosamente se não for possível configurar

# ==============================================================================
# 3. CONSTANTES E CAMINHOS
# ==============================================================================

# Raiz do projeto (dois níveis acima deste arquivo)
BASE_DIR = Path(__file__).resolve().parents[1]

# Diretórios de dados
DATA_DIR    = BASE_DIR / "data"
SCREEN_DIR  = DATA_DIR / "screenshots"   # prints capturados durante a automação
OUTPUT_DIR  = DATA_DIR / "outputs"       # PDFs e ZIPs gerados

# Arquivos JSON de persistência (um por plataforma)
JSON_PATHS: Dict[str, Path] = {
    "ig"  : DATA_DIR / "last_run.json",
    "tt"  : DATA_DIR / "last_run_tiktok.json",
    "th"  : DATA_DIR / "last_run_threads.json",
    "fb"  : DATA_DIR / "last_run_facebook.json",
    "pin" : DATA_DIR / "last_run_pinterest.json",
}

# Usuários/caminhos do Instagram que devem ser ignorados na varredura
IG_SYSTEM_USERS = frozenset({
    "explore", "reels", "p", "accounts",
    "login", "direct", "developer",
})

# Configuração básica de logging (visível no terminal / logs do servidor)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ggtab")

# ==============================================================================
# 4. INICIALIZAÇÃO (executa uma única vez por sessão do Streamlit)
# ==============================================================================

# Garante que os diretórios necessários existem antes de qualquer operação
SCREEN_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Carrega variáveis de ambiente do arquivo .env na raiz do projeto
load_dotenv(BASE_DIR / ".env")

# Configuração global da página do Streamlit
st.set_page_config(
    layout="wide",
    page_title="GGTAB - Monitoramento Integrado",
    page_icon="🔎",
)

# Garante que a página inicial está definida no estado da sessão
if "current_page" not in st.session_state:
    st.session_state["current_page"] = "home"


# ==============================================================================
# 5. UTILITÁRIOS GERAIS
# ==============================================================================

def deduplicar(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """
    Remove duplicatas de uma lista de pares (termo, link/path),
    preservando a ordem de aparição.

    Args:
        items: Lista de tuplas (termo, url_ou_path).

    Returns:
        Lista sem duplicatas, com a primeira ocorrência de cada URL mantida.
    """
    vistos: set = set()
    return [(t, l) for t, l in items if not (l in vistos or vistos.add(l))]


def salvar_resultado_json(platform_key: str, resultados: List[Dict]) -> None:
    """
    Serializa os resultados de uma execução em JSON para a pasta de dados.

    Args:
        platform_key : Chave da plataforma (ex: "ig", "tt").
        resultados   : Lista de dicionários com os dados extraídos.
    """
    payload = {
        "timestamp": datetime.now().isoformat(),
        "results": resultados,
    }
    JSON_PATHS[platform_key].write_text(
        json.dumps(payload, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("JSON salvo: %s", JSON_PATHS[platform_key])


def gerar_artefatos(resultados: List[Dict]) -> Dict[str, str]:
    """
    Gera o relatório PDF e o pacote ZIP de evidências a partir dos resultados.

    Nota: O PDF precisa ser gerado antes do ZIP, pois o ZIP o inclui.

    Args:
        resultados: Lista de dicionários com os dados extraídos.

    Returns:
        Dicionário com as chaves "pdf" e "zip" apontando para os caminhos gerados.
    """
    caminho_pdf = build_pdf(resultados, str(OUTPUT_DIR))
    caminho_zip = criar_volume_evidencias(
        str(OUTPUT_DIR), str(SCREEN_DIR), caminho_pdf
    )
    return {"pdf": caminho_pdf, "zip": caminho_zip}


def capturar_screenshot(page: Page, prefixo: str, nome: str) -> Optional[Path]:
    """
    Tira um screenshot da página atual e salva em SCREEN_DIR.

    Args:
        page   : Instância do Playwright Page.
        prefixo: Prefixo do arquivo (ex: "ig", "tt").
        nome   : Nome base (ex: nome do perfil).

    Returns:
        Caminho do arquivo salvo, ou None em caso de falha.
    """
    uid       = uuid.uuid4().hex[:8]
    safe_nome = re.sub(r"[^a-zA-Z0-9]", "_", nome)[:30] or "item"
    filename  = f"print_{prefixo}_{safe_nome}_{uid}.png"
    img_path  = SCREEN_DIR / filename

    try:
        page.screenshot(path=str(img_path), full_page=False)
        return img_path
    except Exception as exc:
        logger.warning("Falha ao capturar screenshot (%s): %s", filename, exc)
        return None


def register_vote(idx: int, sentiment: str, platform_key: str) -> None:
    """
    Registra um voto (👍/👎) para um resultado específico.

    Votos são armazenados em st.session_state["votes_batch"] como lista.
    Se o usuário já votou naquele par (term, profile), o voto anterior é
    substituído pelo novo.

    Args:
        idx          : Índice do resultado dentro da lista de resultados.
        sentiment    : "up" para positivo, "down" para negativo.
        platform_key : Chave da sessão onde os resultados estão (ex: "res_ig").
    """
    run_data = st.session_state.get(platform_key)
    if not run_data:
        return

    resultados = run_data.get("results") or []
    if not (0 <= idx < len(resultados)):
        return

    alvo = resultados[idx]
    novo_voto = {
        "term"     : alvo["termo"],
        "profile"  : alvo["perfil"],
        "vote"     : sentiment,
        "ts"       : datetime.now().isoformat(),
        "platform" : platform_key.replace("res_", ""),
    }

    votos: List[Dict] = st.session_state.setdefault("votes_batch", [])

    # Substitui voto existente para o mesmo par (termo, perfil)
    for i, existente in enumerate(votos):
        if existente["term"] == novo_voto["term"] and existente["profile"] == novo_voto["profile"]:
            votos[i] = novo_voto
            return

    votos.append(novo_voto)


# ==============================================================================
# 6. COMPONENTES DE UI REUTILIZÁVEIS
# ==============================================================================

def render_sidebar_header() -> None:
    """
    Renderiza o cabeçalho padrão da barra lateral:
    logo (se existir), botão de voltar e um divisor.
    """
    logo_path = DATA_DIR / "assets" / "logo_anvisa.png"

    if logo_path.exists():
        st.sidebar.image(str(logo_path), use_container_width=True)
    else:
        st.sidebar.markdown("### GGTAB | ANVISA")

    st.sidebar.markdown("")

    if st.sidebar.button("← Voltar para Home", use_container_width=True):
        st.session_state["current_page"] = "home"
        st.rerun()

    st.sidebar.divider()


def render_resultados(
    data: Dict,
    emoji: str,
    platform_key: str,
    voto_prefix: str,
) -> None:
    """
    Renderiza a lista de resultados de uma plataforma de forma padronizada,
    incluindo botões de download (PDF / ZIP) e controles de votação.

    Args:
        data         : Dicionário com "results", "pdf" e "zip".
        emoji        : Emoji identificador da plataforma (ex: "👤").
        platform_key : Chave da sessão (ex: "res_ig").
        voto_prefix  : Prefixo único para as keys dos botões de voto (ex: "ig").
    """
    col_pdf, col_zip = st.columns(2)

    if data.get("pdf") and Path(data["pdf"]).exists():
        col_pdf.download_button(
            "⬇️ Baixar Relatório PDF",
            open(data["pdf"], "rb"),
            f"relatorio_{voto_prefix}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    if data.get("zip") and Path(data["zip"]).exists():
        col_zip.download_button(
            "⬇️ Baixar Evidências ZIP",
            open(data["zip"], "rb"),
            f"evidencias_{voto_prefix}.zip",
            mime="application/zip",
            use_container_width=True,
        )

    st.divider()

    for i, r in enumerate(data.get("results", [])):
        # Cabeçalho do resultado
        st.markdown(f"### {emoji} {r['perfil']}")
        st.markdown(f"🔗 **Link:** [{r['url']}]({r['url']})")

        # Origem do post (somente TikTok)
        if r.get("post_original") and r["post_original"] != r["url"]:
            st.caption(f"📌 Post original: {r['post_original']}")

        # Métricas de risco
        risco = r.get("risk_score", 0)
        cor   = "🔴" if risco >= 7 else ("🟡" if risco >= 4 else "🟢")
        st.caption(f"{cor} Risco: **{risco}** | Termo: `{r['termo']}`")

        # Conteúdo analisado (expansível para não poluir a tela)
        with st.expander("📄 Ver conteúdo analisado"):
            st.text(r.get("bio", "N/A"))

        # Screenshot (se disponível)
        screenshot_path = r.get("screenshot")
        if screenshot_path:
            full_path = BASE_DIR / screenshot_path
            if full_path.exists():
                st.image(str(full_path), caption="📸 Print capturado")

        # Botões de votação
        col_up, col_down, _ = st.columns([1, 1, 5])
        with col_up:
            if st.button("👍 Relevante", key=f"{voto_prefix}_u{i}"):
                register_vote(i, "up", platform_key)
                st.toast("✅ Voto salvo!")
        with col_down:
            if st.button("👎 Irrelevante", key=f"{voto_prefix}_d{i}"):
                register_vote(i, "down", platform_key)
                st.toast("✅ Voto salvo!")

        st.markdown("---")


def render_homepage() -> None:
    """
    Renderiza a página inicial com o menu de navegação para cada plataforma.
    """
    logo_path = DATA_DIR / "assets" / "logo_anvisa.png"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=False, width=300)

    st.title("🔎 GGTAB – Plataforma de Monitoramento")
    st.markdown("---")
    st.markdown("### Bem-vindo à plataforma GGTAB")
    st.markdown("Selecione a rede social que deseja monitorar:")

    # Configuração de cada card da home: (página, emoji, título, descrição, key)
    plataformas = [
        ("instagram", "📱", "Instagram", "Perfis e publicações.",    "h_ig"),
        ("tiktok",    "🎵", "TikTok",    "Vídeos e perfis.",         "h_tt"),
        ("threads",   "🧵", "Threads",   "Tópicos e perfis.",        "h_th"),
        ("facebook",  "📘", "Facebook",  "Páginas e grupos.",        "h_fb"),
        ("pinterest", "📌", "Pinterest", "Pins, perfis e pastas.",   "h_pin"),
    ]

    colunas = st.columns(len(plataformas))
    for col, (pagina, emoji, titulo, desc, key) in zip(colunas, plataformas):
        with col:
            st.markdown(f"#### {emoji} {titulo}")
            st.write(desc)
            if st.button(f"🚀 Acessar {titulo}", key=key, type="primary", use_container_width=True):
                st.session_state["current_page"] = pagina
                st.rerun()

    st.markdown("---")
    st.markdown("### ℹ️ Sobre")
    st.info(
        "GGTAB é uma plataforma de monitoramento desenvolvida para auxiliar "
        "na identificação e análise de perfis suspeitos em redes sociais."
    )


# ==============================================================================
# 7. MÓDULO INSTAGRAM
# ==============================================================================

def ig_login(page: Page, usuario: str, senha: str) -> None:
    """
    Realiza login no Instagram via formulário web.

    Tenta dois seletores diferentes (padrão e localizado em PT-BR).
    Após o login, descarta diálogos de notificação que possam aparecer.

    Args:
        page   : Instância do Playwright Page.
        usuario: Nome de usuário do Instagram.
        senha  : Senha do Instagram.
    """
    page.goto("https://www.instagram.com/accounts/login/")
    time.sleep(3)  # Aguarda o carregamento completo do formulário

    try:
        if page.locator('input[name="username"]').count() > 0:
            # Seletor padrão (inglês / internacionalizado)
            page.fill('input[name="username"]', usuario)
            page.fill('input[name="password"]', senha)
            page.click('button[type="submit"]')
        else:
            # Seletor em português (pode variar por região)
            page.get_by_label("Número de celular, nome de usuário ou email").fill(usuario)
            page.get_by_label("Senha").fill(senha)
            page.get_by_role("button", name="Entrar", exact=True).click()
    except Exception:
        # Último recurso: envia o formulário via teclado
        try:
            page.keyboard.press("Enter")
        except Exception:
            pass

    # Aguarda o redirecionamento após o login
    time.sleep(8)

    # Fecha diálogos "Agora não" / "Not now" que o Instagram pode exibir
    for texto_botao in ["Agora não", "Not now", "OK", "Ok", "ok"]:
        try:
            btn = page.get_by_role("button", name=texto_botao)
            if btn.count():
                btn.first.click()
                time.sleep(1)
        except Exception:
            pass


def ig_obter_campo_busca(page: Page):
    """
    Localiza e retorna o campo de texto de busca do Instagram.

    Tenta dois seletores diferentes (aria-label e placeholder) para
    cobrir variações de idioma e versão da interface.

    Args:
        page: Instância do Playwright Page.

    Returns:
        Locator do campo de busca.

    Raises:
        RuntimeError: Se o campo não for encontrado com nenhum seletor.
    """
    # Tentativa 1: busca pelo role aria e label em português/inglês
    try:
        locator = page.get_by_role("main").get_by_role(
            "textbox",
            name=re.compile(r"Entrada da pesquisa|Search input|Pesquisar", re.IGNORECASE),
        )
        locator.wait_for(state="visible", timeout=10_000)
        return locator
    except Exception:
        pass

    # Tentativa 2: busca pelo placeholder
    try:
        locator = page.locator(
            'input[placeholder*="Pesquisar"], input[aria-label*="Pesquisa"]'
        )
        locator.wait_for(state="visible", timeout=10_000)
        return locator
    except Exception:
        pass

    raise RuntimeError("Campo de busca do Instagram não localizado.")


def ig_processar_hashtag(page: Page, hashtag: str, maxn: int) -> List[Tuple[str, str]]:
    """
    Navega até a página de uma hashtag do Instagram e coleta links de posts.

    Realiza scroll progressivo para carregar mais resultados até atingir
    o buffer desejado (3× o limite) ou o número máximo de tentativas.

    Args:
        page   : Instância do Playwright Page.
        hashtag: Hashtag com ou sem o caractere "#".
        maxn   : Número máximo de posts a retornar.

    Returns:
        Lista de tuplas (hashtag, path_do_post).
    """
    tag_limpa = hashtag.replace("#", "").strip()
    url = f"https://www.instagram.com/explore/tags/{tag_limpa}/"

    try:
        page.goto(url, timeout=20_000)
        time.sleep(5)  # Aguarda carregamento inicial dos posts
    except Exception:
        return []

    posts_encontrados: set = set()
    buffer_alvo = maxn * 3  # Coleta mais do que o necessário e filtra depois
    tentativas = 0

    while len(posts_encontrados) < buffer_alvo and tentativas < 15:
        try:
            hrefs = page.eval_on_selector_all(
                "a", "els => els.map(e => e.getAttribute('href'))"
            )
            novos = [h for h in hrefs if h and "/p/" in h]
            posts_encontrados.update(novos)

            if len(posts_encontrados) >= buffer_alvo:
                break

            page.keyboard.press("PageDown")
            time.sleep(1.5)
            tentativas += 1
        except Exception:
            break

    return [(hashtag, link) for link in list(posts_encontrados)[:maxn]]


def ig_buscar(page: Page, termos: List[str], maxn: int) -> List[Tuple[str, str]]:
    """
    Busca perfis ou posts no Instagram para uma lista de termos.

    Para hashtags (iniciadas com "#"): navega direto para a página da tag.
    Para termos normais: usa a gaveta lateral de busca do Instagram.

    Atenção: NUNCA pressionar Enter na busca do Instagram Web para perfis —
    isso redireciona para resultados gerais e não para a lista de perfis.

    Args:
        page  : Instância do Playwright Page.
        termos: Lista de termos ou hashtags a pesquisar.
        maxn  : Limite máximo de resultados por termo.

    Returns:
        Lista deduplicada de tuplas (termo, path_do_perfil_ou_post).
    """
    search_box = None
    acumulado: List[Tuple[str, str]] = []

    for termo in termos:
        termo = termo.strip()
        if not termo:
            continue

        if termo.startswith("#"):
            # Hashtags têm fluxo próprio via URL direta
            acumulado.extend(ig_processar_hashtag(page, termo, maxn))
            continue

        # --- Busca por nome de perfil ---

        # Passo 1: Clica no ícone de lupa para abrir a gaveta lateral de busca
        try:
            lupa = page.locator("svg[aria-label='Pesquisa'], svg[aria-label='Search']")
            if lupa.count() > 0:
                lupa.first.click(force=True)
                time.sleep(2)
        except Exception:
            pass

        # Passo 2: Localiza o campo de busca (com fallback para reload)
        if search_box is None:
            try:
                search_box = ig_obter_campo_busca(page)
            except RuntimeError:
                page.goto("https://www.instagram.com/")
                time.sleep(3)
                try:
                    search_box = ig_obter_campo_busca(page)
                except RuntimeError:
                    logger.error("Campo de busca indisponível para o termo: %s", termo)
                    continue

        # Passo 3: Digita o termo e aguarda o carregamento da lista de sugestões
        try:
            search_box.fill("")
            time.sleep(0.5)
            search_box.fill(termo)
            time.sleep(5)  # O Instagram popula a lista de forma assíncrona

            # Passo 4: Extrai os hrefs visíveis na gaveta lateral
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")

            conta_termo = 0
            for link in hrefs:
                if conta_termo >= maxn:
                    break

                # Valida que o link é um perfil IG válido (não uma rota de sistema)
                match = re.search(
                    r"https://www\.instagram\.com/([a-zA-Z0-9_.\-]{3,30})/$",
                    link,
                )
                if match:
                    usuario = match.group(1)
                    if usuario not in IG_SYSTEM_USERS:
                        acumulado.append((termo, f"/{usuario}/"))
                        conta_termo += 1

        except Exception as exc:
            logger.warning("Erro na busca do termo '%s': %s", termo, exc)

    return deduplicar(acumulado)


def ig_visitar(page: Page, pares: List[Tuple[str, str]]) -> List[Dict]:
    """
    Visita cada perfil/post do Instagram, extrai texto e captura screenshot.

    Args:
        page  : Instância do Playwright Page.
        pares : Lista de tuplas (termo, path) retornada por ig_buscar().

    Returns:
        Lista de dicionários com os dados extraídos e a classificação de risco.
    """
    resultados: List[Dict] = []

    for termo, path in pares:
        url = f"https://www.instagram.com{path}"

        try:
            page.goto(url, timeout=20_000)
        except Exception:
            logger.warning("Falha ao navegar para: %s", url)
            continue

        time.sleep(3)

        is_post    = "/p/" in path
        tipo_item  = "post" if is_post else "perfil"
        nome_perfil = "Desconhecido"
        texto_analise = ""

        if is_post:
            # Extrai autor e legenda de uma publicação
            try:
                autor_el = page.locator("header h2 a").first
                if autor_el.count() > 0:
                    nome_perfil = autor_el.inner_text().strip()
                texto_artigo = page.locator("article").first.inner_text(timeout=2_000)
                texto_analise = f"[Legenda do Post]: {texto_artigo[:600]}"
            except Exception:
                texto_analise = "Erro ao ler conteúdo do post."
        else:
            # Extrai a bio de um perfil
            try:
                nome_perfil   = path.strip("/")
                bio_js        = page.evaluate(
                    "document.querySelector('header section')"
                    " ? document.querySelector('header section').innerText : ''"
                )
                texto_analise = f"[Bio do Perfil]: {bio_js}"
            except Exception:
                texto_analise = "Erro ao ler bio do perfil."

        # Captura screenshot da página
        img_path = capturar_screenshot(page, "ig", nome_perfil)

        # Classifica o conteúdo pelo módulo de análise
        classificacao = classificar_bio(texto_analise)

        resultados.append({
            "termo"                 : termo,
            "perfil"                : nome_perfil,
            "url"                   : url,
            "tipo"                  : tipo_item,
            "bio"                   : texto_analise,
            "status"                : classificacao["status"],
            "match"                 : classificacao["match"],
            "risk_score"            : classificacao.get("risk_score", 0),
            "risk_terms"            : classificacao.get("risk_terms", []),
            "screenshot"            : f"data/screenshots/{img_path.name}" if img_path else None,
            "verification_timestamp": datetime.now().isoformat(),
        })

    return resultados


# ==============================================================================
# 8. MÓDULO TIKTOK
# ==============================================================================

def tt_aguardar_login(page: Page) -> None:
    """
    Navega para a tela de login do TikTok e aguarda o usuário autenticar
    manualmente (necessário por causa dos CAPTCHAs).

    Considera login bem-sucedido quando o ícone de perfil aparecer.

    Args:
        page: Instância do Playwright Page.
    """
    page.goto("https://www.tiktok.com/login")
    st.toast("⚠️ Faça login manual no TikTok! Você tem 60 segundos.")

    try:
        page.wait_for_selector("[data-e2e='profile-icon']", timeout=60_000)
        st.toast("✅ Login efetuado com sucesso!", icon="✅")
        logger.info("TikTok: login confirmado.")
    except PWTimeout:
        logger.warning("TikTok: timeout aguardando login. Continuando mesmo assim.")


def tt_buscar_hashtag(page: Page, hashtag: str, maxn: int) -> List[Tuple[str, str]]:
    """
    Coleta links de vídeos de uma página de hashtag do TikTok.

    Args:
        page   : Instância do Playwright Page.
        hashtag: Hashtag com ou sem "#".
        maxn   : Limite de vídeos a retornar.

    Returns:
        Lista de tuplas (hashtag, url_do_video).
    """
    url = f"https://www.tiktok.com/tag/{hashtag.replace('#', '').strip()}"

    try:
        page.goto(url, timeout=20_000, wait_until="domcontentloaded")
        page.wait_for_selector("a[href*='/video/']", timeout=10_000)
    except Exception:
        return []

    links: set = set()
    tentativas = 0

    while len(links) < maxn * 3 and tentativas < 15:
        try:
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            links.update([h.split("?")[0] for h in hrefs if "/video/" in h])
            if len(links) >= maxn * 3:
                break
            page.keyboard.press("PageDown")
            time.sleep(1.5)
            tentativas += 1
        except Exception:
            break

    return [(hashtag, l) for l in list(links)[:maxn]]


def tt_coletar_videos_perfil(page: Page, username: str, limite: int) -> List[Tuple[str, str]]:
    """
    Coleta links dos vídeos mais recentes de um perfil do TikTok.

    Args:
        page    : Instância do Playwright Page.
        username: Nome do perfil com ou sem "@".
        limite  : Máximo de vídeos a retornar.

    Returns:
        Lista de tuplas (username, url_do_video).
    """
    usuario_limpo = username.replace("@", "")
    url = f"https://www.tiktok.com/@{usuario_limpo}"

    try:
        page.goto(url, timeout=20_000, wait_until="domcontentloaded")
        page.wait_for_selector("[data-e2e='user-post-item']", timeout=10_000)
    except Exception:
        # Retorna ao menos o link do perfil se não encontrar vídeos
        return [(username, url)]

    links: set = set()
    tentativas = 0

    while len(links) < limite and tentativas < 10:
        try:
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            novos = [
                h.split("?")[0]
                for h in hrefs
                if "/video/" in h and usuario_limpo in h
            ]
            links.update(novos)
            if len(links) >= limite:
                break
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.5)
            tentativas += 1
        except Exception:
            break

    return [(username, l) for l in list(links)[:limite]]


def tt_buscar_keyword(page: Page, keyword: str, maxn: int) -> List[Tuple[str, str]]:
    """
    Busca vídeos no TikTok por palavra-chave usando a URL de busca.

    Args:
        page   : Instância do Playwright Page.
        keyword: Palavra-chave a pesquisar.
        maxn   : Limite de vídeos a retornar.

    Returns:
        Lista de tuplas (keyword, url_do_video).
    """
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.tiktok.com/search/video?q={encoded}"

    try:
        page.goto(url, timeout=20_000, wait_until="domcontentloaded")
        page.wait_for_selector("[data-e2e='search_video-item']", timeout=10_000)
    except Exception:
        return []

    links: set = set()
    tentativas = 0

    while len(links) < maxn * 3 and tentativas < 15:
        try:
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            novos = [
                h.split("?")[0]
                for h in hrefs
                if "/video/" in h and "tiktok.com" in h
            ]
            links.update(novos)
            if len(links) >= maxn * 3:
                break
            page.keyboard.press("PageDown")
            time.sleep(1.5)
            tentativas += 1
        except Exception:
            break

    return [(keyword, l) for l in list(links)[:maxn]]


def tt_buscar(page: Page, termos: List[str], maxn: int) -> List[Tuple[str, str]]:
    """
    Roteador de busca do TikTok: delega para a função correta com base
    no prefixo do termo (#hashtag, @perfil ou palavra-chave livre).

    Args:
        page  : Instância do Playwright Page.
        termos: Lista de termos (hashtags, @perfis ou palavras-chave).
        maxn  : Limite por termo.

    Returns:
        Lista deduplicada de tuplas (termo, url_do_video).
    """
    acumulado: List[Tuple[str, str]] = []

    for termo in termos:
        termo = termo.strip()
        if not termo:
            continue

        if termo.startswith("#"):
            acumulado.extend(tt_buscar_hashtag(page, termo, maxn))
        elif termo.startswith("@"):
            acumulado.extend(tt_coletar_videos_perfil(page, termo, maxn))
        else:
            acumulado.extend(tt_buscar_keyword(page, termo, maxn))

    return deduplicar(acumulado)


def tt_visitar(page: Page, items: List[Tuple[str, str]], modo_detalhado: bool) -> List[Dict]:
    """
    Visita cada vídeo/perfil do TikTok, extrai metadados e captura screenshot.

    Otimização: bloqueia o download de arquivos de mídia (mp4, webm, mp3)
    para reduzir drasticamente o tempo de carregamento de cada página.

    Args:
        page          : Instância do Playwright Page.
        items         : Lista de tuplas (termo, url).
        modo_detalhado: Se True, visita também o perfil do autor para extrair a bio.

    Returns:
        Lista de dicionários com os dados extraídos e a classificação de risco.
    """
    resultados: List[Dict] = []

    # Bloqueia downloads de mídia pesada para acelerar a navegação
    for padrao in ["**/*.mp4", "**/*.webm", "**/*.mp3"]:
        page.route(padrao, lambda route: route.abort())

    for termo, url in items:
        # Carrega a página do vídeo
        try:
            page.goto(url, timeout=15_000, wait_until="domcontentloaded")
            # Pausa vídeos que possam ter iniciado automaticamente
            try:
                page.evaluate("document.querySelectorAll('video').forEach(v => v.pause())")
            except Exception:
                pass
            # Aguarda seletor relevante para confirmar o carregamento do conteúdo
            try:
                seletor = "[data-e2e='browse-username']" if "/video/" in url else "[data-e2e='user-bio']"
                page.wait_for_selector(seletor, timeout=4_000)
            except Exception:
                pass
        except Exception as exc:
            logger.warning("Erro ao navegar para %s: %s", url, exc)

        # --- Extração de dados do vídeo ---
        is_video      = "/video/" in url
        bio_legenda   = "N/A"
        nome_perfil   = "Desconhecido"
        url_perfil    = ""
        url_original  = url if is_video else None

        try:
            if is_video:
                desc_el = page.locator("[data-e2e='video-desc']").first
                if desc_el.count():
                    bio_legenda = desc_el.inner_text()

                autor_el = page.locator("[data-e2e='browse-username']").first
                if autor_el.count():
                    nome_perfil = autor_el.inner_text()
                    url_perfil  = f"https://www.tiktok.com/@{nome_perfil}"
            else:
                url_perfil  = url
                nome_perfil = url.split("@")[-1].split("?")[0]
        except Exception:
            pass

        # Fallback para extrair username diretamente da URL
        if nome_perfil == "Desconhecido" and "@" in url:
            try:
                nome_perfil = url.split("@")[1].split("/")[0]
                url_perfil  = f"https://www.tiktok.com/@{nome_perfil}"
            except Exception:
                pass

        # --- Modo detalhado: visita o perfil para capturar a bio completa ---
        bio_final         = bio_legenda
        url_para_screenshot = url

        if modo_detalhado and url_perfil and "tiktok.com" in url_perfil:
            try:
                page.goto(url_perfil, timeout=15_000, wait_until="domcontentloaded")
                time.sleep(3)

                try:
                    page.wait_for_selector("[data-e2e='user-bio']", timeout=3_000)
                except Exception:
                    pass

                bio_perfil_el = page.locator("[data-e2e='user-bio']").first
                bio_perfil    = bio_perfil_el.inner_text() if bio_perfil_el.count() else ""
                bio_final     = f"[Legenda]: {bio_legenda}\n[Bio do Perfil]: {bio_perfil}"
                url_para_screenshot = url_perfil

            except Exception as exc:
                bio_final = f"{bio_legenda} (Erro ao carregar perfil: {exc})"

        # Captura screenshot
        img_path = capturar_screenshot(page, "tt", nome_perfil)

        # Classifica o conteúdo
        classificacao = classificar_bio(bio_final)

        resultados.append({
            "termo"                 : termo,
            "perfil"                : nome_perfil,
            "url"                   : url_para_screenshot,
            "post_original"         : url_original,
            "bio"                   : bio_final,
            "status"                : classificacao["status"],
            "match"                 : classificacao["match"],
            "risk_score"            : classificacao.get("risk_score", 0),
            "risk_terms"            : classificacao.get("risk_terms", []),
            "screenshot"            : f"data/screenshots/{img_path.name}" if img_path else None,
            "verification_timestamp": datetime.now().isoformat(),
        })

    # Remove os bloqueios de rota para não afetar outros usos futuros do contexto
    try:
        for padrao in ["**/*.mp4", "**/*.webm", "**/*.mp3"]:
            page.unroute(padrao)
    except Exception:
        pass

    return resultados


# ==============================================================================
# 9. MÓDULO THREADS
# ==============================================================================

def th_aguardar_login(page: Page) -> None:
    """
    Navega para o Threads e aguarda que o usuário esteja autenticado
    (detecta a presença de qualquer link de perfil na página).

    Args:
        page: Instância do Playwright Page.
    """
    page.goto("https://www.threads.net/login")
    st.toast("⚠️ Faça login manual no Threads se necessário.")

    try:
        # Um link com "/@" na página indica que o feed foi carregado
        page.wait_for_selector("a[href*='/@']", timeout=60_000)
    except PWTimeout:
        logger.warning("Threads: timeout aguardando login.")


def th_buscar(
    page: Page,
    termos: List[str],
    maxn: int,
    modo: str,
) -> List[Tuple[str, str]]:
    """
    Busca posts ou perfis no Threads para cada termo fornecido.

    Args:
        page  : Instância do Playwright Page.
        termos: Lista de termos de busca.
        maxn  : Limite de resultados por termo.
        modo  : "Principais", "Recentes" ou "Perfis".

    Returns:
        Lista deduplicada de tuplas (termo, url).
    """
    # Mapeamento do modo amigável para o parâmetro da URL do Threads
    mapa_serp = {"Recentes": "recent", "Perfis": "user"}
    serp_type = mapa_serp.get(modo, "default")

    acumulado: List[Tuple[str, str]] = []

    for termo in termos:
        encoded = urllib.parse.quote(termo.strip())
        url_busca = f"https://www.threads.net/search?q={encoded}&serp_type={serp_type}"

        try:
            page.goto(url_busca, timeout=20_000)
            time.sleep(4)

            links: set = set()
            tentativas = 0

            while len(links) < maxn and tentativas < 10:
                hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")

                for h in hrefs:
                    if modo == "Perfis":
                        if "/@" in h and "/post/" not in h:
                            links.add(h)
                    else:
                        if "/post/" in h:
                            links.add(h)

                if len(links) >= maxn:
                    break

                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                tentativas += 1

            acumulado.extend((termo, l) for l in list(links)[:maxn])

        except Exception as exc:
            logger.warning("Threads: erro buscando '%s': %s", termo, exc)

    return deduplicar(acumulado)


# ==============================================================================
# 10. MÓDULO FACEBOOK
# ==============================================================================

def fb_buscar(
    page: Page,
    termos: List[str],
    maxn: int,
    modo: str,
) -> List[Tuple[str, str]]:
    """
    Busca páginas, grupos ou resultados principais no Facebook.

    Args:
        page  : Instância do Playwright Page.
        termos: Lista de termos de busca.
        maxn  : Limite de resultados por termo.
        modo  : "Principais", "Páginas" ou "Grupos".

    Returns:
        Lista deduplicada de tuplas (termo, url).
    """
    mapa_tipo = {"Páginas": "pages", "Grupos": "groups"}
    tipo_url  = mapa_tipo.get(modo, "top")

    acumulado: List[Tuple[str, str]] = []

    for termo in termos:
        encoded   = urllib.parse.quote(termo.strip())
        url_busca = f"https://www.facebook.com/search/{tipo_url}/?q={encoded}"

        try:
            page.goto(url_busca, timeout=20_000)
            time.sleep(4)

            links: set = set()
            tentativas = 0

            while len(links) < maxn and tentativas < 10:
                hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")

                for h in hrefs:
                    # Filtra apenas links do Facebook que não sejam de busca ou login
                    if "facebook.com" in h and "/search/" not in h and "login" not in h:
                        links.add(h.split("?")[0])

                if len(links) >= maxn:
                    break

                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                tentativas += 1

            acumulado.extend((termo, l) for l in list(links)[:maxn])

        except Exception as exc:
            logger.warning("Facebook: erro buscando '%s': %s", termo, exc)

    return deduplicar(acumulado)


# ==============================================================================
# 11. MÓDULO PINTEREST
# ==============================================================================

def pin_buscar(
    page: Page,
    termos: List[str],
    maxn: int,
    modo: str,
) -> List[Tuple[str, str]]:
    """
    Busca pins, perfis ou pastas no Pinterest.

    Args:
        page  : Instância do Playwright Page.
        termos: Lista de termos de busca.
        maxn  : Limite de resultados por termo.
        modo  : "Pins", "Perfis" ou "Pastas".

    Returns:
        Lista deduplicada de tuplas (termo, url).
    """
    mapa_tipo = {"Perfis": "users", "Pastas": "boards"}
    tipo_url  = mapa_tipo.get(modo, "pins")

    acumulado: List[Tuple[str, str]] = []

    for termo in termos:
        encoded   = urllib.parse.quote(termo.strip())
        url_busca = f"https://br.pinterest.com/search/{tipo_url}/?q={encoded}"

        try:
            page.goto(url_busca, timeout=20_000)
            time.sleep(4)

            links: set = set()
            tentativas = 0

            while len(links) < maxn and tentativas < 10:
                hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")

                for h in hrefs:
                    if modo == "Pins" and "/pin/" in h:
                        links.add(h)
                    elif modo != "Pins" and "pinterest.com" in h and "/search/" not in h:
                        links.add(h)

                if len(links) >= maxn:
                    break

                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                tentativas += 1

            acumulado.extend((termo, l) for l in list(links)[:maxn])

        except Exception as exc:
            logger.warning("Pinterest: erro buscando '%s': %s", termo, exc)

    return deduplicar(acumulado)


# ==============================================================================
# 12. VISITADOR GENÉRICO (Threads, Facebook, Pinterest)
# ==============================================================================

def visitar_generico(
    page: Page,
    items: List[Tuple[str, str]],
    prefixo: str,
) -> List[Dict]:
    """
    Visita cada URL de uma lista genérica, extrai texto da página e captura
    screenshot. Usado pelas plataformas Threads, Facebook e Pinterest.

    Args:
        page   : Instância do Playwright Page.
        items  : Lista de tuplas (termo, url).
        prefixo: Prefixo para nomear screenshots (ex: "th", "fb", "pin").

    Returns:
        Lista de dicionários com os dados extraídos e a classificação de risco.
    """
    resultados: List[Dict] = []

    for termo, url in items:
        # Navega para a URL e aguarda carregamento
        try:
            page.goto(url, timeout=20_000)
            time.sleep(4)
        except Exception as exc:
            logger.warning("[%s] Erro ao navegar para %s: %s", prefixo, url, exc)

        # Extração de texto e nome do perfil
        bio_text    = "N/A"
        nome_perfil = "Desconhecido"

        try:
            # Captura o texto principal da página (limitado a 1000 chars)
            bio_text = (
                page.locator("body")
                .inner_text()[:1_000]
                .replace("\n", " ")
            )

            # Tenta inferir o nome do perfil pela URL
            segmentos   = [s for s in url.split("/") if s]
            nome_perfil = segmentos[-1] if segmentos else "Desconhecido"

        except Exception as exc:
            logger.warning("[%s] Erro ao extrair texto de %s: %s", prefixo, url, exc)

        # Captura screenshot
        img_path = capturar_screenshot(page, prefixo, nome_perfil)

        # Classifica o conteúdo
        classificacao = classificar_bio(bio_text)

        resultados.append({
            "termo"                 : termo,
            "perfil"                : nome_perfil,
            "url"                   : url,
            "bio"                   : bio_text,
            "status"                : classificacao["status"],
            "match"                 : classificacao["match"],
            "risk_score"            : classificacao.get("risk_score", 0),
            "risk_terms"            : classificacao.get("risk_terms", []),
            "screenshot"            : f"data/screenshots/{img_path.name}" if img_path else None,
            "verification_timestamp": datetime.now().isoformat(),
        })

    return resultados


# ==============================================================================
# 13. ROTEADOR DE PÁGINAS (Ponto de entrada do Streamlit)
# ==============================================================================
# O Streamlit re-executa este arquivo a cada interação do usuário.
# O estado da página atual é mantido em st.session_state["current_page"].
# ==============================================================================

pagina_atual = st.session_state["current_page"]

# ------------------------------------------------------------------------------
# HOME
# ------------------------------------------------------------------------------
if pagina_atual == "home":
    render_homepage()

# ------------------------------------------------------------------------------
# INSTAGRAM
# ------------------------------------------------------------------------------
elif pagina_atual == "instagram":
    st.title("🔎 GGTAB – Busca Automática no Instagram")

    with st.sidebar:
        render_sidebar_header()

        st.markdown("#### 🔑 Credenciais")
        ig_usuario = st.text_input("Usuário", value=os.getenv("IG_USERNAME", ""))
        ig_senha   = st.text_input("Senha", type="password", value=os.getenv("IG_PASSWORD", ""))

        st.markdown("#### 🔍 Termos de Busca")
        if st.button("✨ Sugerir termos"):
            st.session_state["ig_sug"] = suggest_terms(4)

        termos_atuais = st.session_state.get("ig_terms", ["vape brasil", "pod descartavel sp"])
        texto_termos  = st.text_area(
            "Termos (um por linha)",
            value="\n".join(termos_atuais),
            height=120,
            help="Use # para hashtags. Ex: #vapebrasil",
        )
        st.session_state["ig_terms"] = [x.strip() for x in texto_termos.splitlines() if x.strip()]

        st.markdown("#### ⚙️ Configurações")
        limite_perfis   = st.number_input("Limite de perfis por termo", 5, 200, 24)
        mostrar_browser = st.checkbox("Mostrar navegador (debug)", False)
        iniciar         = st.button("🚀 Iniciar Busca", type="primary", use_container_width=True)

    if iniciar:
        if not ig_usuario or not ig_senha:
            st.error("⛔ Usuário e senha são obrigatórios para o Instagram.")
        else:
            barra    = st.progress(0, text="Iniciando...")
            log_area = st.empty()

            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=not mostrar_browser)
                    ctx     = browser.new_context(viewport={"width": 1366, "height": 768})
                    page    = ctx.new_page()

                    log_area.info("🔐 Realizando login no Instagram...")
                    ig_login(page, ig_usuario, ig_senha)
                    barra.progress(20, text="Login concluído.")

                    log_area.info("🔍 Buscando perfis e posts...")
                    items_encontrados = ig_buscar(page, st.session_state["ig_terms"], limite_perfis)

                    # Remove perfis bloqueados e o próprio usuário logado
                    bloqueados = set(get_blocked_profiles())
                    usuario_lower = ig_usuario.strip().lower()
                    items_filtrados = [
                        item for item in items_encontrados
                        if item[1].strip("/").lower() not in bloqueados
                        and item[1].strip("/").lower() != usuario_lower
                    ]

                    log_area.info(f"📋 {len(items_filtrados)} itens encontrados. Visitando perfis...")
                    barra.progress(50, text="Visitando perfis...")

                    resultados = ig_visitar(page, items_filtrados)
                    browser.close()

                salvar_resultado_json("ig", resultados)
                artefatos = gerar_artefatos(resultados)

                st.session_state["res_ig"] = {"results": resultados, **artefatos}
                barra.progress(100, text="✅ Concluído!")
                log_area.success(f"✅ Busca finalizada! {len(resultados)} resultados.")

            except Exception as exc:
                st.error(f"❌ Erro durante a execução: {exc}")
                logger.exception("Erro no módulo Instagram")

    dados_ig = st.session_state.get("res_ig")
    if dados_ig:
        render_resultados(dados_ig, "👤", "res_ig", "ig")

# ------------------------------------------------------------------------------
# TIKTOK
# ------------------------------------------------------------------------------
elif pagina_atual == "tiktok":
    st.title("🎵 GGTAB – Busca Automática no TikTok")

    with st.sidebar:
        render_sidebar_header()
        st.info("ℹ️ Login manual obrigatório (CAPTCHA).")

        texto_termos = st.text_area(
            "Termos / Hashtags / @Perfis",
            value="\n".join(st.session_state.get("tt_terms", ["#vapebrasil"])),
            height=120,
            help="Use # para hashtags e @ para perfis.",
        )
        st.session_state["tt_terms"] = [t.strip() for t in texto_termos.splitlines() if t.strip()]

        limite  = st.number_input("Limite de itens por termo", min_value=1, max_value=500, value=10)
        modo    = st.radio(
            "Modo de Visita",
            ["⚡ Rápida (Apenas Vídeo)", "🕵️ Detalhada (Visita o Perfil)"],
        )
        detalhado = "Detalhada" in modo
        iniciar   = st.button("🚀 Iniciar Busca TikTok", type="primary", use_container_width=True)

    if iniciar:
        barra    = st.progress(0, text="Iniciando...")
        log_area = st.empty()

        try:
            profile_dir = str(DATA_DIR / "tiktok_profile")
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    viewport={"width": 1366, "height": 768},
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                log_area.info("🔐 Aguardando login manual no TikTok...")
                tt_aguardar_login(page)
                barra.progress(20, text="Login confirmado.")

                log_area.info("🔍 Buscando termos...")
                links_encontrados = tt_buscar(page, st.session_state["tt_terms"], limite)
                barra.progress(50, text=f"{len(links_encontrados)} itens encontrados. Visitando...")

                log_area.info(f"🌐 Visitando {len(links_encontrados)} itens...")
                resultados = tt_visitar(page, links_encontrados, detalhado)
                ctx.close()

            salvar_resultado_json("tt", resultados)
            artefatos = gerar_artefatos(resultados)

            st.session_state["res_tt"] = {"results": resultados, **artefatos}
            barra.progress(100, text="✅ Concluído!")
            log_area.success(f"✅ Busca finalizada! {len(resultados)} resultados.")

        except Exception as exc:
            st.error(f"❌ Erro durante a execução: {exc}")
            logger.exception("Erro no módulo TikTok")

    dados_tt = st.session_state.get("res_tt")
    if dados_tt:
        render_resultados(dados_tt, "🎵", "res_tt", "tt")

# ------------------------------------------------------------------------------
# THREADS
# ------------------------------------------------------------------------------
elif pagina_atual == "threads":
    st.title("🧵 GGTAB – Busca Automática no Threads")

    with st.sidebar:
        render_sidebar_header()
        st.info("ℹ️ Login manual necessário na 1ª vez.")

        texto_termos = st.text_area("Termos (um por linha)", value="vape", height=120)
        st.session_state["th_terms"] = [t.strip() for t in texto_termos.splitlines() if t.strip()]

        filtro  = st.radio("Filtro de Busca", ["Principais", "Recentes", "Perfis"])
        limite  = st.number_input("Limite de itens", 5, 100, 10)
        iniciar = st.button("🚀 Iniciar Busca Threads", type="primary", use_container_width=True)

    if iniciar:
        barra    = st.progress(0, text="Iniciando...")
        log_area = st.empty()

        try:
            profile_dir = str(DATA_DIR / "threads_profile")
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    viewport={"width": 1366, "height": 768},
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                log_area.info("🔐 Aguardando login no Threads...")
                th_aguardar_login(page)
                barra.progress(20, text="Login confirmado.")

                log_area.info(f"🔍 Buscando ({filtro})...")
                links_encontrados = th_buscar(page, st.session_state["th_terms"], limite, filtro)
                barra.progress(50, text=f"{len(links_encontrados)} itens. Visitando...")

                log_area.info(f"🌐 Visitando {len(links_encontrados)} itens...")
                resultados = visitar_generico(page, links_encontrados, "th")
                ctx.close()

            salvar_resultado_json("th", resultados)
            artefatos = gerar_artefatos(resultados)

            st.session_state["res_th"] = {"results": resultados, **artefatos}
            barra.progress(100, text="✅ Concluído!")
            log_area.success(f"✅ Busca finalizada! {len(resultados)} resultados.")

        except Exception as exc:
            st.error(f"❌ Erro durante a execução: {exc}")
            logger.exception("Erro no módulo Threads")

    dados_th = st.session_state.get("res_th")
    if dados_th:
        render_resultados(dados_th, "🧵", "res_th", "th")

# ------------------------------------------------------------------------------
# FACEBOOK
# ------------------------------------------------------------------------------
elif pagina_atual == "facebook":
    st.title("📘 GGTAB – Busca Automática no Facebook")

    with st.sidebar:
        render_sidebar_header()
        st.warning("⚠️ Requer login manual na 1ª vez.")

        texto_termos = st.text_area("Termos (um por linha)", value="vape", height=120)
        termos_fb    = [t.strip() for t in texto_termos.splitlines() if t.strip()]

        modo    = st.radio("Buscar em", ["Principais", "Páginas", "Grupos"])
        limite  = st.number_input("Limite de itens", 5, 100, 10)
        iniciar = st.button("🚀 Iniciar Busca Facebook", type="primary", use_container_width=True)

    if iniciar:
        barra    = st.progress(0, text="Iniciando...")
        log_area = st.empty()

        try:
            profile_dir = str(DATA_DIR / "facebook_profile")
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    viewport={"width": 1366, "height": 768},
                    args=[
                        "--disable-notifications",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                log_area.info("🔐 Aguardando login no Facebook (30s)...")
                page.goto("https://www.facebook.com/")
                time.sleep(30)
                barra.progress(20, text="Login confirmado.")

                log_area.info("🔍 Buscando...")
                links_encontrados = fb_buscar(page, termos_fb, limite, modo)
                barra.progress(50, text=f"{len(links_encontrados)} itens. Visitando...")

                log_area.info(f"🌐 Visitando {len(links_encontrados)} itens...")
                resultados = visitar_generico(page, links_encontrados, "fb")
                ctx.close()

            salvar_resultado_json("fb", resultados)
            artefatos = gerar_artefatos(resultados)

            st.session_state["res_fb"] = {"results": resultados, **artefatos}
            barra.progress(100, text="✅ Concluído!")
            log_area.success(f"✅ Busca finalizada! {len(resultados)} resultados.")

        except Exception as exc:
            st.error(f"❌ Erro durante a execução: {exc}")
            logger.exception("Erro no módulo Facebook")

    dados_fb = st.session_state.get("res_fb")
    if dados_fb:
        render_resultados(dados_fb, "📘", "res_fb", "fb")

# ------------------------------------------------------------------------------
# PINTEREST
# ------------------------------------------------------------------------------
elif pagina_atual == "pinterest":
    st.title("📌 GGTAB – Busca Automática no Pinterest")

    with st.sidebar:
        render_sidebar_header()

        texto_termos = st.text_area("Termos (um por linha)", value="vape brasil", height=120)
        termos_pin   = [t.strip() for t in texto_termos.splitlines() if t.strip()]

        modo    = st.radio("Buscar por", ["Pins", "Perfis", "Pastas"])
        limite  = st.number_input("Limite de itens", 5, 100, 10)
        iniciar = st.button("🚀 Iniciar Busca Pinterest", type="primary", use_container_width=True)

    if iniciar:
        barra    = st.progress(0, text="Iniciando...")
        log_area = st.empty()

        try:
            profile_dir = str(DATA_DIR / "pinterest_profile")
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    viewport={"width": 1366, "height": 768},
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                log_area.info("🔐 Aguardando login opcional no Pinterest (15s)...")
                page.goto("https://br.pinterest.com/")
                time.sleep(15)
                barra.progress(20, text="Pronto para buscar.")

                log_area.info("🔍 Buscando...")
                links_encontrados = pin_buscar(page, termos_pin, limite, modo)
                barra.progress(50, text=f"{len(links_encontrados)} itens. Visitando...")

                log_area.info(f"🌐 Visitando {len(links_encontrados)} itens...")
                resultados = visitar_generico(page, links_encontrados, "pin")
                ctx.close()

            salvar_resultado_json("pin", resultados)
            artefatos = gerar_artefatos(resultados)

            st.session_state["res_pin"] = {"results": resultados, **artefatos}
            barra.progress(100, text="✅ Concluído!")
            log_area.success(f"✅ Busca finalizada! {len(resultados)} resultados.")

        except Exception as exc:
            st.error(f"❌ Erro durante a execução: {exc}")
            logger.exception("Erro no módulo Pinterest")

    dados_pin = st.session_state.get("res_pin")
    if dados_pin:
        render_resultados(dados_pin, "📌", "res_pin", "pin")
