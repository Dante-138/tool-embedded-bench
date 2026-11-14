"""Margem de link LoRa (RSSI e SNR) e alcance teórico em espaço livre.

Uso:
    python radio/lora_link_budget.py avaliar --rssi -98 --snr -3 --sf 7
    python radio/lora_link_budget.py alcance --ptx 14 --gtx 2 --grx 3 --perdas 2 --freq 915 --sf 9

Os dois números do gateway dizem coisas diferentes:
  - RSSI compara com a sensibilidade do rádio: "o sinal tem energia suficiente?"
  - SNR compara com o SNR mínimo de demodulação: "o sinal se separa do ruído?"
Um link pode ter RSSI folgado e SNR no limite (interferência ou piso de ruído alto).
A margem efetiva é a MENOR das duas.

Valores de referência por SF (BW 125 kHz): sensibilidade e SNR mínimo típicos
citados nos materiais da Semtech para a família SX127x. São típicos, não
garantidos. Confira o datasheet do rádio do seu gateway/nó antes de usar como
critério de projeto. Para outras larguras de banda a sensibilidade é ajustada
por 10*log10(BW/125 kHz).

Este script NÃO reproduz a "margem do link" exibida por nenhuma plataforma
específica: cada uma define a sua. Aqui a definição é explícita.

O alcance por espaço livre (FSPL) é um limite OTIMISTA, de visada direta e sem
obstáculos. Em ambiente real (prédios, chão, vegetação) o alcance é bem menor.
"""

import argparse
import math
import sys

SENSIBILIDADE_125K_DBM = {7: -123.0, 8: -126.0, 9: -129.0, 10: -132.0, 11: -134.5, 12: -137.0}
SNR_MINIMO_DB = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}


def _validar_sf(sf):
    if sf not in SENSIBILIDADE_125K_DBM:
        raise ValueError("SF deve estar entre 7 e 12")


def sensibilidade_dbm(sf, bw_hz=125_000):
    _validar_sf(sf)
    return SENSIBILIDADE_125K_DBM[sf] + 10 * math.log10(bw_hz / 125_000)


def margem_rssi_db(rssi_dbm, sf, bw_hz=125_000):
    return rssi_dbm - sensibilidade_dbm(sf, bw_hz)


def margem_snr_db(snr_db, sf):
    _validar_sf(sf)
    return snr_db - SNR_MINIMO_DB[sf]


def avaliar(rssi_dbm, snr_db, sf, bw_hz=125_000, margem_desejada_db=10.0):
    m_rssi = margem_rssi_db(rssi_dbm, sf, bw_hz)
    m_snr = margem_snr_db(snr_db, sf)
    efetiva = min(m_rssi, m_snr)
    if efetiva < 0:
        status = "abaixo do limite de demodulação"
    elif efetiva < margem_desejada_db:
        status = "funciona, mas sem a margem desejada"
    else:
        status = "margem adequada"
    return {
        "margem_rssi_db": m_rssi,
        "margem_snr_db": m_snr,
        "margem_efetiva_db": efetiva,
        "limitante": "RSSI" if m_rssi <= m_snr else "SNR",
        "status": status,
    }


def perda_espaco_livre_db(dist_km, freq_mhz):
    """FSPL em dB: 20*log10(d_km) + 20*log10(f_MHz) + 32,44."""
    if dist_km <= 0 or freq_mhz <= 0:
        raise ValueError("distância e frequência devem ser > 0")
    return 20 * math.log10(dist_km) + 20 * math.log10(freq_mhz) + 32.44


def rssi_esperado_dbm(ptx_dbm, gtx_dbi, grx_dbi, perdas_db, dist_km, freq_mhz):
    return ptx_dbm + gtx_dbi + grx_dbi - perdas_db - perda_espaco_livre_db(dist_km, freq_mhz)


def distancia_maxima_km(ptx_dbm, gtx_dbi, grx_dbi, perdas_db, freq_mhz, sf,
                        bw_hz=125_000, margem_db=10.0):
    """Distância em que o RSSI esperado cai para (sensibilidade + margem), em espaço livre."""
    orcamento = ptx_dbm + gtx_dbi + grx_dbi - perdas_db - (sensibilidade_dbm(sf, bw_hz) + margem_db)
    return 10 ** ((orcamento - 32.44 - 20 * math.log10(freq_mhz)) / 20)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Margem de link LoRa e alcance teórico.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("avaliar", help="margem a partir do RSSI e SNR reportados pelo gateway")
    a.add_argument("--rssi", type=float, required=True, help="dBm")
    a.add_argument("--snr", type=float, required=True, help="dB")
    a.add_argument("--sf", type=int, required=True)
    a.add_argument("--bw", type=float, default=125, help="kHz")
    a.add_argument("--margem", type=float, default=10.0, help="margem desejada em dB (padrão 10)")

    r = sub.add_parser("alcance", help="alcance máximo teórico em espaço livre")
    r.add_argument("--ptx", type=float, required=True, help="potência de transmissão, dBm")
    r.add_argument("--gtx", type=float, default=0.0, help="ganho da antena de TX, dBi")
    r.add_argument("--grx", type=float, default=0.0, help="ganho da antena de RX, dBi")
    r.add_argument("--perdas", type=float, default=0.0, help="cabos/conectores, dB")
    r.add_argument("--freq", type=float, required=True, help="MHz")
    r.add_argument("--sf", type=int, required=True)
    r.add_argument("--bw", type=float, default=125, help="kHz")
    r.add_argument("--margem", type=float, default=10.0)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "avaliar":
            res = avaliar(args.rssi, args.snr, args.sf, int(args.bw * 1000), args.margem)
            print(f"Sensibilidade SF{args.sf}/{args.bw:g} kHz: "
                  f"{sensibilidade_dbm(args.sf, int(args.bw * 1000)):.1f} dBm | "
                  f"SNR mínimo: {SNR_MINIMO_DB[args.sf]:.1f} dB")
            print(f"Margem de RSSI: {res['margem_rssi_db']:+.1f} dB")
            print(f"Margem de SNR:  {res['margem_snr_db']:+.1f} dB")
            print(f"Margem efetiva: {res['margem_efetiva_db']:+.1f} dB (limitada por {res['limitante']})")
            print(f"Avaliação (desejado {args.margem:g} dB): {res['status']}")
        else:
            d = distancia_maxima_km(args.ptx, args.gtx, args.grx, args.perdas, args.freq,
                                    args.sf, int(args.bw * 1000), args.margem)
            print(f"Alcance máximo teórico (espaço livre, margem {args.margem:g} dB): {d:.1f} km")
            print("Limite otimista: visada direta, sem obstáculos. Em campo, espere bem menos.")
    except ValueError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
