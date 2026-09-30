import importlib.util
from pathlib import Path

import pytest

DEMO = Path(__file__).parents[1] / "scripts" / "demo.py"


def test_demo_runs_real_stdio_session(tmp_path):
    pytest.importorskip("ats_match")  # a demo usa analisar_aderencia; roda completa no workflow demo.yml
    spec = importlib.util.spec_from_file_location("demo", DEMO)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    saida = tmp_path / "index.html"
    dados = demo.main(str(saida))
    erros = [p["ferramenta"] for p in dados["passos"] if p["erro"]]
    assert erros == ["registrar_vaga"]  # só a duplicata proposital
    assert "vagas://relatorio-semanal" in dados["recursos"] and "revisao_semanal" in dados["prompts"]
    html = saida.read_text(encoding="utf-8")
    assert "Já existe uma vaga com este link" in html and "teste técnico" in html
    assert "AppData" not in html and "/tmp" not in html
