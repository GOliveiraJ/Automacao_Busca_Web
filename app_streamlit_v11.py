# automation/app_final_v10_pro.py
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import asyncio
import os
import platform
import time
import json
import re
import urllib.parse
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional

import streamlit as st
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

# Importações dos módulos auxiliares
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
# 1. CONFIGURAÇÕES INICIAIS
# --------------------------
if platform.system() == "Windows":
    try:
        import asyncio.windows_events
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception: pass

BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "data"
SCREEN_DIR = DATA_DIR / "screenshots"
OUTPUT_DIR = DATA_DIR / "outputs"
JSON_IG = BASE / "data" / "last_run.json"
JSON_TT = BASE / "data" / "last_run_tiktok.json"
JSON_TH = BASE / "data" / "last_run_threads.json"
JSON_FB = BASE / "data" / "last_run_facebook.json"   
JSON_PIN = BASE / "data" / "last_run_pinterest.json" 

# Garante a existência das pastas
SCREEN_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE / ".env")

st.set_page_config(layout="wide", page_title="GGTAB - Monitoramento Integrado", page_icon="🔎")

if "current_page" not in st.session_state:
    st.session_state["current_page"] = "home"

# ==============================================================================
# 2. FUNÇÕES GERAIS E DE INTERFACE (FRONTEND)
# ==============================================================================

def render_sidebar_header():
    """Renderiza a logo e o botão de voltar na barra lateral."""
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

def register_vote(idx: int, sentiment: str, platform_key: str) -> None:
    """Registra o feedback positivo/negativo do usuário na memória."""
    run_data = st.session_state.get(platform_key)
    if not run_data: return
    resultados = run_data.get("results") or []
    if idx < 0 or idx >= len(resultados): return
    alvo = resultados[idx]
    voto = {
        "term": alvo["termo"],
        "profile": alvo["perfil"],
        "vote": sentiment,
        "ts": datetime.now().isoformat(),
        "platform": platform_key.replace("res_", "")
    }
    votos = st.session_state.setdefault("votes_batch", [])
    for i, existente in enumerate(votos):
        if existente["term"] == voto["term"] and existente["profile"] == voto["profile"]:
            votos[i] = voto; break
    else: votos.append(voto)

def exibir_resultados_ui(session_key: str, icone: str, key_prefix: str) -> None:
    """
    Função Genérica para exibir os resultados na tela de forma limpa.
    Substitui a repetição de código que existia no final de cada plataforma.
    """
    data = st.session_state.get(session_key)
    if not data: return
    
    c1, c2 = st.columns(2)
    if Path(data.get("pdf", "")).exists(): 
        c1.download_button("⬇️ Baixar PDF", open(data["pdf"], "rb"), f"relatorio_{key_prefix}.pdf", use_container_width=True)
    if Path(data.get("zip", "")).exists(): 
        c2.download_button("⬇️ Baixar ZIP", open(data["zip"], "rb"), f"evidencias_{key_prefix}.zip", use_container_width=True)
    
    st.divider()
    for i, r in enumerate(data["results"]):
        st.markdown(f"### {icone} {r['perfil']}")
        st.markdown(f"**Link:** [{r['url']}]({r['url']})")
        if r.get('post_original') and r['post_original'] != r['url']: 
            st.caption(f"Origem: {r['post_original']}")
            
        st.caption(f"Risco: {r['risk_score']} | Termo: {r['termo']}")
        
        with st.expander("Conteúdo Analisado"): 
            st.text(r['bio'])
            
        if r.get('screenshot') and Path(BASE/r['screenshot']).exists(): 
            st.image(str(BASE/r['screenshot']), caption="Print capturado")
        else:
            st.warning("Print não pôde ser gerado.")
            
        c_v1, c_v2, _ = st.columns([1, 1, 5])
        with c_v1:
            if st.button("👍", key=f"{key_prefix}u{i}"): register_vote(i, "up", session_key); st.toast("Voto salvo!")
        with c_v2:
            if st.button("👎", key=f"{key_prefix}d{i}"): register_vote(i, "down", session_key); st.toast("Voto salvo!")
        st.markdown("---")

