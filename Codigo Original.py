# automation/app_streamlit_v8.py
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import asyncio
import os
import platform
import time
import json
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

import streamlit as st
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from analyzer import classificar_bio
from report_pdf import build_pdf, criar_volume_evidencias
from recommender import (
    suggest_terms,
    append_terms_history,
    append_feedback,
    get_top_voted_terms,
    get_blocked_profiles,
)

# --------------------------
# Compat Windows (event loop)
# --------------------------
if platform.system() == "Windows":
    try:
        import asyncio.windows_events
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

# --------------------------
# Paths e .env
# --------------------------
BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "data"
SCREEN_DIR = DATA_DIR / "screenshots"
OUTPUT_DIR = DATA_DIR / "outputs"
FRONT_JSON = BASE / "data" / "last_run.json"  # repositório de resultado atual (não há mais HTML)

load_dotenv(BASE / ".env")

# --------------------------
# Streamlit UI
# --------------------------
st.set_page_config(layout="wide", page_title="GGTAB - Monitoramento", page_icon="🔎")

# Inicializa a página selecionada se não existir
if "current_page" not in st.session_state:
    st.session_state["current_page"] = "home"

# Função para renderizar a homepage
def render_homepage():
    # Logo no topo
    logo_path = DATA_DIR / "assets" / "logo_anvisa.png"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=False, width=300)
        st.markdown("")
    
    st.title("🔎 GGTAB – Plataforma de Monitoramento")
    st.markdown("---")
    st.markdown("### Bem-vindo à plataforma GGTAB")
    st.markdown("Selecione o projeto que deseja utilizar:")
    st.markdown("")
    
    # Botões em colunas
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 📱 Busca no Instagram")
        st.markdown("Sistema de busca automática de perfis no Instagram com análise de biografias e geração de relatórios.")
        if st.button("🚀 Acessar Busca Instagram", key="btn_instagram", use_container_width=True, type="primary"):
            st.session_state["current_page"] = "instagram"
            st.rerun()
    
    with col2:
        st.markdown("#### 🍔 Busca no iFood")
        st.markdown("Sistema de busca automática de estabelecimentos no iFood com análise de produtos e avaliações.")
        if st.button("🚀 Acessar Busca iFood", key="btn_ifood", use_container_width=True, type="primary"):
            st.session_state["current_page"] = "ifood"
            st.rerun()
    
    st.markdown("---")
    st.markdown("### ℹ️ Sobre")
    st.info("""
    **GGTAB** é uma plataforma de monitoramento desenvolvida para auxiliar na identificação e análise de perfis e estabelecimentos 
    em redes sociais e plataformas de delivery. Os sistemas utilizam automação e inteligência artificial para facilitar 
    o trabalho de análise e geração de relatórios.
    """)

# Função para renderizar a página do iFood (placeholder)
def render_ifood_page():
    st.title("🍔 GGTAB – Busca Automática no iFood")
    st.markdown("---")
    
    if st.button("← Voltar para Home", key="btn_back_ifood"):
        st.session_state["current_page"] = "home"
        st.rerun()
    
    st.markdown("### 🚧 Em Desenvolvimento")
    st.warning("""
    O sistema de busca no iFood está em desenvolvimento e estará disponível em breve.
    
    **Funcionalidades planejadas:**
    - Busca automática de estabelecimentos no iFood
    - Análise de produtos e cardápios
    - Análise de avaliações e comentários
    - Geração de relatórios em PDF
    - Exportação de evidências
    """)
    
    st.info("💡 Enquanto isso, você pode utilizar o sistema de busca no Instagram que já está totalmente funcional!")

# Renderiza a página apropriada
if st.session_state["current_page"] == "home":
    render_homepage()
elif st.session_state["current_page"] == "ifood":
    render_ifood_page()
