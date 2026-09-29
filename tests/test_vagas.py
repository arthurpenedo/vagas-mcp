import asyncio
import json
from datetime import date

import pytest

from vagas_mcp import VagaStore
from vagas_mcp.server import build_server

D1, D5, D20 = date(2026, 9, 1), date(2026, 9, 5), date(2026, 9, 20)


@pytest.fixture
def store():
    return VagaStore()


def test_add_and_list(store):
    v = store.adicionar("Empresa A", "Analista de IA Jr", link="https://x/1", modelo="remoto", hoje=D1)
    assert v.id == 1 and v.status == "encontrada"
    assert [x.empresa for x in store.listar(empresa="empresa")] == ["Empresa A"]


def test_duplicate_link_and_invalid_values_rejected(store):
    store.adicionar("A", "Cargo", link="https://x/1")
    with pytest.raises(ValueError, match="Já existe"):
        store.adicionar("B", "Cargo", link="https://x/1")
    with pytest.raises(ValueError):
        store.adicionar("C", "Cargo", modelo="marte")
    with pytest.raises(ValueError):
        store.atualizar_status(1, "contratado_ontem")
    with pytest.raises(KeyError):
        store.obter(99)


def test_status_update_appends_dated_note(store):
    store.adicionar("A", "Cargo", hoje=D1)
    v = store.atualizar_status(1, "aplicada", nota="Enviei pela Gupy", hoje=D5)
    assert v.status == "aplicada" and v.data_status == "2026-09-05"
    assert v.notas == "[2026-09-05] Enviei pela Gupy"


def test_funnel_counts_history_not_just_current_status(store):
    for i in range(4):
        store.adicionar(f"E{i}", "Cargo", hoje=D1)
        store.atualizar_status(i + 1, "aplicada", hoje=D1)
    store.atualizar_status(1, "entrevista", hoje=D5)
    store.atualizar_status(1, "recusada", hoje=D20)  # passou por entrevista, depois recusada
    store.atualizar_status(2, "entrevista", hoje=D5)
    funil = store.funil()
    assert funil["alcancaram"] == {"aplicada": 4, "entrevista": 2, "teste_tecnico": 0, "oferta": 0}
    assert funil["conversao"]["aplicada->entrevista"] == 0.5
    assert funil["conversao"]["teste_tecnico->oferta"] is None


def test_stalled_applications(store):
    store.adicionar("A", "Cargo", hoje=D1)
    store.atualizar_status(1, "aplicada", hoje=D1)
    store.adicionar("B", "Cargo", hoje=D1)
    store.atualizar_status(2, "aplicada", hoje=D20)
    assert [v.empresa for v in store.paradas(dias=10, hoje=D20)] == ["A"]


def test_mcp_server_exposes_tools_and_calls_store(store):
    server = build_server(store)

    async def run():
        names = {t.name for t in await server.list_tools()}
        result = await server.call_tool("registrar_vaga", {"empresa": "Empresa Z", "cargo": "Dev IA"})
        funil = await server.call_tool("resumo_do_funil", {})
        return names, result, funil

    names, result, funil = asyncio.run(run())
    assert names == {"registrar_vaga", "listar_vagas", "atualizar_status", "resumo_do_funil", "vagas_paradas"}
    assert not result.is_error
    assert json.loads(result.content[0].text)["empresa"] == "Empresa Z"
    assert json.loads(funil.content[0].text)["total"] == 1