def render_homepage():
    logo_path = DATA_DIR / "assets" / "logo_anvisa.png"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=False, width=300)
        
    st.title("🔎 GGTAB – Plataforma de Monitoramento")
    st.markdown("---")
    st.markdown("### Bem-vindo à plataforma GGTAB")
    st.markdown("Selecione o projeto que deseja utilizar:")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown("#### 📱 Instagram")
        if st.button("🚀 Acessar Instagram", key="h_ig", type="primary", use_container_width=True):
            st.session_state["current_page"] = "instagram"; st.rerun()
    with c2:
        st.markdown("#### 🎵 TikTok")
        if st.button("🚀 Acessar TikTok", key="h_tt", type="primary", use_container_width=True):
            st.session_state["current_page"] = "tiktok"; st.rerun()
    with c3:
        st.markdown("#### 🧵 Threads")
        if st.button("🚀 Acessar Threads", key="h_th", type="primary", use_container_width=True):
            st.session_state["current_page"] = "threads"; st.rerun()
    with c4:
        st.markdown("#### 📘 Facebook")
        if st.button("🚀 Acessar Facebook", key="h_fb", type="primary", use_container_width=True):
            st.session_state["current_page"] = "facebook"; st.rerun()
    with c5:
        st.markdown("#### 📌 Pinterest")
        if st.button("🚀 Acessar Pinterest", key="h_pin", type="primary", use_container_width=True):
            st.session_state["current_page"] = "pinterest"; st.rerun()

    st.markdown("---"); st.markdown("### ℹ️ Sobre")
    st.info("GGTAB é uma plataforma de monitoramento desenvolvida para auxiliar na identificação e análise de perfis em redes sociais.")

# ==============================================================================
# 3. FUNÇÕES NÚCLEO E SCRAPING (BACKEND)
# ==============================================================================

def acelerar_navegador(page: Page) -> None:
    """Bloqueia mídias pesadas (vídeos e gifs) para o robô navegar mais rápido."""
    try:
        page.route("**/*.{mp4,webm,ogg,mp3,wav,gif}", lambda route: route.abort())
    except: pass

# --- INSTAGRAM FUNCTIONS ---

def ig_login(page: Page, user: str, pwd: str):
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
    except:
        try: page.keyboard.press("Enter")
        except: pass
    time.sleep(8)
    for name in ["Agora não", "Not now", "OK", "Ok", "ok"]:
        try:
            if page.get_by_role("button", name=name).count(): 
                page.get_by_role("button", name=name).first.click()
                time.sleep(1)
        except: pass

def ig_get_search_box(page: Page):
    try:
        locator = page.get_by_role("main").get_by_role("textbox", name=re.compile("Entrada da pesquisa|Search input|Pesquisar", re.IGNORECASE))
        locator.wait_for(state="visible", timeout=10000); return locator
    except: pass
    try:
        locator = page.locator('input[placeholder*="Pesquisar"], input[aria-label*="Pesquisa"]')
        locator.wait_for(state="visible", timeout=10000); return locator
    except: pass
    raise RuntimeError("Campo de busca do Instagram não localizado.")

def ig_processar_hashtag(page: Page, hashtag: str, maxn: int) -> List[Tuple[str, str]]:
    tag_clean = hashtag.replace("#", "").strip()
    url = f"https://www.instagram.com/explore/tags/{tag_clean}/"
    try: page.goto(url, timeout=20000); time.sleep(5)
    except: return []
    post_links = set(); tentativas = 0; buffer_size = maxn * 3
    while len(post_links) < buffer_size and tentativas < 15:
        try:
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.getAttribute('href'))")
            novos = [h for h in hrefs if h and "/p/" in h]
            post_links.update(novos)
            if len(post_links) >= buffer_size: break
            page.keyboard.press("PageDown"); time.sleep(1.5); tentativas += 1
        except: break
    return [(hashtag, link) for link in list(post_links)[:maxn]]

def ig_buscar(page: Page, termos: List[str], maxn: int) -> List[Tuple[str, str]]:
    search_box = None; acumulado = []
    for termo in termos:
        termo = termo.strip()
        if termo.startswith("#"):
            acumulado.extend(ig_processar_hashtag(page, termo, maxn))
        else:
            try:
                lupa = page.locator("svg[aria-label='Pesquisa'], svg[aria-label='Search']")
                if lupa.count() > 0:
                    lupa.first.click(force=True)
                    time.sleep(2)
            except: pass

            if not search_box:
                try: search_box = ig_get_search_box(page)
                except: 
                    page.goto("https://www.instagram.com/")
                    time.sleep(3)
                    search_box = ig_get_search_box(page)
            try:
                search_box.fill("")
                time.sleep(0.5)
                search_box.fill(termo)
                time.sleep(5) 
                
                hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
                conta_termo = 0
                for link in hrefs:
                    if conta_termo >= maxn: break
                    m = re.search(r"https://www\.instagram\.com/([a-zA-Z0-9_.-]{3,30})/$", link)
                    if m:
                        user = m.group(1)
                        if user not in {"explore", "reels", "p", "accounts", "login", "direct", "developer"}:
                            acumulado.append((termo, f"/{user}/"))
                            conta_termo += 1
            except Exception as e:
                print(f"Erro na busca do termo {termo}: {e}")

    seen = set(); out = []
    for t, p in acumulado:
        if p not in seen: seen.add(p); out.append((t, p))
    return out

