"""Servidor MCP: expõe o controle de candidaturas como ferramentas para o Claude.

Rodar (stdio, para Claude Desktop / Claude Code):  vagas-mcp
Banco: arquivo definido em VAGAS_DB (padrão: ~/.vagas-mcp/vagas.sqlite3)
"""

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .store import VagaStore

INSTRUCTIONS = """Ferramentas para organizar uma busca de emprego.
Fluxo típico: registrar_vaga quando o usuário encontra uma vaga; atualizar_status a cada avanço;
resumo_do_funil para mostrar como a busca está indo; vagas_paradas para sugerir follow-ups.
Nunca registre dados pessoais sensíveis (CPF, senhas) nas notas."""


def default_db() -> Path:
    path = Path(os.getenv("VAGAS_DB", Path.home() / ".vagas-mcp" / "vagas.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_server(store: VagaStore) -> MCPServer:
    server = MCPServer("vagas-mcp", instructions=INSTRUCTIONS, version="0.1.0")

    @server.tool()
    def registrar_vaga(empresa: str, cargo: str, link: str | None = None, plataforma: str | None = None,
                       modelo: str | None = None, nivel: str | None = None, notas: str = "") -> dict:
        """Registra uma vaga encontrada. modelo: remoto | hibrido | presencial. plataforma: ex. Gupy, LinkedIn."""
        return store.adicionar(empresa, cargo, link, plataforma, modelo, nivel, notas).to_dict()

    @server.tool()
    def listar_vagas(status: str | None = None, empresa: str | None = None) -> list[dict]:
        """Lista vagas, opcionalmente filtrando por status (encontrada, aplicada, entrevista, teste_tecnico,
        oferta, recusada, desisti) ou por parte do nome da empresa."""
        return [v.to_dict() for v in store.listar(status, empresa)]

    @server.tool()
    def atualizar_status(vaga_id: int, status: str, nota: str | None = None) -> dict:
        """Muda o status de uma vaga (encontrada, aplicada, entrevista, teste_tecnico, oferta, recusada, desisti)
        e registra uma nota opcional com a data."""
        return store.atualizar_status(vaga_id, status, nota).to_dict()

    @server.tool()
    def resumo_do_funil() -> dict:
        """Totais por status e taxas de conversão do funil aplicada -> entrevista -> teste técnico -> oferta."""
        return store.funil()

    @server.tool()
    def vagas_paradas(dias: int = 10) -> list[dict]:
        """Candidaturas com status 'aplicada' sem novidade há pelo menos `dias` dias (candidatas a follow-up)."""
        return [v.to_dict() for v in store.paradas(dias)]

    return server


def main() -> None:
    build_server(VagaStore(default_db())).run("stdio")


if __name__ == "__main__":
    main()
