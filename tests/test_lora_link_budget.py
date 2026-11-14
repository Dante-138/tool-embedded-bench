import contextlib
import io
import math
import unittest

from radio import lora_link_budget as m


class TestSensibilidade(unittest.TestCase):
    def test_valores_de_referencia_em_125khz(self):
        self.assertEqual(m.sensibilidade_dbm(7), -123.0)
        self.assertEqual(m.sensibilidade_dbm(12), -137.0)

    def test_dobrar_a_largura_de_banda_piora_3_db(self):
        self.assertAlmostEqual(m.sensibilidade_dbm(9, 250_000) - m.sensibilidade_dbm(9), 3.0103, places=3)

    def test_sf_maior_e_mais_sensivel(self):
        valores = [m.sensibilidade_dbm(sf) for sf in range(7, 13)]
        self.assertEqual(valores, sorted(valores, reverse=True))

    def test_sf_invalido(self):
        with self.assertRaises(ValueError):
            m.sensibilidade_dbm(6)


class TestMargens(unittest.TestCase):
    def test_margens_simples(self):
        self.assertAlmostEqual(m.margem_rssi_db(-98, 7), 25.0)
        self.assertAlmostEqual(m.margem_snr_db(-3, 7), 4.5)

    def test_margem_efetiva_e_a_menor_e_aponta_o_limitante(self):
        # RSSI folgado, SNR no limite: o SNR limita.
        r = m.avaliar(rssi_dbm=-98, snr_db=-3, sf=7)
        self.assertAlmostEqual(r["margem_efetiva_db"], 4.5)
        self.assertEqual(r["limitante"], "SNR")
        self.assertEqual(r["status"], "funciona, mas sem a margem desejada")

    def test_rssi_pode_ser_o_limitante(self):
        r = m.avaliar(rssi_dbm=-120, snr_db=5, sf=7)
        self.assertEqual(r["limitante"], "RSSI")
        self.assertAlmostEqual(r["margem_efetiva_db"], 3.0)

    def test_status_por_faixa(self):
        self.assertEqual(m.avaliar(-70, 8, 7)["status"], "margem adequada")
        self.assertEqual(m.avaliar(-130, 8, 7)["status"], "abaixo do limite de demodulação")

    def test_margem_desejada_muda_o_status(self):
        self.assertEqual(m.avaliar(-98, -3, 7, margem_desejada_db=3)["status"], "margem adequada")


class TestEspacoLivre(unittest.TestCase):
    def test_fspl_de_referencia(self):
        # 1 km a 900 MHz: cerca de 91,5 dB.
        self.assertAlmostEqual(m.perda_espaco_livre_db(1, 900), 91.52, places=2)

    def test_dobrar_a_distancia_soma_6_db(self):
        dif = m.perda_espaco_livre_db(2, 915) - m.perda_espaco_livre_db(1, 915)
        self.assertAlmostEqual(dif, 20 * math.log10(2), places=6)

    def test_alcance_maximo_fecha_o_orcamento(self):
        d = m.distancia_maxima_km(14, 2, 3, 2, 915, sf=9, margem_db=10)
        rssi = m.rssi_esperado_dbm(14, 2, 3, 2, d, 915)
        self.assertAlmostEqual(rssi, m.sensibilidade_dbm(9) + 10, places=6)

    def test_mais_sf_alcanca_mais(self):
        d7 = m.distancia_maxima_km(14, 0, 0, 0, 915, sf=7)
        d12 = m.distancia_maxima_km(14, 0, 0, 0, 915, sf=12)
        self.assertGreater(d12, d7)

    def test_entradas_invalidas(self):
        with self.assertRaises(ValueError):
            m.perda_espaco_livre_db(0, 915)


class TestCLI(unittest.TestCase):
    def test_avaliar(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = m.main(["avaliar", "--rssi", "-98", "--snr", "-3", "--sf", "7"])
        self.assertEqual(codigo, 0)
        self.assertIn("limitada por SNR", saida.getvalue())

    def test_alcance(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = m.main(["alcance", "--ptx", "14", "--freq", "915", "--sf", "9"])
        self.assertEqual(codigo, 0)
        self.assertIn("otimista", saida.getvalue())

    def test_sf_invalido(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.main(["avaliar", "--rssi", "-98", "--snr", "-3", "--sf", "5"]), 2)


if __name__ == "__main__":
    unittest.main()
