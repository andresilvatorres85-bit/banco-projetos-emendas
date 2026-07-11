# DEPLOY.md — Como publicar o Banco de Projetos no GitHub Pages

Este guia publica o aplicativo **gratuitamente** na sua conta do GitHub. Ao final,
o site estará no ar em `https://SEU-USUARIO.github.io/banco-projetos-emendas/`
e será **reconstruído automaticamente todos os dias** a partir das cartilhas do
repositório `andresilvatorres85-bit/cartilhas`.

Tempo estimado: **5 a 10 minutos**. Pré-requisitos: uma conta no GitHub e o
`git` instalado (ou use a opção de upload pelo navegador, seção 1-B).

---

## 1. Criar o repositório e enviar o código

### 1-A. Pelo terminal (recomendado)

1. Crie um repositório novo em <https://github.com/new>:
   - **Nome:** `banco-projetos-emendas`
   - **Visibilidade:** Público (necessário para GitHub Pages gratuito)
   - **NÃO** marque "Add a README" (o projeto já tem um).

2. No terminal, dentro da pasta deste projeto (a que contém `etl/`, `site/`,
   `DEPLOY.md`), rode:

   ```bash
   git init
   git add .
   git commit -m "Banco de Projetos de Emendas Parlamentares do Exército"
   git branch -M main
   git remote add origin https://github.com/SEU-USUARIO/banco-projetos-emendas.git
   git push -u origin main
   ```

   Troque `SEU-USUARIO` pelo seu nome de usuário do GitHub. Se o git pedir
   senha, use um *Personal Access Token* (Settings → Developer settings →
   Personal access tokens) — o GitHub não aceita mais senha comum no push.

### 1-B. Pelo navegador (sem terminal)

1. Crie o repositório como acima.
2. Na página do repositório, clique em **"uploading an existing file"** e
   arraste **todo o conteúdo** da pasta do projeto (inclusive as pastas
   ocultas `.github/` — se o upload pelo navegador não aceitar a pasta
   `.github`, crie o arquivo manualmente: botão **Add file → Create new
   file**, digite o caminho `.github/workflows/build-deploy.yml` e cole o
   conteúdo do arquivo homônimo deste projeto).
3. Confirme o commit na branch `main`.

## 2. Habilitar o GitHub Pages (fonte: GitHub Actions)

1. No repositório, vá em **Settings → Pages**.
2. Em **Build and deployment → Source**, escolha **"GitHub Actions"**
   (não escolha "Deploy from a branch").
3. Pronto — nenhuma outra configuração é necessária nessa tela.

## 3. Conferir as permissões do Actions e rodar o primeiro build

1. Vá em **Settings → Actions → General**:
   - Em **Actions permissions**, deixe "Allow all actions and reusable
     workflows" (padrão).
   - Em **Workflow permissions**, "Read repository contents" é suficiente —
     o deploy do Pages usa as permissões declaradas no próprio workflow
     (`pages: write`, `id-token: write`), já configuradas em
     `.github/workflows/build-deploy.yml`.
2. Vá na aba **Actions**, clique no workflow **"Build e Deploy (GitHub
   Pages)"** e em **"Run workflow"** (botão à direita) para disparar o
   primeiro build manualmente.
3. Acompanhe a execução (leva alguns minutos: o build baixa ~270 MB de
   cartilhas, extrai os 718 projetos e gera os PDFs de página única).
4. Ao terminar, o endereço do site aparece no job **deploy**
   (`https://SEU-USUARIO.github.io/banco-projetos-emendas/`).

O passo "Publicar relatório de build no log" imprime o `build_report.json`,
que lista **códigos de Ação não mapeados** (hoje: nenhum) e
qualquer aviso de parsing. Consulte-o após cada build.

## 4. Atualizações automáticas

O workflow já roda sozinho **todos os dias às 06:00 (horário de Brasília)**.
Como ele lista os PDFs do repositório `cartilhas` dinamicamente pela API do
GitHub, cartilhas **adicionadas, removidas ou renomeadas** (por exemplo, a
futura cartilha de Mato Grosso) entram no site automaticamente, sem alterar
código.

Para forçar uma atualização imediata (ex.: logo após publicar uma cartilha
nova), use a aba **Actions → Run workflow**.

## 5. (Opcional) Disparo instantâneo a cada push no repositório de dados

Se quiser que o site se atualize **no momento** em que uma cartilha for
publicada, adicione no repositório **`cartilhas`** o arquivo
`.github/workflows/notificar-app.yml`:

```yaml
name: Notificar app
on:
  push:
    branches: [main]
jobs:
  disparar:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST \
            -H "Authorization: Bearer ${{ secrets.APP_DISPATCH_TOKEN }}" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/repos/SEU-USUARIO/banco-projetos-emendas/dispatches \
            -d '{"event_type":"cartilhas-atualizadas"}'
```

E crie o segredo `APP_DISPATCH_TOKEN` no repositório `cartilhas`
(Settings → Secrets and variables → Actions) contendo um *fine-grained
personal access token* com permissão **Contents: read-write** no repositório
`banco-projetos-emendas`. O workflow do app já escuta esse evento
(`repository_dispatch: cartilhas-atualizadas`).

## 6. Testar localmente antes de publicar

Requisitos: Python 3.10+, `pdftotext` (pacote `poppler-utils` no
Linux/`brew install poppler` no macOS) e `pip install -r etl/requirements.txt`.

```bash
# 1. Rodar o ETL (baixa as cartilhas e gera site/data + site/pdfs)
python3 etl/build.py

#    — ou, se você já tem os PDFs baixados em uma pasta:
python3 etl/build.py --local-dir /caminho/para/cartilhas

# 2. Servir o site localmente
cd site && python3 -m http.server 8000
# Abra http://localhost:8000 no navegador
```

## 7. Manutenção da tabela de Órgãos Gestores

A classificação Ação → Órgão Gestor fica em **`etl/config/orgao_gestor.json`**
(arquivo de configuração, não código). Quando o relatório de build apontar um
código não mapeado, confirme o órgão correto na documentação orçamentária
oficial e acrescente a linha ao JSON, por exemplo:

```json
"1ABC": "COTER"
```

Enquanto um código não estiver mapeado, seus projetos aparecem no site com o
selo **"⚠ a confirmar"** — eles nunca são ocultados nem recebem classificação
inventada.

No mesmo arquivo ficam também: a regra especial da Ação `2000` (SEF vs IMBEL
conforme a Unidade Orçamentária), em `regras_especiais`; e a seção
`orgaos_por_titulo`, que classifica projetos pelo título — com
`"substituir": true` o órgão indicado troca o derivado da Ação (hoje: títulos
com "PROFISSIONALIZANTE" pertencem ao COTER), e com `"substituir": false` o
órgão é apenas adicionado ao filtro, mantendo o principal.

## 8. Solução de problemas

| Sintoma | Causa provável / solução |
|---|---|
| Página 404 após o deploy | Confira se **Settings → Pages → Source = GitHub Actions** e se o job `deploy` terminou verde. |
| Build falha em "Rodar ETL" com erro 403/rate limit | O `GITHUB_TOKEN` já é passado pelo workflow; confira se o repositório de dados continua público. |
| Site no ar, mas sem projetos | Veja o log do passo "Publicar relatório de build" — se `totalProjetos` for 0, o formato das cartilhas pode ter mudado; abra uma issue com o log. |
| Cartilha nova não apareceu | O agendamento roda 1×/dia. Force com Actions → Run workflow, ou configure a seção 5. |
