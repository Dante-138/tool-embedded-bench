import contextlib
import io
import unittest

from radio import ble_advertising as m

# UUID de exemplo público (AirLocate da Apple), não pertence a nenhum produto real.
UUID_EXEMPLO = "E2C56DB5DFFB48D2B060D0F5A71096E0"

IBEACON = bytes.fromhex("020106" "1AFF" "4C000215" + UUID_EXEMPLO + "0001" "0002" "C5")
EDDYSTONE_UID = bytes.fromhex("020106" "0303AAFE" "1716AAFE" "00" "E7" "00112233445566778899" "AABBCCDDEEFF" "0000")
EDDYSTONE_URL = bytes.fromhex("0303AAFE" "0E16AAFE" "10" "E7" "01" + b"example".hex() + "00")
EDDYSTONE_TLM = bytes.fromhex("0303AAFE" "1116AAFE" "20" "00" "0BB8" "1880" "0000002A" "00000FA0")


def por_tipo(itens, tipo):
    return next(i for i in itens if i["tipo"] == tipo)


class TestEstruturasAD(unittest.TestCase):
    def test_separa_as_estruturas(self):
        estruturas = m.estruturas_ad(IBEACON)
        self.assertEqual([t for t, _ in estruturas], [0x01, 0xFF])
        self.assertEqual(estruturas[0][1], b"\x06")

    def test_zeros_de_preenchimento_encerram_a_leitura(self):
        estruturas = m.estruturas_ad(bytes.fromhex("020106" "000000"))
        self.assertEqual(len(estruturas), 1)

    def test_estrutura_truncada_levanta_erro(self):
        with self.assertRaises(ValueError):
            m.estruturas_ad(bytes.fromhex("020106" "1AFF4C00"))

    def test_flags(self):
        itens = m.interpretar(bytes.fromhex("020106"))
        self.assertEqual(por_tipo(itens, 0x01)["flags"],
                         ["LE general discoverable", "BR/EDR não suportado"])

    def test_nome_completo_e_tx_power(self):
        itens = m.interpretar(bytes.fromhex("0509" + b"Node".hex() + "020AF4"))
        self.assertEqual(por_tipo(itens, 0x09)["texto"], "Node")
        self.assertEqual(por_tipo(itens, 0x0A)["potencia_tx_dbm"], -12)


class TestIBeacon(unittest.TestCase):
    def test_decodifica_campos(self):
        ib = por_tipo(m.interpretar(IBEACON), 0xFF)["ibeacon"]
        self.assertEqual(ib["uuid"], "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0")
        self.assertEqual((ib["major"], ib["minor"]), (1, 2))
        self.assertEqual(ib["potencia_1m_dbm"], -59)

    def test_fabricante_que_nao_e_ibeacon(self):
        item = por_tipo(m.interpretar(bytes.fromhex("05FF" "5900" "0102")), 0xFF)
        self.assertNotIn("ibeacon", item)
        self.assertEqual(item["empresa_id"], "0x0059")

    def test_distancia_estimada(self):
        self.assertAlmostEqual(m.distancia_estimada_m(-59, -59), 1.0)
        self.assertAlmostEqual(m.distancia_estimada_m(-79, -59, n=2.0), 10.0)
        self.assertAlmostEqual(m.distancia_estimada_m(-89, -59, n=3.0), 10.0)


class TestEddystone(unittest.TestCase):
    def test_uid(self):
        ed = por_tipo(m.interpretar(EDDYSTONE_UID), 0x16)["eddystone"]
        self.assertEqual(ed["frame"], "UID")
        self.assertEqual(ed["potencia_0m_dbm"], -25)
        self.assertEqual(ed["namespace"], "00112233445566778899")
        self.assertEqual(ed["instancia"], "AABBCCDDEEFF")

    def test_url(self):
        ed = por_tipo(m.interpretar(EDDYSTONE_URL), 0x16)["eddystone"]
        self.assertEqual(ed["frame"], "URL")
        self.assertEqual(ed["url"], "https://www.example.com/")

    def test_tlm(self):
        ed = por_tipo(m.interpretar(EDDYSTONE_TLM), 0x16)["eddystone"]
        self.assertEqual(ed["frame"], "TLM")
        self.assertEqual(ed["bateria_mv"], 3000)
        self.assertAlmostEqual(ed["temperatura_c"], 24.5)
        self.assertEqual(ed["pacotes_enviados"], 42)
        self.assertAlmostEqual(ed["tempo_ligado_s"], 400.0)

    def test_tlm_sem_sensor_de_temperatura(self):
        dados = bytes.fromhex("0303AAFE" "1116AAFE" "20" "00" "0BB8" "8000" "0000002A" "00000FA0")
        ed = por_tipo(m.interpretar(dados), 0x16)["eddystone"]
        self.assertIsNone(ed["temperatura_c"])

    def test_service_data_de_outro_servico_nao_e_eddystone(self):
        # Service Data do serviço de bateria (0x180F): tamanho 4 = tipo + UUID (2) + 1 byte de dado.
        item = por_tipo(m.interpretar(bytes.fromhex("0416" "0F18" "5A")), 0x16)
        self.assertNotIn("eddystone", item)


class TestHexEEntrada(unittest.TestCase):
    def test_formatos_de_hexadecimal(self):
        for texto in ("02 01 06", "02:01:06", "0x02,0x01,0x06", "020106"):
            with self.subTest(texto=texto):
                self.assertEqual(m.hex_para_bytes(texto), b"\x02\x01\x06")

    def test_cli_com_ibeacon_e_rssi(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = m.main([IBEACON.hex(), "--rssi", "-79"])
        self.assertEqual(codigo, 0)
        texto = saida.getvalue()
        self.assertIn("E2C56DB5-DFFB-48D2-B060-D0F5A71096E0", texto)
        self.assertIn("~10.0 m", texto)

    def test_cli_entrada_truncada(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.main(["1AFF4C00"]), 2)


if __name__ == "__main__":
    unittest.main()
