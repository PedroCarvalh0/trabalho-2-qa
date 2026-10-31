"""
parser_acessibilidade.py
========================

Parser de relatórios de acessibilidade do Portal TechInclusiva.

Lê o JSON gerado pelo axe-core CLI (resultado_axe.json) ou pelo Google
Lighthouse CLI (resultado_lighthouse.json) e:

1. Leitura de Dados ........ carrega o arquivo e detecta a ferramenta de origem;
2. Extração de Falhas ...... extrai as violações (axe) / auditorias reprovadas (Lighthouse);
3. Categorização ........... agrupa por severidade (critical, serious, moderate, minor);
4. Mapeamento de Elementos . lista os seletores CSS e trechos HTML afetados por regra;
5. Relatório Final ......... imprime um resumo consolidado no terminal e salva um PDF
                             no formato de entrega (capa, sumário e seções).

Além disso, cada falha é mapeada para os critérios de sucesso da WCAG 2.1
(níveis A e AA) a partir das tags do axe-core (ex.: "wcag2a", "wcag111").
Os textos das regras são traduzidos com a tradução oficial do axe-core
(node_modules/axe-core/locales/pt_BR.json), quando o arquivo existir.

Uso:
    python parser_acessibilidade.py resultado_axe.json
    python parser_acessibilidade.py resultado_axe.json --pdf relatorio_acessibilidade.pdf
    python parser_acessibilidade.py resultado_axe.json --severidade critical serious
    python parser_acessibilidade.py resultado_axe.json --somente-wcag
    python parser_acessibilidade.py resultado_axe.json \
        --comparar resultado_axe_corrigido.json \
        --html-corrigido index_corrigido.html \
        --github https://github.com/<usuario>/<repositorio> \
        --equipe "Nome 1, Nome 2, Nome 3"

Dependências: Python 3.10+ e reportlab (pip install -r requirements.txt).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import Counter
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Tabelas de referência
# ---------------------------------------------------------------------------

# Ordem de prioridade das severidades do axe-core (da mais grave para a mais leve).
SEVERIDADES = ["critical", "serious", "moderate", "minor"]

SEVERIDADE_PT = {
    "critical": "Crítica",
    "serious": "Grave",
    "moderate": "Moderada",
    "minor": "Leve",
}

# Critérios de sucesso da WCAG 2.1 (níveis A e AA) mais cobertos pelo axe-core.
CRITERIOS_WCAG = {
    "1.1.1": ("Conteúdo não textual", "A"),
    "1.2.1": ("Apenas áudio e apenas vídeo (pré-gravado)", "A"),
    "1.2.2": ("Legendas (pré-gravado)", "A"),
    "1.2.3": ("Audiodescrição ou mídia alternativa", "A"),
    "1.2.5": ("Audiodescrição (pré-gravada)", "AA"),
    "1.3.1": ("Informações e relações", "A"),
    "1.3.2": ("Sequência significativa", "A"),
    "1.3.4": ("Orientação", "AA"),
    "1.3.5": ("Identificar o propósito de entrada", "AA"),
    "1.4.1": ("Uso de cor", "A"),
    "1.4.2": ("Controle de áudio", "A"),
    "1.4.3": ("Contraste (mínimo)", "AA"),
    "1.4.4": ("Redimensionar texto", "AA"),
    "1.4.10": ("Refluxo", "AA"),
    "1.4.11": ("Contraste não textual", "AA"),
    "1.4.12": ("Espaçamento de texto", "AA"),
    "2.1.1": ("Teclado", "A"),
    "2.1.4": ("Atalhos de teclado por caractere", "A"),
    "2.2.1": ("Ajustável por temporização", "A"),
    "2.2.2": ("Pausar, parar, ocultar", "A"),
    "2.4.1": ("Ignorar blocos", "A"),
    "2.4.2": ("Página com título", "A"),
    "2.4.3": ("Ordem do foco", "A"),
    "2.4.4": ("Finalidade do link (em contexto)", "A"),
    "2.4.6": ("Cabeçalhos e rótulos", "AA"),
    "2.4.7": ("Foco visível", "AA"),
    "2.5.3": ("Rótulo no nome", "A"),
    "3.1.1": ("Idioma da página", "A"),
    "3.1.2": ("Idioma das partes", "AA"),
    "3.2.1": ("Em foco", "A"),
    "3.3.1": ("Identificação do erro", "A"),
    "3.3.2": ("Rótulos ou instruções", "A"),
    "4.1.1": ("Análise sintática", "A"),
    "4.1.2": ("Nome, função, valor", "A"),
}

# Orientação de correção (em português) para as regras mais comuns do axe-core.
# Quando a regra não estiver aqui, usa-se o texto "help" da própria ferramenta.
REMEDIACAO = {
    "accesskeys": "Use valores de accesskey únicos na página (ou remova o atributo).",
    "aria-required-attr": "Inclua os atributos ARIA obrigatórios do papel (ex.: aria-checked em role=\"checkbox\") ou use o elemento nativo (<input type=\"checkbox\">).",
    "aria-toggle-field-name": "Dê um nome acessível ao controle (texto visível, aria-label ou aria-labelledby).",
    "aria-valid-attr-value": "Use apenas valores válidos para atributos ARIA (ex.: aria-pressed aceita true, false ou mixed).",
    "autocomplete-valid": "Use tokens válidos do HTML no atributo autocomplete (ex.: autocomplete=\"email\", \"name\").",
    "button-name": "Botões precisam de nome acessível: texto interno, aria-label ou imagem com alt descritivo.",
    "color-contrast": "Ajuste as cores para contraste mínimo de 4.5:1 (texto normal) ou 3:1 (texto grande).",
    "document-title": "Adicione um <title> descritivo e único no <head> da página.",
    "duplicate-id": "Garanta que cada valor de id seja único no documento.",
    "empty-heading": "Cabeçalhos não podem ser vazios; inclua texto ou remova o elemento.",
    "empty-table-header": "Cabeçalhos de tabela (<th>) precisam de texto que descreva a coluna/linha.",
    "frame-title": "Adicione um atributo title descritivo a cada <iframe>.",
    "heading-order": "Mantenha a hierarquia dos cabeçalhos sem pular níveis (h1 > h2 > h3...).",
    "html-has-lang": "Declare o idioma da página no elemento raiz: <html lang=\"pt-BR\">.",
    "image-alt": "Toda <img> precisa de alt: texto descritivo para imagens informativas ou alt=\"\" para decorativas.",
    "image-redundant-alt": "Evite repetir no alt palavras como \"imagem\" ou o texto já presente ao redor.",
    "label": "Associe um <label for=\"id\"> a cada campo de formulário (ou use aria-label/aria-labelledby).",
    "landmark-one-main": "Envolva o conteúdo principal em um único elemento <main>.",
    "link-name": "Links precisam de texto descritivo; links só com imagem exigem alt na imagem ou aria-label.",
    "list": "Listas <ul>/<ol> devem conter apenas elementos <li> (ou <script>/<template>) como filhos diretos.",
    "listitem": "Elementos <li> devem estar dentro de <ul> ou <ol>.",
    "meta-viewport": "Não bloqueie o zoom: remova user-scalable=no e maximum-scale < 2 da meta viewport.",
    "page-has-heading-one": "Inclua um <h1> com o título principal da página.",
    "region": "Coloque todo o conteúdo dentro de landmarks: <header>, <nav>, <main>, <aside>, <footer>.",
    "select-name": "Associe um <label> a cada <select> (ou use aria-label/aria-labelledby).",
    "tabindex": "Não use tabindex maior que 0; reorganize o DOM para que a ordem natural de foco seja lógica.",
}

# Rótulos de tags do axe que indicam o nível de conformidade.
TAGS_NIVEL = {
    "wcag2a": "A",
    "wcag21a": "A",
    "wcag22a": "A",
    "wcag2aa": "AA",
    "wcag21aa": "AA",
    "wcag22aa": "AA",
    "wcag2aaa": "AAA",
    "wcag21aaa": "AAA",
}

# Tradução oficial das regras do axe-core, instalada junto com o @axe-core/cli.
LOCALE_AXE = Path(__file__).resolve().parent / "node_modules" / "axe-core" / "locales" / "pt_BR.json"

# ---------------------------------------------------------------------------
# Modelo de dados
# ---------------------------------------------------------------------------


@dataclass
class Elemento:
    """Um nó do DOM afetado por uma regra violada."""

    seletor: str
    html: str
    resumo: str = ""


@dataclass
class Violacao:
    """Uma regra de acessibilidade reprovada, já normalizada (axe ou Lighthouse)."""

    regra: str
    impacto: str
    descricao: str
    ajuda: str
    url_ajuda: str
    tags: list[str]
    elementos: list[Elemento] = field(default_factory=list)

    @property
    def criterios(self) -> list[str]:
        """Critérios WCAG no formato "1.4.3", extraídos de tags como "wcag143"."""
        criterios = []
        for tag in self.tags:
            m = re.fullmatch(r"wcag(\d)(\d)(\d+)", tag)
            if m:
                criterios.append(".".join(m.groups()))
        return criterios

    @property
    def nivel(self) -> str:
        """Nível de conformidade (A, AA, AAA) ou "Boa prática" quando não é critério WCAG."""
        niveis = [TAGS_NIVEL[t] for t in self.tags if t in TAGS_NIVEL]
        if niveis:
            return min(niveis, key=len)
        return "Boa prática"

    @property
    def remediacao(self) -> str:
        return REMEDIACAO.get(self.regra, self.ajuda)


@dataclass
class Auditoria:
    """Resultado completo de uma varredura."""

    ferramenta: str
    versao: str
    url: str
    data: str
    violacoes: list[Violacao]
    total_aprovadas: int = 0
    # Regras que o axe não conseguiu decidir sozinho ("incomplete"); None no Lighthouse.
    total_incompletas: int | None = None

    def por_severidade(self) -> dict[str, list[Violacao]]:
        grupos: dict[str, list[Violacao]] = {s: [] for s in SEVERIDADES}
        for v in self.violacoes:
            grupos.setdefault(v.impacto, []).append(v)
        return grupos

    @property
    def total_ocorrencias(self) -> int:
        return sum(len(v.elementos) for v in self.violacoes)


# ---------------------------------------------------------------------------
# 1. Leitura de dados e 2. Extração de falhas
# ---------------------------------------------------------------------------


def carregar_json(caminho: Path) -> object:
    """Lê o arquivo JSON de saída do axe-core ou do Lighthouse."""
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
    with caminho.open(encoding="utf-8") as f:
        return json.load(f)


def carregar_auditoria(caminho: Path) -> Auditoria:
    """Detecta a ferramenta de origem e converte o JSON em uma Auditoria."""
    dados = carregar_json(caminho)
    if isinstance(dados, dict) and "audits" in dados and "categories" in dados:
        return extrair_lighthouse(dados)
    if isinstance(dados, list) or (isinstance(dados, dict) and "violations" in dados):
        return extrair_axe(dados)
    raise ValueError(f"{caminho} não parece ser um relatório do axe-core nem do Lighthouse.")


def carregar_traducoes(caminho: Path = LOCALE_AXE) -> dict[str, dict]:
    """Lê os textos em português das regras do axe-core; vazio se o arquivo não existir."""
    try:
        with caminho.open(encoding="utf-8") as f:
            return json.load(f).get("rules", {})
    except (OSError, ValueError):
        return {}


def formatar_seletor(target: list) -> str:
    """Converte o "target" do axe em texto: cada item é um seletor dentro do iframe
    anterior, e listas internas indicam elementos dentro de shadow DOM."""
    return " > ".join(" ".join(t) if isinstance(t, list) else str(t) for t in target)


def extrair_axe(dados: list | dict) -> Auditoria:
    """Extrai as violações do JSON do axe-core CLI.

    O axe CLI salva uma lista com um resultado por URL varrida; aqui usamos o
    primeiro resultado (uma página por execução, como no roteiro do trabalho).
    """
    if isinstance(dados, list):
        if not dados:
            raise ValueError("o JSON do axe não contém resultados.")
        if len(dados) > 1:
            print(f"Aviso: o JSON contém {len(dados)} páginas; apenas a primeira foi analisada.",
                  file=sys.stderr)
        resultado = dados[0]
    else:
        resultado = dados
    violacoes = [
        Violacao(
            regra=v["id"],
            impacto=v.get("impact") or "minor",
            descricao=v.get("description", ""),
            ajuda=v.get("help", ""),
            url_ajuda=v.get("helpUrl", ""),
            tags=v.get("tags", []),
            elementos=[
                Elemento(
                    seletor=formatar_seletor(n.get("target", [])),
                    html=n.get("html", ""),
                    resumo=n.get("failureSummary", ""),
                )
                for n in v.get("nodes", [])
            ],
        )
        for v in resultado.get("violations", [])
    ]
    motor = resultado.get("testEngine", {})
    return Auditoria(
        ferramenta="axe-core",
        versao=motor.get("version", "?"),
        url=resultado.get("url", "?"),
        data=resultado.get("timestamp", ""),
        violacoes=violacoes,
        total_aprovadas=len(resultado.get("passes", [])),
        total_incompletas=len(resultado.get("incomplete", [])),
    )


def extrair_lighthouse(dados: dict) -> Auditoria:
    """Extrai as auditorias de acessibilidade reprovadas do JSON do Lighthouse.

    Os ids das auditorias de acessibilidade do Lighthouse são as próprias regras
    do axe-core; severidade e tags vêm de details.debugData.
    """
    categoria = dados["categories"].get("accessibility")
    if not categoria:
        raise ValueError("o relatório do Lighthouse não contém a categoria de acessibilidade "
                         "(execute com --only-categories=accessibility).")
    ids = [ref["id"] for ref in categoria.get("auditRefs", [])]
    violacoes, aprovadas = [], 0
    for regra in ids:
        audit = dados["audits"].get(regra, {})
        if audit.get("scoreDisplayMode") != "binary":
            continue
        if audit.get("score") == 1:
            aprovadas += 1
            continue
        detalhes = audit.get("details", {})
        debug = detalhes.get("debugData", {})
        # A descrição do Lighthouse termina com um link markdown "[Learn more](url)".
        link = re.search(r"\((https?://[^)\s]+)\)", audit.get("description", ""))
        violacoes.append(
            Violacao(
                regra=regra,
                impacto=debug.get("impact") or "minor",
                descricao=audit.get("description", ""),
                ajuda=audit.get("title", ""),
                url_ajuda=link.group(1) if link else "",
                tags=debug.get("tags", []),
                elementos=[
                    Elemento(
                        seletor=item.get("node", {}).get("selector", ""),
                        html=item.get("node", {}).get("snippet", ""),
                        resumo=item.get("node", {}).get("explanation", ""),
                    )
                    for item in detalhes.get("items", [])
                ],
            )
        )
    return Auditoria(
        ferramenta="Lighthouse",
        versao=dados.get("lighthouseVersion", "?"),
        url=dados.get("finalDisplayedUrl") or dados.get("finalUrl") or dados.get("requestedUrl", "?"),
        data=dados.get("fetchTime", ""),
        violacoes=violacoes,
        total_aprovadas=aprovadas,
    )


def traduzir(auditoria: Auditoria, traducoes: dict[str, dict]) -> Auditoria:
    """Substitui os textos das regras pela tradução em português, quando houver."""
    for v in auditoria.violacoes:
        texto = traducoes.get(v.regra, {})
        v.ajuda = texto.get("help", v.ajuda)
        v.descricao = texto.get("description", v.descricao)
    return auditoria


def filtrar(auditoria: Auditoria, severidades: list[str] | None, somente_wcag: bool) -> Auditoria:
    """Filtra violações por severidade e/ou apenas critérios WCAG (exclui boas práticas)."""
    violacoes = [
        v
        for v in auditoria.violacoes
        if (not severidades or v.impacto in severidades)
        and (not somente_wcag or v.nivel != "Boa prática")
    ]
    auditoria.violacoes = ordenar(violacoes)
    return auditoria


# ---------------------------------------------------------------------------
# 3. Categorização e priorização
# ---------------------------------------------------------------------------


def ordenar(violacoes: list[Violacao]) -> list[Violacao]:
    """Prioriza por severidade e, em seguida, pelo número de elementos afetados."""
    peso = {s: i for i, s in enumerate(SEVERIDADES)}
    return sorted(violacoes, key=lambda v: (peso.get(v.impacto, 99), -len(v.elementos), v.regra))


def resumo_wcag(violacoes: list[Violacao]) -> list[tuple[str, str, str, list[str]]]:
    """Agrupa as regras por critério WCAG: (critério, nome, nível, regras)."""
    mapa: dict[str, list[str]] = {}
    for v in violacoes:
        for c in v.criterios:
            mapa.setdefault(c, []).append(v.regra)
    chave = lambda c: tuple(int(p) for p in c.split("."))  # noqa: E731
    return [
        (c, *CRITERIOS_WCAG.get(c, ("(ver especificação WCAG)", "?")), regras)
        for c, regras in sorted(mapa.items(), key=lambda kv: chave(kv[0]))
    ]


# ---------------------------------------------------------------------------
# 5a. Resumo no terminal
# ---------------------------------------------------------------------------

CORES = {"critical": "\033[91m", "serious": "\033[33m", "moderate": "\033[36m", "minor": "\033[37m"}
NEGRITO, RESET = "\033[1m", "\033[0m"


def usar_cores() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def cor(texto: str, codigo: str) -> str:
    return f"{codigo}{texto}{RESET}" if usar_cores() else texto


def imprimir_resumo(auditoria: Auditoria, comparacao: Auditoria | None = None) -> None:
    """Exibe o resumo consolidado da auditoria no terminal."""
    linha = "=" * 78
    print(linha)
    print(cor(" RELATÓRIO DE ACESSIBILIDADE - PORTAL TECHINCLUSIVA (WCAG 2.1 A/AA)", NEGRITO))
    print(linha)
    print(f" Ferramenta : {auditoria.ferramenta} {auditoria.versao}")
    print(f" URL        : {auditoria.url}")
    print(f" Data       : {formatar_data(auditoria.data)}")
    print(f" Regras violadas: {len(auditoria.violacoes)}   "
          f"Elementos afetados: {auditoria.total_ocorrencias}   "
          f"Regras aprovadas: {auditoria.total_aprovadas}")
    if auditoria.total_incompletas is not None:
        print(f" Regras para revisão manual (incomplete): {auditoria.total_incompletas}")
    print(linha)

    print(cor(" POR SEVERIDADE", NEGRITO))
    grupos = auditoria.por_severidade()
    for sev in SEVERIDADES:
        regras = grupos.get(sev, [])
        ocorr = sum(len(v.elementos) for v in regras)
        rotulo = f"{sev:<9} ({SEVERIDADE_PT[sev]})"
        print(f"  {cor(f'{rotulo:<22}', CORES[sev])} {len(regras):>3} regra(s)  {ocorr:>3} elemento(s)")

    niveis = Counter(v.nivel for v in auditoria.violacoes)
    print(cor(" POR NÍVEL WCAG", NEGRITO))
    for nivel in ["A", "AA", "AAA", "Boa prática"]:
        if niveis.get(nivel):
            print(f"  {nivel:<12} {niveis[nivel]:>3} regra(s)")
    if not niveis:
        print("  (nenhuma regra violada)")
    print(linha)

    print(cor(" VIOLAÇÕES PRIORIZADAS E ELEMENTOS AFETADOS", NEGRITO))
    if not auditoria.violacoes:
        print("\n  Nenhuma violação encontrada.")
    for i, v in enumerate(auditoria.violacoes, 1):
        criterios = ", ".join(v.criterios) or "-"
        print(f"\n {i:>2}. {cor('[' + v.impacto.upper() + ']', CORES.get(v.impacto, ''))} "
              f"{cor(v.regra, NEGRITO)}  (WCAG {criterios} | {v.nivel})")
        print(f"     {v.ajuda}")
        print(f"     Correção: {v.remediacao}")
        for e in v.elementos:
            print(f"       - {e.seletor}")

    if comparacao is not None:
        print("\n" + linha)
        print(cor(" ANTES x DEPOIS DA CORREÇÃO", NEGRITO))
        for rotulo, a, d in tabela_comparacao(auditoria, comparacao):
            print(f"  {rotulo:<26} {a:>6} -> {d:<6}")
    print(linha)


# ---------------------------------------------------------------------------
# 5b. Relatório em PDF (formato de entrega do Trabalho II)
# ---------------------------------------------------------------------------


def formatar_data(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
    except (ValueError, AttributeError):
        return iso or "-"


def tabela_comparacao(antes: Auditoria, depois: Auditoria) -> list[tuple[str, int, int]]:
    ga, gd = antes.por_severidade(), depois.por_severidade()
    linhas = [
        ("Regras violadas", len(antes.violacoes), len(depois.violacoes)),
        ("Elementos afetados", antes.total_ocorrencias, depois.total_ocorrencias),
    ]
    for sev in SEVERIDADES:
        linhas.append((f"{SEVERIDADE_PT[sev]} ({sev})", len(ga.get(sev, [])), len(gd.get(sev, []))))
    linhas.append(("Regras aprovadas", antes.total_aprovadas, depois.total_aprovadas))
    return linhas


# Dados da capa.
DOCUMENTO = {
    "instituicao": "UniSENAI",
    "curso": "Superior de Tecnologia em Análise e Desenvolvimento de Sistemas",
    "equipe": ("Arthur Campana", "Pedro Henrique de Carvalho"),
    "titulo": "Auditoria de Acessibilidade Web: Portal TechInclusiva",
    "disciplina": "Trabalho II – Qualidade e Teste de Software",
    "professor": "Prof. MSc. Hugo Menezes Barra",
}

LOGO_SENAI = Path(__file__).resolve().parent / "assets" / "logo_senai.png"
PRINT_TERMINAL = Path("evidencias") / "terminal_vscode.png"

# Textos específicos da página de teste deste trabalho (seções 2.1 e 4 do relatório).
# Trechos entre crases saem em fonte de código e entre asteriscos, em itálico.
DESCRICAO_PAGINA = (
    "uma versão simplificada da página inicial do portal, com barreiras de acessibilidade colocadas de "
    "propósito: imagens sem texto alternativo, campos e botões sem nome acessível, baixo contraste, "
    "ausência de `lang` e `title`, títulos fora de ordem, `tabindex` positivo e controles ARIA inválidos"
)
COMANDOS = """\
npm run driver          # ChromeDriver da mesma versão do Chrome
npm run servidor        # python -m http.server 8080
npm run scan            # axe http://localhost:8080/index.html
                        #     --save resultado_axe.json --dir .
