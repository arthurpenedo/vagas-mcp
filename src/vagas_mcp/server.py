"""Servidor MCP: expõe o controle de candidaturas como ferramentas para o Claude.

Rodar (stdio, para Claude Desktop / Claude Code):  vagas-mcp
Banco: arquivo definido em VAGAS_DB (padrão: ~/.vagas-mcp/vagas.sqlite3)

Expõe os três tipos de primitiva do MCP:
- tools: registrar, listar, mover no funil, métricas, follow-ups, aderência, Notion;
- resource `vagas://relatorio-semanal`: o resumo da semana em Markdown, para anexar à conversa;
- prompt `revisao_semanal`: roteiro pronto para o Claude revisar a busca e sugerir próximos passos.
"""

import functools
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from .store import VagaStore

INSTRUCTIONS = """Ferramentas para organizar uma busca de emprego.
Fluxo típico: registrar_vaga quando o usuário encontra uma vaga (guarde a descrição, se ele colar);
atualizar_status a cada avanço; resumo_do_funil para mostrar como a busca está indo; vagas_paradas
para sugerir follow-ups; analisar_aderencia para comparar o currículo com a vaga antes de aplicar.
Nunca registre dados pessoais sensíveis (CPF, senhas) nas notas."""


def default_db() -> Path:
    path = Path(os.getenv("VAGAS_DB", Path.home() / ".vagas-mcp" / "vagas.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _mensagem_ao_modelo(fn):
    """Erros de regra de negócio viram ToolError, cuja mensagem chega ao modelo.

    O SDK esconde o texto de exceções comuns (trata como falha interna); sem isto, o Claude
    receberia "Error executing tool" em vez de "Já existe uma vaga com este link" e não saberia corrigir.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, KeyError, RuntimeError) as exc:
            raise ToolError(str(exc.args[0]) if exc.args else str(exc)) from exc
    return wrapper


def build_server(store: VagaStore) -> MCPServer:
    server = MCPServer("vagas-mcp", instructions=INSTRUCTIONS, version=__version__)
    tool = server.tool

    def ferramenta():
        return lambda fn: tool()(_mensagem_ao_modelo(fn))

    @ferramenta()
    def registrar_vaga(empresa: str, cargo: str, link: str | None = None, plataforma: str | None = None,
                       modelo: str | None = None, nivel: str | None = None, notas: str = "",
                       descricao: str = "") -> dict:
        """Registra uma vaga encontrada. modelo: remoto | hibrido | presencial. plataforma: ex. Gupy, LinkedIn.
        descricao: texto do anúncio (opcional), usado depois por analisar_aderencia."""
        return store.adicionar(empresa, cargo, link, plataforma, modelo, nivel, notas, descricao).to_dict()

    @ferramenta()
    def listar_vagas(status: str | None = None, empresa: str | None = None) -> list[dict]:
        """Lista vagas, opcionalmente filtrando por status (encontrada, aplicada, entrevista, teste_tecnico,
        oferta, recusada, desisti) ou por parte do nome da empresa."""
        return [v.to_dict() for v in store.listar(status, empresa)]

    @ferramenta()
    def atualizar_status(vaga_id: int, status: str, nota: str | None = None) -> dict:
        """Muda o status de uma vaga (encontrada, aplicada, entrevista, teste_tecnico, oferta, recusada, desisti)
        e registra uma nota opcional com a data."""
        return store.atualizar_status(vaga_id, status, nota).to_dict()

    @ferramenta()
    def salvar_descricao(vaga_id: int, descricao: str) -> dict:
        """Guarda (ou substitui) o texto do anúncio de uma vaga já registrada."""
        return store.definir_descricao(vaga_id, descricao).to_dict()

    @ferramenta()
    def resumo_do_funil() -> dict:
        """Totais por status e taxas de conversão do funil aplicada -> entrevista -> teste técnico -> oferta."""
        return store.funil()

    @ferramenta()
    def vagas_paradas(dias: int = 10) -> list[dict]:
        """Candidaturas com status 'aplicada' sem novidade há pelo menos `dias` dias (candidatas a follow-up)."""
        return [v.to_dict() for v in store.paradas(dias)]

    @ferramenta()
    def analisar_aderencia(vaga_id: int, curriculo_arquivo: str) -> dict:
        """Compara um currículo (caminho de um .pdf, .docx, .md ou .txt local) com a descrição da vaga,
        como um ATS faria: nota 0-100, habilidades que faltam e dicas. Usa o projeto ats-match."""
        vaga = store.obter(vaga_id)
        if not vaga.descricao.strip():
            raise ValueError("Esta vaga não tem descrição salva. Use salvar_descricao com o texto do anúncio.")
        try:
            from ats_match.extract import read_file
            from ats_match.matcher import analyze
        except ImportError as exc:
            raise RuntimeError('Instale a integração: pip install "vagas-mcp[ats]"') from exc
        report = analyze(read_file(curriculo_arquivo), vaga.descricao)
        return {"vaga": f"{vaga.cargo} · {vaga.empresa}", **report.model_dump()}

    @ferramenta()
    def sincronizar_notion() -> dict:
        """Envia todas as vagas para o banco do Notion configurado (cria as novas, atualiza as existentes)."""
        from .notion import NotionSync

        return NotionSync.from_env().sincronizar(store).to_dict()

    @server.resource("vagas://relatorio-semanal", name="relatorio_semanal", mime_type="text/markdown",
                     description="Resumo dos últimos 7 dias: movimentações, funil e follow-ups pendentes.")
    def relatorio_semanal() -> str:
        return store.relatorio_semanal()

    @server.prompt(title="Revisão semanal da busca de emprego")
    def revisao_semanal() -> str:
        """Pede ao Claude uma revisão da semana com próximos passos concretos."""
        return (
            "Faça a revisão semanal da minha busca de emprego.\n\n"
            f"{store.relatorio_semanal()}\n\n"
            "Com base nisso: (1) diga em 2 frases como a busca está indo, citando as taxas do funil; "
            "(2) liste os follow-ups que devo mandar esta semana, com uma mensagem curta para cada; "
            "(3) sugira uma mudança de estratégia se a conversão aplicada→entrevista estiver abaixo de 15%."
        )

    return server


def main() -> None:
    build_server(VagaStore(default_db())).run("stdio")


if __name__ == "__main__":
    main()
