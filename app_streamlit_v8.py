# automation/app_final_v35.py
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import asyncio
import os
import platform
import time
import json
import re
import urllib.parse
import uuid  # Importante para gerar nomes únicos de arquivo
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

import streamlit as st
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

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

# Garante que as pastas existam
SCREEN_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE / ".env")

st.set_page_config(layout="wide", page_title="GGTAB - Monitoramento Integrado", page_icon="🔎")

if "current_page" not in st.session_state:
    st.session_state["current_page"] = "home"

# ==============================================================================
# 2. DEFINIÇÃO DE TODAS AS FUNÇÕES
# ==============================================================================

def render_sidebar_header():
    """Logo e navegação da Sidebar."""
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
    """Registra feedback do usuário."""
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
        "platform": "tiktok" if "tt" in platform_key else "instagram"
    }
    votos = st.session_state.setdefault("votes_batch", [])
    for i, existente in enumerate(votos):
        if existente["term"] == voto["term"] and existente["profile"] == voto["profile"]:
            votos[i] = voto
            break
    else:
        votos.append(voto)

def render_homepage():
    st.title("🔎 GGTAB – Plataforma de Monitoramento")
    st.markdown("---")
    st.markdown("### Bem-vindo à plataforma GGTAB")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 📱 Busca no Instagram")
        st.write("Busca automática de perfis no Instagram.")
        if st.button("🚀 Acessar Busca Instagram", key="h_ig", type="primary", use_container_width=True):
            st.session_state["current_page"] = "instagram"; st.rerun()
    with col2:
        st.markdown("#### 🎵 Busca no TikTok")
        st.write("Busca automática de vídeos/perfis no TikTok.")
        if st.button("🚀 Acessar Busca TikTok", key="h_tt", type="primary", use_container_width=True):
            st.session_state["current_page"] = "tiktok"; st.rerun()
    st.markdown("---"); st.markdown("### ℹ️ Sobre")
    st.info("GGTAB é uma plataforma de monitoramento para redes sociais e delivery.")

# --- INSTAGRAM FUNCTIONS ---

def ig_login(page, user, pwd):
    page.goto("https://www.instagram.com/accounts/login/")
    time.sleep(3)
    try:
        if page.locator('input[name="username"]').count():
            page.fill('input[name="username"]', user); page.fill('input[name="password"]', pwd); page.click('button[type="submit"]')
        else:
            page.get_by_label("Número de celular, nome de usuário ou email").fill(user); page.get_by_label("Senha").fill(pwd); page.get_by_role("button", name="Entrar", exact=True).click()
    except: pass
    time.sleep(8)
    for name in ["Agora não", "Not now", "OK", "Ok", "ok"]:
        try:
            if page.get_by_role("button", name=name).count(): page.get_by_role("button", name=name).first.click(); time.sleep(1)
        except: pass

def ig_get_search_box(page):
    try:
        locator = page.get_by_role("main").get_by_role("textbox", name=re.compile("Entrada da pesquisa|Search input|Pesquisar", re.IGNORECASE))
        locator.wait_for(state="visible", timeout=10000); return locator
    except: pass
    try:
        locator = page.locator('input[placeholder*="Pesquisar"], input[aria-label*="Pesquisa"]')
        locator.wait_for(state="visible", timeout=10000); return locator
    except: pass
    raise RuntimeError("Campo de busca do Instagram não localizado.")

def ig_processar_hashtag(page, hashtag, maxn):
    tag_clean = hashtag.replace("#", "").strip()
    url = f"https://www.instagram.com/explore/tags/{tag_clean}/"
    try: page.goto(url, timeout=15000); time.sleep(5)
    except: return []
    post_links = set()
    try:
        page.keyboard.press("PageDown"); time.sleep(2)
        hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.getAttribute('href'))")
        for h in hrefs:
            if h and "/p/" in h: post_links.add(h)
            if len(post_links) >= maxn + 5: break
    except: pass
    return [(hashtag, link) for link in list(post_links)[:maxn]]

