# Banco de Projetos — Emendas Parlamentares do Exército

Aplicativo web estático para consulta e visualização do **Banco de Projetos de
Emendas Parlamentares do Exército Brasileiro**, gerado automaticamente a partir
das cartilhas em PDF do repositório
[`andresilvatorres85-bit/cartilhas`](https://github.com/andresilvatorres85-bit/cartilhas).

**Como publicar:** siga o passo a passo em [`DEPLOY.md`](DEPLOY.md).

## O que o app faz

- Lista os **718 projetos** (situação em jul/2026) extraídos página a página
  das 31 cartilhas, com título, cidade/UF, OM beneficiada, valor total, órgão
  gestor e Comando Militar de Área.
- **5 filtros combináveis**, na ordem: Cidade → Estado → Ação Orçamentária →
  Comando Militar de Área → Órgão Gestor. As opções de cada filtro se
  restringem dinamicamente conforme os demais.
- **Página de detalhe** com todos os campos extraídos (objetivo, unidade
  orçamentária, função/subfunção/programa, GND3/GND4/total).
- **Download do PDF da página específica do projeto** (não da cartilha
  inteira) — os PDFs de página única são gerados no build.
- Contador de projetos e valor agregado conforme os filtros ativos; filtros
  refletidos na URL (links compartilháveis); layout responsivo mobile-first.
- Estado 100% no navegador de cada usuário: múltiplas pessoas usam o site ao
  mesmo tempo sem interferência (site estático, sem backend).

## Estrutura

```
├── etl/
│   ├── build.py                 # pipeline: lista PDFs via API → extrai → classifica → divide
│   ├── requirements.txt
│   └── config/
│       ├── orgao_gestor.json    # tabela Ação → Órgão Gestor (editável)
│       └── c_mil_a.json         # tabela UF → C Mil A + regra de MG (editável)
├── site/
│   ├── index.html               # aplicativo (HTML+CSS+JS em arquivo único)
│   ├── data/projects.json       # gerado pelo ETL
│   ├── data/build_report.json   # gerado pelo ETL (avisos + ações não mapeadas)
│   └── pdfs/<id>.pdf            # gerados pelo ETL (1 página por projeto)
├── .github/workflows/build-deploy.yml  # build diário + deploy no Pages
└── DEPLOY.md
```

## Regras de classificação implementadas

- **C Mil A por UF**, com a exceção de **MG por município**: Uberlândia e
  Araguari → CMP; demais municípios mineiros → CML (`etl/config/c_mil_a.json`).
- **Órgão Gestor pela Ação Orçamentária** (`etl/config/orgao_gestor.json`),
  com a regra especial da Ação `2000`: Unidade Orçamentária `52221` (IMBEL) →
  **IMBEL**; caso contrário → **SEF**. A Ação `156M` está mapeada para o **DEC**.
- **Órgão gestor por título**: projetos de "cursos profissionalizantes"
  pertencem ao **COTER**, substituindo o órgão derivado da Ação (regra
  configurável em `orgaos_por_titulo`, que também aceita o modo "adicionar"
  para incluir um projeto em mais de um filtro sem trocar o principal).
- **Códigos de Ação não mapeados** nunca recebem classificação inferida: o
  projeto aparece com selo **"⚠ a confirmar"** e o código é listado no
  `build_report.json` para posterior confirmação documental.

## Desenvolvimento local

```bash
pip install -r etl/requirements.txt   # requer também poppler-utils (pdftotext)
python3 etl/build.py                  # ou --local-dir <pasta-com-pdfs>
cd site && python3 -m http.server 8000
```
