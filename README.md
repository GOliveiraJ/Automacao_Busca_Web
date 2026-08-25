# Automacao_Busca_Web
# 📄 GGTAB - Monitoramento Integrado de Redes Sociais

Uma aplicação web desenvolvida para automatizar a varredura, captura e análise de publicações e perfis em múltiplas redes sociais (Instagram, TikTok, Threads, Facebook e Pinterest). 

O objetivo do projeto é facilitar a fiscalização e o monitoramento regulatório. O robô navega pelas plataformas buscando por palavras-chave específicas, extrai textos (bios e legendas), classifica o nível de risco do conteúdo e captura "prints" da tela para servir como evidência legal, consolidando tudo em relatórios automatizados.

## 🚀 Principais Funcionalidades

* **Scraping Multi-Plataforma:** Scripts dedicados para contornar bloqueios e extrair dados do Instagram, TikTok, Threads, Facebook e Pinterest.
* **Captura de Evidências:** Tira screenshots automáticos de cada perfil ou post suspeito e salva localmente.
* **Relatórios Automáticos:** Integração com geradores de PDF e arquivos ZIP, compilando todas as evidências visuais e textuais em um único pacote para download.
* **Otimização de Navegação:** Bloqueio inteligente de mídias pesadas (vídeos, áudios e GIFs) para acelerar o processamento do Playwright.

## 🛠️ Tecnologias e Pré-requisitos

* **Python 3.8+**
* **[Streamlit](https://streamlit.io/):** Responsável por toda a interface de usuário (Frontend).
* **[Playwright](https://playwright.dev/python/):** Motor de automação de navegadores (Backend/Scraping).
* **python-dotenv:** Para gerenciamento seguro de credenciais via arquivo `.env`.

*Nota: Este script depende de módulos auxiliares locais (`analyzer.py`, `report_pdf.py`, `recommender.py`) que processam o texto e geram os documentos finais.*

## 📦 Como Instalar e Rodar

1. Clone este repositório para sua máquina local.
2. Crie e ative um ambiente virtual (recomendado).
3. Instale as dependências listadas:
   ```bash
   pip install -r requirements.txt
   Instale os binários dos navegadores do Playwright (passo obrigatório):
   playwright install
   Crie um arquivo .env na raiz do projeto com suas credenciais (ex: IG_USERNAME, IG_PASSWORD).
  Execute o painel interativo:
  streamlit run automation/app_final_v10_pro.py
