
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from datetime import datetime
from pathlib import Path
import zipfile, json

def build_pdf(resultados: list, out_dir: str) -> str:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pdf_path = out / f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    w, h = A4
    y = h - 2*cm
    
    # Função auxiliar para formatar data/hora
    def format_timestamp(ts_str):
        try:
            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            return dt.strftime('%d/%m/%Y %H:%M:%S')
        except:
            return ts_str
    
    # Função auxiliar para quebrar texto em múltiplas linhas
    def get_wrapped_lines(canvas, text, max_width, font_name="Helvetica", font_size=10):
        words = text.split(' ')
        lines = []
        current_line = []
        space_width = canvas.stringWidth(' ', font_name, font_size)
        
        for word in words:
            word_width = canvas.stringWidth(word, font_name, font_size)
            current_line_width = canvas.stringWidth(' '.join(current_line), font_name, font_size) if current_line else 0
            
            if current_line_width + space_width + word_width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines
    
    c.setTitle("Relatório GGTAB – Busca Instagram (v7)")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2*cm, y, "Relatório – Perfis analisados")
    y -= 1*cm
    c.setFont("Helvetica", 10)
    
    for item in resultados:
        # Verifica se precisa de nova página
        if y < 8*cm:
            c.showPage()
            y = h - 2*cm
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2*cm, y, "Relatório – Perfis analisados (cont.)")
            y -= 1*cm
            c.setFont("Helvetica", 10)
        
        # Informações básicas
        c.setFont("Helvetica-Bold", 12)
        c.drawString(2*cm, y, f"Perfil: @{item.get('perfil','-')}")
        y -= 0.6*cm
        
        c.setFont("Helvetica", 10)
        c.drawString(2*cm, y, f"Termo de busca: {item.get('termo','-')}")
        y -= 0.4*cm
        
        c.drawString(2*cm, y, f"URL: {item.get('url','-')}")
        y -= 0.4*cm
        
        # Data e hora da verificação
        verification_ts = item.get('verification_timestamp', '')
        if verification_ts:
            formatted_date = format_timestamp(verification_ts)
            c.setFont("Helvetica", 9)
            c.drawString(2*cm, y, f"Data e hora da verificação: {formatted_date}")
            y -= 0.4*cm
            c.setFont("Helvetica", 10)
        
        # Status
        status = item.get('status', 'N/A')
        status_color = HexColor('#d32f2f') if status == 'SUSPEITO' else HexColor('#388e3c')
        c.setFillColor(status_color)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2*cm, y, f"Status: {status}")
        c.setFillColor(HexColor('#000000'))  # Volta para preto
        y -= 0.4*cm
        
        # Pontuação de risco
        risk_score = item.get('risk_score', 0)
        c.setFont("Helvetica", 10)
        c.drawString(2*cm, y, f"Pontuação de risco: {risk_score}")
        y -= 0.4*cm
        
        # Palavra-chave encontrada
        match = item.get('match')
        if match:
            c.drawString(2*cm, y, f"Palavra-chave detectada: {match}")
            y -= 0.4*cm
        
        # Termos de risco
        risk_terms = item.get('risk_terms', [])
        if risk_terms:
            termos_text = ", ".join([f"{t.get('term', '')} (x{t.get('count', 0)})" for t in risk_terms])
            if len(termos_text) > 80:
                termos_text = termos_text[:77] + "..."
            c.drawString(2*cm, y, f"Termos de risco: {termos_text}")
            y -= 0.4*cm
        
        # Biografia
        bio = item.get('bio', '')
        if bio:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(2*cm, y, "Biografia:")
            y -= 0.4*cm
            c.setFont("Helvetica", 9)
            # Quebra a bio em múltiplas linhas se necessário
            max_bio_width = w - 4*cm
            bio_lines = get_wrapped_lines(c, bio, max_bio_width, "Helvetica", 9)
            for line in bio_lines[:5]:  # Limita a 5 linhas
                c.drawString(2*cm, y, line)
                y -= 0.35*cm
            if len(bio_lines) > 5:
                c.drawString(2*cm, y, "...")
                y -= 0.35*cm
            c.setFont("Helvetica", 10)
            y -= 0.2*cm
        
        # Screenshot
        img = item.get('screenshot')
        img_height = 0
        if img:
            # Resolve o caminho da imagem (pode ser relativo ou absoluto)
            img_path = Path(img)
            if not img_path.is_absolute():
                # Se for relativo (ex: "data/screenshots/..."), resolve a partir do diretório base
                # out_dir é "data/outputs", então parent é "data", e parent.parent é a raiz
                base_dir = Path(out_dir).parent.parent  # Raiz do projeto
                img_path = base_dir / img
            if img_path.exists():
                try:
                    img_height = 7*cm
                    c.drawImage(str(img_path), 2*cm, y-img_height, width=10*cm, height=img_height, preserveAspectRatio=True, anchor='sw')
                except Exception as e:
                    c.drawString(2*cm, y, f"[Falha ao carregar imagem: {str(e)[:50]}]")
                    img_height = 0.4*cm
            else:
                # Tenta caminho absoluto direto se não encontrou
                img_path_abs = Path(img).resolve()
                if img_path_abs.exists():
                    try:
                        img_height = 7*cm
                        c.drawImage(str(img_path_abs), 2*cm, y-img_height, width=10*cm, height=img_height, preserveAspectRatio=True, anchor='sw')
                    except Exception:
                        c.drawString(2*cm, y, "[Falha ao carregar imagem]")
                        img_height = 0.4*cm
                else:
                    c.drawString(2*cm, y, f"[Imagem não encontrada]")
                    img_height = 0.4*cm
        
        y -= img_height + 0.5*cm
        c.line(2*cm, y, w-2*cm, y)
        y -= 0.5*cm
    
    c.save()
    return str(pdf_path)

def criar_volume_evidencias(out_dir: str, screenshots_dir: str, pdf_path: str) -> str:
    out = Path(out_dir)
    shots = Path(screenshots_dir)
    pdf = Path(pdf_path)
    zip_path = out / f"evidencias_{Path(pdf_path).stem}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(pdf, arcname=pdf.name)
        if shots.exists():
            for img in shots.glob("*.png"):
                zf.write(img, arcname=f"screenshots/{img.name}")
    return str(zip_path)

def escrever_artifacts_json(frontend_dir: str, pdf_path: str, zip_path: str):
    # Salva arquivo para o HTML v6 ler dinamicamente
    artifacts = {
        "pdf": f"data/outputs/{Path(pdf_path).name}",
        "zip": f"data/outputs/{Path(zip_path).name}"
    }
    Path(frontend_dir).mkdir(parents=True, exist_ok=True)
    (Path(frontend_dir) / "data" / "outputs").mkdir(parents=True, exist_ok=True)
    (Path(frontend_dir) / "data" / "outputs" / "artifacts.json").write_text(
        json.dumps(artifacts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return artifacts