def ig_visitar(page: Page, items_pairs: List[Tuple[str, str]]) -> List[Dict]:
    SCREEN_DIR.mkdir(parents=True, exist_ok=True); resultados = []
    for i, (termo, path) in enumerate(items_pairs):
        url = f"https://www.instagram.com{path}"
        try: page.goto(url, timeout=20000)
        except: continue
        time.sleep(3)
        
        is_post = "/p/" in path
        nome_perfil = "Desconhecido"; link_final = url; tipo_item = "post" if is_post else "perfil"
        texto_analise = ""

        if is_post:
            try:
                author_el = page.locator("header h2 a").first
                if author_el.count() > 0: nome_perfil = author_el.inner_text().strip()
                art_text = page.locator("article").first.inner_text(timeout=2000)
                texto_analise = f"[Legenda Post]: {art_text[:600]}"
            except: texto_analise = "Erro ao ler post"
        else:
            try:
                nome_perfil = path.strip("/")
                bio_js = page.evaluate("document.querySelector('header section') ? document.querySelector('header section').innerText : ''")
                texto_analise = f"[Bio Perfil]: {bio_js}"
            except: texto_analise = "Erro ao ler bio"

        unique_id = uuid.uuid4().hex[:8]
        safe = path.strip("/").replace("/", "_")[:30]
        filename = f"print_ig_{safe}_{unique_id}.png"
        img_path = SCREEN_DIR / filename
        try: page.screenshot(path=str(img_path), full_page=True)
        except: pass

        k = classificar_bio(texto_analise)
        resultados.append({
            "termo": termo, "perfil": nome_perfil, "url": link_final, "tipo": tipo_item,
            "bio": texto_analise, "status": k["status"], "match": k["match"], "risk_score": k.get("risk_score", 0),
            "risk_terms": k.get("risk_terms", []), "screenshot": f"data/screenshots/{filename}" if img_path.exists() else None, 
            "verification_timestamp": datetime.now().isoformat()
        })
    return resultados

# --- TIKTOK FUNCTIONS ---

def tt_wait_login(page: Page):
    page.goto("https://www.tiktok.com/login")
    st.toast("⚠️ Faça login manual no TikTok! Você tem 1 minuto.")
    try: 
        page.wait_for_selector("[data-e2e='profile-icon']", timeout=60000)
        st.success("Login efetuado com sucesso!")
        st.toast("Login efetuado com sucesso!", icon="✅")
    except: pass 

def tt_buscar_tag(page: Page, tag: str, maxn: int) -> List[Tuple[str, str]]:
    url = f"https://www.tiktok.com/tag/{tag.replace('#','').strip()}"
    try: 
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_selector("a[href*='/video/']", timeout=10000)
    except: return []
    links = set(); tr = 0
    while len(links) < maxn * 3 and tr < 15:
        try:
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            links.update([h.split("?")[0] for h in hrefs if "/video/" in h])
            if len(links) >= maxn * 3: break
            page.keyboard.press("PageDown"); time.sleep(1.5); tr += 1
        except: break
    return [(tag, l) for l in list(links)[:maxn]]

def tt_collect_profile_videos(page: Page, username: str, limit: int) -> List[Tuple[str, str]]:
    url = f"https://www.tiktok.com/@{username.replace('@', '')}"
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_selector("[data-e2e='user-post-item']", timeout=10000)
    except: return [(username, url)]
    links = set(); attempts = 0; clean_user = username.replace('@', '')
    while len(links) < limit and attempts < 10:
        try:
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            new_links = [h.split("?")[0] for h in hrefs if "/video/" in h and clean_user in h]
            links.update(new_links)
            if len(links) >= limit: break
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(2.5); attempts += 1
        except: break
    return [(username, l) for l in list(links)[:limit]]