else:
    # Página do Instagram (conteúdo original)
    st.title("🔎 GGTAB – Busca Automática no Instagram (v8)")
    
    # Todo o conteúdo do Instagram continua aqui
    FALLBACK_CUSTOM_TERMS = ["vape brasil", "pod descartavel sp", "narguile delivery rj"]


    def _initial_custom_terms() -> List[str]:
        voted_terms = get_top_voted_terms(20)
        if voted_terms:
            return list(voted_terms)
        return FALLBACK_CUSTOM_TERMS.copy()


    INITIAL_CUSTOM_TERMS = _initial_custom_terms()
    SESSION_DEFAULTS = {
        "custom_terms": INITIAL_CUSTOM_TERMS,
        "ollama_suggestions": [],
        "last_results": None,
        "votes_batch": [],
    }
    for _key, _default in SESSION_DEFAULTS.items():
        if _key not in st.session_state:
            st.session_state[_key] = _default.copy() if isinstance(_default, list) else _default

    with st.sidebar:
        # Logo no topo da sidebar
        logo_path = DATA_DIR / "assets" / "logo_anvisa.png"
        if logo_path.exists():
            st.image(str(logo_path), use_container_width=True)
            st.markdown("")
        
        # Botão para voltar à home
        if st.button("← Voltar para Home", key="btn_back_instagram", use_container_width=True):
            st.session_state["current_page"] = "home"
            st.rerun()
        
        st.divider()
        
        st.header("Credenciais")
        ig_username = st.text_input("Usuário do Instagram", value=os.getenv("IG_USERNAME", ""))
        ig_password = st.text_input("Senha do Instagram", type="password", value=os.getenv("IG_PASSWORD", ""))

        st.header("Termos")
        # Sugestões do Ollama (4 termos)
        if st.button("✨ Sugerir termos com Ollama"):
            st.session_state["ollama_suggestions"] = suggest_terms(4)
        suggestions = st.session_state.get("ollama_suggestions", [])
        if suggestions:
            st.caption("Sugestões do Ollama (clique para adicionar):")
            cols = st.columns(len(suggestions))
            for i, s in enumerate(suggestions):
                if cols[i].button(s, key=f"sugg_{i}"):
                    if s not in st.session_state["custom_terms"]:
                        st.session_state["custom_terms"].append(s)

        custom_terms = st.text_area(
            "Seus termos (um por linha)",
            value="\n".join(st.session_state.get("custom_terms", INITIAL_CUSTOM_TERMS)),
            height=120,
        )
        st.session_state["custom_terms"] = [t.strip() for t in custom_terms.splitlines() if t.strip()]
        headful = st.checkbox("Mostrar navegador (não headless)", value=False)
        max_perfis = st.number_input("Limite de perfis", min_value=5, max_value=200, value=24, step=1)
        
        st.divider()
        
        # Botão para iniciar busca
        go = st.button("🚀 Iniciar Busca", use_container_width=True, type="primary")
    
    # Barra de progresso e log (fora da sidebar, no conteúdo principal)
    bar = st.progress(0)
    log = st.empty()

    # --------------------------
    # Funções auxiliares
    # --------------------------
    def register_vote(idx: int, sentiment: str) -> None:
        run_data = st.session_state.get("last_results")
        if not run_data:
            return
        resultados = run_data.get("results") or []
        if idx < 0 or idx >= len(resultados):
            return
        alvo = resultados[idx]
        voto = {
            "term": alvo["termo"],
            "profile": alvo["perfil"],
            "vote": sentiment,
            "ts": datetime.now().isoformat(),
        }
        votos = st.session_state.setdefault("votes_batch", [])
        for i, existente in enumerate(votos):
            if existente["term"] == voto["term"] and existente["profile"] == voto["profile"]:
                votos[i] = voto
                break
        else:
            votos.append(voto)

    def login(page, user: str, pwd: str) -> None:
        page.goto("https://www.instagram.com/accounts/login/")
        time.sleep(3)

        try:
            if page.locator('input[name="username"]').count() > 0:
                page.fill('input[name="username"]', user)
                page.fill('input[name="password"]', pwd)
                page.click('button[type="submit"]')
            else:
                page.get_by_label("Número de celular, nome de usuário ou email").fill(user)
                page.get_by_label("Senha").fill(pwd)
                page.get_by_role("button", name="Entrar", exact=True).click()
        except Exception:
            try:
                page.keyboard.press("Enter")
            except Exception:
                pass

        time.sleep(10)

        for name in ["Agora não", "Not now", "OK", "Ok", "ok"]:
            btn = page.get_by_role("button", name=name)
            if btn.count() > 0 and btn.first.is_visible():
                try:
                    btn.first.click()
                    time.sleep(1.5)
                except Exception:
                    pass

    def _get_search_box(page):
        try:
            locator = page.get_by_role("main").get_by_role(
                "textbox",
                name=re.compile("Entrada da pesquisa|Search input|Pesquisar", re.IGNORECASE),
            )
            locator.wait_for(state="visible", timeout=15000)
            return locator
        except Exception:
            pass

        try:
            locator = page.locator('input[placeholder*="Pesquisar"], input[aria-label*="Pesquisa"]')
            locator.wait_for(state="visible", timeout=15000)
            return locator
        except Exception:
            pass

        raise RuntimeError("Campo de busca do Instagram não localizado. A UI pode ter mudado.")

    def buscar(page, termos: List[str], maxn: int) -> List[Tuple[str, str]]:
        search = _get_search_box(page)
        acumulado: List[Tuple[str, str]] = []

        for termo in termos:
            if len(acumulado) >= maxn:
                break

            search.fill("")
            time.sleep(0.4)
            search.fill(termo)
            try:
                page.wait_for_load_state("load", timeout=7000)
            except PWTimeout:
                pass
            time.sleep(8)

            try:
                links = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            except Exception:
                links = []

            for link in links:
                m = re.search(r"https://www\.instagram\.com/([a-zA-Z0-9_.-]{3,30})/$", link)
                if not m:
                    continue
                user = m.group(1)
                if user in {"explore", "reels", "p", "accounts", "login"}:
                    continue
                acumulado.append((termo, f"/{user}/"))

            time.sleep(0.8)

        seen = set()
        out_list: List[Tuple[str, str]] = []
        for termo, p in acumulado:
            if p not in seen:
                seen.add(p)
                out_list.append((termo, p))

        return out_list[:maxn]

    def visitar(page, perfis_pairs: List[Tuple[str, str]]) -> List[Dict]:
        SCREEN_DIR.mkdir(parents=True, exist_ok=True)
        resultados = []

        for termo, p in perfis_pairs:
            url = f"https://www.instagram.com{p}"
            try:
                page.goto(url, timeout=20000)
            except PWTimeout:
                continue

            time.sleep(4)
            safe = p.replace("/", "_")
            filename = f"print_{safe}.png"
            img_path = SCREEN_DIR / filename
            page.screenshot(path=str(img_path), full_page=True)

            bio = ""
            bio_links = []
            perfil_nome = p.strip("/")
            
            print(f"\n{'='*60}")
            print(f"[BIO] Processando perfil: @{perfil_nome}")
            print(f"{'='*60}")
            
            # Primeiro, tenta clicar no botão "mais..." se existir para expandir o texto
            try:
                # Usa JavaScript para encontrar e clicar no botão "mais..."
                expand_clicked = page.evaluate("""
                    () => {
                        // Procura por botões na área da biografia que contenham "mais", "more", etc
                        const headerSection = document.querySelector('header section');
                        if (!headerSection) return false;
                        
                        const allButtons = headerSection.querySelectorAll('div[role="button"], button, span[role="button"]');
                        for (let btn of allButtons) {
                            const text = (btn.innerText || btn.textContent || '').toLowerCase();
                            if (text.includes('mais') || text.includes('more') || text.includes('ver mais') || text.includes('see more')) {
                                try {
                                    btn.click();
                                    return true;
                                } catch (e) {
                                    // Tenta com dispatchEvent se click não funcionar
                                    try {
                                        const event = new MouseEvent('click', { bubbles: true, cancelable: true });
                                        btn.dispatchEvent(event);
                                        return true;
                                    } catch (e2) {
                                        continue;
                                    }
                                }
                            }
                        }
                        return false;
                    }
                """)
                
                if expand_clicked:
                    print(f"[BIO] Botão 'mais...' encontrado e clicado via JavaScript")
                    time.sleep(1.5)  # Aguarda o texto expandir
                else:
                    print(f"[BIO] Nenhum botão 'mais...' encontrado (ou já expandido)")
            except Exception as e:
                print(f"[BIO] Erro ao procurar/clicar no botão 'mais...': {str(e)[:50]}")
            
            # Captura biografia completa usando JavaScript com o elemento específico
            try:
                # Usa JavaScript para extrair o texto completo da biografia
                # Procura pelo elemento específico: div[role="button"] com span dentro
                bio_js_result = page.evaluate("""
                    () => {
                        // Função auxiliar para verificar se é apenas números
                        function isOnlyNumbers(str) {
                            // Remove tudo exceto números, vírgulas, pontos e espaços
                            const cleaned = str.replace(/[^0-9,. ]/g, '');
                            if (cleaned.length === 0) return false;
                            // Remove vírgulas, pontos e espaços
                            const numbersOnly = cleaned.replace(/[,. ]/g, '');
                            // Se sobrar apenas números e tiver pelo menos um, é só números
                            return /^[0-9]+$/.test(numbersOnly) && numbersOnly.length > 0;
                        }
                        
                        // Função auxiliar para verificar se é texto de botão
                        function isButtonText(str) {
                            const lower = str.toLowerCase();
                            const buttonTexts = ['seguir', 'seguindo', 'mensagem', 'mais', 'more', 'ver mais', 'see more'];
                            return buttonTexts.includes(lower);
                        }
                        
                        // Primeiro, procura dentro do header section (mais específico)
                        const headerSection = document.querySelector('header section');
                        if (!headerSection) return null;
                        
                        // Procura pelo elemento específico da biografia: div[role="button"] com span[dir="auto"]
                        const bioDivs = headerSection.querySelectorAll('div[role="button"]');
                        
                        for (let bioDiv of bioDivs) {
                            // Procura pelo span[dir="auto"] dentro do div
                            const bioSpan = bioDiv.querySelector('span[dir="auto"]');
                            if (bioSpan) {
                                // Captura o texto completo, preservando quebras de linha
                                // innerText já converte <br> em quebras de linha (\\n)
                                let text = bioSpan.innerText || bioSpan.textContent || '';
                                
                                // Se não encontrou texto no span, tenta no div
                                if (!text || text.trim().length === 0) {
                                    text = bioDiv.innerText || bioDiv.textContent || '';
                                }
                                
                                if (text && text.trim().length > 5) {
                                    const cleanText = text.trim();
                                    if (!isOnlyNumbers(cleanText) && !isButtonText(cleanText)) {
                                        return cleanText;
                                    }
                                }
                            }
                        }
                        
                        // Fallback: Procura por qualquer div[role="button"] com span na seção do header
                        for (let bioDiv of bioDivs) {
                            const spans = bioDiv.querySelectorAll('span');
                            for (let span of spans) {
                                const text = span.innerText || span.textContent || '';
                                if (text && text.trim().length > 5) {
                                    const cleanText = text.trim();
                                    if (!isOnlyNumbers(cleanText) && !isButtonText(cleanText)) {
                                        return cleanText;
                                    }
                                }
                            }
                        }
                        
                        // Fallback 2: Procura pelo h1 e pega o próximo elemento com texto
                        const h1 = document.querySelector('header section h1');
                        if (h1) {
                            let nextEl = h1.nextElementSibling;
                            let attempts = 0;
                            while (nextEl && attempts < 5) {
                                const text = nextEl.innerText || nextEl.textContent || '';
                                if (text && text.trim().length > 5) {
                                    const cleanText = text.trim();
                                    if (!isOnlyNumbers(cleanText) && !isButtonText(cleanText)) {
                                        return cleanText;
                                    }
                                }
                                nextEl = nextEl.nextElementSibling;
                                attempts++;
                            }
                        }
                        
                        return null;
                    }
                """)
                
                if bio_js_result:
                    bio = bio_js_result
                    print(f"[BIO] Texto capturado via JavaScript: {bio[:200]}...")
                else:
                    print(f"[BIO] JavaScript não retornou texto, tentando seletores do Playwright...")
                    
                    # Fallback: Seletores do Playwright focados no elemento específico
                    bio_selectors = [
                        'div[role="button"][tabindex="0"] span[dir="auto"]',
                        'div[role="button"] span[dir="auto"]',
                        'header section div[role="button"] span',
                        '//h1/following-sibling::div[@role="button"]//span',
                    ]
                    
                    for selector in bio_selectors:
                        try:
                            if selector.startswith('//'):
                                bio_el = page.locator(selector).first
                            else:
                                bio_el = page.locator(selector).first
                            
                            if bio_el.count() > 0:
                                text_content = bio_el.inner_text(timeout=3000)
                                if text_content and text_content.strip() and len(text_content.strip()) > 5:
                                    # Verifica se não é apenas números
                                    if not re.match(r'^[\d,\s\.]+$', text_content.replace(',', '').replace('.', '').strip()):
                                        bio = text_content.strip()
                                        print(f"[BIO] Texto capturado (seletor: {selector[:40]}...): {bio[:100]}...")
                                        break
                        except Exception as e:
                            print(f"[BIO] Seletor '{selector[:40]}...' falhou: {str(e)[:50]}")
                            continue
                    
                    # Última tentativa: captura toda a área da bio e filtra
                    if not bio:
                        try:
                            bio_area = page.locator('header section').first
                            if bio_area.count() > 0:
                                all_text = bio_area.inner_text(timeout=3000)
                                lines = all_text.split('\n')
                                for line in lines:
                                    line_clean = line.strip()
                                    # Ignora linhas muito curtas, só números, ou que parecem ser botões
                                    if (len(line_clean) > 10 and 
                                        not re.match(r'^[\d,\s\.]+$', line_clean.replace(',', '').replace('.', '')) and
                                        line_clean.lower() not in ['seguir', 'seguindo', 'mensagem', 'mais', 'more', 'ver mais', 'see more']):
                                        bio = line_clean
                                        print(f"[BIO] Texto capturado da área geral: {bio[:100]}...")
                                        break
                        except Exception as e:
                            print(f"[BIO] Captura da área geral falhou: {str(e)[:50]}")
                
                if not bio:
                    print(f"[BIO] ⚠️ Nenhum texto de biografia encontrado")
                else:
                    print(f"[BIO] Texto final da biografia capturado ({len(bio)} caracteres): {bio[:200]}...")
                
                # Captura links separadamente usando JavaScript
                try:
                    links_js_result = page.evaluate("""
                        () => {
                            const links = [];
                            // Procura links na área da biografia (header section)
                            const headerSection = document.querySelector('header section');
                            if (headerSection) {
                                const allLinks = headerSection.querySelectorAll('a[href]');
                                allLinks.forEach(link => {
                                    const href = link.getAttribute('href');
                                    if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
                                        const linkText = (link.innerText || link.textContent || '').trim();
                                        links.push({
                                            url: href,
                                            text: linkText
                                        });
                                    }
                                });
                            }
                            return links;
                        }
                    """)
                    
                    if links_js_result and len(links_js_result) > 0:
                        bio_links = links_js_result
                        print(f"[BIO] Links capturados via JavaScript: {len(bio_links)}")
                        for link in bio_links:
                            link_text = link.get('text', '') or ''
                            print(f"[BIO]   - {link['url']} (texto: '{link_text[:50]}')")
                    else:
                        # Fallback: tenta com seletores do Playwright
                        print(f"[BIO] JavaScript não retornou links, tentando seletores...")
                        try:
                            bio_links_elements = page.locator('header section a[href]').all()
                            for link_el in bio_links_elements:
                                try:
                                    href = link_el.get_attribute('href')
                                    if href and (href.startswith('http://') or href.startswith('https://')):
                                        link_text = link_el.inner_text(timeout=1000) or ""
                                        bio_links.append({
                                            'url': href,
                                            'text': link_text.strip()
                                        })
                                        print(f"[BIO] Link encontrado (seletor): {href}")
                                except Exception:
                                    continue
                        except Exception as e:
                            print(f"[BIO] Erro ao capturar links com seletores: {str(e)[:50]}")
                    
                    if bio_links:
                        print(f"[BIO] Total de links encontrados: {len(bio_links)}")
                    else:
                        print(f"[BIO] Nenhum link encontrado na biografia")
                        
                except Exception as e:
                    print(f"[BIO] Erro ao capturar links: {str(e)}")
                
                # Combina texto e links de forma inteligente
                if bio_links:
                    # Remove links que já estão no texto da bio
                    links_to_add = []
                    for link in bio_links:
                        # Verifica se a URL já está no texto da bio
                        if link['url'] not in bio:
                            links_to_add.append(link)
                        else:
                            print(f"[BIO] Link já presente no texto: {link['url'][:50]}...")
                    
                    if links_to_add:
                        if bio:
                            # Adiciona links ao final do texto
                            links_text = ' | '.join([
                                f"{link['text']} ({link['url']})" if link['text'] and link['text'] != link['url'] 
                                else link['url'] 
                                for link in links_to_add
                            ])
                            bio = f"{bio} | Links: {links_text}"
                            print(f"[BIO] Links adicionados ao texto da bio")
                        else:
                            # Se não tem texto, usa os links como bio
                            bio = ' | '.join([link['url'] for link in links_to_add])
                            print(f"[BIO] Bio contém apenas links: {bio}")
                elif not bio:
                    print(f"[BIO] ⚠️ Nenhum conteúdo (texto ou links) encontrado na biografia")
                    
            except Exception as e:
                print(f"[BIO] ❌ Erro geral ao capturar biografia: {str(e)}")
                bio = ""
            
            print(f"[BIO] Resultado final - Texto: {'Sim' if bio else 'Não'} | Links: {len(bio_links)}")
            print(f"{'='*60}\n")

            klass = classificar_bio(bio)
            # Timestamp da verificação deste perfil
            verification_timestamp = datetime.now().isoformat()
            resultados.append(
                {
                    "termo": termo,
                    "perfil": p.strip("/"),
                    "url": url,
                    "bio": bio,
                    "status": klass["status"],
                    "match": klass["match"],
                    "risk_score": klass.get("risk_score", 0),
                    "risk_terms": klass.get("risk_terms", []),
                    "screenshot": f"data/screenshots/{filename}",  # relativo p/ PDF ok
                    "verification_timestamp": verification_timestamp,  # Data e hora da verificação
                }
            )
        return resultados

    # --------------------------
    # Execução
