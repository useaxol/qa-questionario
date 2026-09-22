#!/usr/bin/env python3
"""
Extrai APENAS as formulas de um .xlsx, sem nenhum dado.

    pip install openpyxl
    python dump_formulas.py "MATRIZ PARA CALCULOS DE ED 2.0 MAIN.xlsx"

Gera <nome>_formulas.txt ao lado do arquivo. Formulas identicas arrastadas por milhares de
linhas viram UMA linha no relatorio, com a contagem e o intervalo de celulas onde aparecem.
Um arquivo de 12 MB costuma virar poucos KB.
"""
import re
import sys
from collections import OrderedDict
from pathlib import Path

try:
    import openpyxl
except ImportError:
    sys.exit("falta o openpyxl:  pip install openpyxl")

CELL = re.compile(r"(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7})(?![0-9(])")


def normalizar(formula, col, row):
    """Troca referencias relativas por deslocamento, para agrupar a mesma formula arrastada."""
    def sub(m):
        fc, c, fr, r = m.group(1), m.group(2), m.group(3), int(m.group(4))
        c_idx = 0
        for ch in c:
            c_idx = c_idx * 26 + (ord(ch) - 64)
        cc = c if fc else f"C[{c_idx - col:+d}]"
        rr = str(r) if fr else f"R[{r - row:+d}]"
        return f"{fc}{cc}{fr}{rr}"
    return CELL.sub(sub, formula)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    caminho = Path(sys.argv[1])
    wb = openpyxl.load_workbook(caminho, data_only=False, read_only=True)

    linhas = [f"ARQUIVO: {caminho.name}", f"ABAS: {len(wb.sheetnames)}", ""]
    for nome in wb.sheetnames:
        ws = wb[nome]
        grupos = OrderedDict()
        cabecalhos = []
        for linha in ws.iter_rows():
            for c in linha:
                v = c.value
                if v is None:
                    continue
                if isinstance(v, str) and v.startswith("="):
                    chave = normalizar(v, c.column, c.row)
                    g = grupos.setdefault(chave, {"n": 0, "1a": c.coordinate,
                                                  "ex": v, "ult": c.coordinate})
                    g["n"] += 1
                    g["ult"] = c.coordinate
                elif c.row <= 6 and isinstance(v, str) and len(v) < 60:
                    cabecalhos.append(f"{c.coordinate}={v}")

        linhas.append("=" * 78)
        linhas.append(f"ABA: {nome}    dim={ws.calculate_dimension()}    "
                      f"formulas distintas={len(grupos)}")
        linhas.append("=" * 78)
        if cabecalhos:
            linhas.append("  cabecalhos: " + " | ".join(cabecalhos[:40]))
            linhas.append("")
        if not grupos:
            linhas.append("  (sem formulas)")
        for chave, g in grupos.items():
            faixa = g["1a"] if g["n"] == 1 else f"{g['1a']}..{g['ult']}  ({g['n']}x)"
            linhas.append(f"  [{faixa}]")
            linhas.append(f"     {g['ex']}")
        linhas.append("")

    saida = caminho.with_name(caminho.stem + "_formulas.txt")
    saida.write_text("\n".join(linhas), encoding="utf8")
    print(f"gerado: {saida}   ({saida.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