def tt_buscar_keyword(page: Page, keyword: str, maxn: int) -> List[Tuple[str, str]]:
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.tiktok.com/search/video?q={encoded}"
    try: 
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_selector("[data-e2e='search_video-item']", timeout=10000)
    except: return []
    links = set(); tr = 0
    while len(links) < maxn * 3 and tr < 15:
        try:
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            novos = [h.split("?")[0] for h in hrefs if "/video/" in h and "tiktok.com" in h]
            links.update(novos)
            if len(links) >= maxn * 3: break
            page.keyboard.press("PageDown"); time.sleep(1.5); tr += 1
        except: break
    return [(keyword, l) for l in list(links)[:maxn]]

def tt_buscar(page: Page, termos: List[str], maxn: int) -> List[Tuple[str, str]]:
    acc = []
    for t in termos:
        t = t.strip()
        if t.startswith("#"): acc.extend(tt_buscar_tag(page, t, maxn))
        elif t.startswith("@"): acc.extend(tt_collect_profile_videos(page, t, maxn))
        else: acc.extend(tt_buscar_keyword(page, t, maxn))
    seen = set(); out = []
    for t, l in acc:
        if l not in seen: seen.add(l); out.append((t, l))
    return out

def tt_visitar(page: Page, items: List[Tuple[str, str]], detailed_mode: bool) -> List[Dict]:
    SCREEN_DIR.mkdir(parents=True, exist_ok=True); res = []
    for i, (termo, url) in enumerate(items):
        try: 
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            time.sleep(2)
            try: page.evaluate("document.querySelectorAll('video').forEach(v => v.pause())")
            except: pass
        except: pass
        
        is_vid = "/video/" in url; bio_legenda = "N/A"; pid = "Desconhecido"; profile_url = ""
        orig = url if is_vid else None
        
        try:
            if is_vid:
                desc_el = page.locator("[data-e2e='video-desc']").first
                if desc_el.count(): bio_legenda = desc_el.inner_text()
                auth_el = page.locator("[data-e2e='browse-username']").first
                if auth_el.count(): pid = auth_el.inner_text(); profile_url = f"https://www.tiktok.com/@{pid}"
            else: profile_url = url; pid = url.split("@")[-1].split("?")[0]
        except: pass

        if pid == "Desconhecido" and "@" in url:
            try: pid = url.split("@")[1].split("/")[0]; profile_url = f"https://www.tiktok.com/@{pid}"
            except: pass

        final_bio = bio_legenda; screenshot_target_url = url
        if detailed_mode and profile_url and "tiktok.com" in profile_url:
            try:
                page.goto(profile_url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(2)
                try: page.wait_for_selector("[data-e2e='user-bio']", timeout=3000)
                except: pass
                bio_perfil = ""
                bio_el = page.locator("[data-e2e='user-bio']").first
                if bio_el.count(): bio_perfil = bio_el.inner_text()
                final_bio = f"[Legenda]: {bio_legenda}\n[Bio Perfil]: {bio_perfil}"; screenshot_target_url = profile_url
            except: final_bio = f"{bio_legenda} (Erro ao carregar perfil)"

        unique_id = uuid.uuid4().hex[:8]
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', pid)[:30]
        filename = f"print_tt_{safe_name}_{unique_id}.png"
        img_path = SCREEN_DIR / filename
        
        try: page.screenshot(path=str(img_path), full_page=False)
        except: pass
        
        k = classificar_bio(final_bio)
        res.append({
            "termo": termo, "perfil": pid, "url": screenshot_target_url, "post_original": orig, "bio": final_bio, 
            "status": k["status"], "match": k["match"], "risk_score": k.get("risk_score", 0), "risk_terms": k.get("risk_terms", []), 
            "screenshot": f"data/screenshots/{filename}" if img_path.exists() else None,
            "verification_timestamp": datetime.now().isoformat()
        })
    return res

# --- THREADS FUNCTIONS ---

def th_wait_login(page: Page):
    page.goto("https://www.threads.net/login")
    st.toast("⚠️ Faça login manual no Threads (se necessário).")
    try: page.wait_for_selector("a[href*='/@']", timeout=60000)
    except: pass 

def th_buscar(page: Page, termos: List[str], maxn: int, mode: str) -> List[Tuple[str, str]]:
    acc = []; serp = "default"
    if mode == "Recentes": serp = "recent"
    elif mode == "Perfis": serp = "user"
    
    for t in termos:
        encoded = urllib.parse.quote(t.strip())
        try:
            page.goto(f"https://www.threads.net/search?q={encoded}&serp_type={serp}", timeout=20000)
            time.sleep(4)
            links = set(); attempts = 0
            while len(links) < maxn and attempts < 10:
                hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
                for h in hrefs:
                    if mode == "Perfis" and "/@" in h and "/post/" not in h: links.add(h)
                    elif mode != "Perfis" and "/post/" in h: links.add(h)
                if len(links) >= maxn: break
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(2); attempts += 1
            for l in list(links)[:maxn]: acc.append((t, l))
        except: pass
    seen = set(); out = []
    for t, l in acc:
        if l not in seen: seen.add(l); out.append((t, l))
    return out

def th_visitar(page: Page, items: List[Tuple[str, str]]) -> List[Dict]:
    SCREEN_DIR.mkdir(parents=True, exist_ok=True); res = []
    for i, (termo, url) in enumerate(items):
        try: page.goto(url, timeout=20000); time.sleep(3)
        except: pass
        
        perfil = "Desconhecido"; bio_text = "N/A"
        try:
            bio_text = page.locator("body").inner_text()[:800].replace("\n", " ")
            if "/@" in url:
                parts = url.split("/@")
                if len(parts) > 1: perfil = parts[1].split("/")[0]
        except: pass
        
        unique_id = uuid.uuid4().hex[:8]
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', perfil)[:30]
        filename = f"print_th_{safe_name}_{unique_id}.png"
        img_path = SCREEN_DIR / filename
        
        try: page.screenshot(path=str(img_path), full_page=True)
        except: pass
        
        k = classificar_bio(bio_text)
        res.append({
            "termo": termo, "perfil": perfil, "url": url, "bio": bio_text,
            "status": k["status"], "match": k["match"], "risk_score": k.get("risk_score", 0),
            "risk_terms": k.get("risk_terms", []), "screenshot": f"data/screenshots/{filename}" if img_path.exists() else None,
            "verification_timestamp": datetime.now().isoformat()
        })
    return res

# --- FACEBOOK E PINTEREST FUNCTIONS ---

def fb_buscar(page: Page, termos: List[str], maxn: int, mode: str) -> List[Tuple[str, str]]:
    acc = []
    t_url = "top"
    if mode == "Páginas": t_url = "pages"
    elif mode == "Grupos": t_url = "groups"
    
    for t in termos:
        encoded = urllib.parse.quote(t.strip())
        try:
            page.goto(f"https://www.facebook.com/search/{t_url}/?q={encoded}", timeout=20000)
            time.sleep(4)
            links = set(); attempts = 0
            while len(links) < maxn and attempts < 10:
                hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
                for h in hrefs:
                    if "facebook.com" in h and "/search/" not in h and "login" not in h:
                        links.add(h.split("?")[0]) 
                if len(links) >= maxn: break
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(2); attempts += 1
            for l in list(links)[:maxn]: acc.append((t, l))
        except: pass
    seen = set(); out = []
    for t, l in acc:
        if l not in seen: seen.add(l); out.append((t, l))
    return out

def pin_buscar(page: Page, termos: List[str], maxn: int, mode: str) -> List[Tuple[str, str]]:
    acc = []
    t_url = "pins"
    if mode == "Perfis": t_url = "users"
    elif mode == "Pastas": t_url = "boards"
    
    for t in termos:
        encoded = urllib.parse.quote(t.strip())
        try:
            page.goto(f"https://br.pinterest.com/search/{t_url}/?q={encoded}", timeout=20000)
            time.sleep(4)
            links = set(); attempts = 0
            while len(links) < maxn and attempts < 10:
                hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
                for h in hrefs:
                    if mode == "Pins" and "/pin/" in h: links.add(h)
                    elif mode != "Pins" and "pinterest.com" in h and "/search/" not in h: links.add(h)
                if len(links) >= maxn: break
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(2); attempts += 1
            for l in list(links)[:maxn]: acc.append((t, l))
        except: pass
    seen = set(); out = []
    for t, l in acc:
        if l not in seen: seen.add(l); out.append((t, l))
    return out

def general_visitar(page: Page, items: List[Tuple[str, str]], prefix: str) -> List[Dict]:
    SCREEN_DIR.mkdir(parents=True, exist_ok=True); res = []
    for termo, url in items:
        try: page.goto(url, timeout=20000); time.sleep(4)
        except: pass
        
        bio_text = "N/A"
        perfil = "Desconhecido"
        try: 
            bio_text = page.locator("body").inner_text()[:1000].replace("\n", " ")
            perfil = url.split("/")[-1] or url.split("/")[-2]
        except: pass
        
        unique_id = uuid.uuid4().hex[:8]
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', perfil)[:20]
        if not safe_name: safe_name = "item"
        filename = f"print_{prefix}_{safe_name}_{unique_id}.png"
        img_path = SCREEN_DIR / filename
        
        try: page.screenshot(path=str(img_path), full_page=True) 
        except: pass
        
        k = classificar_bio(bio_text)
        res.append({
            "termo": termo, "perfil": safe_name, "url": url, "bio": bio_text,
            "status": k["status"], "match": k["match"], "risk_score": k.get("risk_score", 0),
            "risk_terms": k.get("risk_terms", []), "screenshot": f"data/screenshots/{filename}" if img_path.exists() else None,
            "verification_timestamp": datetime.now().isoformat()
        })
    return res

# ==============================================================================
# 4. ROTEAMENTO E RENDERIZAÇÃO DAS PÁGINAS (FRONTEND STREAMLIT)
# ==============================================================================

if st.session_state["current_page"] == "home":
    render_homepage()

# ================= INSTAGRAM =================
elif st.session_state["current_page"] == "instagram":
    st.title("🔎 GGTAB – Busca Automática no Instagram")
    with st.sidebar:
        render_sidebar_header()
        ig_u = st.text_input("Usuário", value=os.getenv("IG_USERNAME", ""))
        ig_p = st.text_input("Senha", type="password", value=os.getenv("IG_PASSWORD", ""))
        st.markdown("### Termos")
        if st.button("✨ Sugerir"): st.session_state["ig_sug"] = suggest_terms(4)
        curr = st.session_state.get("ig_terms", ["vape brasil", "pod descartavel sp"])
        txt = st.text_area("Termos", value="\n".join(curr), height=120)
        st.session_state["ig_terms"] = [x.strip() for x in txt.splitlines() if x.strip()]
        max_p = st.number_input("Limite de perfis", 5, 200, 24)
        head = st.checkbox("Mostrar navegador", False)
        go = st.button("🚀 Iniciar Busca", type="primary", use_container_width=True)

    if go:
        if not ig_u or not ig_p: st.error("Login obrigatório.")
        else:
            bar = st.progress(0); log = st.empty()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=not head)
                    ctx = browser.new_context(viewport={"width": 1366, "height": 768})
                    page = ctx.new_page()
                    acelerar_navegador(page) # OTIMIZAÇÃO
                    
                    log.info("Fazendo login..."); ig_login(page, ig_u, ig_p); bar.progress(20)
                    log.info("Buscando..."); items = ig_buscar(page, st.session_state["ig_terms"], max_p)
                    blocked = set(get_blocked_profiles()); me = ig_u.strip().lower()
                    filt = [i for i in items if i[1].strip("/").lower() not in blocked and i[1].strip("/").lower() != me]
                    log.info(f"{len(filt)} itens encontrados. Visitando..."); bar.progress(50)
                    res = ig_visitar(page, filt)
                    ts = datetime.now().isoformat()
                    JSON_IG.write_text(json.dumps({"timestamp": ts, "results": res}, default=str), encoding="utf-8")
                    st.session_state["res_ig"] = {
                        "results": res, "pdf": build_pdf(res, str(OUTPUT_DIR)),
                        "zip": criar_volume_evidencias(str(OUTPUT_DIR), str(SCREEN_DIR), build_pdf(res, str(OUTPUT_DIR)))
                    }
                    bar.progress(100); log.success("Concluído!")
            except Exception as e: st.error(f"Erro: {e}")

    exibir_resultados_ui("res_ig", "👤", "iu")
    if st.session_state.get("votes_batch"):
        if st.button("💾 Salvar Votos (IG)", key="save_ig"):
            append_feedback(st.session_state["votes_batch"]); st.session_state["votes_batch"] = []; st.success("Feedback salvo!")

