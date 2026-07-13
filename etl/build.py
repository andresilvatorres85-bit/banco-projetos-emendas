#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETL do Banco de Projetos de Emendas Parlamentares do Exército.

Fluxo:
  1. Lista dinamicamente os PDFs do repositório de dados (GitHub API `contents`)
     ou usa uma pasta local (--local-dir) já contendo os PDFs.
  2. Extrai o texto de cada página com `pdftotext -layout` (1 página = 1 projeto).
  3. Aplica as regras de parsing e classificação (C Mil A, Órgão Gestor).
  4. Gera site/data/projects.json, divide cada cartilha em PDFs de página única
     (site/pdfs/<id>.pdf) e escreve um relatório de build (build_report.json).

Uso:
  python3 etl/build.py                          # baixa os PDFs via GitHub API
  python3 etl/build.py --local-dir /caminho     # usa PDFs já baixados
  python3 etl/build.py --repo dono/repositorio  # outro repositório de dados

Requisitos: pdftotext (poppler-utils), pypdf.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from pypdf import PdfReader, PdfWriter

BASE_DIR = Path(__file__).resolve().parent
SITE_DIR = BASE_DIR.parent / "site"
CONFIG_DIR = BASE_DIR / "config"

DEFAULT_REPO = "andresilvatorres85-bit/cartilhas"

# ---------------------------------------------------------------------------
# Configuração (tabelas de referência editáveis, nunca hardcoded no código)
# ---------------------------------------------------------------------------

def load_config():
    with open(CONFIG_DIR / "orgao_gestor.json", encoding="utf-8") as f:
        orgao_cfg = json.load(f)
    with open(CONFIG_DIR / "c_mil_a.json", encoding="utf-8") as f:
        cmila_cfg = json.load(f)
    return orgao_cfg, cmila_cfg


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def slugify(s: str) -> str:
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "x"


# ---------------------------------------------------------------------------
# Descoberta e download dos PDFs
# ---------------------------------------------------------------------------

def list_repo_pdfs(repo: str):
    """Lista os PDFs do repositório de dados via GitHub API (sem hardcodar nomes)."""
    url = f"https://api.github.com/repos/{repo}/contents"
    req = urllib.request.Request(url, headers=_gh_headers())
    with urllib.request.urlopen(req) as resp:
        entries = json.load(resp)
    pdfs = [e for e in entries
            if e.get("type") == "file" and e["name"].lower().endswith(".pdf")]
    pdfs.sort(key=lambda e: e["name"])
    return pdfs


