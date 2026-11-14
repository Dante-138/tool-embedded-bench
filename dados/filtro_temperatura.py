"""Filtro de temperatura do firmware (média aparada + EMA) e análise de CSV exportado.

O firmware de referência lê o sensor de temperatura do die do ESP32 assim:
  1. 20 amostras seguidas;
  2. ordena e descarta 25 % de cada lado (média aparada);
  3. suaviza com EMA, alpha = 0,3 (a primeira leitura inicializa o filtro).
Este módulo reproduz as mesmas contas para conferir o comportamento offline e
aplica a mesma suavização a uma coluna de um CSV, marcando outliers.

Uso:
    python dados/filtro_temperatura.py leituras.csv --coluna temperatura \\
        --saida saidas/filtrado.csv --grafico saidas/temperatura.png

O formato do CSV varia (separador, decimal, nomes de coluna), então nada é
assumido: informe `--coluna`, `--sep` e `--decimal` conforme o seu arquivo.

Outliers: escore z modificado (Iglewicz-Hoaglin), com mediana e MAD, limite 3,5.
Quando MAD = 0 (comum em sensor quantizado, com muitas leituras iguais), usa o
desvio médio absoluto. Vale para a série inteira: para séries longas com deriva
lenta, uma janela deslizante seria mais adequada (não implementada).
"""

import argparse
import statistics
import sys
from pathlib import Path

TEMP_SAMPLES = 20      # espelham config.h do firmware
TEMP_TRIM_PCT = 25
TEMP_EMA_ALPHA = 0.3


def media_aparada(amostras, trim_pct=TEMP_TRIM_PCT):
    """Média depois de descartar `trim_pct` % de cada extremo (divisão inteira, como no C)."""
    n = len(amostras)
    corte = n * trim_pct // 100
    miolo = sorted(amostras)[corte:n - corte]
    if not miolo:
        raise ValueError("sem amostras após o corte; reduza trim_pct ou traga mais amostras")
    return sum(miolo) / len(miolo)


def ema(serie, alpha=TEMP_EMA_ALPHA):
    """Média móvel exponencial. O primeiro valor inicializa o filtro (igual ao firmware)."""
    if not 0 < alpha <= 1:
        raise ValueError("alpha deve estar em (0, 1]")
    saida = []
    ultimo = None
    for x in serie:
        ultimo = x if ultimo is None else alpha * x + (1 - alpha) * ultimo
        saida.append(ultimo)
    return saida


def marcar_outliers(serie, limiar=3.5):
    """Lista de booleanos: True onde o valor é outlier pelo escore z modificado."""
    if len(serie) < 3:
        return [False] * len(serie)
    med = statistics.median(serie)
    mad = statistics.median(abs(x - med) for x in serie)
    if mad > 0:
        return [abs(0.6745 * (x - med) / mad) > limiar for x in serie]
    desvio_medio = sum(abs(x - med) for x in serie) / len(serie)
    if desvio_medio == 0:
        return [False] * len(serie)
    return [abs((x - med) / (1.253314 * desvio_medio)) > limiar for x in serie]


def processar(entrada, coluna, saida=None, grafico=None, sep=",", decimal=".",
              encoding="utf-8-sig", alpha=TEMP_EMA_ALPHA, limiar=3.5, descartar_outliers=False):
    """Lê o CSV, acrescenta `<coluna>_ema` e `<coluna>_outlier` e devolve o DataFrame.

    Tudo é lido como texto: assim as demais colunas voltam idênticas no CSV de saída e
    a coluna alvo é convertida à mão. Deixar o pandas inferir o tipo falha justamente
    nos arquivos reais: um único "n/d" faz a coluna inteira virar texto e o separador
    decimal deixa de valer. Células vazias ou não numéricas são ignoradas no filtro.
    """
    import pandas as pd

    df = pd.read_csv(entrada, sep=sep, encoding=encoding, dtype=str, keep_default_na=False)
    if coluna not in df.columns:
        raise ValueError(f"coluna {coluna!r} não existe. Colunas do arquivo: {list(df.columns)}")

    texto = df[coluna].str.strip()
    if decimal != ".":
        texto = texto.str.replace(decimal, ".", regex=False)
    valores = pd.to_numeric(texto, errors="coerce")
    validos = valores.dropna()
    if validos.empty:
        raise ValueError(f"a coluna {coluna!r} não tem nenhum valor numérico "
                         f"(confira --sep={sep!r} e --decimal={decimal!r})")

    flags = pd.Series(marcar_outliers(validos.tolist(), limiar), index=validos.index)
    base = validos[~flags] if descartar_outliers else validos
    suavizado = pd.Series(ema(base.tolist(), alpha), index=base.index)

    df[f"{coluna}_ema"] = suavizado.reindex(df.index)
    # dtype "boolean" (anulável): linhas sem valor numérico ficam <NA>, não viram False.
    df[f"{coluna}_outlier"] = flags.astype("boolean").reindex(df.index)

    if saida:
        Path(saida).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(saida, index=False, sep=sep, decimal=decimal, encoding="utf-8")
    if grafico:
        _plotar(valores, df[f"{coluna}_ema"], flags, coluna, grafico)
    return df


def _plotar(valores, suavizado, flags, coluna, caminho):
    import matplotlib
    matplotlib.use("Agg")  # sem janela: funciona em servidor e em automação
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(valores.index, valores, ".", color="0.6", label="leitura")
    ax.plot(suavizado.index, suavizado, "-", color="tab:blue", label="EMA")
    marcados = valores[flags[flags].index]
    ax.plot(marcados.index, marcados, "x", color="tab:red", label="outlier")
    ax.set_xlabel("índice da leitura")
    ax.set_ylabel(coluna)
    ax.grid(True, alpha=0.3)
    ax.legend()
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(caminho, dpi=120)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description="EMA e outliers em uma coluna de temperatura de um CSV.")
    ap.add_argument("entrada", help="arquivo CSV")
    ap.add_argument("--coluna", required=True, help="nome da coluna numérica")
    ap.add_argument("--sep", default=",", help="separador de colunas (ex.: ';')")
    ap.add_argument("--decimal", default=".", help="separador decimal (ex.: ',')")
    ap.add_argument("--encoding", default="utf-8-sig")
    ap.add_argument("--alpha", type=float, default=TEMP_EMA_ALPHA, help="peso da nova leitura (padrão 0,3)")
    ap.add_argument("--limiar", type=float, default=3.5, help="limiar do escore z modificado")
    ap.add_argument("--descartar-outliers", action="store_true", help="tira os outliers antes do EMA")
    ap.add_argument("--saida", help="CSV de saída com as colunas novas")
    ap.add_argument("--grafico", help="PNG do gráfico")
    args = ap.parse_args(argv)

    try:
        df = processar(args.entrada, args.coluna, args.saida, args.grafico, args.sep, args.decimal,
                       args.encoding, args.alpha, args.limiar, args.descartar_outliers)
    except (ValueError, OSError) as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2

    total = int(df[f"{args.coluna}_outlier"].fillna(False).astype(bool).sum())
    print(f"{len(df)} linhas | {total} outlier(s) | EMA com alpha={args.alpha:g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
