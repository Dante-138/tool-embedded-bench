"""Parser de pacotes de advertising BLE: estruturas AD, iBeacon e Eddystone.

Uso:
    python radio/ble_advertising.py "02 01 06 1A FF 4C 00 02 15 <uuid 16 bytes> 00 01 00 02 C5"
    python radio/ble_advertising.py <hex> --rssi -68

O advertising é uma sequência de estruturas AD: [tamanho][tipo][dados...], em que
"tamanho" conta o byte de tipo mais os dados. Este módulo decodifica as
estruturas mais comuns e reconhece:
  - iBeacon (fabricante 0x004C, subtipo 0x02 0x15): UUID, major, minor e potência a 1 m;
  - Eddystone (Service Data 0xFEAA): frames UID, URL e TLM (bateria, temperatura, contadores).

Distância por RSSI (`--rssi`) usa o modelo log-distância:
    d = 10 ^ ((P_1m - RSSI) / (10 * n))
É uma ESTIMATIVA grosseira: RSSI varia muito com corpo humano, paredes,
orientação da antena e canal. Serve para "perto/longe", não como medida.
"""

import argparse
import sys
import uuid

TIPOS_AD = {
    0x01: "Flags",
    0x02: "UUIDs 16 bits (incompleto)",
    0x03: "UUIDs 16 bits (completo)",
    0x06: "UUIDs 128 bits (incompleto)",
    0x07: "UUIDs 128 bits (completo)",
    0x08: "Nome curto",
    0x09: "Nome completo",
    0x0A: "TX Power",
    0x16: "Service Data (UUID 16 bits)",
    0xFF: "Dados de fabricante",
}

FLAGS = {
    0: "LE limited discoverable",
    1: "LE general discoverable",
    2: "BR/EDR não suportado",
    3: "LE+BR/EDR (controlador)",
    4: "LE+BR/EDR (host)",
}

URL_ESQUEMAS = {0x00: "http://www.", 0x01: "https://www.", 0x02: "http://", 0x03: "https://"}
URL_SUFIXOS = {
    0x00: ".com/", 0x01: ".org/", 0x02: ".edu/", 0x03: ".net/", 0x04: ".info/", 0x05: ".biz/",
    0x06: ".gov/", 0x07: ".com", 0x08: ".org", 0x09: ".edu", 0x0A: ".net", 0x0B: ".info",
    0x0C: ".biz", 0x0D: ".gov",
}


def hex_para_bytes(texto):
    limpo = texto.replace("0x", "").replace(",", " ").replace(":", " ")
    return bytes.fromhex("".join(limpo.split()))


def estruturas_ad(dados):
    """Lista de (tipo, valor). Para no primeiro tamanho 0 (preenchimento)."""
    itens = []
    i = 0
    while i < len(dados):
        tamanho = dados[i]
        if tamanho == 0:
            break
        if i + 1 + tamanho > len(dados):
            raise ValueError(f"estrutura AD truncada no byte {i}: declara {tamanho} bytes, "
                             f"restam {len(dados) - i - 1}")
        itens.append((dados[i + 1], bytes(dados[i + 2:i + 1 + tamanho])))
        i += 1 + tamanho
    return itens


def decodificar_flags(valor):
    if not valor:
        return []
    return [nome for bit, nome in FLAGS.items() if valor[0] & (1 << bit)]


def decodificar_ibeacon(valor):
    """`valor` são os dados de fabricante. Retorna dict ou None se não for iBeacon."""
    if len(valor) != 25 or valor[0:2] != b"\x4c\x00" or valor[2] != 0x02 or valor[3] != 0x15:
        return None
    return {
        "uuid": str(uuid.UUID(bytes=bytes(valor[4:20]))).upper(),
        "major": int.from_bytes(valor[20:22], "big"),
        "minor": int.from_bytes(valor[22:24], "big"),
        "potencia_1m_dbm": int.from_bytes(valor[24:25], "big", signed=True),
    }


def decodificar_url_eddystone(bruto):
    if not bruto or bruto[0] not in URL_ESQUEMAS:
        raise ValueError("esquema de URL Eddystone desconhecido")
    url = URL_ESQUEMAS[bruto[0]]
    for byte in bruto[1:]:
        url += URL_SUFIXOS[byte] if byte in URL_SUFIXOS else chr(byte)
    return url


