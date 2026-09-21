#!/usr/bin/env python3
"""
Decomposicao do crescimento entre dois MATs: volume organico + itens novos + preco/mix.

    python3 decompor_crescimento.py extracao.xlsx --base "MAT Jul'25" --atual "MAT Jul'26" \
        --item FCC --periodo MAT --valor Valor --unidades Unidades \
        --por Segmento --por Fabricante

Aceita .xlsx, .csv e .tsv. Imprime a decomposicao do total e de cada dimensao pedida em --por,
mais o saneamento que o passo 3 da skill exige (itens novos, descontinuados, sortimento ativo).

Convencao (identica a de reference/metodos-analiticos.md):
    volume organico = SUM (un_t - un_t1) * preco_t1   [itens presentes nos dois MATs]
    itens novos     = SUM valor_t                     [itens sem venda no MAT base]
    preco/mix       = delta total - organico - novos   [residuo]

Itens descontinuados (venda no base, zero no atual) sao reportados como parcela propria, nao
dentro do organico, para nao esconder perda de base.
"""
import argparse
import sys
from pathlib import Path


def carregar(caminho, aba=None):
    import pandas as pd
    p = Path(caminho)
    if p.suffix.lower() in {".csv", ".tsv"}:
        sep = "\t" if p.suffix.lower() == ".tsv" else None
        return pd.read_csv(p, sep=sep, engine="python")
    return pd.read_excel(p, sheet_name=aba or 0)


def decompor(df, col_item, col_periodo, col_valor, col_un, base, atual):
    """Retorna (dict com as parcelas, dict com o saneamento)."""
    import pandas as pd

    d = df[df[col_periodo].isin([base, atual])].copy()
    d[col_valor] = d[col_valor].astype(float)
    d[col_un] = d[col_un].astype(float)
    piv = d.pivot_table(
        index=col_item, columns=col_periodo,
        values=[col_valor, col_un], aggfunc="sum", fill_value=0.0,
    )
    for m in (base, atual):
        for c in (col_valor, col_un):
            if (c, m) not in piv.columns:
                piv[(c, m)] = 0.0

    v0, v1 = piv[(col_valor, base)], piv[(col_valor, atual)]
    u0, u1 = piv[(col_un, base)], piv[(col_un, atual)]

    existente = (v0 > 0) & (v1 > 0)
    novo = (v0 <= 0) & (v1 > 0)
    descontinuado = (v0 > 0) & (v1 <= 0)

    # preco do ano base, apenas onde ha unidades no base
    preco0 = pd.Series(0.0, index=piv.index)
    tem_un = u0 > 0
    preco0[tem_un] = v0[tem_un] / u0[tem_un]

    organico = float(((u1[existente] - u0[existente]) * preco0[existente]).sum())
    perda_desc = float((-u0[descontinuado] * preco0[descontinuado]).sum())
    novos = float(v1[novo].sum())
    delta = float(v1.sum() - v0.sum())
    preco_mix = delta - organico - perda_desc - novos

    parcelas = {
        "valor_base": float(v0.sum()),
        "valor_atual": float(v1.sum()),
        "delta": delta,
        "var_pct": (delta / float(v0.sum()) * 100) if v0.sum() else float("nan"),
        "volume_organico": organico,
        "perda_descontinuados": perda_desc,
        "itens_novos": novos,
        "preco_mix": preco_mix,
    }
    saneamento = {
        "itens_base": int((v0 > 0).sum()),
        "itens_atual": int((v1 > 0).sum()),
        "itens_novos": int(novo.sum()),
        "itens_descontinuados": int(descontinuado.sum()),
        "un_base": float(u0.sum()),
        "un_atual": float(u1.sum()),
    }
    return parcelas, saneamento


