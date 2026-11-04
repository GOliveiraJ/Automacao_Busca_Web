
# 🔎 GGTAB – Sistema de Busca Ativa em Redes Sociais (MVP 3)

Este repositório contém o código-fonte do **MVP 3 – Sistema de Busca Ativa Automatizada**, desenvolvido para a **Gerência-Geral de Registro e Fiscalização de Produtos Fumígenos (GGTAB)** da **ANVISA**.

O objetivo deste MVP é automatizar e aprimorar a identificação de perfis suspeitos de comercializar **produtos fumígenos de forma irregular** nas redes sociais, começando pelo **Instagram**.

A solução utiliza:
- **Automação via Playwright**
- **Streamlit para UI**
- **Análise textual automática**
- **Sistema de pontuação de risco**
- **IA local via Ollama (modelos LLaMA)**
- **Geração de relatórios em PDF e ZIP**
- **Aprendizado contínuo via feedback do usuário**

---

## 📌 Sumário

- [Visão Geral](#-visão-geral)
- [Funcionalidades](#-funcionalidades)
- [Arquitetura](#-arquitetura)
- [Instalação](#-instalação)
- [Configuração do Ambiente](#-configuração-do-ambiente)
- [Execução](#-execução)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [Fluxo de Funcionamento](#-fluxo-de-funcionamento)
- [Modelos de IA (Ollama)](#-modelos-de-ia-ollama)
- [Geração de Relatórios](#-geração-de-relatórios)
- [Feedback e Aprendizado](#-feedback-e-aprendizado)
- [Limitações](#-limitações)
- [Roadmap](#-roadmap)
- [Licença](#-licença)

---

## 🔎 Visão Geral

O MVP 3 automatiza o processo de **busca ativa de possíveis infrações sanitárias**, permitindo que servidores da GGTAB identifiquem rapidamente perfis suspeitos de comercializar produtos fumígenos proibidos ou irregulares.

Essa automação reduz:
- tempo gasto em buscas manuais;
- risco de perda de evidências;
- dificuldade em detectar variações linguísticas (ex.: “v4pe”, “p0d”).

E aumenta:
- padronização,
- eficiência,
- velocidade de fiscalização digital.

---

## 🚀 Funcionalidades

### **Busca Automatizada**
- Login automático no Instagram via Playwright
- Busca por múltiplos termos simultaneamente
- Coleta estruturada de perfis encontrados

### **Análise de Biografia**
- Extração robusta do texto da bio (inclusive após clicar em "ver mais")
- Coleta de links externos presentes na bio
- Filtragem de ruídos (números isolados, botões, spans irrelevantes)

### **Classificação de Risco**
- Sistema baseado em palavras-chave com diversos pesos
- Pontuação automática `risk_score`
- Identificação de padrão infracional
- Status final: `OK` ou `SUSPEITO`

### **IA – Geração de Termos Suspeitos**
- Integração com **Ollama** (modelo LLaMA local)
- Geração de listas de termos suspeitos (máx 3 palavras, 4 resultados)
- Determinação automática baseada em:
  - histórico de buscas  
  - termos mais votados positivamente  
  - feedback de execuções anteriores  

### **Captura de Evidências**
- Screenshot full-page de cada perfil encontrado
- Registro de termo que originou a busca
- Salvamento dos resultados em JSON

### **Geração de Relatórios**
- Relatório PDF profissional (via ReportLab)
- Arquivo ZIP com todas as evidências e relatório

### **Aprendizado Contínuo**
- Sistema RLHF simples (feedback humano)
- Perfis irrelevantes passam a ser ignorados automaticamente
- Termos relevantes são priorizados nas próximas sugestões de IA

---

## 🏗 Arquitetura

```

Streamlit UI  →  Playwright → Analyzer → IA (Ollama)
↓            ↓             ↓            ↓
Persistência JSON  ← Feedback/Votos ← PDF/ZIP Reports

````

Um diagrama completo está disponível no diretório `docs/` (pode ser importado como PNG).

---

## ⚙ Instalação

### **1. Clone o repositório**
```bash
git clone https://github.com/seu-usuario/ggtab-busca-ativa.git
cd ggtab-busca-ativa
````

### **2. Crie o ambiente virtual**

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

### **3. Instale as dependências**

```bash
pip install -r requirements.txt
```

### **4. Instale o Playwright**

```bash
playwright install chromium
```

---

## 🔧 Configuração do Ambiente

Crie um arquivo `.env` na raiz:

```
IG_USERNAME=seu_usuario
IG_PASSWORD=sua_senha
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
```

---

## ▶ Execução

```bash
streamlit run app_streamlit_v8.py
```

Acesse o endereço exibido no terminal (geralmente `http://localhost:8501`).

---

## 📂 Estrutura do Projeto

```
📁 automation/
 ├── app_streamlit_v8.py      # Interface principal
 ├── analyzer.py              # Classificador de risco
 ├── recommender.py           # IA + sistema de feedback
 ├── report_pdf.py            # Geração de PDF e ZIP
📁 data/
 ├── screenshots/             # Evidências capturadas
 ├── outputs/                 # PDFs e ZIPs gerados
 ├── knowledge/
 │    ├── feedback.json
 │    ├── terms_history.json
```

---

## 🔄 Fluxo de Funcionamento

1. Usuário insere credenciais e termos
2. IA gera termos adicionais (opcional)
3. Sistema faz login e busca perfis
4. Perfis são visitados e analisados
5. Classificação de risco é aplicada
6. Usuário vota se o resultado é relevante
7. IA aprende com os votos
8. Relatório e evidências são gerados

---

## 🧠 Modelos de IA (Ollama)

O sistema utiliza modelos **executados localmente**, garantindo privacidade e segurança.

### Instalação do Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Baixar o modelo recomendado:

```bash
ollama pull llama3.2:3b
```

---

## 📑 Geração de Relatórios

Cada execução gera:

### 📄 `report_YYYYMMDD_HHMM.pdf`

Inclui:

* termo pesquisado
* perfil identificado
* URL
* screenshot

### 📦 `evidencias_report_YYYYMMDD_HHMM.zip`

Inclui:

* relatório PDF
* todas as screenshots

---

## 👍 Feedback e Aprendizado

O usuário pode marcar cada perfil como:

* **Relevante (👍)**
* **Irrelevante (👎)**

Essas decisões alimentam:

* bloqueio automático de perfis irrelevantes
* priorização de termos eficazes
* sugestão inteligente de novos termos

---

## ⚠ Limitações

* Mudanças na interface do Instagram podem exigir ajustes
* Necessidade de credenciais válidas
* Execução restrita pelo ritmo e limitações da própria web
* Não deve ser utilizado para login em contas de risco (2FA pode interferir)

---

## 🗺 Roadmap

| Versão | Features planejadas                                   |
| ------ | ----------------------------------------------------- |
| MVP 4  | Suporte ao iFood (raspagem de cardápios + avaliações) |
| MVP 5  | Detecção visual (CV + OCR)                            |
| MVP 6  | Integração com dashboard operacional (Power BI)       |
| Final  | Execução agendada + múltiplas plataformas             |

---

## 📜 Licença

Este projeto está sob domínio de uso institucional da **ANVISA / GGTAB**.
Para reutilização ou distribuição, consulte os responsáveis legais.

---

## 🤝 Contato

Se tiver dúvidas ou precisar de suporte técnico:

**Desenvolvedor:** Gustavo Canedo Gusmão
**E-mail:** *(preencher conforme necessário)*

---

## ⭐ Gostou do projeto?

Considere deixar uma estrela no repositório para apoiar o desenvolvimento contínuo!

---