def decodificar_eddystone(valor):
    """`valor` são os dados de Service Data (tipo 0x16). Retorna dict ou None."""
    if len(valor) < 3 or valor[0:2] != b"\xaa\xfe":
        return None
    frame = valor[2:]
    tipo = frame[0]
    if tipo == 0x00 and len(frame) >= 18:
        return {"frame": "UID", "potencia_0m_dbm": int.from_bytes(frame[1:2], "big", signed=True),
                "namespace": frame[2:12].hex().upper(), "instancia": frame[12:18].hex().upper()}
    if tipo == 0x10 and len(frame) >= 3:
        return {"frame": "URL", "potencia_0m_dbm": int.from_bytes(frame[1:2], "big", signed=True),
                "url": decodificar_url_eddystone(frame[2:])}
    if tipo == 0x20 and len(frame) >= 14:
        bruto_temp = int.from_bytes(frame[4:6], "big", signed=True)
        return {
            "frame": "TLM", "versao": frame[1],
            "bateria_mv": int.from_bytes(frame[2:4], "big") or None,        # 0 = não suportado
            "temperatura_c": None if bruto_temp == -32768 else bruto_temp / 256.0,  # 0x8000 = n/d
            "pacotes_enviados": int.from_bytes(frame[6:10], "big"),
            "tempo_ligado_s": int.from_bytes(frame[10:14], "big") / 10.0,
        }
    return {"frame": f"desconhecido (0x{tipo:02X})"}


def distancia_estimada_m(rssi_dbm, potencia_1m_dbm, n=2.0):
    """Modelo log-distância. n ~ 2 em espaço livre; 2,5 a 4 em ambientes internos."""
    return 10 ** ((potencia_1m_dbm - rssi_dbm) / (10 * n))


def interpretar(dados):
    """Decodifica o advertising em uma lista de dicts {tipo, nome, ...}."""
    saida = []
    for tipo, valor in estruturas_ad(dados):
        item = {"tipo": tipo, "nome": TIPOS_AD.get(tipo, f"tipo 0x{tipo:02X}"), "bruto": valor.hex().upper()}
        if tipo == 0x01:
            item["flags"] = decodificar_flags(valor)
        elif tipo in (0x08, 0x09):
            item["texto"] = valor.decode("utf-8", errors="replace")
        elif tipo == 0x0A and valor:
            item["potencia_tx_dbm"] = int.from_bytes(valor[0:1], "big", signed=True)
        elif tipo == 0xFF:
            item["empresa_id"] = f"0x{int.from_bytes(valor[0:2], 'little'):04X}" if len(valor) >= 2 else None
            ibeacon = decodificar_ibeacon(valor)
            if ibeacon:
                item["ibeacon"] = ibeacon
        elif tipo == 0x16:
            eddystone = decodificar_eddystone(valor)
            if eddystone:
                item["eddystone"] = eddystone
        saida.append(item)
    return saida


def main(argv=None):
    ap = argparse.ArgumentParser(description="Parser de advertising BLE (AD, iBeacon, Eddystone).")
    ap.add_argument("hex", help="bytes do advertising em hexadecimal (aceita espaços, ':' e '0x')")
    ap.add_argument("--rssi", type=float, help="RSSI em dBm para estimar distância (iBeacon)")
    ap.add_argument("-n", type=float, default=2.0, help="expoente de perda de percurso (padrão 2)")
    args = ap.parse_args(argv)

    try:
        itens = interpretar(hex_para_bytes(args.hex))
    except ValueError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2

    for item in itens:
        print(f"[0x{item['tipo']:02X}] {item['nome']}: {item['bruto']}")
        for chave in ("flags", "texto", "potencia_tx_dbm", "empresa_id"):
            if chave in item:
                print(f"       {chave}: {item[chave]}")
        for grupo in ("ibeacon", "eddystone"):
            if grupo in item:
                print(f"       {grupo}:")
                for k, v in item[grupo].items():
                    print(f"         {k}: {v}")
                if grupo == "ibeacon" and args.rssi is not None:
                    d = distancia_estimada_m(args.rssi, item[grupo]["potencia_1m_dbm"], args.n)
                    print(f"         distância estimada: ~{d:.1f} m (estimativa grosseira)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
