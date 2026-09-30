"""Sincroniza as vagas locais com um banco de dados do Notion (mão única: SQLite → Notion).

O SQLite continua sendo a fonte da verdade (rápido, offline, testável); o Notion é a vitrine
para acompanhar pelo celular. Antes de escrever, o sincronizador lê o schema do banco e preenche
cada propriedade conforme o tipo que ela tem lá (title, rich_text, select, status, url, date).
Assim funciona com bancos criados à mão, sem exigir um template exato:

- propriedade que não existe no banco é ignorada (e avisada);
- em propriedades do tipo `status`, o Notion não aceita opções novas pela API, então um valor
  sem opção correspondente é pulado com aviso em vez de derrubar a sincronização.

Upsert: vaga já sincronizada é atualizada pelo id da página; vaga nova com link procura primeiro
uma página com o mesmo link no Notion, para não duplicar o que já foi cadastrado à mão.

Configuração: NOTION_TOKEN (integração interna, com acesso ao banco) e NOTION_DATABASE_ID.
"""

import os
from dataclasses import dataclass, field

import httpx

from .store import VagaStore

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
LIMITE_TEXTO = 2000  # limite do Notion por bloco de rich_text

# campo local → nome da propriedade no Notion (padrão: base "Vagas - Candidaturas")
CAMPOS = {
    "cargo": "Vaga", "empresa": "Empresa", "plataforma": "Plataforma", "nivel": "Nível",
    "modelo": "Modelo", "link": "Link", "status": "Status", "data_status": "Data", "notas": "Notas",
}
ROTULOS = {
    "status": {"encontrada": "Encontrada", "aplicada": "Aplicada", "entrevista": "Entrevista",
               "teste_tecnico": "Teste técnico", "oferta": "Oferta", "recusada": "Recusada", "desisti": "Desisti"},
    "modelo": {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial"},
}


class NotionError(RuntimeError):
    pass


@dataclass
class Resultado:
    criadas: int = 0
    atualizadas: int = 0
    avisos: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"criadas": self.criadas, "atualizadas": self.atualizadas, "avisos": self.avisos}


class NotionSync:
    def __init__(self, token: str, database_id: str, client: httpx.Client | None = None,
                 campos: dict[str, str] | None = None):
        self.database_id = database_id
        self.campos = campos or CAMPOS
        self.http = client or httpx.Client(timeout=30)
        self.headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}

    @classmethod
    def from_env(cls) -> "NotionSync":
        token, db = os.getenv("NOTION_TOKEN"), os.getenv("NOTION_DATABASE_ID")
        if not token or not db:
            raise NotionError("Configure NOTION_TOKEN e NOTION_DATABASE_ID para sincronizar com o Notion.")
        return cls(token, db)

    def _req(self, method: str, path: str, json: dict | None = None) -> dict:
        resp = self.http.request(method, f"{API}{path}", headers=self.headers, json=json)
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("message", resp.text)
            except ValueError:
                msg = resp.text
            raise NotionError(f"Notion respondeu {resp.status_code}: {msg}")
        return resp.json()

    def schema(self) -> dict[str, dict]:
        return self._req("GET", f"/databases/{self.database_id}")["properties"]

    def propriedades(self, vaga: dict, schema: dict[str, dict], avisos: list[str]) -> dict:
        props = {}
        for campo, nome in self.campos.items():
            valor = vaga.get(campo)
            if nome not in schema:
                if valor:
                    avisos.append(f"Propriedade '{nome}' não existe no banco; campo '{campo}' ignorado.")
                continue
            valor = ROTULOS.get(campo, {}).get(valor, valor)
            tipo = schema[nome]["type"]
            if tipo == "status" and valor:
                opcoes = {o["name"] for o in schema[nome]["status"]["options"]}
                if valor not in opcoes:
                    avisos.append(f"Status '{valor}' não existe no Notion ({vaga['empresa']}); status não enviado.")
                    continue
            props[nome] = _valor(tipo, valor)
        return {k: v for k, v in props.items() if v is not None}

    def _pagina_por_link(self, link: str, schema: dict) -> str | None:
        nome = self.campos.get("link")
        if not link or nome not in schema or schema[nome]["type"] != "url":
            return None
        resultado = self._req("POST", f"/databases/{self.database_id}/query",
                              {"filter": {"property": nome, "url": {"equals": link}}, "page_size": 1})
        return resultado["results"][0]["id"] if resultado["results"] else None

    def sincronizar(self, store: VagaStore) -> Resultado:
        schema = self.schema()
        res = Resultado()
        avisos: list[str] = []
        for vaga in store.listar():
            props = self.propriedades(vaga.to_dict(), schema, avisos)
            page_id = vaga.notion_id or self._pagina_por_link(vaga.link, schema)
            if page_id:
                self._req("PATCH", f"/pages/{page_id}", {"properties": props})
                res.atualizadas += 1
            else:
                page_id = self._req("POST", "/pages", {"parent": {"database_id": self.database_id},
                                                        "properties": props})["id"]
                res.criadas += 1
            if page_id != vaga.notion_id:
                store.vincular_notion(vaga.id, page_id)
        res.avisos = list(dict.fromkeys(avisos))  # sem repetir o mesmo aviso por vaga
        return res


def _texto(valor: str) -> list[dict]:
    return [{"type": "text", "text": {"content": str(valor)[:LIMITE_TEXTO]}}]


def _valor(tipo: str, valor) -> dict | None:
    if tipo == "title":
        return {"title": _texto(valor or "")}
    if valor in (None, ""):
        return None
    if tipo == "rich_text":
        return {"rich_text": _texto(valor)}
    if tipo in ("select", "status"):
        return {tipo: {"name": str(valor)[:100]}}
    if tipo == "multi_select":
        return {"multi_select": [{"name": str(valor)[:100]}]}
    if tipo == "url":
        return {"url": valor}
    if tipo == "date":
        return {"date": {"start": valor}}
    return None  # tipos não suportados (fórmula, relação...) não são escritos