def ig_buscar(page, termos, maxn):
    search_box = None; acumulado = []
    for termo in termos:
        termo = termo.strip()
        if termo.startswith("#"):
            acumulado.extend(ig_processar_hashtag(page, termo, maxn))
        else:
            if not search_box:
                try: search_box = ig_get_search_box(page)
                except: 
                    page.goto("https://www.instagram.com/"); time.sleep(3)
                    search_box = ig_get_search_box(page)
            
            search_box.fill(""); time.sleep(0.5); search_box.fill(termo); time.sleep(1.5)
            page.keyboard.press("Enter"); page.keyboard.press("Enter")
            time.sleep(5) 
            
            links_perfil = set()
            attempts = 0
            while len(links_perfil) < maxn and attempts < 10:
                try:
                    hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
                    for link in hrefs:
                        m = re.search(r"https://www\.instagram\.com/([a-zA-Z0-9_.-]{3,30})/$", link)
                        if m:
                            user = m.group(1)
                            if user not in {"explore", "reels", "p", "accounts", "login", "direct", "developer"}:
                                links_perfil.add(f"/{user}/")
                    
                    if len(links_perfil) >= maxn: break
                    page.keyboard.press("PageDown"); time.sleep(1.5); attempts += 1
                except: break
            
            for lp in list(links_perfil)[:maxn]:
                acumulado.append((termo, lp))

    seen = set(); out = []
    for t, p in acumulado:
        if p not in seen: seen.add(p); out.append((t, p))
    return out

def ig_visitar(page, items_pairs):
    # Garante a criação da pasta
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)
    resultados = []
    
    for i, (termo, path) in enumerate(items_pairs):
        url = f"https://www.instagram.com{path}"
        try: page.goto(url, timeout=20000)
        except: continue
        time.sleep(4) 
        
        is_post = "/p/" in path
        nome_perfil = "Desconhecido"
        link_final = url
        tipo_item = "post" if is_post else "perfil"
        texto_analise = ""

        if is_post:
            try:
                author_el = page.locator("header h2 a").first
                if author_el.count(): nome_perfil = author_el.inner_text()
                art_text = page.locator("article").first.inner_text(timeout=2000)
                texto_analise = f"[Legenda Post]: {art_text[:600]}"
            except: texto_analise = "Erro ao ler post"
        else:
            try:
                nome_perfil = path.strip("/")
                bio_js = page.evaluate("document.querySelector('header section') ? document.querySelector('header section').innerText : ''")
                texto_analise = f"[Bio Perfil]: {bio_js}"
            except: texto_analise = "Erro ao ler bio"

        # [CORREÇÃO CRÍTICA] Nome único para o print a cada execução
        unique_id = uuid.uuid4().hex[:8]
        safe = path.strip("/").replace("/", "_")[:30]
        filename = f"ig_{safe}_{unique_id}.png"
        
        try: 
            page.screenshot(path=str(SCREEN_DIR / filename), full_page=False)
        except Exception as e:
            print(f"Erro print IG: {e}")
            filename = ""

        k = classificar_bio(texto_analise)
        resultados.append({
            "termo": termo, "perfil": nome_perfil, "url": link_final, "tipo": tipo_item,
            "bio": texto_analise, "status": k["status"], "match": k["match"], "risk_score": k.get("risk_score", 0),
            "risk_terms": k.get("risk_terms", []), "screenshot": f"data/screenshots/{filename}" if filename else None, 
            "verification_timestamp": datetime.now().isoformat()
        })
    return resultados

# --- TIKTOK FUNCTIONS ---

def tt_wait_login(page):
    page.goto("https://www.tiktok.com/login")
    st.toast("⚠️ Faça login manual no TikTok! Você tem 1 minuto.")
    try: 
        page.wait_for_selector("[data-e2e='profile-icon']", timeout=60000)
        st.success("Login efetuado com sucesso!")
        st.toast("Login efetuado com sucesso!", icon="✅")
    except: pass