def br(x, dec=1):
    s = f"{x:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def imprimir(titulo, p, s=None, total_base=None):
    print(f"\n{titulo}")
    print("-" * len(titulo))
    print(f"  valor base           {br(p['valor_base'])}")
    print(f"  valor atual          {br(p['valor_atual'])}")
    print(f"  delta                {br(p['delta']):>15}   ({br(p['var_pct'])}%)")
    if total_base:
        print(f"  contribuicao         {br(p['delta'] / total_base * 100, 2)} p.p.")
    print(f"  volume organico      {br(p['volume_organico']):>15}")
    if abs(p["perda_descontinuados"]) > 0:
        print(f"  descontinuados       {br(p['perda_descontinuados']):>15}")
    print(f"  itens novos          {br(p['itens_novos']):>15}")
    print(f"  preco / mix          {br(p['preco_mix']):>15}")
    if s:
        print(f"  sortimento ativo     {s['itens_base']} -> {s['itens_atual']}"
              f"   (novos {s['itens_novos']}, descontinuados {s['itens_descontinuados']})")
        var_un = (s["un_atual"] / s["un_base"] - 1) * 100 if s["un_base"] else float("nan")
        print(f"  unidades             {br(s['un_base'])} -> {br(s['un_atual'])}   ({br(var_un)}%)")
    pm0 = p["valor_base"] / s["un_base"] if s and s["un_base"] else None
    pm1 = p["valor_atual"] / s["un_atual"] if s and s["un_atual"] else None
    if pm0 and pm1:
        print(f"  preco medio          {br(pm0, 2)} -> {br(pm1, 2)}   ({br((pm1/pm0-1)*100)}%)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arquivo")
    ap.add_argument("--aba")
    ap.add_argument("--base", required=True, help="rotulo do MAT anterior")
    ap.add_argument("--atual", required=True, help="rotulo do MAT corrente")
    ap.add_argument("--item", default="FCC", help="coluna de identificacao do item (default: FCC)")
    ap.add_argument("--periodo", default="MAT", help="coluna de periodo (default: MAT)")
    ap.add_argument("--valor", default="Valor")
    ap.add_argument("--unidades", default="Unidades")
    ap.add_argument("--por", action="append", default=[],
                    help="dimensao para abrir a decomposicao; repetir para varias")
    ap.add_argument("--min-peso", type=float, default=0.0,
                    help="omite recortes com menos desse %% do valor atual")
    a = ap.parse_args()

    df = carregar(a.arquivo, a.aba)
    faltando = [c for c in (a.item, a.periodo, a.valor, a.unidades) + tuple(a.por)
                if c not in df.columns]
    if faltando:
        sys.exit(f"colunas ausentes: {faltando}\ncolunas do arquivo: {list(df.columns)}")

    periodos = set(df[a.periodo].astype(str).unique())
    for m in (a.base, a.atual):
        if m not in periodos:
            sys.exit(f"periodo '{m}' nao encontrado. disponiveis: {sorted(periodos)}")
    df[a.periodo] = df[a.periodo].astype(str)

    total, san = decompor(df, a.item, a.periodo, a.valor, a.unidades, a.base, a.atual)
    imprimir(f"TOTAL  ({a.base} -> {a.atual})", total, san)

    soma = total["delta"]
    for dim in a.por:
        print(f"\n\n### por {dim}")
        linhas = []
        for chave, grp in df.groupby(dim, dropna=False):
            p, s = decompor(grp, a.item, a.periodo, a.valor, a.unidades, a.base, a.atual)
            if p["valor_atual"] / total["valor_atual"] * 100 < a.min_peso:
                continue
            linhas.append((chave, p, s))
        linhas.sort(key=lambda t: -t[1]["valor_atual"])
        for chave, p, s in linhas:
            peso = p["valor_atual"] / total["valor_atual"] * 100
            imprimir(f"{chave}   [peso {br(peso)}%]", p, s, total_base=total["valor_base"])
        checagem = sum(p["delta"] for _, p, _ in linhas)
        print(f"\n  soma dos deltas de {dim}: {br(checagem)}   |   total: {br(soma)}"
              f"   |   diferenca: {br(checagem - soma)}")
        if abs(checagem - soma) > abs(soma) * 0.001:
            print("  ATENCAO: as partes nao fecham o total — conferir antes de plotar")


if __name__ == "__main__":
    main()
