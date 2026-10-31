# Auditoria de Acessibilidade Web — Portal TechInclusiva

Trabalho Prático II — Qualidade e Teste de Software (UniSENAI)
Ferramentas: **VSCode**, **axe-core CLI** e **Python**. Meta: conformidade **WCAG 2.1 nível AA**.
Repositório: https://github.com/PedroCarvalh0/trabalho-2-qa

## Estrutura

| Arquivo | Descrição |
|---|---|
| `index.html` | Página original do portal, com barreiras de acessibilidade |
| `index_corrigido.html` | Página corrigida (cada correção comentada com a regra axe e o critério WCAG) |
| `resultado_axe.json` | Saída do axe CLI para `index.html` (**entregável 2**) |
| `resultado_axe_corrigido.json` | Saída do axe CLI para `index_corrigido.html` (re-teste) |
| `parser_acessibilidade.py` | Script Python documentado que lê o JSON e gera a análise (**entregável 3**) |
| `relatorio_acessibilidade.pdf` | Relatório gerado pelo script, no formato de entrega do trabalho (**entregável 4**) |
| `evidencias/terminal_vscode.png` | Print do terminal do VSCode, usado como Figura 1 do relatório (você salva aqui) |
| `assets/logo_senai.png` | Logo da capa do relatório |
| `package.json` | Scripts npm que executam o axe CLI no terminal do VSCode (**entregável 1**) |
| `baixar_chromedriver.ps1` | Baixa o ChromeDriver compatível com o Chrome instalado |
| `.vscode/` | Extensões recomendadas e tarefas (Terminal > Run Task) |

## Pré-requisitos

- Windows, Node.js LTS, Python 3.10+ e Google Chrome (os scripts usam `chromedriver.exe` e PowerShell)
- Extensões do VSCode (sugeridas automaticamente): axe Accessibility Linter, Live Server, Python

## Como executar (terminal do VSCode)

```powershell
# 1. Dependências
npm install
py -m venv .venv              # ou: python -m venv .venv
.\.venv\Scripts\Activate.ps1  # repita em cada terminal novo (o VSCode faz isso sozinho
                              # quando o interpretador .venv está selecionado)
pip install -r requirements.txt

# 2. ChromeDriver compatível com o seu Chrome (o axe CLI usa o Chrome headless)
npm run driver

# 3. Servidor local (deixe rodando em outro terminal, com o .venv ativado)
python -m http.server 8080

# 4. Varredura com o axe CLI -> resultado_axe.json
npm run scan
npm run scan:corrigido

# 5. Print do terminal do VSCode (Figura 1 do relatório) -> evidencias/terminal_vscode.png

# 6. Análise em Python -> resumo no terminal + relatorio_acessibilidade.pdf
npm run relatorio

# Versão de entrega do PDF, com o link do repositório na introdução
python parser_acessibilidade.py resultado_axe.json --comparar resultado_axe_corrigido.json `
  --html-original index.html --html-corrigido index_corrigido.html --github https://github.com/<usuario>/<repo>
```

## Formato do relatório

O PDF segue o formato de entrega do trabalho:
- **Abertura:** capa com o logo e a equipe, seguida do sumário (página "i").
- **1 Introdução:** contexto do problema e objetivos.
- **2 Método:** ferramentas usadas, código da página de teste, comandos e print do terminal do VSCode, e uma tabela que relaciona os requisitos às funções do script.
- **3 Diagnóstico:** tabelas por severidade e por regra, com critério WCAG e elementos afetados, mais a saída completa do script no terminal.
- **4 Correções:** tabela de correções, código HTML corrigido e o resultado da nova auditoria.
- **5 Conclusão.**

Os dados da capa (equipe, curso, título, disciplina e professor) ficam no dicionário `DOCUMENTO`, na seção de PDF do script. A opção `--equipe "Ana e Bruno"` substitui só a equipe. Sem o print em `evidencias/terminal_vscode.png`, a Figura 1 sai como um quadro "pendente", e o script avisa no terminal.

## O script Python

`parser_acessibilidade.py` atende aos 5 requisitos do roteiro:

1. **Leitura de dados** — carrega `resultado_axe.json` ou `resultado_lighthouse.json` (detecta a ferramenta automaticamente).
2. **Extração de falhas** — violações do axe ou auditorias reprovadas do Lighthouse.
3. **Categorização** — agrupa por severidade (`critical`, `serious`, `moderate`, `minor`) e prioriza.
4. **Mapeamento de elementos** — lista seletores CSS e trechos HTML afetados por regra, e mapeia cada regra para os critérios WCAG 2.1 (A/AA).
5. **Relatório final** — resumo no terminal e PDF com diagnóstico, mapeamento WCAG, comparação antes × depois e o código HTML corrigido.

Os textos das regras saem em português, usando a tradução oficial do axe-core (`node_modules/axe-core/locales/pt_BR.json`). Sem o `npm install`, o script continua funcionando, mas com esses textos em inglês.

Opções úteis:

```powershell
python parser_acessibilidade.py resultado_axe.json --sem-pdf                     # só terminal
python parser_acessibilidade.py resultado_axe.json --severidade critical serious # filtra severidade
python parser_acessibilidade.py resultado_axe.json --somente-wcag                # ignora boas práticas
python parser_acessibilidade.py resultado_axe.json --equipe "Ana e Bruno"        # outra equipe na capa
python parser_acessibilidade.py resultado_axe.json --github https://github.com/<usuario>/<repo>
```

## Resultado da auditoria

| Indicador | Antes | Depois |
|---|---|---|
| Regras violadas | 22 | 0 |
| Elementos afetados | 58 | 0 |
| Críticas | 6 | 0 |
| Graves | 10 | 0 |
| Moderadas | 5 | 0 |
| Leves | 1 | 0 |

Além do que o axe aponta, a versão corrigida trata pontos que só aparecem em verificação manual:
link "Pular para o conteúdo principal" (WCAG 2.4.1), indicador de foco com contraste mínimo de 3:1
(WCAG 2.4.7 / 1.4.11) e separadores visuais ocultos para leitores de tela.

> Ferramentas automáticas detectam apenas parte das barreiras (20%–50%). Complemente com testes manuais:
> navegação só por teclado, leitor de tela (NVDA) e zoom de 200%.