def _encode_url(url: str) -> str:
    """Codifica espaços/acentos no caminho da URL (os nomes das cartilhas
    contêm espaços, parênteses e acentos, que a API devolve sem codificar)."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, quote(p.path),
                       quote(p.query, safe="=&"), p.fragment))


def _gh_headers(com_token: bool = True):
    """Cabeçalhos para a API. O token só deve ir para api.github.com —
    enviá-lo ao raw.githubusercontent.com de outro repositório causa 404."""
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "banco-projetos-emendas-etl"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and com_token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def download_pdfs(repo: str, dest: Path):
    """Baixa os PDFs listados pela API, com cache por SHA do blob."""
    dest.mkdir(parents=True, exist_ok=True)
    entries = list_repo_pdfs(repo)
    files = []
    for e in entries:
        # Nome de cache baseado no SHA: nomes de arquivo mudam a cada
        # atualização da cartilha, o SHA identifica o conteúdo.
        local = dest / f"{e['sha']}.pdf"
        if not local.exists():
            print(f"  baixando: {e['name']}")
            req = urllib.request.Request(_encode_url(e["download_url"]),
                                         headers=_gh_headers(com_token=False))
            with urllib.request.urlopen(req) as resp, open(local, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
        files.append({"path": local, "name": e["name"], "sha": e["sha"]})
    return files


def local_pdfs(local_dir: Path):
    files = []
    for p in sorted(local_dir.glob("*.pdf")):
        files.append({"path": p, "name": p.name, "sha": None})
    return files


# ---------------------------------------------------------------------------
# Extração de texto e parsing de cada página
# ---------------------------------------------------------------------------

# Artefato da camada de texto sobre imagens: "Imagens Ilustrativas." aparece
# normal ou invertido ("snegamI .savitartsulI") — nunca é dado de projeto.
_ARTIFACT_RE = re.compile(
    r"imagens?\s+ilustrativas?|savitartsuli|snegami", re.IGNORECASE)

_MUNICIPIO_RE = re.compile(r"MUNIC[ÍI]PIO:\s*(.+?)\s*[-–]\s*([A-Z]{2})\s*$")
_UO_RE = re.compile(
    r"^\s*(\d{5})\s*[-–]\s*(.+?)\s{2,}([0-9A-Z]{3,4})\s{2,}(\d{2})\s*$")
_FUNCAO_RE = re.compile(r"^\s*(\d{1,2})\s{2,}(\d{2,4})\s{2,}([0-9A-Z]{3,4})\s*$")
_MONEY_RE = re.compile(r"R\$\s*([\d.\s]+,\d{2})")
_PAGENUM_RE = re.compile(r"^\s*\d{1,4}\s*$")


def parse_money(token: str):
    m = _MONEY_RE.search(token)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(" ", "").replace(",", ".")
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def extract_pages_text(pdf_path: Path):
    """Extrai o texto por página; quebras de página viram form-feed (\\f)."""
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, check=True)
    text = out.stdout.decode("utf-8", errors="replace")
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def clean_lines(page_text: str):
    lines = []
    for raw in page_text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            lines.append("")
            continue
        if _ARTIFACT_RE.search(line):
            continue
        lines.append(line)
    return lines


def parse_page(page_text: str, warnings: list, ctx: str):
    """Converte o texto de uma página em um dicionário de campos brutos."""
    lines = clean_lines(page_text)
    nonempty = [(i, l.strip()) for i, l in enumerate(lines) if l.strip()]
    if not nonempty:
        return None

    fields = {}

    # --- Município / UF -----------------------------------------------------
    municipio_idx = None
    for i, l in nonempty:
        m = _MUNICIPIO_RE.search(l)
        if m:
            fields["cidade"] = re.sub(r"\s+", " ", m.group(1)).strip().upper()
            fields["uf"] = m.group(2)
            municipio_idx = i
            break
    if municipio_idx is None:
        warnings.append(f"{ctx}: linha MUNICÍPIO não encontrada — página ignorada")
        return None

    # --- Título e Objetivo (antes do MUNICÍPIO) -----------------------------
    header_lines = [l for i, l in nonempty if i < municipio_idx]
    titulo_parts, objetivo_parts, in_obj = [], [], False
    for l in header_lines:
        if not in_obj and re.match(r"(?i)^objetivo\s*:", l):
            in_obj = True
            objetivo_parts.append(re.sub(r"(?i)^objetivo\s*:\s*", "", l))
        elif in_obj:
            objetivo_parts.append(l)
        else:
            titulo_parts.append(l)
    fields["titulo"] = re.sub(r"\s+", " ", " ".join(titulo_parts)).strip()
    fields["objetivo"] = re.sub(r"\s+", " ", " ".join(objetivo_parts)).strip()
    if not fields["titulo"]:
        warnings.append(f"{ctx}: título vazio")
    if not fields["objetivo"]:
        warnings.append(f"{ctx}: objetivo vazio")

    # --- OM Beneficiada ------------------------------------------------------
    om_lines = []
    after = [(i, l) for i, l in nonempty if i > municipio_idx]
    state = None
    for i, l in after:
        u = strip_accents(l).upper()
        if "OM BENEFICIADA" in u:
            state = "om"
            continue
        if "UNIDADE ORCAMENTARIA" in u:
            break
        if state == "om":
            om_lines.append(l)
    fields["omBeneficiada"] = re.sub(r"\s+", " ", " ".join(om_lines)).strip()
    if not fields["omBeneficiada"]:
        warnings.append(f"{ctx}: OM beneficiada não encontrada")

    # --- Unidade Orçamentária / Ação / Modalidade ---------------------------
    fields["unidadeOrcamentaria"] = None
    fields["acaoOrcamentaria"] = None
    fields["modalidadeAplicacao"] = None
    for i, l in after:
        m = _UO_RE.match(l)
        if m:
            fields["unidadeOrcamentaria"] = {
                "codigo": m.group(1),
                "nome": re.sub(r"\s+", " ", m.group(2)).strip(),
            }
            fields["acaoOrcamentaria"] = m.group(3)
            fields["modalidadeAplicacao"] = m.group(4)
            break
    if fields["acaoOrcamentaria"] is None:
        warnings.append(f"{ctx}: linha de Unidade Orçamentária/Ação não reconhecida")

    # --- Função / Subfunção / Programa ---------------------------------------
    fields["funcao"] = fields["subfuncao"] = fields["programa"] = None
    seen_funcao_header = False
    for i, l in after:
        u = strip_accents(l).upper()
        if "FUNCAO" in u and "SUBFUNCAO" in u:
            seen_funcao_header = True
            continue
        if seen_funcao_header:
            m = _FUNCAO_RE.match(l)
            if m:
                fields["funcao"], fields["subfuncao"], fields["programa"] = m.groups()
                break
            if "GND" in u:
                break

    # --- GND3 / GND4 / Total --------------------------------------------------
    fields["gnd3"] = fields["gnd4"] = fields["total"] = None
    seen_gnd_header = False
    for i, l in after:
        u = l.upper()
        if "GND3" in u and "TOTAL" in u:
            seen_gnd_header = True
            continue
        if seen_gnd_header and l.strip() and not _PAGENUM_RE.match(l):
            cols = re.split(r"\s{2,}", l.strip())
            if len(cols) >= 3 and all(c == "-" or "R$" in c for c in cols[:3]):
                fields["gnd3"] = parse_money(cols[0])
                fields["gnd4"] = parse_money(cols[1])
                fields["total"] = parse_money(cols[2])
                break
    if fields["total"] is None:
        warnings.append(f"{ctx}: valor TOTAL não encontrado")

    return fields


# ---------------------------------------------------------------------------
# Classificação derivada
# ---------------------------------------------------------------------------

def classify_c_mil_a(uf: str, cidade: str, cmila_cfg: dict):
    if uf == "MG":
        cidade_norm = strip_accents(cidade).upper().strip()
        if cidade_norm in cmila_cfg["mg_cmp_municipios"]:
            return "CMP"
        return cmila_cfg["mg_padrao"]
    return cmila_cfg["por_uf"].get(uf)


def classify_orgao_gestor(acao: str, uo_codigo, orgao_cfg: dict):
    """Retorna (orgao, confirmado). Códigos não mapeados => NÃO CLASSIFICADO."""
    if not acao:
        return None, False
    especial = orgao_cfg.get("regras_especiais", {}).get(acao)
    if especial:
        por_uo = especial.get("por_unidade_orcamentaria", {})
        if uo_codigo and uo_codigo in por_uo:
            return por_uo[uo_codigo], True
        return especial.get("padrao"), True
    orgao = orgao_cfg.get("acoes", {}).get(acao)
    if orgao:
        return orgao, True
    return None, False  # NÃO CLASSIFICADO — nunca inferir


def regras_por_titulo(titulo: str, orgao_cfg: dict):
    """Regras de órgão gestor por palavra-chave no título (configurável).

    Retorna (substituto, extras): 'substituto' troca o órgão principal
    derivado da Ação (regra com "substituir": true); 'extras' são órgãos
    apenas ADICIONADOS ao filtro, mantendo o principal.
    """
    substituto, extras = None, []
    titulo_norm = strip_accents(titulo or "").upper()
    for regra in orgao_cfg.get("orgaos_por_titulo", []):
        chave = strip_accents(regra.get("titulo_contem", "")).upper()
        if chave and chave in titulo_norm:
            if regra.get("substituir"):
                substituto = regra["orgao"]
            else:
                extras.append(regra["orgao"])
    return substituto, extras


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=DEFAULT_REPO,
                    help="Repositório de dados no formato dono/nome")
    ap.add_argument("--local-dir", type=Path, default=None,
                    help="Pasta local com os PDFs (pula o download)")
    ap.add_argument("--cache-dir", type=Path, default=BASE_DIR / ".cache",
                    help="Pasta de cache dos PDFs baixados")
    ap.add_argument("--out-dir", type=Path, default=SITE_DIR,
                    help="Pasta do site (recebe data/projects.json e pdfs/)")
    args = ap.parse_args()

    orgao_cfg, cmila_cfg = load_config()

    print("1/4 Listando PDFs…")
    if args.local_dir:
        files = local_pdfs(args.local_dir)
    else:
        files = download_pdfs(args.repo, args.cache_dir)
    if not files:
        print("ERRO: nenhum PDF encontrado.", file=sys.stderr)
        sys.exit(1)
    print(f"    {len(files)} PDFs encontrados.")

    pdfs_out = args.out_dir / "pdfs"
    data_out = args.out_dir / "data"
    previews_out = args.out_dir / "previews"
    pdfs_out.mkdir(parents=True, exist_ok=True)
    data_out.mkdir(parents=True, exist_ok=True)
    previews_out.mkdir(parents=True, exist_ok=True)
    for old in pdfs_out.glob("*.pdf"):
        old.unlink()
    for old in previews_out.glob("*.jpg"):
        old.unlink()

    projects, warnings, unmapped = [], [], {}
    id_seq = {}

    print("2/4 Extraindo e classificando projetos…")
    for f in files:
        pages = extract_pages_text(f["path"])
        reader = PdfReader(str(f["path"]))
        if len(pages) != len(reader.pages):
            warnings.append(
                f"{f['name']}: pdftotext extraiu {len(pages)} páginas, "
                f"mas o PDF tem {len(reader.pages)} — verifique.")
        for page_no, page_text in enumerate(pages, start=1):
            ctx = f"{f['name']} p.{page_no}"
            fields = parse_page(page_text, warnings, ctx)
            if fields is None:
                continue

            c_mil_a = classify_c_mil_a(fields["uf"], fields["cidade"], cmila_cfg)
            if c_mil_a is None:
                warnings.append(f"{ctx}: UF {fields['uf']} sem C Mil A mapeado")
            acao = fields["acaoOrcamentaria"]
            uo = fields["unidadeOrcamentaria"]
            orgao, confirmado = classify_orgao_gestor(
                acao, uo["codigo"] if uo else None, orgao_cfg)
            if acao and not confirmado:
                unmapped.setdefault(acao, []).append(ctx)
            substituto, extras = regras_por_titulo(fields["titulo"], orgao_cfg)
            if substituto:
                orgao_principal, confirmado = substituto, True
            else:
                orgao_principal = orgao if confirmado else "NÃO CLASSIFICADO"
            lista_orgaos = [orgao_principal]
            for extra in extras:
                if extra not in lista_orgaos:
                    lista_orgaos.append(extra)

            base = "-".join([
                slugify(fields["uf"]), slugify(fields["cidade"]),
                slugify(acao or "sem-acao")])
            id_seq[base] = id_seq.get(base, 0) + 1
            proj_id = f"{base}-{id_seq[base]:02d}"

            projects.append({
                "id": proj_id,
                "titulo": fields["titulo"],
                "objetivo": fields["objetivo"],
                "cidade": fields["cidade"],
                "uf": fields["uf"],
                "cMilA": c_mil_a,
                "cMilANome": cmila_cfg["nomes_completos"].get(c_mil_a),
                "omBeneficiada": fields["omBeneficiada"],
                "unidadeOrcamentaria": uo,
                "acaoOrcamentaria": acao,
                "orgaoGestor": orgao_principal,
                "orgaosGestores": lista_orgaos,
                "orgaoGestorConfirmado": confirmado,
                "modalidadeAplicacao": fields["modalidadeAplicacao"],
                "funcao": fields["funcao"],
                "subfuncao": fields["subfuncao"],
                "programa": fields["programa"],
                "gnd3": fields["gnd3"],
                "gnd4": fields["gnd4"],
                "total": fields["total"],
                "pdfOrigem": f["name"],
                "pdfPaginaOriginal": page_no,
                "pdfDownloadUrl": f"pdfs/{proj_id}.pdf",
                "previewUrl": f"previews/{proj_id}.jpg",
                "_writer_src": (str(f["path"]), page_no - 1),
            })

    print(f"    {len(projects)} projetos extraídos.")

    print("3/4 Gerando PDFs de página única…")
    readers = {}
    for p in projects:
        src, page_idx = p.pop("_writer_src")
        if src not in readers:
            readers[src] = PdfReader(src)
        writer = PdfWriter()
        writer.add_page(readers[src].pages[page_idx])
        with open(pdfs_out / f"{p['id']}.pdf", "wb") as out:
            writer.write(out)

    print("3b/4 Gerando imagens de pré-visualização (visor interno do app)…")
    for p in projects:
        # imagem da página para o visor interno (funciona em qualquer celular,
        # inclusive no app instalado na tela de início, sem sair do aplicativo)
        subprocess.run(
            ["pdftoppm", "-jpeg", "-jpegopt", "quality=72", "-r", "100",
             "-singlefile", str(pdfs_out / f"{p['id']}.pdf"),
             str(previews_out / p["id"])],
            check=True)

    print("4/4 Gravando projects.json e relatório de build…")
    dataset = {
        "geradoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonteRepo": args.repo if not args.local_dir else str(args.local_dir),
        "fontes": [{"arquivo": f["name"], "sha": f["sha"]} for f in files],
        "totalProjetos": len(projects),
        "projetos": projects,
    }
    with open(data_out / "projects.json", "w", encoding="utf-8") as out:
        json.dump(dataset, out, ensure_ascii=False, separators=(",", ":"))

    report = {
        "geradoEm": dataset["geradoEm"],
        "totalPdfs": len(files),
        "totalProjetos": len(projects),
        "acoesNaoMapeadas": {
            k: {"ocorrencias": len(v), "paginas": v} for k, v in sorted(unmapped.items())
        },
        "avisos": warnings,
    }
    with open(data_out / "build_report.json", "w", encoding="utf-8") as out:
        json.dump(report, out, ensure_ascii=False, indent=2)

    if unmapped:
        print("\n⚠ AÇÕES NÃO MAPEADAS (classificadas como NÃO CLASSIFICADO):")
        for k, v in sorted(unmapped.items()):
            print(f"    {k}: {len(v)} ocorrência(s)")
        print("    → complete etl/config/orgao_gestor.json com base em "
              "documentação orçamentária oficial.")
    if warnings:
        print(f"\n⚠ {len(warnings)} aviso(s) — ver site/data/build_report.json")
    print("\nConcluído.")


if __name__ == "__main__":
    main()