# ================= TIKTOK =================
elif st.session_state["current_page"] == "tiktok":
    st.title("🎵 GGTAB – Busca Automática no TikTok")
    with st.sidebar:
        render_sidebar_header()
        st.info("Login manual obrigatório na 1ª vez.")
        txt = st.text_area("Termos / Hashtags / @Perfis", value="\n".join(st.session_state.get("tt_terms", ["#vapebrasil"])), height=120)
        st.session_state["tt_terms"] = [t.strip() for t in txt.splitlines() if t.strip()]
        maxn = st.number_input("Limite de itens (por termo/perfil)", min_value=1, max_value=500, value=10)
        mode = st.radio("Modo de Visita", ["⚡ Rápida (Apenas Vídeo)", "🕵️ Detalhada (Entrar no Perfil)"])
        is_detailed = "Detalhada" in mode
        go = st.button("🚀 Iniciar Busca TikTok", type="primary", use_container_width=True)

    if go:
        bar = st.progress(0); log = st.empty()
        try:
            PROFILE_DIR = str(DATA_DIR / "tiktok_profile")
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=PROFILE_DIR,
                    headless=False,
                    viewport={"width": 1366, "height": 768},
                    args=["--disable-blink-features=AutomationControlled"]
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                acelerar_navegador(page) # OTIMIZAÇÃO
                
                log.info("Aguardando Login Manual..."); tt_wait_login(page); bar.progress(20)
                log.info("Buscando termos..."); links = tt_buscar(page, st.session_state["tt_terms"], maxn)
                log.info(f"{len(links)} itens encontrados. Visitando..."); bar.progress(50)
                res = tt_visitar(page, links, is_detailed) 
                ts = datetime.now().isoformat()
                JSON_TT.write_text(json.dumps({"timestamp": ts, "results": res}, default=str), encoding="utf-8")
                st.session_state["res_tt"] = {
                    "results": res, "pdf": build_pdf(res, str(OUTPUT_DIR)),
                    "zip": criar_volume_evidencias(str(OUTPUT_DIR), str(SCREEN_DIR), build_pdf(res, str(OUTPUT_DIR)))
                }
                bar.progress(100); log.success("Concluído!")
        except Exception as e: st.error(f"Erro: {e}")

    exibir_resultados_ui("res_tt", "🎵", "tu")
    if st.session_state.get("votes_batch"):
        if st.button("💾 Salvar Votos (TikTok)", key="save_tt"):
            append_feedback(st.session_state["votes_batch"]); st.session_state["votes_batch"] = []; st.success("Feedback salvo!")

