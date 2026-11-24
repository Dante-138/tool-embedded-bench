import contextlib
import io
import unittest

from radio import lora_airtime as m


def toa(payload, sf, **kw):
    return m.tempo_no_ar_ms(payload, m.ParametrosLoRa(sf=sf, **kw))


class TestTempoNoAr(unittest.TestCase):
    # Referências: os calculadores públicos de airtime (ex.: TTN) dão 41,2 ms / 991,2 ms
    # para 10 bytes de payload PHY em SF7 e SF12 (BW 125 kHz, CR 4/5, preâmbulo 8, CRC).
    def test_sf7_payload_phy_de_10_bytes(self):
        self.assertAlmostEqual(toa(10, 7), 41.216, places=3)

    def test_sf12_payload_phy_de_10_bytes(self):
        self.assertAlmostEqual(toa(10, 12), 991.232, places=3)

    def test_uplink_lorawan_soma_13_bytes_de_overhead(self):
        # 10 bytes de aplicação + 13 = 23 bytes PHY: 61,7 ms em SF7 e 1482,8 ms em SF12.
        self.assertAlmostEqual(toa(10 + m.SOBRECARGA_LORAWAN_UPLINK, 7), 61.696, places=3)
        self.assertAlmostEqual(toa(10 + m.SOBRECARGA_LORAWAN_UPLINK, 12), 1482.752, places=3)

    def test_header_implicito_encurta_o_pacote(self):
        self.assertAlmostEqual(toa(10, 7, header_explicito=False), 36.096, places=3)

    def test_sf_maior_sempre_demora_mais(self):
        tempos = [toa(20, sf) for sf in range(7, 13)]
        self.assertEqual(tempos, sorted(tempos))

    def test_payload_maior_nunca_demora_menos(self):
        tempos = [toa(n, 9) for n in range(0, 100)]
        self.assertEqual(tempos, sorted(tempos))

    def test_largura_de_banda_maior_reduz_o_tempo(self):
        self.assertLess(toa(20, 9, bw_hz=250_000), toa(20, 9, bw_hz=125_000))


class TestLDRO(unittest.TestCase):
    def test_automatico(self):
        self.assertTrue(m.precisa_ldro(12, 125_000))
        self.assertTrue(m.precisa_ldro(11, 125_000))  # 16,384 ms > 16 ms
        self.assertFalse(m.precisa_ldro(10, 125_000))
        self.assertFalse(m.precisa_ldro(12, 500_000))  # 8,192 ms

    def test_forcar_ldro_muda_o_tempo(self):
        self.assertNotAlmostEqual(toa(20, 10, ldro=True), toa(20, 10, ldro=False))


class TestTaxaEDutyCycle(unittest.TestCase):
    def test_taxa_de_bits_conhecida(self):
        self.assertAlmostEqual(m.taxa_bits_por_s(m.ParametrosLoRa(sf=7)), 5468.75, places=2)
        self.assertAlmostEqual(m.taxa_bits_por_s(m.ParametrosLoRa(sf=12)), 292.97, places=2)

    def test_intervalo_minimo_para_1_por_cento(self):
        self.assertAlmostEqual(m.intervalo_minimo_s(991.232, 1.0), 99.1232, places=4)

    def test_duty_cycle_invalido(self):
        for valor in (0, -1, 101):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                m.intervalo_minimo_s(100, valor)


class TestValidacao(unittest.TestCase):
    def test_parametros_invalidos(self):
        casos = [
            (10, dict(sf=6)),
            (10, dict(sf=13)),
            (10, dict(sf=7, cr=0)),
            (10, dict(sf=7, cr=5)),
            (256, dict(sf=7)),
            (-1, dict(sf=7)),
            (10, dict(sf=7, bw_hz=0)),
        ]
        for payload, kw in casos:
            with self.subTest(payload=payload, **kw), self.assertRaises(ValueError):
                m.tempo_no_ar_ms(payload, m.ParametrosLoRa(**kw))


class TestCLI(unittest.TestCase):
    def test_tabela_com_todos_os_sf(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = m.main(["--payload", "10", "--lorawan", "--duty-cycle", "1"])
        self.assertEqual(codigo, 0)
        texto = saida.getvalue()
        self.assertIn("61.7", texto)  # SF7, 23 bytes PHY
        self.assertIn("1482.8", texto)  # SF12, 23 bytes PHY
        self.assertIn("intervalo min", texto)

    def test_sf_invalido_retorna_erro(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.main(["--payload", "10", "--sf", "5"]), 2)


if __name__ == "__main__":
    unittest.main()
