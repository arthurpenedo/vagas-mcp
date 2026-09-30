"""Demonstração ponta a ponta: sobe o vagas-mcp como subprocesso (stdio, como o Claude Desktop faz),
conversa com ele por um cliente MCP de verdade e gera uma página HTML com cada chamada e a resposta real.

    python scripts/demo.py site/index.html

As falas do usuário são ilustrativas (é o Claude quem escolheria as ferramentas numa conversa real);
as chamadas e as respostas são as do servidor. Empresas e vagas são fictícias.
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from html import escape
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client import Client

from vagas_mcp import VagaStore

VAGA_DESCRICAO = """Analista de IA Júnior
Requisitos:
- Python e SQL
- Experiência com LLMs e engenharia de prompt
- Git
Diferenciais:
- AWS
- Docker"""

CURRICULO = """Engenheiro da Computação (formando). Experiência em pipelines de IA para atendimento:
engenharia de prompt, testes de prompt e monitoramento de qualidade com LLMs.
Ferramentas: Python, SQL, AWS Athena, Power Automate, Git."""


def semear(db: Path, hoje: date) -> None:
    """Três semanas de busca simuladas, com datas relativas a hoje."""
    s = VagaStore(db)
    d = lambda n: hoje - timedelta(days=n)  # noqa: E731
    vagas = [
        ("Acme Pagamentos", "Analista de IA Jr", "Gupy", "remoto", [("aplicada", 20), ("entrevista", 12), ("teste_tecnico", 6)]),
        ("Orbital Seguros", "Analista de Automação", "LinkedIn", "hibrido", [("aplicada", 18), ("entrevista", 9), ("recusada", 3)]),
        ("Pixel Varejo", "Cientista de Dados Jr", "Gupy", "remoto", [("aplicada", 16)]),
        ("Vértice Saúde", "Engenheiro de Prompt", "site próprio", "remoto", [("aplicada", 13)]),
        ("Loja Modelo", "Analista de Dados", "Gupy", "presencial", [("aplicada", 8), ("entrevista", 2)]),
        ("Nuvem Clara", "Assistente de IA Generativa", "LinkedIn", "hibrido", [("aplicada", 4)]),
        ("Banco Exemplo", "Analista de Atendimento e IA", "Greenhouse", "hibrido", [("aplicada", 2)]),
    ]
    for i, (empresa, cargo, plataforma, modelo, passos) in enumerate(vagas, start=1):
        s.adicionar(empresa, cargo, link=f"https://exemplo.com/vaga/{i}", plataforma=plataforma,
                    modelo=modelo, nivel="Júnior", hoje=d(passos[0][1] + 1))
        for status, dias in passos:
            s.atualizar_status(i, status, hoje=d(dias))
    s.close()


ROTEIRO = [
    ("Achei uma vaga de Analista de IA Jr na Estrela Tech, remota, pela Gupy. Guarda pra mim com a descrição.",
     "registrar_vaga", {"empresa": "Estrela Tech", "cargo": "Analista de IA Jr", "plataforma": "Gupy",
                        "modelo": "remoto", "link": "https://exemplo.com/vaga/8", "descricao": VAGA_DESCRICAO}),
    ("Quão aderente meu currículo está a essa vaga?",
     "analisar_aderencia", {"vaga_id": 8, "curriculo_arquivo": "{curriculo}"}),
    ("Beleza, apliquei.", "atualizar_status", {"vaga_id": 8, "status": "aplicada", "nota": "Enviado pela Gupy"}),
    ("Registra de novo aquela da Estrela Tech.",
     "registrar_vaga", {"empresa": "Estrela Tech", "cargo": "Analista de IA Jr", "link": "https://exemplo.com/vaga/8"}),
    ("Como está meu funil?", "resumo_do_funil", {}),
    ("Quem eu preciso cobrar?", "vagas_paradas", {"dias": 10}),
]


async def sessao(db: Path, curriculo: Path) -> dict:
    params = StdioServerParameters(command=sys.executable, args=["-m", "vagas_mcp.server"],
                                   env={**os.environ, "VAGAS_DB": str(db)})
    passos = []
    async with Client(params) as c:
        info = {"servidor": f"{c.server_info.name} {c.server_info.version}",
                "ferramentas": [t.name for t in (await c.list_tools()).tools],
                "recursos": [str(r.uri) for r in (await c.list_resources()).resources],
                "prompts": [p.name for p in (await c.list_prompts()).prompts]}
        for fala, ferramenta, args in ROTEIRO:
            args = json.loads(json.dumps(args).replace("{curriculo}", curriculo.as_posix()))
            r = await c.call_tool(ferramenta, args)
            texto = r.content[0].text if r.content else ""
            try:
                resposta = json.loads(texto)
            except ValueError:
                resposta = texto
            if isinstance(resposta, dict) and "result" in resposta and len(resposta) == 1:
                resposta = resposta["result"]  # listas vêm embrulhadas em {"result": [...]}
            passos.append({"fala": fala, "ferramenta": ferramenta, "args": args,
                           "erro": r.is_error, "resposta": resposta})
        relatorio = (await c.read_resource("vagas://relatorio-semanal")).contents[0].text
    return {**info, "passos": passos, "relatorio": relatorio}


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e4e4e0;--accent:#6d4aff;
--accent-bg:#efeafe;--ok:#1f8a4c;--bad:#c2372e;--code:#f2f2ef}
@media (prefers-color-scheme:dark){:root{--bg:#131316;--card:#1c1c20;--fg:#ececf0;--muted:#9a9aa3;
--line:#2c2c33;--accent:#a08bff;--accent-bg:#2a2540;--ok:#4cc38a;--bad:#ff6b61;--code:#16161a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:900px;margin:0 auto;padding:32px 16px 64px}h1{font-size:26px;margin:0 0 4px}
h2{font-size:18px;margin:36px 0 12px}a{color:var(--accent)}.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{font:12px ui-monospace,Consolas,monospace;padding:2px 8px;
border-radius:999px;background:var(--accent-bg);color:var(--accent)}
.passo{margin-bottom:16px}.fala{margin:0 0 10px;padding:10px 14px;border-radius:14px 14px 14px 4px;
background:var(--accent-bg);display:inline-block;max-width:100%}
.call{font:13px ui-monospace,Consolas,monospace;color:var(--muted);margin-bottom:6px;overflow-wrap:anywhere}
.call b{color:var(--accent)}pre{margin:0;padding:10px 12px;background:var(--code);border-radius:8px;
font:12.5px/1.45 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto}
.erro{color:var(--bad);font-weight:600;font-size:13px;margin-bottom:6px}
.funil{display:grid;gap:8px}.etapa{display:grid;grid-template-columns:120px 1fr 48px;gap:10px;align-items:center}
.bar{height:14px;border-radius:7px;background:var(--accent-bg);overflow:hidden}.bar span{display:block;height:100%;background:var(--accent)}
.num{text-align:right;font-variant-numeric:tabular-nums}footer{margin-top:40px;font-size:13px}
"""