# ================= THREADS =================
elif st.session_state["current_page"] == "threads":
    st.title("🧵 GGTAB – Busca Automática no Threads")
    with st.sidebar:
        render_sidebar_header()
        st.info("Login manual na 1ª vez.")
        txt = st.text_area("Termos", value="vape", height=120)
        st.session_state["th_terms"] = [t.strip() for t in txt.splitlines() if t.strip()]
        search_mode = st.radio("Filtro de Busca", ["Principais", "Recentes", "Perfis"])
        maxn = st.number_input("Limite de itens", 5, 100, 10)
        go = st.button("🚀 Iniciar Busca Threads", type="primary", use_container_width=True)

    if go:
        bar = st.progress(0); log = st.empty()
        try:
            PROFILE_DIR = str(DATA_DIR / "threads_profile")
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=PROFILE_DIR,
                    headless=False,
                    viewport={"width": 1366, "height": 768},
                    args=["--disable-blink-features=AutomationControlled"]
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                acelerar_navegador(page) # OTIMIZAÇÃO
                
                log.info("Aguardando Login..."); th_wait_login(page); bar.progress(20)
                log.info(f"Buscando ({search_mode})..."); links = th_buscar(page, st.session_state["th_terms"], maxn, search_mode)
                log.info(f"Visitando {len(links)} itens..."); bar.progress(50)
                res = th_visitar(page, links)
                ts = datetime.now().isoformat()
                JSON_TH.write_text(json.dumps({"timestamp": ts, "results": res}, default=str), encoding="utf-8")
                st.session_state["res_th"] = {
                    "results": res, "pdf": build_pdf(res, str(OUTPUT_DIR)),
                    "zip": criar_volume_evidencias(str(OUTPUT_DIR), str(SCREEN_DIR), build_pdf(res, str(OUTPUT_DIR)))
                }
                bar.progress(100); log.success("Concluído!")
        except Exception as e: st.error(f"Erro: {e}")

    exibir_resultados_ui("res_th", "🧵", "hu")
    if st.session_state.get("votes_batch"):
        if st.button("💾 Salvar Votos (Threads)", key="save_th"):
            append_feedback(st.session_state["votes_batch"]); st.session_state["votes_batch"] = []; st.success("Feedback salvo!")

