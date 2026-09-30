import asyncio
import json
import sqlite3
from datetime import date

import httpx
import pytest

from vagas_mcp import VagaStore
from vagas_mcp.notion import NotionError, NotionSync
from vagas_mcp.server import build_server

D1, D5, D12 = date(2026, 9, 1), date(2026, 9, 5), date(2026, 9, 12)

# Sem "Nível" e sem a opção "Teste técnico", como pode acontecer num banco criado à mão.
SCHEMA_NOTION = {
    "Vaga": {"type": "title"}, "Empresa": {"type": "rich_text"}, "Plataforma": {"type": "select"},
    "Modelo": {"type": "select"}, "Link": {"type": "url"}, "Data": {"type": "date"}, "Notas": {"type": "rich_text"},
    "Status": {"type": "status", "status": {"options": [
        {"name": n} for n in ("Encontrada", "Aplicada", "Entrevista", "Recusada", "Oferta")]}},
}


class FakeNotion:
    """Imita a API do Notion o suficiente para o upsert: schema, query por link, criar e atualizar página."""

    def __init__(self, existentes=None):
        self.paginas = dict(existentes or {})  # page_id -> properties

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        if request.method == "GET" and path == "/v1/databases/db1":
            return httpx.Response(200, json={"properties": SCHEMA_NOTION})
        if path == "/v1/databases/db1/query":
            link = body["filter"]["url"]["equals"]
            achadas = [pid for pid, p in self.paginas.items() if p.get("Link", {}).get("url") == link]
            return httpx.Response(200, json={"results": [{"id": pid} for pid in achadas]})
        if request.method == "POST" and path == "/v1/pages":
            pid = f"p{len(self.paginas) + 1}"
            self.paginas[pid] = body["properties"]
            return httpx.Response(200, json={"id": pid})
        if request.method == "PATCH" and path.startswith("/v1/pages/"):
            pid = path.rsplit("/", 1)[1]
            if pid not in self.paginas:
                return httpx.Response(404, json={"message": "Could not find page"})
            self.paginas[pid].update(body["properties"])
            return httpx.Response(200, json={"id": pid})
        return httpx.Response(400, json={"message": f"rota inesperada {path}"})


def sync_com(fake):
    return NotionSync("tok", "db1", client=httpx.Client(transport=httpx.MockTransport(fake)))


@pytest.fixture
def store():
    s = VagaStore()
    s.adicionar("Empresa A", "Analista de IA", link="https://x/a", plataforma="Gupy", modelo="remoto",
                nivel="Júnior", hoje=D1)
    s.adicionar("Empresa B", "Dev Python", link="https://x/b", hoje=D1)
    s.atualizar_status(1, "aplicada", nota="via Gupy", hoje=D5)
    return s


def test_notion_creates_then_updates_without_duplicates(store):
    fake = FakeNotion(existentes={"manual": {"Link": {"url": "https://x/b"}}})  # B já foi cadastrada à mão
    res = sync_com(fake).sincronizar(store)
    assert (res.criadas, res.atualizadas) == (1, 1)
    assert set(fake.paginas) == {"manual", "p2"}
    a = fake.paginas["p2"]
    assert a["Vaga"]["title"][0]["text"]["content"] == "Analista de IA"
    assert a["Status"] == {"status": {"name": "Aplicada"}}
    assert a["Modelo"] == {"select": {"name": "Remoto"}}
    assert a["Data"] == {"date": {"start": "2026-09-05"}}
    assert any("Nível" in aviso for aviso in res.avisos)
    assert store.obter(1).notion_id == "p2" and store.obter(2).notion_id == "manual"

    store.atualizar_status(1, "entrevista", hoje=D12)
    res2 = sync_com(fake).sincronizar(store)
    assert (res2.criadas, res2.atualizadas) == (0, 2)
    assert fake.paginas["p2"]["Status"] == {"status": {"name": "Entrevista"}}


def test_notion_skips_status_option_that_does_not_exist(store):
    store.atualizar_status(1, "teste_tecnico", hoje=D12)
    fake = FakeNotion()
    res = sync_com(fake).sincronizar(store)
    pagina_a = next(p for p in fake.paginas.values() if p["Link"]["url"] == "https://x/a")
    assert "Status" not in pagina_a
    assert any("Teste técnico" in aviso for aviso in res.avisos)


def test_notion_errors_are_readable(store, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    with pytest.raises(NotionError, match="NOTION_TOKEN"):
        NotionSync.from_env()
    store.vincular_notion(1, "apagada")
    with pytest.raises(NotionError, match="404: Could not find page"):
        sync_com(FakeNotion()).sincronizar(store)


def test_weekly_report(store):
    store.adicionar("Empresa C", "Cientista de Dados", hoje=D12)
    rel = store.relatorio_semanal(hoje=D12)
    assert "semana de 2026-09-06 a 2026-09-12" in rel
    assert "Empresa C (Cientista de Dados) → encontrada" in rel
    assert "Empresa A" not in rel.split("Follow-ups")[1]  # aplicada há só 7 dias
    assert "Empresa A" in store.relatorio_semanal(hoje=date(2026, 9, 16)).split("Follow-ups")[1]


def test_old_database_gets_new_columns(tmp_path):
    db = tmp_path / "v01.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE vagas (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa TEXT NOT NULL, cargo TEXT NOT NULL,"
        " link TEXT, plataforma TEXT, modelo TEXT, nivel TEXT, status TEXT NOT NULL DEFAULT 'encontrada',"
        " data_status TEXT NOT NULL, notas TEXT DEFAULT '');"
        "INSERT INTO vagas (empresa, cargo, data_status) VALUES ('Antiga', 'Cargo', '2026-08-01');"
    )
    conn.commit()
    conn.close()
    store = VagaStore(db)
    assert store.obter(1).empresa == "Antiga" and store.obter(1).descricao == ""
    assert store.definir_descricao(1, "Requisitos: Python").descricao == "Requisitos: Python"


def test_resource_prompt_and_ats_integration(store, tmp_path):
    pytest.importorskip("ats_match")
    from mcp.client import Client
    curriculo = tmp_path / "cv.md"
    curriculo.write_text("Experiência com Python, SQL e LLMs em pipelines de atendimento.", encoding="utf-8")
    store.definir_descricao(1, "Requisitos:\n- Python\n- SQL\n- Docker\n\nDiferenciais:\n- AWS")

    async def run():
        async with Client(build_server(store)) as server:
            recursos = [str(r.uri) for r in (await server.list_resources()).resources]
            conteudo = (await server.read_resource("vagas://relatorio-semanal")).contents
            prompt = await server.get_prompt("revisao_semanal")
            args = {"curriculo_arquivo": str(curriculo)}
            sem_desc = await server.call_tool("analisar_aderencia", {"vaga_id": 2, **args})
            ader = await server.call_tool("analisar_aderencia", {"vaga_id": 1, **args})
            return recursos, conteudo, prompt, sem_desc, ader

    recursos, conteudo, prompt, sem_desc, ader = asyncio.run(run())
    assert recursos == ["vagas://relatorio-semanal"]
    assert "# Busca de emprego" in conteudo[0].text
    assert "revisão semanal" in prompt.messages[0].content.text
    assert sem_desc.is_error and "salvar_descricao" in sem_desc.content[0].text
    rel = json.loads(ader.content[0].text)
    assert rel["vaga"] == "Analista de IA · Empresa A"
    assert "docker" in [s.lower() for s in rel["missing_required"]]
    assert 0 <= rel["score"] <= 100