def tt_buscar_tag(page, tag, maxn):
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

def tt_collect_profile_videos(page, username, limit):
    url = f"https://www.tiktok.com/@{username.replace('@', '')}"
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_selector("[data-e2e='user-post-item']", timeout=10000)
    except: return [(username, url)]

    links = set(); attempts = 0
    clean_user = username.replace('@', '')
    
    while len(links) < limit and attempts < 10:
        try:
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            new_links = [h.split("?")[0] for h in hrefs if "/video/" in h and clean_user in h]
            links.update(new_links)
            if len(links) >= limit: break
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(2.5); attempts += 1
        except: break
    
    return [(username, l) for l in list(links)[:limit]]

def tt_buscar_keyword(page, keyword, maxn):
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

def tt_buscar(page, termos, maxn):
    acc = []
    for t in termos:
        t = t.strip()
        if t.startswith("#"):
            acc.extend(tt_buscar_tag(page, t, maxn))
        elif t.startswith("@"):
            acc.extend(tt_collect_profile_videos(page, t, maxn))
        else:
            acc.extend(tt_buscar_keyword(page, t, maxn))
    seen = set(); out = []
    for t, l in acc:
        if l not in seen: seen.add(l); out.append((t, l))
    return out

def tt_visitar(page, items, detailed_mode):
    # Garante a criação da pasta
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)
    res = []
    
    page.route("**/*.mp4", lambda route: route.abort())
    page.route("**/*.webm", lambda route: route.abort())
    page.route("**/*.mp3", lambda route: route.abort())
    
    for i, (termo, url) in enumerate(items):
        try: 
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            try: page.evaluate("document.querySelectorAll('video').forEach(v => v.pause())")
            except: pass
            try: 
                if "/video/" in url: page.wait_for_selector("[data-e2e='browse-username']", timeout=4000)
                else: page.wait_for_selector("[data-e2e='user-bio']", timeout=4000)
            except: pass
        except: pass
        
        is_vid = "/video/" in url
        bio_legenda = "N/A"; pid = "Desconhecido"; profile_url = ""
        orig = url if is_vid else None
        
        try:
            if is_vid:
                desc_el = page.locator("[data-e2e='video-desc']").first
                if desc_el.count(): bio_legenda = desc_el.inner_text()
                auth_el = page.locator("[data-e2e='browse-username']").first
                if auth_el.count(): pid = auth_el.inner_text(); profile_url = f"https://www.tiktok.com/@{pid}"
            else:
                profile_url = url; pid = url.split("@")[-1].split("?")[0]
        except: pass

        if pid == "Desconhecido" and "@" in url:
            try: pid = url.split("@")[1].split("/")[0]; profile_url = f"https://www.tiktok.com/@{pid}"
            except: pass

        final_bio = bio_legenda; screenshot_target_url = url

        if detailed_mode and profile_url and "tiktok.com" in profile_url:
            try:
                page.goto(profile_url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(3) 
                try: page.wait_for_selector("[data-e2e='user-bio']", timeout=3000)
                except: pass
                bio_perfil = ""
                bio_el = page.locator("[data-e2e='user-bio']").first
                if bio_el.count(): bio_perfil = bio_el.inner_text()
                final_bio = f"[Legenda]: {bio_legenda}\n[Bio Perfil]: {bio_perfil}"
                screenshot_target_url = profile_url
            except: final_bio = f"{bio_legenda} (Erro ao carregar perfil)"

        # [CORREÇÃO CRÍTICA] Nome único para evitar conflito de arquivo/cache
        unique_id = uuid.uuid4().hex[:8]
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', pid)[:30]
        filename = f"tt_{safe_name}_{unique_id}.png"
        
        try: 
            page.screenshot(path=str(SCREEN_DIR / filename), full_page=False)
        except Exception as e: 
            print(f"Erro print TT: {e}")
            filename = ""
        
        k = classificar_bio(final_bio)
        res.append({
            "termo": termo, "perfil": pid, "url": screenshot_target_url,
            "post_original": orig, "bio": final_bio, 
            "status": k["status"], "match": k["match"], "risk_score": k.get("risk_score", 0),
            "risk_terms": k.get("risk_terms", []), "screenshot": f"data/screenshots/{filename}" if filename else None,
            "verification_timestamp": datetime.now().isoformat()
        })
    
    try: page.unroute("**/*.mp4"); page.unroute("**/*.webm"); page.unroute("**/*.mp3")
    except: pass
    
    return res

# ==============================================================================
# 3. EXECUÇÃO PRINCIPAL
# ==============================================================================

if st.session_state["current_page"] == "home":
    render_homepage()

elif st.session_state["current_page"] == "instagram":
    st.title("🔎 GGTAB – Busca Automática no Instagram")
    with st.sidebar:
        render_sidebar_header()
        ig_u = st.text_input("Usuário", value=os.getenv("IG_USERNAME", ""))
        ig_p = st.text_input("Senha", type="password", value=os.getenv("IG_PASSWORD", ""))
        st.header("Termos")
        if st.button("✨ Sugerir"): st.session_state["ig_sug"] = suggest_terms(4)
        if "ig_sug" in st.session_state:
            for s in st.session_state["ig_sug"]:
                if st.button(s, key=f"s_{s}"): st.session_state.setdefault("ig_terms", []).append(s)
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
                    ctx = browser.new_context(viewport={"width":1366,"height":768})
                    page = ctx.new_page()
                    log.info("Login..."); ig_login(page, ig_u, ig_p); bar.progress(20)
                    log.info("Buscando..."); items = ig_buscar(page, st.session_state["ig_terms"], max_p)
                    blocked = set(get_blocked_profiles()); me = ig_u.strip().lower()
                    filt = [i for i in items if i[1].strip("/").lower() not in blocked and i[1].strip("/").lower() != me]
                    log.info(f"Visitando {len(filt)} itens..."); bar.progress(50)
                    res = ig_visitar(page, filt)
                    ts = datetime.now().isoformat()
                    JSON_IG.write_text(json.dumps({"timestamp": ts, "results": res}, default=str), encoding="utf-8")
                    st.session_state["res_ig"] = {
                        "results": res, "pdf": build_pdf(res, str(OUTPUT_DIR)),
                        "zip": criar_volume_evidencias(str(OUTPUT_DIR), str(SCREEN_DIR), build_pdf(res, str(OUTPUT_DIR)))
                    }
                    bar.progress(100); log.success("Concluído!")
            except Exception as e: st.error(f"Erro: {e}")

    data = st.session_state.get("res_ig")
    if data:
        c1, c2 = st.columns(2)
        if Path(data["pdf"]).exists(): 
            with open(data["pdf"], "rb") as f: c1.download_button("⬇️ PDF", f, "rel_ig.pdf", use_container_width=True)
        if Path(data["zip"]).exists(): 
            with open(data["zip"], "rb") as f: c2.download_button("⬇️ ZIP", f, "evid_ig.zip", use_container_width=True)
        st.divider()
        for i, r in enumerate(data["results"]):
            st.markdown(f"### 👤 {r['perfil']}")
            if r.get('tipo') == 'post':
                st.markdown(f"🔗 **Link da Publicação:** [{r['url']}]({r['url']})")
                label_print = "Print da Publicação"
            else:
                st.markdown(f"🔗 **Link do Perfil:** [{r['url']}]({r['url']})")
                label_print = "Print do Perfil"
            
            st.caption(f"Risco: {r['risk_score']} | Termo: {r['termo']}")
            st.text(r['bio'])
            
            img_path = BASE / r['screenshot'] if r['screenshot'] else None
            if img_path and img_path.exists(): st.image(str(img_path), caption=label_print, use_container_width=True)
            else: st.warning("Print não disponível")
            
            c_v1, c_v2, _ = st.columns([1, 1, 5])
            with c_v1:
                if st.button("👍", key=f"iu{i}"): register_vote(i, "up", "res_ig"); st.toast("Voto salvo!")
            with c_v2:
                if st.button("👎", key=f"id{i}"): register_vote(i, "down", "res_ig"); st.toast("Voto salvo!")
            st.markdown("---")
            
    if st.session_state.get("votes_batch"):
        if st.button("💾 Salvar Votos (IG)", key="save_ig"):
            append_feedback(st.session_state["votes_batch"])
            st.session_state["votes_batch"] = []
            st.success("Feedback salvo!")

elif st.session_state["current_page"] == "tiktok":
    st.title("🎵 GGTAB – Busca Automática no TikTok")
    with st.sidebar:
        render_sidebar_header()
        st.info("Login manual obrigatório.")
        txt = st.text_area("Termos / Hashtags / @Perfis", value="\n".join(st.session_state.get("tt_terms", ["#vapebrasil"])), height=120)
        st.session_state["tt_terms"] = [t.strip() for t in txt.splitlines() if t.strip()]
        maxn = st.number_input("Limite de itens (por termo/perfil)", min_value=1, max_value=500, value=10)
        mode = st.radio("Modo de Visita", ["⚡ Rápida (Apenas Vídeo)", "🕵️ Detalhada (Entrar no Perfil)"])
        is_detailed = "Detalhada" in mode
        go = st.button("🚀 Iniciar Busca TikTok", type="primary", use_container_width=True)

    if go:
        bar = st.progress(0); log = st.empty()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False, args=["--start-maximized", "--disable-blink-features=AutomationControlled"])
                ctx = browser.new_context(viewport={"width":1366,"height":768})
                page = ctx.new_page()
                log.info("Login Manual (1 min)..."); tt_wait_login(page); bar.progress(20)
                log.info("Buscando termos..."); links = tt_buscar(page, st.session_state["tt_terms"], maxn)
                if not links:
                    st.error("Nenhum link coletado! Verifique captcha.")
                else:
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

    data = st.session_state.get("res_tt")
    if data:
        c1, c2 = st.columns(2)
        if Path(data["pdf"]).exists(): 
            with open(data["pdf"], "rb") as f: c1.download_button("⬇️ PDF", f, "rel_tt.pdf", use_container_width=True)
        if Path(data["zip"]).exists(): 
            with open(data["zip"], "rb") as f: c2.download_button("⬇️ ZIP", f, "evid_tt.zip", use_container_width=True)
        st.divider()
        for i, r in enumerate(data["results"]):
            st.markdown(f"### 👤 {r['perfil']}")
            st.markdown(f"**Link Visualizado:** [{r['url']}]({r['url']})")
            if r.get('post_original') and r['post_original'] != r['url']:
                st.caption(f"Origem: {r['post_original']}")
            st.caption(f"Termo: {r['termo']} | Risco: {r['risk_score']}")
            with st.expander("Ver Conteúdo"): st.text(r['bio'])
            
            img_path = BASE / r["screenshot"] if r["screenshot"] else None
            if img_path and img_path.exists(): st.image(str(img_path), caption="Print capturado", use_container_width=True)
            else: st.warning(f"Print não encontrado.")
            
            c_v1, c_v2, _ = st.columns([1, 1, 5])
            with c_v1:
                if st.button("👍 Útil", key=f"tu{i}"): register_vote(i, "up", "res_tt"); st.toast(f"Voto salvo!")
            with c_v2:
                if st.button("👎 Inútil", key=f"td{i}"): register_vote(i, "down", "res_tt"); st.toast(f"Voto salvo!")
            st.markdown("---")

    if st.session_state.get("votes_batch"):
        if st.button("💾 Salvar Votos (TikTok)", key="save_tt"):
            append_feedback(st.session_state["votes_batch"])
            st.session_state["votes_batch"] = []
            st.success("Feedback salvo!")