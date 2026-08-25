# 🤖 GGTAB - Monitoramento Integrado com IA Local (Ollama)

Uma plataforma de inteligência e automação desenvolvida para varrer múltiplas redes sociais (Instagram, TikTok, Threads, Facebook e Pinterest), impulsionada por **Inteligência Artificial Executada Localmente**.

Diferente de scrapers tradicionais, este sistema utiliza o modelo **Llama 3.2 via Ollama** (sem dependência de APIs pagas ou envio de dados à nuvem) como um agente classificador. A IA analisa os textos extraídos em tempo real (bios e legendas), determina o grau de risco (ex: venda ilegal de vapes ou produtos restritos), sugere novos termos de busca e aprende com o feedback do usuário.

## 🚀 Principais Funcionalidades

* **Integração com IA Local (Ollama):** Classificação semântica de textos utilizando o Llama 3.2. A IA identifica menções a produtos fumígenos, cataloga os perfis suspeitos e sugere novas hashtags e termos de pesquisa baseados no comportamento de mercado.
* **Sistema de Votação & Machine Learning (Feedback Loop):** O usuário pode dar "👍" ou "👎" nas análises geradas. Esse feedback é armazenado localmente para que o modelo aprenda e filtre falsos-positivos nas próximas varreduras.
* **Scraping Multi-Plataforma Robusto:** Utiliza o *Playwright* com gerenciamento de contextos persistentes, garantindo que o robô consiga navegar logado e contornar bloqueios em plataformas complexas como Instagram e TikTok.
* **Geração Automática de Dossiês:** Todas as evidências coletadas (screenshots de tela cheia, avaliações da IA e links) são compiladas automaticamente em um Relatório PDF estruturado e exportadas junto com as imagens em um arquivo ZIP seguro.
* **Navegação Otimizada:** Função de intercepção de rede para bloquear o carregamento de vídeos e GIFs, acelerando exponencialmente a velocidade de raspagem do robô.

## 🛠️ Stack Tecnológico

* **Interface e Dashboard:** Python & [Streamlit](https://streamlit.io/)
* **Inteligência Artificial (LLM Local):** [Ollama](https://ollama.ai/) rodando o modelo `llama3.2`
* **Automação Web (Scraping):** [Playwright](https://playwright.dev/python/) (Síncrono)
* **Processamento de Relatórios:** `FPDF` (para criação dos dossiês) e `zipfile`

## ⚙️ Arquitetura do Projeto

O sistema é modularizado em 4 núcleos:
1. `app_final_v10_pro.py`: O maestro (Frontend Streamlit + Controle do Playwright).
2. `analyzer.py`: A ponte com o Ollama, enviando os textos extraídos para classificação de risco pelo Llama 3.2.
3. `recommender.py`: Motor que analisa o histórico de buscas e votos do usuário para sugerir novas ações.
4. `report_pdf.py`: O formatador legal que gera os pacotes de evidências.

## 📦 Como Instalar e Rodar

### 1. Pré-requisito da Inteligência Artificial
Para que o `analyzer.py` e o `recommender.py` funcionem, é estritamente necessário ter o Ollama rodando no background.
1. Baixe e instale o [Ollama](https://ollama.ai/).
2. Abra o terminal e baixe o modelo necessário:
   ollama run llama3.2
   Clone este repositório:
   git clone [https://github.com/seu-usuario/nome-do-repositorio.git](https://github.com/seu-usuario/nome-do-repositorio.git)
   cd nome-do-repositorio

   Crie e ative um ambiente virtual, depois instale as dependências:
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   pip install -r requirements.txt

   Instale os binários dos navegadores do Playwright:
   playwright install

   Configure as credenciais no arquivo .env (ex: IG_USERNAME, IG_PASSWORD).
   
    Iniciar a Plataforma
   Com o Ollama rodando silenciosamente no seu PC, levante o servidor do Streamlit:
   streamlit run automation/app_final_v10_pro.py
   
   