npm run scan:corrigido  # mesma auditoria em index_corrigido.html
npm run relatorio       # parser_acessibilidade.py: terminal e PDF"""
# Correção aplicada em index_corrigido.html para cada regra (tabela de correções). Regras com o
# mesmo texto aparecem juntas; regras sem entrada usam a orientação genérica de REMEDIACAO.
CORRECOES = {
    "image-alt": 'Foto da notícia e ícone de RSS com `alt` descritivo; `alt=""` no logo e na lupa, que são '
                 "decorativos",
    "label": "`<label for>` nos campos Nome e E-mail (a busca também ganhou rótulo, visualmente oculto)",
    "aria-required-attr": '`<span role="checkbox">` trocado por `<input type="checkbox">` com rótulo',
    "aria-valid-attr-value": '`<div role="button" aria-pressed="talvez">` trocado por '
                             '`<button type="submit">Assinar</button>`',
    "aria-toggle-field-name": '`<div role="button" aria-pressed="talvez">` trocado por '
                              '`<button type="submit">Assinar</button>`',
    "button-name": "Botão de busca com o texto “Buscar”",
    "select-name": '`<label for="frequencia">` associado ao `<select>`',
    "color-contrast": "Datas em `#595959` sobre branco (7:1), destaque em `#1a1a1a` sobre `#ffd54f` (12,3:1) e "
                      "rodapé em `#333333` sobre `#eeeeee` (10,9:1); antes eram 1,7:1, 1,4:1 e 2:1",
    "tabindex": "Removidos os `tabindex` positivos do menu; a ordem do foco segue o código",
    "link-name": 'Ícone de RSS com `alt="Assinar feed RSS"` e links de “Mais lidas” com texto descritivo',
    "frame-title": '`<iframe>` com `title="Vídeo da reportagem (player)"`',
    "html-has-lang": '`<html lang="pt-BR">`',
    "document-title": "`<title>TechInclusiva - Notícias de tecnologia e acessibilidade</title>`",
    "list": "`<ul>` apenas com itens `<li>`",
    "autocomplete-valid": '`autocomplete="email"` no lugar do valor inválido `mail`',
    "accesskeys": "Removidos os `accesskey` repetidos do rodapé",
    "region": "Conteúdo organizado em `<header>`, `<nav>`, `<main>`, `<aside>` e `<footer>`",
    "landmark-one-main": "Conteúdo organizado em `<header>`, `<nav>`, `<main>`, `<aside>` e `<footer>`",
    "page-has-heading-one": "“Notícias de hoje” passou de `<div>` estilizada para `<h1>`",
    "heading-order": "Hierarquia de títulos `h1` e `h2`, sem saltos (antes havia `h3` e `h5`)",
    "meta-viewport": "Removidos `maximum-scale=1.0` e `user-scalable=no` do `viewport`",
    "empty-table-header": "Cabeçalhos `<th>` com texto e `scope`, e tabela com `<caption>`",
}
AJUSTES_MANUAIS = (
    "Além das regras apontadas pelo axe, a verificação manual com o teclado levou a três ajustes: um link "
    "“Pular para o conteúdo principal” (critério 2.4.1), indicador de foco com contraste mínimo de 3:1 "
    "(critérios 2.4.7 e 1.4.11) e o separador “|” do rodapé oculto para leitores de tela."
)