# --------------------------
    if go:
        if not ig_username or not ig_password:
            st.error("Preencha usuário e senha do Instagram.")
            st.stop()

        termos = [t.strip() for t in custom_terms.splitlines() if t.strip()]
        if not termos:
            st.error("Informe ao menos um termo.")
            st.stop()

        # guarda histórico de termos (alimenta Ollama nas próximas)
        append_terms_history(termos)

        resultados = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=not headful)
                ctx = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/114.0.0.0 Safari/537.36"
                )
                page = ctx.new_page()

                log.info("Fazendo login...")
                bar.progress(10)
                login(page, ig_username, ig_password)

                log.info("Buscando termos...")
                bar.progress(40)
                perfis = buscar(page, termos, max_perfis)

                # Excluir perfis bloqueados e o perfil logado
                blocked = set(get_blocked_profiles())
                login_user = (ig_username or "").strip().lower()
                if login_user:
                    blocked.add(login_user)

                before = len(perfis)
                perfis_removidos = []
                perfis_filtrados = []
                for t, p in perfis:
                    perfil_clean = p.strip("/").lower()
                    if perfil_clean in blocked:
                        perfis_removidos.append((t, p.strip("/")))
                    else:
                        perfis_filtrados.append((t, p))
                
                perfis = perfis_filtrados
                removed = before - len(perfis)
                if removed > 0:
                    with st.expander(f"ℹ️ {removed} perfis ignorados (bloqueados/conta logada)", expanded=False):
                        st.caption("Estes perfis foram encontrados na busca mas foram ignorados por estarem na lista de bloqueados ou serem a conta logada.")
                        for termo, perfil in perfis_removidos:
                            st.text(f"• @{perfil} (termo: {termo})")

                log.info(f"{len(perfis)} perfis encontrados. Visitando...")
                bar.progress(60)
                resultados = visitar(page, perfis)

        except Exception as e:
            st.exception(e)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

        # Persistência "last run" (não há mais HTML)
        run_ts = datetime.now().isoformat()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        FRONT_JSON.write_text(
            json.dumps(
                {"timestamp": run_ts, "terms": termos, "results": resultados},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # PDF + ZIP
        bar.progress(80)
        pdf_path = build_pdf(resultados, str(OUTPUT_DIR))
        zip_path = criar_volume_evidencias(str(OUTPUT_DIR), str(SCREEN_DIR), pdf_path)
        bar.progress(100)

        st.session_state["last_results"] = {
            "timestamp": run_ts,
            "terms": termos,
            "results": resultados,
            "pdf_path": pdf_path,
            "zip_path": zip_path,
        }
        st.session_state["votes_batch"] = []

    run_data = st.session_state.get("last_results")
    if run_data:
        resultados = run_data.get("results") or []

        st.success(f"✅ Execução concluída: {len(resultados)} perfis.")
        
        # Botões de download para PDF e ZIP
        st.subheader("📥 Download dos Arquivos Gerados")
        download_cols = st.columns(2)
        
        with download_cols[0]:
            if run_data.get("pdf_path"):
                pdf_path_obj = Path(run_data['pdf_path'])
                if pdf_path_obj.exists():
                    # Mostra informações do arquivo
                    file_size = pdf_path_obj.stat().st_size / 1024  # Tamanho em KB
                    st.caption(f"📄 Relatório PDF ({file_size:.1f} KB)")
                    with open(pdf_path_obj, "rb") as pdf_file:
                        pdf_bytes = pdf_file.read()
                        st.download_button(
                            label="⬇️ Baixar PDF",
                            data=pdf_bytes,
                            file_name=pdf_path_obj.name,
                            mime="application/pdf",
                            key="download_pdf",
                            use_container_width=True
                        )
                else:
                    st.warning(f"PDF não encontrado: {run_data['pdf_path']}")
            else:
                st.info("PDF ainda não foi gerado.")
        
        with download_cols[1]:
            if run_data.get("zip_path"):
                zip_path_obj = Path(run_data['zip_path'])
                if zip_path_obj.exists():
                    # Mostra informações do arquivo
                    file_size = zip_path_obj.stat().st_size / 1024  # Tamanho em KB
                    st.caption(f"📦 Arquivo ZIP com evidências ({file_size:.1f} KB)")
                    with open(zip_path_obj, "rb") as zip_file:
                        zip_bytes = zip_file.read()
                        st.download_button(
                            label="⬇️ Baixar ZIP",
                            data=zip_bytes,
                            file_name=zip_path_obj.name,
                            mime="application/zip",
                            key="download_zip",
                            use_container_width=True
                        )
                else:
                    st.warning(f"ZIP não encontrado: {run_data['zip_path']}")
            else:
                st.info("ZIP ainda não foi gerado.")

        st.divider()
        st.subheader("Feedback dos resultados (treina próximas sugestões)")

        if not resultados:
            st.info("Nenhum resultado para votar desta vez.")
        else:
            votes_batch = st.session_state.get("votes_batch", [])
            for i, r in enumerate(resultados):
                with st.container():
                    cols = st.columns([3, 1, 1])
                    with cols[0]:
                        st.markdown(f"**@{r['perfil']}** — {r['url']}")
                        st.caption(f"Status: {r.get('status', 'N/A')} | Palavra-chave: {r.get('match') or '—'}")
                        st.metric("Pontuação de risco", r.get("risk_score", 0))
                        risk_terms = r.get("risk_terms") or []
                        if risk_terms:
                            termos_fmt = ", ".join(f"{item['term']} (x{item['count']})" for item in risk_terms)
                            st.caption(f"Termos de risco detectados: {termos_fmt}")
                        else:
                            st.caption("Termos de risco detectados: —")
                        if r.get("bio"):
                            st.write(r["bio"])
                        if r.get("screenshot"):
                            img_abs = (BASE / r["screenshot"]).resolve()
                            if img_abs.exists():
                                st.image(str(img_abs), use_container_width=True)
                        current_vote = next(
                            (v for v in votes_batch if v["term"] == r["termo"] and v["profile"] == r["perfil"]),
                            None,
                        )
                        if current_vote:
                            emoji = "👍" if current_vote["vote"] == "up" else "👎"
                            rotulo = "Relevante" if current_vote["vote"] == "up" else "Irrelevante"
                            st.caption(f"Voto atual: {emoji} {rotulo}")

                    with cols[1]:
                        st.button("👍 Relevante", key=f"up_{i}", on_click=register_vote, args=(i, "up"))
                    with cols[2]:
                        st.button("👎 Irrelevante", key=f"down_{i}", on_click=register_vote, args=(i, "down"))

                    st.markdown("---")

        votes_to_save = st.session_state.get("votes_batch", [])
        if st.button("💾 Salvar votos desta execução", disabled=not votes_to_save):
            if votes_to_save:
                append_feedback(votes_to_save)
                st.success(f"{len(votes_to_save)} votos salvos! Eles influenciarão as próximas sugestões do Ollama.")
                st.session_state["votes_batch"] = []
            else:
                st.info("Sem votos para salvar.")
    elif go:
        # Protege contra cenário em que a execução falha antes de produzir resultados
        st.info("Execução concluída sem resultados para exibir.")

# As funções register_vote, login, buscar e visitar foram movidas para dentro do bloco do Instagram
# (antes do código de execução) para evitar erros de "not defined"