# ================= FACEBOOK =================
elif st.session_state["current_page"] == "facebook":
    st.title("📘 GGTAB – Busca Automática no Facebook")
    with st.sidebar:
        render_sidebar_header()
        st.warning("Requer login manual na 1ª vez.")
        txt = st.text_area("Termos", value="vape", height=120)
        termos = [t.strip() for t in txt.splitlines() if t.strip()]
        mode = st.radio("Buscar em", ["Principais", "Páginas", "Grupos"])
        maxn = st.number_input("Limite de itens", 5, 100, 10)
        go = st.button("🚀 Iniciar Busca Facebook", type="primary", use_container_width=True)

    if go:
        bar = st.progress(0); log = st.empty()
        try:
            PROFILE_DIR = str(DATA_DIR / "facebook_profile")
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=PROFILE_DIR,
                    headless=False, 
                    viewport={"width": 1366, "height": 768},
                    args=["--disable-notifications", "--disable-blink-features=AutomationControlled"]
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                acelerar_navegador(page) # OTIMIZAÇÃO
                
                log.info("Aguardando Login (30s)...")
                page.goto("https://www.facebook.com/"); time.sleep(30); bar.progress(20)
                log.info("Buscando..."); links = fb_buscar(page, termos, maxn, mode); bar.progress(50)
                log.info("Visitando..."); res = general_visitar(page, links, "fb")
                ts = datetime.now().isoformat()
                JSON_FB.write_text(json.dumps({"timestamp": ts, "results": res}, default=str), encoding="utf-8")
                st.session_state["res_fb"] = {
                    "results": res, "pdf": build_pdf(res, str(OUTPUT_DIR)), 
                    "zip": criar_volume_evidencias(str(OUTPUT_DIR), str(SCREEN_DIR), build_pdf(res, str(OUTPUT_DIR)))
                }
                bar.progress(100); log.success("Concluído!")
        except Exception as e: st.error(f"Erro: {e}")
            
    exibir_resultados_ui("res_fb", "📘", "fbu")
    if st.session_state.get("votes_batch"):
        if st.button("💾 Salvar Votos (Facebook)", key="save_fb"):
            append_feedback(st.session_state["votes_batch"]); st.session_state["votes_batch"] = []; st.success("Feedback salvo!")