# Medidas do formato de entrega, em pontos (A4): bloco de texto de 71,3 a 552,3 pt.
MARGEM_ESQ, LARGURA_TEXTO = 71.3, 481.0
TOPO_TEXTO, BASE_TEXTO = 741.0, 67.0
CENTRO_TEXTO = MARGEM_ESQ + LARGURA_TEXTO / 2

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def registrar_fontes() -> dict[str, str]:
    """Registra Calibri (texto) e Courier New (código) a partir do Windows.

    Sem elas (ex.: Linux/macOS), usa as equivalentes padrão do PDF: Helvetica e Courier.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pasta = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    familias = {
        "texto": ("Calibri", ("calibri", "calibrib", "calibrii", "calibriz"),
                  ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique")),
        "mono": ("CourierNew", ("cour", "courbd", "couri", "courbi"),
                 ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique")),
    }
    fontes = {}
    for chave, (familia, arquivos, padrao) in familias.items():
        nomes = tuple(familia + sufixo for sufixo in ("", "-Bold", "-Italic", "-BoldItalic"))
        try:
            for nome, arquivo in zip(nomes, arquivos):
                pdfmetrics.registerFont(TTFont(nome, str(pasta / f"{arquivo}.ttf")))
            pdfmetrics.registerFontFamily(familia, normal=nomes[0], bold=nomes[1], italic=nomes[2],
                                          boldItalic=nomes[3])
        except Exception:  # TTFError/OSError: fonte ausente nesta máquina
            nomes = padrao
        fontes.update({chave: nomes[0], f"{chave}-b": nomes[1], f"{chave}-i": nomes[2]})
    return fontes


def juntar(nomes: list[str]) -> str:
    """["A", "B", "C"] -> "A, B e C"."""
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def qtd(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def saida_terminal(auditoria: Auditoria) -> str:
    """O mesmo resumo que imprimir_resumo mostra no terminal, sem cores, como texto."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        imprimir_resumo(auditoria)
    return buffer.getvalue().strip("\n")


