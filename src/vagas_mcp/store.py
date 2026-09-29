"""Persistência das candidaturas em SQLite (um arquivo local, zero configuração).

Toda a regra de negócio fica aqui; o servidor MCP é só uma casca fina por cima.
Assim a lógica é testável sem subir servidor nenhum.
"""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

STATUS = ("encontrada", "aplicada", "entrevista", "teste_tecnico", "oferta", "recusada", "desisti")
# ordem do funil: quem chegou em "entrevista" também passou por "aplicada"
FUNIL = ("aplicada", "entrevista", "teste_tecnico", "oferta")
MODELOS = ("remoto", "hibrido", "presencial")

SCHEMA = """
CREATE TABLE IF NOT EXISTS vagas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa TEXT NOT NULL,
    cargo TEXT NOT NULL,
    link TEXT,
    plataforma TEXT,
    modelo TEXT,
    nivel TEXT,
    status TEXT NOT NULL DEFAULT 'encontrada',
    data_status TEXT NOT NULL,
    notas TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS historico (
    vaga_id INTEGER NOT NULL REFERENCES vagas(id),
    status TEXT NOT NULL,
    data TEXT NOT NULL
);
"""


@dataclass
class Vaga:
    id: int
    empresa: str
    cargo: str
    link: str | None
    plataforma: str | None
    modelo: str | None
    nivel: str | None
    status: str
    data_status: str
    notas: str

    def to_dict(self) -> dict:
        return asdict(self)


class VagaStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def adicionar(self, empresa: str, cargo: str, link: str | None = None, plataforma: str | None = None,
                  modelo: str | None = None, nivel: str | None = None, notas: str = "",
                  hoje: date | None = None) -> Vaga:
        if modelo and modelo not in MODELOS:
            raise ValueError(f"modelo deve ser um de {MODELOS}")
        if link and self._por_link(link):
            raise ValueError(f"Já existe uma vaga com este link (id {self._por_link(link)}).")
        dia = (hoje or date.today()).isoformat()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO vagas (empresa, cargo, link, plataforma, modelo, nivel, status, data_status, notas)"
                " VALUES (?, ?, ?, ?, ?, ?, 'encontrada', ?, ?)",
                (empresa.strip(), cargo.strip(), link, plataforma, modelo, nivel, dia, notas),
            )
            self.conn.execute("INSERT INTO historico VALUES (?, 'encontrada', ?)", (cur.lastrowid, dia))
        return self.obter(cur.lastrowid)

    def obter(self, vaga_id: int) -> Vaga:
        row = self.conn.execute("SELECT * FROM vagas WHERE id = ?", (vaga_id,)).fetchone()
        if row is None:
            raise KeyError(f"Vaga {vaga_id} não encontrada.")
        return Vaga(**dict(row))

    def listar(self, status: str | None = None, empresa: str | None = None) -> list[Vaga]:
        sql, params = "SELECT * FROM vagas WHERE 1=1", []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if empresa:
            sql += " AND lower(empresa) LIKE ?"
            params.append(f"%{empresa.lower()}%")
        rows = self.conn.execute(sql + " ORDER BY data_status DESC, id DESC", params).fetchall()
        return [Vaga(**dict(r)) for r in rows]

    def atualizar_status(self, vaga_id: int, status: str, nota: str | None = None, hoje: date | None = None) -> Vaga:
        if status not in STATUS:
            raise ValueError(f"status deve ser um de {STATUS}")
        vaga = self.obter(vaga_id)
        dia = (hoje or date.today()).isoformat()
        notas = f"{vaga.notas}\n[{dia}] {nota}".strip() if nota else vaga.notas
        with self.conn:
            self.conn.execute("UPDATE vagas SET status = ?, data_status = ?, notas = ? WHERE id = ?",
                              (status, dia, notas, vaga_id))
            self.conn.execute("INSERT INTO historico VALUES (?, ?, ?)", (vaga_id, status, dia))
        return self.obter(vaga_id)

    def funil(self) -> dict:
        """Quantas vagas chegaram a cada etapa (pelo histórico) e as taxas de conversão."""
        alcancou = {}
        for etapa in FUNIL:
            posteriores = FUNIL[FUNIL.index(etapa):]
            marks = ",".join("?" * len(posteriores))
            alcancou[etapa] = self.conn.execute(
                f"SELECT count(DISTINCT vaga_id) FROM historico WHERE status IN ({marks})", posteriores
            ).fetchone()[0]
        conversao = {
            f"{a}->{b}": round(alcancou[b] / alcancou[a], 3) if alcancou[a] else None
            for a, b in zip(FUNIL, FUNIL[1:])
        }
        total = self.conn.execute("SELECT count(*) FROM vagas").fetchone()[0]
        por_status = dict(self.conn.execute("SELECT status, count(*) FROM vagas GROUP BY status").fetchall())
        return {"total": total, "por_status": por_status, "alcancaram": alcancou, "conversao": conversao}

    def paradas(self, dias: int = 10, hoje: date | None = None) -> list[Vaga]:
        """Candidaturas aplicadas sem novidade há X dias: hora de fazer follow-up."""
        ref = (hoje or date.today()).toordinal()
        return [v for v in self.listar(status="aplicada") if ref - date.fromisoformat(v.data_status).toordinal() >= dias]

    def _por_link(self, link: str) -> int | None:
        row = self.conn.execute("SELECT id FROM vagas WHERE link = ?", (link,)).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.conn.close()