ROTULOS = {"aplicada": "aplicada", "entrevista": "entrevista", "teste_tecnico": "teste técnico", "oferta": "oferta"}


def _mostrar(chave: str, valor):
    if chave == "curriculo_arquivo":
        return Path(valor).name  # o caminho temporário não interessa a quem lê
    return valor if len(str(valor)) < 60 else str(valor)[:57] + "…"


def render(dados: dict) -> str:
    funil = next(p["resposta"] for p in dados["passos"] if p["ferramenta"] == "resumo_do_funil")
    maximo = max(funil["alcancaram"].values()) or 1
    etapas = "".join(
        f'<div class="etapa"><span>{escape(ROTULOS[e])}</span><div class="bar">'
        f'<span style="width:{n / maximo:.0%}"></span></div><span class="num">{n}</span></div>'
        for e, n in funil["alcancaram"].items()
    )
    taxas = " · ".join(f"{escape(' → '.join(ROTULOS[e] for e in k.split('->')))}: {v:.0%}"
                       for k, v in funil["conversao"].items() if v is not None)
    passos = []
    for p in dados["passos"]:
        args = ", ".join(f"{k}={json.dumps(_mostrar(k, v), ensure_ascii=False)}"
                         for k, v in p["args"].items())
        corpo = p["resposta"] if isinstance(p["resposta"], str) else json.dumps(p["resposta"], ensure_ascii=False, indent=2)
        erro = '<div class="erro">is_error: a mensagem volta para o Claude, que pode corrigir o pedido</div>' if p["erro"] else ""
        passos.append(f'<div class="passo"><p class="fala">{escape(p["fala"])}</p><div class="card">'
                      f'<div class="call">→ <b>{escape(p["ferramenta"])}</b>({escape(args)})</div>{erro}'
                      f"<pre>{escape(corpo)}</pre></div></div>")
    chips = lambda xs: "".join(f'<span class="chip">{escape(x)}</span>' for x in xs)  # noqa: E731
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>vagas-mcp · demonstração</title>
<style>{CSS}</style></head><body><main>
<h1>vagas-mcp: o Claude organizando uma busca de emprego</h1>
<p class="muted">Sessão real com o servidor MCP rodando por stdio, como no Claude Desktop. As chamadas e as respostas
abaixo foram geradas pelo servidor no CI; as falas são ilustrativas e as empresas, fictícias.
Código: <a href="https://github.com/arthurpenedo/vagas-mcp">github.com/arthurpenedo/vagas-mcp</a></p>

<h2>O que o servidor oferece ({escape(dados["servidor"])})</h2>
<div class="card"><p style="margin:0 0 8px"><strong>Ferramentas</strong></p><div class="chips">{chips(dados["ferramentas"])}</div>
<p style="margin:14px 0 8px"><strong>Resource</strong> e <strong>prompt</strong></p>
<div class="chips">{chips(dados["recursos"] + dados["prompts"])}</div></div>

<h2>Funil da busca</h2>
<div class="card"><div class="funil">{etapas}</div><p class="muted" style="margin:12px 0 0;font-size:13px">{taxas}.
Conta quem <em>alcançou</em> cada etapa pelo histórico: uma vaga recusada depois da entrevista conta como entrevista.</p></div>

<h2>A conversa</h2>
{"".join(passos)}

<h2>Resource <code>vagas://relatorio-semanal</code></h2>
<div class="card"><pre>{escape(dados["relatorio"])}</pre></div>

<footer class="muted">Gerado por <code>scripts/demo.py</code> em {date.today():%d/%m/%Y}. Feito por
<a href="https://github.com/arthurpenedo">Arthur Penedo</a>.</footer>
</main></body></html>"""


def main(saida: str = "site/index.html") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        db, curriculo = Path(tmp) / "demo.sqlite3", Path(tmp) / "curriculo.md"
        curriculo.write_text(CURRICULO, encoding="utf-8")
        semear(db, date.today())
        dados = asyncio.run(sessao(db, curriculo))
    destino = Path(saida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(render(dados), encoding="utf-8")
    return dados


if __name__ == "__main__":
    dados = main(*sys.argv[1:2])
    for p in dados["passos"]:
        print(f"{'✗' if p['erro'] else '✓'} {p['ferramenta']}")
