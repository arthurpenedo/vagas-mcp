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


def test_listar_filtra_por_status(store):
    a = store.adicionar("A", "Cargo", hoje=D1)
    b = store.adicionar("B", "Cargo", hoje=D1)
    store.atualizar_status(a.id, "aplicada", hoje=D5)
    assert [v.empresa for v in store.listar()] == ["A", "B"]  # a mais recente em novidade vem primeiro
    assert [v.empresa for v in store.listar(status="aplicada")] == ["A"]
    assert [v.id for v in store.listar(status="encontrada")] == [b.id]


def test_paradas_conta_o_dia_limite_e_ignora_quem_nao_esta_aplicada(store):
    a = store.adicionar("A", "Cargo", hoje=D1)
    b = store.adicionar("B", "Cargo", hoje=D1)
    store.atualizar_status(a.id, "aplicada", hoje=D5)
    store.atualizar_status(b.id, "aplicada", hoje=D5)
    store.atualizar_status(b.id, "entrevista", hoje=D5)
    assert [v.empresa for v in store.paradas(dias=15, hoje=D20)] == ["A"]  # exatamente 15 dias já pede follow-up
    assert store.paradas(dias=16, hoje=D20) == []


def test_definir_descricao_grava_e_exige_vaga_existente(store):
    v = store.adicionar("A", "Cargo", hoje=D1)
    assert store.definir_descricao(v.id, "Python e SQL").descricao == "Python e SQL"
    with pytest.raises(KeyError):
        store.definir_descricao(99, "texto")


def test_mcp_server_exposes_tools_and_calls_store(store):
    server = build_server(store)

    async def run():
        names = {t.name for t in await server.list_tools()}
        result = await server.call_tool("registrar_vaga", {"empresa": "Empresa Z", "cargo": "Dev IA"})
        funil = await server.call_tool("resumo_do_funil", {})
        return names, result, funil

    names, result, funil = asyncio.run(run())
    assert names == {"registrar_vaga", "listar_vagas", "atualizar_status", "salvar_descricao", "resumo_do_funil",
                     "vagas_paradas", "analisar_aderencia", "sincronizar_notion"}
    assert not result.is_error
    assert json.loads(result.content[0].text)["empresa"] == "Empresa Z"
    assert json.loads(funil.content[0].text)["total"] == 1


def test_business_errors_reach_the_model(store):
    from mcp.client import Client

    async def run():
        async with Client(build_server(store)) as server:
            return await _dup_e_inexistente(server)

    async def _dup_e_inexistente(server):
        await server.call_tool("registrar_vaga", {"empresa": "A", "cargo": "C", "link": "https://x/1"})
        dup = await server.call_tool("registrar_vaga", {"empresa": "B", "cargo": "C", "link": "https://x/1"})
        inexistente = await server.call_tool("atualizar_status", {"vaga_id": 42, "status": "aplicada"})
        return dup, inexistente

    dup, inexistente = asyncio.run(run())
    assert dup.is_error and "Já existe uma vaga com este link" in dup.content[0].text
    assert inexistente.is_error and "Vaga 42 não encontrada" in inexistente.content[0].text
