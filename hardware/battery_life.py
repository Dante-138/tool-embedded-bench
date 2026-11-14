"""Autonomia de bateria a partir de um perfil de consumo por fases (duty-cycle).

Uso:
    python hardware/battery_life.py --capacidade 2000 \\
        --fase transmissao:120:8 --fase escuta:25:12 --fase sleep:0.05:580

Cada `--fase` é `nome:corrente_mA:duração_s` dentro de UM ciclo repetitivo.
A corrente média é a média ponderada pelo tempo: soma(I*t) / soma(t).

O que o modelo NÃO cobre (a estimativa é otimista por isso):
  - capacidade cai com temperatura baixa, envelhecimento e correntes de pico altas;
  - eficiência do regulador (use correntes medidas na BATERIA, não no rail);
  - tensão de corte: o parâmetro `aproveitamento` (0-1) absorve isso.
Para os valores de corrente, o ideal é a média medida com um analisador de
consumo (ex.: PPK2) em cada fase, não o valor de datasheet.
"""

import argparse
import sys
from dataclasses import dataclass

HORAS_POR_MES = 30 * 24


@dataclass(frozen=True)
class Fase:
    nome: str
    corrente_ma: float
    duracao_s: float


def corrente_media_ma(fases):
    ciclo = sum(f.duracao_s for f in fases)
    if not fases or ciclo <= 0:
        raise ValueError("o ciclo precisa ter pelo menos uma fase com duração > 0")
    return sum(f.corrente_ma * f.duracao_s for f in fases) / ciclo


def autodescarga_ma(capacidade_mah, pct_por_mes):
    """Corrente equivalente à autodescarga (ex.: 3 %/mês numa célula de 1000 mAh = 0,042 mA)."""
    return capacidade_mah * (pct_por_mes / 100.0) / HORAS_POR_MES


def autonomia_horas(capacidade_mah, fases, aproveitamento=0.8, autodescarga_pct_mes=0.0):
    if capacidade_mah <= 0:
        raise ValueError("capacidade deve ser > 0")
    if not 0 < aproveitamento <= 1:
        raise ValueError("aproveitamento deve estar em (0, 1]")
    corrente = corrente_media_ma(fases) + autodescarga_ma(capacidade_mah, autodescarga_pct_mes)
    if corrente <= 0:
        raise ValueError("corrente total zero: autonomia infinita, confira os dados")
    return capacidade_mah * aproveitamento / corrente


def participacao_por_fase(fases):
    """Fração (0-1) da carga por ciclo consumida por cada fase. Mostra onde otimizar."""
    total = sum(f.corrente_ma * f.duracao_s for f in fases)
    if total <= 0:
        raise ValueError("carga por ciclo zero")
    return {f.nome: f.corrente_ma * f.duracao_s / total for f in fases}


def parse_fase(texto):
    partes = texto.split(":")
    if len(partes) != 3:
        raise argparse.ArgumentTypeError(f"fase inválida {texto!r}: use nome:corrente_mA:duração_s")
    nome, corrente, duracao = partes
    try:
        fase = Fase(nome.strip(), float(corrente), float(duracao))
    except ValueError:
        raise argparse.ArgumentTypeError(f"fase inválida {texto!r}: corrente e duração são números")
    if not fase.nome or fase.corrente_ma < 0 or fase.duracao_s < 0:
        raise argparse.ArgumentTypeError(f"fase inválida {texto!r}: sem nome ou valores negativos")
    return fase


def main(argv=None):
    ap = argparse.ArgumentParser(description="Autonomia de bateria por perfil de consumo.")
    ap.add_argument("--capacidade", type=float, required=True, help="capacidade nominal em mAh")
    ap.add_argument("--fase", type=parse_fase, action="append", required=True,
                    help="nome:corrente_mA:duração_s (repita para cada fase do ciclo)")
    ap.add_argument("--aproveitamento", type=float, default=0.8,
                    help="fração utilizável da capacidade (padrão 0,8)")
    ap.add_argument("--autodescarga", type=float, default=0.0, help="autodescarga em %% ao mês")
    args = ap.parse_args(argv)

    try:
        horas = autonomia_horas(args.capacidade, args.fase, args.aproveitamento, args.autodescarga)
        media = corrente_media_ma(args.fase)
        partes = participacao_por_fase(args.fase)
    except ValueError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2

    ciclo = sum(f.duracao_s for f in args.fase)
    print(f"Ciclo: {ciclo:g} s | corrente média: {media:.4g} mA")
    if args.autodescarga:
        print(f"Autodescarga equivalente: {autodescarga_ma(args.capacidade, args.autodescarga):.4g} mA")
    dias = horas / 24
    print(f"Autonomia: {horas:.1f} h = {dias:.1f} dias = {dias / 30:.1f} meses (de 30 dias)")
    print("Carga por fase:")
    for nome, fracao in sorted(partes.items(), key=lambda kv: -kv[1]):
        print(f"  {nome:<16} {fracao * 100:5.1f} %")
    return 0


if __name__ == "__main__":
    sys.exit(main())