# ================= PINTEREST =================
elif st.session_state["current_page"] == "pinterest":
    st.title("📌 GGTAB – Busca Automática no Pinterest")
    with st.sidebar:
        render_sidebar_header()
        txt = st.text_area("Termos", value="vape brasil", height=120)
        termos = [t.strip() for t in txt.splitlines() if t.strip()]
        mode = st.radio("Buscar por", ["Pins", "Perfis", "Pastas"])
        maxn = st.number_input("Limite de itens", 5, 100, 10)
        go = st.button("🚀 Iniciar Busca Pinterest", type="primary", use_container_width=True)

    if go:
        bar = progress(0); log = st.empty()
        try:
            PROFILE_DIR = str(DATA_DIR / "pinterest_profile")
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=PROFILE_DIR,
                    headless=False,
                    viewport={"width": 1366, "height": 768},
                    args=["--disable-blink-features=AutomationControlled"]
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                acelerar_navegador(page) # OTIMIZAÇÃO
                
                log.info("Aguardando Login opcional (15s)...")
                page.goto("https://br.pinterest.com/"); time.sleep(15); bar.progress(20)
                log.info("Buscando..."); links = pin_buscar(page, termos, maxn, mode); bar.progress(50)
                log.info("Visitando..."); res = general_visitar(page, links, "pin")
                ts = datetime.now().isoformat()
                JSON_PIN.write_text(json.dumps({"timestamp": ts, "results": res}, default=str), encoding="utf-8")
                st.session_state["res_pin"] = {
                    "results": res, "pdf": build_pdf(res, str(OUTPUT_DIR)), 
                    "zip": criar_volume_evidencias(str(OUTPUT_DIR), str(SCREEN_DIR), build_pdf(res, str(OUTPUT_DIR)))
                }
                bar.progress(100); log.success("Concluído!")
        except Exception as e: st.error(f"Erro: {e}")
            
    exibir_resultados_ui("res_pin", "📌", "pinu")
    if st.session_state.get("votes_batch"):
        if st.button("💾 Salvar Votos (Pinterest)", key="save_pin"):
            append_feedback(st.session_state["votes_batch"]); st.session_state["votes_batch"] = []; st.success("Feedback salvo!")