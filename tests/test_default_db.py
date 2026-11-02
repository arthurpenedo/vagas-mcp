from pathlib import Path

from vagas_mcp.server import default_db


def test_default_db_usa_variavel_de_ambiente_e_cria_pasta(tmp_path, monkeypatch):
    alvo = tmp_path / "sub" / "vagas.sqlite3"
    monkeypatch.setenv("VAGAS_DB", str(alvo))
    assert default_db() == alvo
    assert alvo.parent.is_dir()


def test_default_db_sem_variavel_fica_na_home(tmp_path, monkeypatch):
    monkeypatch.delenv("VAGAS_DB", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert default_db() == tmp_path / ".vagas-mcp" / "vagas.sqlite3"
    assert (tmp_path / ".vagas-mcp").is_dir()
