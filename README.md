# vagas-mcp

[![CI](https://github.com/arthurpenedo/vagas-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/arthurpenedo/vagas-mcp/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![MCP](https://img.shields.io/badge/MCP-server-purple)
![License](https://img.shields.io/badge/license-MIT-green)

> **Servidor MCP** (Model Context Protocol) que dá ao Claude ferramentas para organizar uma busca de emprego: registrar vagas, acompanhar o status, medir o **funil de conversão** e lembrar dos **follow-ups**.

## O problema

Quem está buscando emprego aplica para dezenas de vagas em plataformas diferentes (Gupy, LinkedIn, sites próprios) e perde o controle: onde já apliquei? Quem não respondeu há duas semanas? Minha taxa de entrevista está boa?

Com o `vagas-mcp` conectado, dá para conversar com o Claude assim:

> "Registra a vaga de Analista de IA Jr da Empresa X que achei na Gupy, é remota."
> "Apliquei na vaga 3 hoje."
> "Como está meu funil?"
> "Quais candidaturas estão paradas há mais de 10 dias?"

E o Claude chama as ferramentas certas, com os dados guardados localmente em SQLite.

## Ferramentas expostas

| Ferramenta | O que faz |
|---|---|
| `registrar_vaga` | Cadastra uma vaga (empresa, cargo, link, plataforma, modelo, nível, notas). Bloqueia links duplicados. |
| `listar_vagas` | Lista com filtro por status ou por parte do nome da empresa. |
| `atualizar_status` | Move a vaga no funil (`encontrada → aplicada → entrevista → teste_tecnico → oferta`, ou `recusada`/`desisti`) e registra uma nota datada. |
| `resumo_do_funil` | Quantas vagas **alcançaram** cada etapa e as taxas de conversão entre etapas. |
| `vagas_paradas` | Candidaturas "aplicadas" sem novidade há N dias, que pedem follow-up. |

## Arquitetura

```
Claude Desktop / Claude Code ──(MCP, stdio)──► server.py (MCPServer: casca fina)
                                                     │
                                                     ▼
                                          store.py (regras + SQLite)
                                          tabelas: vagas, historico
```

### Decisões técnicas

- **Regra de negócio separada do protocolo.** `store.py` não sabe o que é MCP e é testado diretamente; `server.py` só traduz ferramentas em chamadas. Trocar de protocolo (API REST, CLI) não mexe na lógica.
- **Funil pelo histórico, não pelo status atual.** Uma vaga que chegou à entrevista e depois foi recusada **conta** como entrevista no funil. Olhar só o status atual subestimaria a conversão.
- **Local-first.** SQLite num arquivo do usuário, sem conta nem servidor externo. As instruções do servidor orientam o modelo a não registrar dados sensíveis.
- **MCP SDK 2.x** (`MCPServer`), com os testes chamando as ferramentas pelo próprio servidor (`list_tools` / `call_tool`).

## Como usar

```bash
git clone https://github.com/arthurpenedo/vagas-mcp && cd vagas-mcp
pip install -e ".[dev]"
pytest -q
```

**Claude Code:**

```bash
claude mcp add vagas -- vagas-mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "vagas": { "command": "vagas-mcp", "env": { "VAGAS_DB": "C:/Users/voce/vagas.sqlite3" } }
  }
}
```

O banco fica em `VAGAS_DB` (padrão: `~/.vagas-mcp/vagas.sqlite3`).

## Próximos passos

- [ ] Sincronização com um banco do Notion
- [ ] Ferramenta `analisar_vaga` integrada ao [ats-match](https://github.com/arthurpenedo/ats-match) (nota de aderência do currículo)
- [ ] Resource MCP com o relatório semanal da busca
- [ ] Vídeo de demonstração no Claude Desktop

---

Feito por [Arthur Penedo](https://github.com/arthurpenedo) · [LinkedIn](https://www.linkedin.com/in/arthuralves-penedo)