def gerar_pdf(
    auditoria: Auditoria,
    destino: Path,
    comparacao: Auditoria | None = None,
    html_original: Path | None = None,
    html_corrigido: Path | None = None,
    github: str | None = None,
    equipe: list[str] | None = None,
    print_terminal: Path | None = None,
) -> None:
    """Gera o relatório no formato de entrega do Trabalho II: capa, sumário e as seções
    Introdução, Método, Diagnóstico, Correções e Conclusão (requer reportlab)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.platypus import (
            BaseDocTemplate, CondPageBreak, Flowable, Frame, Image, KeepTogether, NextPageTemplate, PageBreak,
            PageTemplate, Paragraph, Table, TableStyle,
        )
        from xml.sax.saxutils import escape
    except ImportError:
        sys.exit("reportlab não instalado. Execute: pip install -r requirements.txt")

    f = registrar_fontes()
    equipe = list(equipe or DOCUMENTO["equipe"])
    agora = datetime.now()
    preto = colors.black
    seta = "→" if f["mono"] == "CourierNew" else "»"  # marca a continuação de linhas de código quebradas
    eh_axe = auditoria.ferramenta == "axe-core"
    cli = "axe-core CLI" if eh_axe else "Lighthouse CLI"

    # --- Estilos: corpo em 12 pt, entrelinha de 18,55 pt e recuo de 1,5 em, como no modelo ---
    corpo = ParagraphStyle("corpo", fontName=f["texto"], fontSize=12, leading=18.55, alignment=TA_JUSTIFY,
                           firstLineIndent=18)
    item = ParagraphStyle("item", parent=corpo, firstLineIndent=0, leftIndent=29.7, bulletIndent=13.4,
                          bulletFontName=f["texto"], bulletFontSize=12, spaceBefore=14.65)
    legenda = ParagraphStyle("legenda", parent=corpo, alignment=TA_CENTER, firstLineIndent=0, spaceBefore=14,
                             spaceAfter=7)
    celula = ParagraphStyle("celula", fontName=f["texto"], fontSize=10, leading=12.5)
    celula_centro = ParagraphStyle("celula_centro", parent=celula, alignment=TA_CENTER)

    def md(texto: str) -> str:
        """Escapa o texto, põe `trechos` em fonte de código e *trechos* em itálico."""
        partes = []
        for i, trecho in enumerate(texto.split("`")):
            if i % 2:
                partes.append(f'<font face="{f["mono"]}">{escape(trecho)}</font>')
            else:
                partes.append(re.sub(r"\*(.+?)\*", r"<i>\1</i>", escape(trecho)))
        return "".join(partes)

    def p(texto: str, estilo=corpo, **kw) -> Paragraph:
        return Paragraph(texto, estilo, **kw)

    def codigo(texto: str, tamanho: float | None = None) -> str:
        tam = f' size="{tamanho}"' if tamanho else ""
        return f'<font face="{f["mono"]}"{tam}>{escape(texto)}</font>'

    # --- Flowables próprios: títulos, sumário e listagens de código --------------------------
    class Titulo(Flowable):
        """Título de seção (nível 0) ou subseção (nível 1), com as medidas do LaTeX."""

        def __init__(self, numero: str, texto: str, nivel: int, sufixo_codigo: str = ""):
            super().__init__()
            self.numero, self.texto, self.nivel, self.sufixo_codigo = numero, texto, nivel, sufixo_codigo
            self.tamanho = 17.28 if nivel == 0 else 14.4
            self.recuo = 31.0 if nivel == 0 else 37.4  # onde começa o texto, depois do número
            self.spaceBefore = 0 if nivel == 0 else 20.35
            self.spaceAfter = 21.6 if nivel == 0 else 17.1
            self.keepWithNext = True

        def wrap(self, aW, aH):
            return aW, self.tamanho * 0.73

        def draw(self):
            c = self.canv
            c.setFont(f["texto-b"], self.tamanho)
            c.drawString(0, 0.4, self.numero)
            c.drawString(self.recuo, 0.4, self.texto)
            if self.sufixo_codigo:
                x = self.recuo + c.stringWidth(self.texto, f["texto-b"], self.tamanho)
                c.setFont(f["mono"], self.tamanho)
                c.drawString(x, 0.4, self.sufixo_codigo)

    class Sumario(Flowable):
        """Página "Sumário": seções em negrito e subseções com pontilhado alinhado, como no LaTeX."""

        def __init__(self, entradas: list):
            super().__init__()
            self.entradas = entradas  # [(nível, número, texto, sufixo_codigo, página)]

        def wrap(self, aW, aH):
            self.largura, self.altura = aW, aH
            return aW, aH

        def draw(self):
            c = self.canv
            c.setFont(f["texto-b"], 17.28)
            y = self.altura - 12.2
            c.drawString(0, y, "Sumário")
            y -= 42.4
            for i, (nivel, numero, texto, sufixo, pagina) in enumerate(self.entradas):
                if nivel == 0 and i > 0:
                    y -= 11.5  # espaço extra antes de cada seção
                fonte = f["texto-b"] if nivel == 0 else f["texto"]
                x_numero = 0 if nivel == 0 else 18
                x_texto = x_numero + (18 if nivel == 0 else 27.6)
                c.setFont(fonte, 12)
                c.drawString(x_numero, y, numero)
                c.drawString(x_texto, y, texto)
                fim = x_texto + c.stringWidth(texto, fonte, 12)
                if sufixo:
                    c.setFont(f["mono"], 12)
                    c.drawString(fim, y, sufixo)
                    fim += c.stringWidth(sufixo, f["mono"], 12)
                    c.setFont(fonte, 12)
                c.drawRightString(self.largura, y, str(pagina))
                if nivel > 0:  # pontilhado em colunas fixas, a partir da direita
                    x = self.largura - 22
                    while x > fim + 6:
                        c.drawString(x, y, ".")
                        x -= 7.2
                y -= 19

    class Listagem(Flowable):
        """Bloco de código em moldura, como o pacote listings do LaTeX: números de linha à
        esquerda, fora da moldura, e quebra entre páginas sem fechar a moldura no meio."""

        def __init__(self, linhas: list, tamanho: float, entrelinha: float, topo=True, base=True):
            super().__init__()
            self.linhas, self.tamanho, self.entrelinha = linhas, tamanho, entrelinha  # [(número, texto)]
            self.topo, self.base = topo, base
            self.folga = 4.0  # entre a moldura e a primeira/última linha
            self.spaceBefore = 8 if topo else 0
            self.spaceAfter = 12 if base else 0

        def _altura(self, n: int) -> float:
            return n * self.entrelinha + self.folga * (self.topo + self.base)

        def wrap(self, aW, aH):
            self.largura = aW
            return aW, self._altura(len(self.linhas))

        def split(self, aW, aH):
            cabem = int((aH - self.folga * self.topo) // self.entrelinha)
            if cabem < 2 or cabem >= len(self.linhas):
                return []
            return [Listagem(self.linhas[:cabem], self.tamanho, self.entrelinha, self.topo, False),
                    Listagem(self.linhas[cabem:], self.tamanho, self.entrelinha, False, self.base)]

        def draw(self):
            c = self.canv
            altura = self._altura(len(self.linhas))
            c.setLineWidth(0.4)
            c.line(0, 0, 0, altura)
            c.line(self.largura, 0, self.largura, altura)
            if self.topo:
                c.line(0, altura, self.largura, altura)
            if self.base:
                c.line(0, 0, self.largura, 0)
            c.setFont(f["mono"], self.tamanho)
            y = altura - self.folga * self.topo - 0.72 * self.entrelinha
            for numero, texto in self.linhas:
                if numero:
                    c.drawRightString(-12.7, y, numero)
                c.drawString(3.7, y, texto)
                y -= self.entrelinha

    def listagem(texto: str, tamanho: float, entrelinha: float, numerar: bool) -> Listagem:
        """Quebra as linhas longas (no último espaço que couber) e marca as continuações com a seta."""
        maximo = int((LARGURA_TEXTO - 7.4) // pdfmetrics.stringWidth("M", f["mono"], tamanho))
        linhas = []
        for n, linha in enumerate(texto.rstrip("\n").split("\n"), 1):
            linha = linha.rstrip().replace("\t", "    ")
            numero = str(n) if numerar else ""
            prefixo = " " * min(len(linha) - len(linha.lstrip(" ")), maximo // 2) + seta + " "
            while len(linha) > maximo:
                corte = linha.rfind(" ", len(prefixo), maximo)
                if corte <= len(prefixo):
                    corte = maximo
                linhas.append((numero, linha[:corte]))
                linha = prefixo + linha[corte:].lstrip(" ")
                numero = ""
            linhas.append((numero, linha))
        return Listagem(linhas, tamanho, entrelinha)

    def tabela(dados: list, larguras: list[float], tamanho: float = 10, total=False, centro=()) -> Table:
        """Tabela no estilo do LaTeX: grade fina e cabeçalho em negrito com linha dupla."""
        t = Table(dados, colWidths=larguras, repeatRows=1, spaceAfter=14)
        estilo = [
            ("GRID", (0, 0), (-1, -1), 0.4, preto),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, preto, None, None, None, 2, 2),
            ("FONTNAME", (0, 0), (-1, -1), f["texto"]),
            ("FONTNAME", (0, 0), (-1, 0), f["texto-b"]),
            ("FONTSIZE", (0, 0), (-1, -1), tamanho),
            ("LEADING", (0, 0), (-1, -1), tamanho * 1.25),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        estilo += [("ALIGN", (col, 0), (col, -1), "CENTER") for col in centro]
        if total:
            estilo += [("FONTNAME", (0, -1), (-1, -1), f["texto-b"]),
                       ("LINEABOVE", (0, -1), (-1, -1), 0.4, preto, None, None, None, 2, 2)]
        t.setStyle(TableStyle(estilo))
        return t

    def figura(caminho: Path | None, frase: str, titulo: str) -> list:
        """Frase que apresenta a figura, legenda e a imagem (ou um aviso, se o print ainda não
        existir), sempre na mesma página."""
        if caminho is not None and caminho.exists():
            conteudo = Image(str(caminho))
            escala = min(LARGURA_TEXTO / conteudo.imageWidth, 420 / conteudo.imageHeight)
            conteudo.drawWidth, conteudo.drawHeight = conteudo.imageWidth * escala, conteudo.imageHeight * escala
            conteudo.spaceAfter = 14
        else:
            conteudo = Table([[p(f"Print do terminal do VSCode pendente: salve a captura em "
                                 f"{codigo(PRINT_TERMINAL.as_posix())} e gere o relatório de novo.", celula_centro)]],
                             colWidths=[LARGURA_TEXTO], rowHeights=[120], spaceAfter=14)
            conteudo.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.grey, None, (3, 3)),
                                          ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        return [KeepTogether([p(frase), p(titulo, legenda), conteudo])]

    # --- Páginas: capa sem número, sumário em romano e o restante a partir de 1 -------------
    def numero_pagina(canv, texto: str) -> None:
        canv.saveState()
        canv.setFont(f["texto"], 12)
        canv.drawCentredString(CENTRO_TEXTO, 42.5, texto)
        canv.restoreState()

    def capa(canv, _doc) -> None:
        canv.saveState()
        if LOGO_SENAI.exists():
            canv.drawImage(str(LOGO_SENAI), CENTRO_TEXTO - 62.5, 711.0, width=125, height=32)
        canv.setFont(f["texto-b"], 12)
        canv.drawCentredString(CENTRO_TEXTO, 687, DOCUMENTO["instituicao"])
        canv.drawCentredString(CENTRO_TEXTO, 666, DOCUMENTO["curso"])
        for i, nome in enumerate(equipe):
            canv.drawCentredString(CENTRO_TEXTO, 564 - 21 * i, nome)
        canv.drawCentredString(CENTRO_TEXTO, 413, DOCUMENTO["titulo"])
        canv.setFont(f["texto"], 12)
        canv.drawCentredString(CENTRO_TEXTO, 385, DOCUMENTO["disciplina"])
        canv.drawCentredString(CENTRO_TEXTO, 365, DOCUMENTO["professor"])
        canv.drawCentredString(CENTRO_TEXTO, 85, f"{agora.day} de {MESES[agora.month - 1]} de {agora.year}")
        canv.restoreState()

    class Documento(BaseDocTemplate):
        """Guarda a página de cada título (para o sumário) e cria os marcadores do PDF."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.secoes = []

        def afterFlowable(self, flowable):
            if isinstance(flowable, Titulo):
                self.secoes.append((flowable.nivel, flowable.numero, flowable.texto, flowable.sufixo_codigo,
                                    self.page - 2))
                chave = f"secao{len(self.secoes)}"
                self.canv.bookmarkPage(chave)
                self.canv.addOutlineEntry(f"{flowable.numero} {flowable.texto}{flowable.sufixo_codigo}", chave,
                                          level=flowable.nivel)

    def novo_documento(saida) -> Documento:
        def moldura(nome: str) -> Frame:
            return Frame(MARGEM_ESQ, BASE_TEXTO, LARGURA_TEXTO, TOPO_TEXTO - BASE_TEXTO, id=nome,
                         leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

        return Documento(
            saida, pagesize=A4, title=DOCUMENTO["titulo"], author=juntar(equipe), subject=DOCUMENTO["disciplina"],
            pageTemplates=[
                PageTemplate("capa", [moldura("capa")], onPage=capa),
                PageTemplate("sumario", [moldura("sumario")], onPage=lambda canv, _d: numero_pagina(canv, "i")),
                PageTemplate("corpo", [moldura("corpo")],
                             onPage=lambda canv, d: numero_pagina(canv, str(d.page - 2))),
            ],
        )

    # --- Conteúdo -------------------------------------------------------------------------
    def montar(entradas: list) -> list:
        contador = {"secao": 0, "sub": 0, "tabela": 0, "figura": 0}

        def secao(texto: str) -> list:
            contador["secao"] += 1
            contador["sub"] = 0
            return [PageBreak(), Titulo(str(contador["secao"]), texto, 0)]

        def subsecao(texto: str, sufixo_codigo: str = "") -> list:
            contador["sub"] += 1
            return [Titulo(f'{contador["secao"]}.{contador["sub"]}', texto, 1, sufixo_codigo)]

        def proxima(tipo: str) -> int:
            return contador[tipo] + 1

        def tabela_com_legenda(frase: str, titulo: str, t: Table) -> list:
            """Frase que apresenta a tabela, legenda acima e a tabela. As curtas ficam inteiras na
            mesma página da frase; as longas começam onde couberem as primeiras linhas."""
            contador["tabela"] += 1
            bloco = [p(md(frase)), p(f'Tabela {contador["tabela"]}: {md(titulo)}', legenda), t]
            if t.wrap(LARGURA_TEXTO, 10_000)[1] <= 360:
                return [KeepTogether(bloco)]
            return [CondPageBreak(220), *bloco]

        def itens(textos: list[str]) -> list:
            return [p(md(t) + (";" if i < len(textos) - 1 else "."), item, bulletText=f"{chr(97 + i)})")
                    for i, t in enumerate(textos)]

        grupos = auditoria.por_severidade()
        n, m = len(auditoria.violacoes), auditoria.total_ocorrencias
        criticas = len(grupos.get("critical", []))
        e: list = [NextPageTemplate("sumario"), PageBreak(), Sumario(entradas), NextPageTemplate("corpo")]

        # 1 Introdução
        e += secao("Introdução")
        e += [
            p("O portal de notícias TechInclusiva recebeu relatos de usuários com deficiência visual e motora sobre "
              "barreiras de acesso. Para garantir a conformidade com a WCAG 2.1 (nível AA), a diretoria técnica "
              "decidiu integrar testes automatizados de acessibilidade ao fluxo de desenvolvimento no VSCode."),
            p(md(f"A solução é híbrida: o {cli}, executado no terminal do VSCode, audita a página e gera o "
                 "diagnóstico em JSON; o script em Python `parser_acessibilidade.py` lê esse JSON, classifica as "
                 "violações por severidade, lista os elementos afetados, indica o critério WCAG de cada regra e gera "
                 "este relatório.")),
        ]
        if github:
            # alinhado à esquerda: a URL não quebra, e o texto justificado esticaria a linha anterior
            e.append(p(f'Todo o código do projeto está no repositório <a href="{escape(github)}">{codigo(github)}</a>.',
                       ParagraphStyle("repositorio", parent=corpo, alignment=TA_LEFT)))
        e += subsecao("Objetivos")
        e += itens([
            f"configurar e executar o {cli} no terminal do VSCode, auditando a página servida localmente",
            "ler o JSON gerado com Python, classificando as violações por severidade e listando os elementos "
            "afetados",
            "relacionar cada falha aos critérios de sucesso da WCAG 2.1 (níveis A e AA)",
            "corrigir o HTML e validar as correções com uma nova auditoria",
        ])

        # 2 Método
        e += secao("Método")
        if eh_axe:
            ferramentas = (f"Ferramentas utilizadas: VSCode, Node.js com o pacote `@axe-core/cli` (motor axe-core "
                           f"{auditoria.versao}, com o Chrome em modo *headless*) e Python 3 com a biblioteca "
                           "ReportLab, usada apenas para gerar este PDF.")
        else:
            ferramentas = (f"Ferramentas utilizadas: VSCode, Node.js com o Lighthouse {auditoria.versao} e Python 3 "
                           "com a biblioteca ReportLab, usada apenas para gerar este PDF.")
        e.append(p(md(ferramentas)))
        if html_original is not None:
            e += subsecao("Página de teste")
            e += [p(md(f"A página auditada é o arquivo `{html_original.name}`, {DESCRICAO_PAGINA}.")),
                  listagem(html_original.read_text(encoding="utf-8"), 9.5, 14.5, True)]
        e += subsecao("Execução da auditoria no VSCode")
        n_figura = proxima("figura")
        contador["figura"] += 1
        e += [
            p(md("A página foi servida localmente e auditada no terminal integrado do VSCode. Os comandos ficam no "
                 "`package.json` e foram repetidos em `.vscode/tasks.json`, para que também possam ser executados "
                 "pelo menu *Terminal > Run Task*:")),
            listagem(COMANDOS, 10, 16, False),
            *figura(print_terminal, f"A Figura {n_figura} mostra a execução no terminal do VSCode.",
                    f"Figura {n_figura}: Execução do {'axe CLI' if eh_axe else 'Lighthouse'} e do parser no terminal "
                    "do VSCode"),
        ]
        e += subsecao("Script ", "parser_acessibilidade.py")
        requisitos = [
            ("1. Leitura de dados", "`carregar_auditoria`",
             "Abre o `resultado_axe.json` (ou o JSON do Lighthouse) e identifica a ferramenta"),
            ("2. Extração de falhas", "`extrair_axe`, `extrair_lighthouse`",
             "Lê a lista `violations` do axe ou as auditorias reprovadas do Lighthouse"),
            ("3. Categorização", "`por_severidade`, `ordenar`",
             "Agrupa pelo campo `impact` (*critical*, *serious*, *moderate* e *minor*) e prioriza"),
            ("4. Mapeamento de elementos", "`formatar_seletor`, `Violacao.criterios`",
             "Lista os seletores CSS de `nodes[].target` e converte as tags do axe (ex.: `wcag111` e `wcag2a`) "
             "no critério “1.1.1 (nível A)”"),
            ("5. Relatório final", "`imprimir_resumo`, `gerar_pdf`",
             "Mostra o resumo no terminal e gera este relatório em PDF"),
        ]
        dados = [["Requisito", "Funções", "O que faz"]]
        dados += [[p(md(a), celula), p(md(b), celula), p(md(c), celula)] for a, b, c in requisitos]
        e.append(p("O script atende aos cinco requisitos do roteiro: leitura dos dados, extração das falhas, "
                   "categorização por severidade, mapeamento dos elementos e relatório final."))
        e += tabela_com_legenda(f"A Tabela {proxima('tabela')} relaciona cada requisito às funções que o implementam.",
                                "Requisitos e funções do `parser_acessibilidade.py`",
                                tabela(dados, [118, 150, LARGURA_TEXTO - 268]))
        e.append(p(md("Regras que o axe marca como `best-practice` não correspondem a um critério WCAG e aparecem "
                      "como “boa prática”. Os textos das regras saem em português, com a tradução oficial do "
                      "axe-core (`locales/pt_BR.json`), e o mesmo script também aceita o JSON do Lighthouse.")))

        # 3 Diagnóstico
        e += secao("Diagnóstico")
        dados = [["Severidade", "Regras", "Elementos"]]
        dados += [[sev, str(len(grupos.get(sev, []))), str(sum(len(v.elementos) for v in grupos.get(sev, [])))]
                  for sev in SEVERIDADES]
        dados.append(["Total", str(n), str(m)])
        e += tabela_com_legenda(f"A auditoria da página original encontrou {qtd(n, 'regra violada', 'regras violadas')} "
                                f"em {qtd(m, 'elemento', 'elementos')}. A Tabela {proxima('tabela')} resume as falhas "
                                "por severidade.",
                                "Violações por severidade",
                                tabela(dados, [110, 70, 80], tamanho=12, total=True, centro=(1, 2)))
        dados = [["Regra", "Severidade", "WCAG 2.1", "Elementos", "Problema"]]
        for v in auditoria.violacoes:
            seletores = [el.seletor for el in v.elementos]
            if len(seletores) <= 3:
                elementos = ", ".join(codigo(s, 8.5) for s in seletores)
            else:
                elementos = f"{len(seletores)} elementos ({', '.join(codigo(s, 8.5) for s in seletores[:2])}, …)"
            wcag = f"{', '.join(v.criterios)} ({v.nivel})" if v.criterios else "boa prática"
            dados.append([p(escape(v.regra), celula), p(v.impacto, celula_centro), p(wcag, celula_centro),
                          p(elementos, celula), p(escape(v.ajuda), celula)])
        if not auditoria.violacoes:
            dados.append(["-", "-", "-", "-", "Nenhuma violação encontrada"])
        e += tabela_com_legenda(f"A Tabela {proxima('tabela')} detalha cada regra, o critério WCAG 2.1 correspondente "
                                "e os elementos afetados.",
                                "Violações encontradas e critérios WCAG 2.1",
                                tabela(dados, [118, 54, 60, 114, LARGURA_TEXTO - 346]))
        e += [p(md("A saída completa do `parser_acessibilidade.py` no terminal foi:")),
              listagem(saida_terminal(auditoria), 8.5, 11.5, False)]

        # 4 Correções
        if comparacao is not None or html_corrigido is not None:
            e += secao("Correções")
            correcoes: dict[str, list[str]] = {}
            for v in auditoria.violacoes:
                correcoes.setdefault(CORRECOES.get(v.regra, v.remediacao), []).append(v.regra)
            dados = [["Regra", "Correção"]]
            dados += [[p(escape(juntar(regras)), celula), p(md(texto), celula)] for texto, regras in correcoes.items()]
            e += tabela_com_legenda(f"A Tabela {proxima('tabela')} apresenta a correção aplicada para cada regra "
                                    "violada.", "Correções aplicadas", tabela(dados, [130, LARGURA_TEXTO - 130]))
            if html_corrigido is not None:
                e += [p(md(f"{AJUSTES_MANUAIS} O código HTML corrigido (`{html_corrigido.name}`) ficou assim:")),
                      listagem(html_corrigido.read_text(encoding="utf-8"), 9.5, 14.5, True)]
            if comparacao is not None:
                restantes = len(comparacao.violacoes)
                resultado = ("não encontrou violações" if not restantes
                             else f"encontrou {qtd(restantes, 'regra violada', 'regras violadas')}")
                e += [p(md(f"Uma nova auditoria (`npm run scan:corrigido`) {resultado}:")),
                      listagem(saida_terminal(comparacao), 8.5, 11.5, False)]

        # Conclusão
        e += secao("Conclusão")
        n_wcag = sum(1 for v in auditoria.violacoes if v.nivel != "Boa prática")
        texto = (f"A combinação do {cli}, executado no terminal do VSCode, com o `parser_acessibilidade.py` "
                 f"transformou o JSON da auditoria em um diagnóstico priorizado: "
                 f"{qtd(n, 'regra violada', 'regras violadas')} em {qtd(m, 'elemento', 'elementos')}")
        texto += f", sendo {qtd(criticas, 'regra crítica', 'regras críticas')}. " if criticas else ". "
        if n:
            outras = n - n_wcag
            if not n_wcag:
                texto += "Todas são boas práticas, sem critério WCAG associado. "
            else:
                texto += (f"Dessas, {n_wcag} {'corresponde' if n_wcag == 1 else 'correspondem'} a critérios WCAG 2.1 "
                          f"de nível A ou AA")
                texto += (f", e {'a outra é boa prática' if outras == 1 else f'as outras {outras} são boas práticas'}. "
                          if outras else ". ")
        if comparacao is not None:
            if comparacao.violacoes:
                texto += (f"Depois das correções, restaram "
                          f"{qtd(len(comparacao.violacoes), 'regra violada', 'regras violadas')}.")
            else:
                texto += (f"Depois das correções, a nova auditoria não encontrou violações, e as regras aprovadas "
                          f"passaram de {auditoria.total_aprovadas} para {comparacao.total_aprovadas}.")
        e += [p(md(texto)),
              p("Ferramentas automáticas detectam apenas parte dos problemas de acessibilidade"
                + (" (de 20% a 50%, segundo o aviso do próprio axe CLI)" if eh_axe else "")
                + ". Por isso, a auditoria automatizada deve ser complementada por testes manuais, como a navegação "
                  "só pelo teclado e o uso de leitores de tela, como o NVDA.")]
        return e

    # Duas passagens: a primeira só descobre em que página cai cada título, para o sumário.
    rascunho = novo_documento(io.BytesIO())
    rascunho.build(montar([]))
    novo_documento(str(destino)).build(montar(rascunho.secoes))


# ---------------------------------------------------------------------------
# Execução via linha de comando
# ---------------------------------------------------------------------------


def arquivo_html(informado: str | None, auditoria: Auditoria | None) -> Path | None:
    """Arquivo HTML para listar no PDF: o informado ou, sem ele, o arquivo local servido na URL
    auditada (ex.: http://localhost:8080/index.html -> index.html)."""
    if informado:
        caminho = Path(informado)
    elif auditoria is not None and (nome := Path(urlparse(auditoria.url).path).name):
        caminho = Path(nome)
    else:
        return None
    return caminho if caminho.is_file() else None


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Analisa o JSON do axe-core/Lighthouse e gera relatório de acessibilidade (WCAG 2.1 A/AA).")
    parser.add_argument("entrada", nargs="?", default="resultado_axe.json",
                        help="resultado_axe.json ou resultado_lighthouse.json (padrão: resultado_axe.json)")
    parser.add_argument("--pdf", default="relatorio_acessibilidade.pdf",
                        help="caminho do PDF de saída (padrão: relatorio_acessibilidade.pdf)")
    parser.add_argument("--sem-pdf", action="store_true", help="apenas imprime o resumo no terminal")
    parser.add_argument("--severidade", nargs="+", choices=SEVERIDADES,
                        help="filtra pelas severidades informadas")
    parser.add_argument("--somente-wcag", action="store_true",
                        help="ignora regras de boas práticas (mantém apenas critérios WCAG)")
    parser.add_argument("--comparar", help="JSON da varredura do HTML corrigido, para a tabela antes x depois")
    parser.add_argument("--html-original", help="HTML auditado, listado no PDF (padrão: o arquivo da URL auditada)")
    parser.add_argument("--html-corrigido", help="HTML corrigido, listado no PDF (padrão: o arquivo da URL do re-teste)")
    parser.add_argument("--print-terminal", default=str(PRINT_TERMINAL),
                        help=f"print do terminal do VSCode usado como Figura 1 (padrão: {PRINT_TERMINAL})")
    parser.add_argument("--github", help="URL do repositório do projeto no GitHub")
    parser.add_argument("--equipe", help='integrantes para a capa do PDF (ex.: "Ana e Bruno"); '
                                         'padrão: a equipe definida em DOCUMENTO')
    args = parser.parse_args(argv)

    traducoes = carregar_traducoes()

    def analisar(caminho: str) -> Auditoria:
        auditoria = traduzir(carregar_auditoria(Path(caminho)), traducoes)
        return filtrar(auditoria, args.severidade, args.somente_wcag)

    try:
        auditoria = analisar(args.entrada)
        comparacao = analisar(args.comparar) if args.comparar else None
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1

    imprimir_resumo(auditoria, comparacao)

    if not args.sem_pdf:
        html_original = arquivo_html(args.html_original, auditoria)
        html_corrigido = arquivo_html(args.html_corrigido, comparacao)
        for informado, html in ((args.html_original, html_original), (args.html_corrigido, html_corrigido)):
            if informado and html is None:
                print(f"Erro: arquivo não encontrado: {informado}", file=sys.stderr)
                return 1
        equipe = [nome.strip() for nome in re.split(r",|\s+e\s+", args.equipe) if nome.strip()] if args.equipe else None
        print_terminal = Path(args.print_terminal)
        if not args.github:
            print("Aviso: sem --github, o relatório sai sem o link do repositório.", file=sys.stderr)
        if not print_terminal.exists():
            print(f"Aviso: {print_terminal.as_posix()} não existe; a Figura 1 sai como pendente.", file=sys.stderr)
        try:
            gerar_pdf(auditoria, Path(args.pdf), comparacao, html_original, html_corrigido, args.github, equipe,
                      print_terminal)
        except PermissionError:
            print(f"Erro: não foi possível gravar {args.pdf}. Feche o PDF se ele estiver aberto e "
                  f"rode de novo.", file=sys.stderr)
            return 1
        print(f"\nRelatório PDF salvo em: {Path(args.pdf).resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
