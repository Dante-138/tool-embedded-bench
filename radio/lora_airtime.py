"""Tempo no ar (time-on-air) de um pacote LoRa, pela fórmula do datasheet SX127x.

Uso:
    python radio/lora_airtime.py --payload 10 --lorawan            # tabela SF7..SF12
    python radio/lora_airtime.py --payload 10 --sf 9 --bw 125
    python radio/lora_airtime.py --payload 23 --sf 12 --duty-cycle 1

`--payload` é o tamanho da camada de aplicação. Com `--lorawan` soma os 13 bytes
de overhead de um uplink LoRaWAN sem opções de MAC (MHDR 1 + DevAddr 4 + FCtrl 1
+ FCnt 2 + FPort 1 + MIC 4). Sem a flag, o valor é tratado como payload PHY bruto.

Fórmula (Semtech SX1276, seção "LoRa Packet Airtime"):
    Tsym      = 2^SF / BW
    Tpreamble = (n_preamble + 4,25) * Tsym
    n_payload = 8 + max( ceil((8*PL - 4*SF + 28 + 16*CRC - 20*IH) / (4*(SF - 2*DE))) * (CR + 4), 0 )
    ToA       = Tpreamble + n_payload * Tsym
com CR = 1..4 (codificação 4/5..4/8), IH = 1 se header implícito, CRC = 1 se o
payload tem CRC e DE = 1 se a otimização de baixa taxa (LDRO) estiver ativa.

Duty cycle: algumas regiões limitam o tempo no ar por hora (ex.: 1 %% no EU868).
O parâmetro `--duty-cycle` só faz a conta; confirme a regra do seu plano de
frequência e da sua homologação. Não assumo região aqui.
"""

import argparse
import math
import sys
from dataclasses import dataclass

SOBRECARGA_LORAWAN_UPLINK = 13  # bytes: MHDR + FHDR(7) + FPort + MIC, sem FOpts


@dataclass(frozen=True)
class ParametrosLoRa:
    sf: int
    bw_hz: int = 125_000
    cr: int = 1  # 1..4 => 4/5, 4/6, 4/7, 4/8
    preambulo: int = 8
    header_explicito: bool = True
    crc_payload: bool = True
    ldro: bool | None = None  # None => decide automaticamente


def duracao_simbolo_s(sf, bw_hz):
    return (2**sf) / bw_hz


def precisa_ldro(sf, bw_hz):
    """LDRO é obrigatório quando o símbolo dura mais de 16 ms (SF11/SF12 em 125 kHz)."""
    return duracao_simbolo_s(sf, bw_hz) * 1000 > 16


def _validar(payload_bytes, p):
    if not 7 <= p.sf <= 12:
        raise ValueError("SF deve estar entre 7 e 12")
    if not 1 <= p.cr <= 4:
        raise ValueError("CR deve estar entre 1 (4/5) e 4 (4/8)")
    if not 0 <= payload_bytes <= 255:
        raise ValueError("payload PHY deve ter entre 0 e 255 bytes")
    if p.bw_hz <= 0:
        raise ValueError("largura de banda deve ser > 0")


def tempo_no_ar_ms(payload_bytes, p):
    _validar(payload_bytes, p)
    tsym = duracao_simbolo_s(p.sf, p.bw_hz)
    ldro = precisa_ldro(p.sf, p.bw_hz) if p.ldro is None else p.ldro
    ih = 0 if p.header_explicito else 1
    crc = 1 if p.crc_payload else 0
    de = 1 if ldro else 0

    numerador = 8 * payload_bytes - 4 * p.sf + 28 + 16 * crc - 20 * ih
    denominador = 4 * (p.sf - 2 * de)
    simbolos_payload = 8 + max(math.ceil(numerador / denominador) * (p.cr + 4), 0)
    t_preambulo = (p.preambulo + 4.25) * tsym
    return (t_preambulo + simbolos_payload * tsym) * 1000


def taxa_bits_por_s(p):
    """Taxa de bits nominal: SF * (BW / 2^SF) * 4/(4+CR)."""
    return p.sf * (p.bw_hz / 2**p.sf) * 4 / (4 + p.cr)


def intervalo_minimo_s(toa_ms, duty_cycle_pct):
    """Menor intervalo entre inícios de transmissão para respeitar o duty cycle."""
    if not 0 < duty_cycle_pct <= 100:
        raise ValueError("duty cycle deve estar em (0, 100] %")
    return (toa_ms / 1000.0) / (duty_cycle_pct / 100.0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tempo no ar de pacotes LoRa.")
    ap.add_argument("--payload", type=int, required=True, help="bytes de payload")
    ap.add_argument(
        "--lorawan", action="store_true", help=f"soma {SOBRECARGA_LORAWAN_UPLINK} bytes de overhead de uplink LoRaWAN"
    )
    ap.add_argument("--sf", type=int, help="fator de espalhamento 7..12 (omita para ver todos)")
    ap.add_argument("--bw", type=float, default=125, help="largura de banda em kHz (padrão 125)")
    ap.add_argument("--cr", type=int, default=1, choices=(1, 2, 3, 4), help="1=4/5 ... 4=4/8")
    ap.add_argument("--preambulo", type=int, default=8)
    ap.add_argument("--header-implicito", action="store_true")
    ap.add_argument("--sem-crc", action="store_true", help="payload sem CRC")
    ap.add_argument("--duty-cycle", type=float, help="duty cycle em %% para calcular o intervalo mínimo")
    args = ap.parse_args(argv)

    pl = args.payload + (SOBRECARGA_LORAWAN_UPLINK if args.lorawan else 0)
    sfs = [args.sf] if args.sf else list(range(7, 13))
    cabecalho = f"{'SF':>3} {'ToA (ms)':>10} {'taxa (bit/s)':>13} {'LDRO':>5}"
    if args.duty_cycle:
        cabecalho += f" {'intervalo min (s)':>18}"

    linhas = []
    try:  # calcula tudo antes de imprimir: entrada inválida não deixa saída pela metade
        for sf in sfs:
            p = ParametrosLoRa(
                sf=sf,
                bw_hz=int(args.bw * 1000),
                cr=args.cr,
                preambulo=args.preambulo,
                header_explicito=not args.header_implicito,
                crc_payload=not args.sem_crc,
            )
            toa = tempo_no_ar_ms(pl, p)
            linha = (
                f"{sf:>3} {toa:>10.1f} {taxa_bits_por_s(p):>13.0f} {'sim' if precisa_ldro(sf, p.bw_hz) else 'não':>5}"
            )
            if args.duty_cycle:
                linha += f" {intervalo_minimo_s(toa, args.duty_cycle):>18.1f}"
            linhas.append(linha)
    except ValueError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2

    print(f"Payload PHY: {pl} bytes | BW {args.bw:g} kHz | CR 4/{4 + args.cr} | preâmbulo {args.preambulo}")
    print(cabecalho)
    print("\n".join(linhas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
