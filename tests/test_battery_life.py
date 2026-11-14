import argparse
import contextlib
import io
import unittest

from hardware import battery_life as m

CICLO = [m.Fase("ativo", 100.0, 10.0), m.Fase("sleep", 1.0, 90.0)]


class TestCorrenteMedia(unittest.TestCase):
    def test_media_ponderada_pelo_tempo(self):
        # (100*10 + 1*90) / 100 = 10,9 mA
        self.assertAlmostEqual(m.corrente_media_ma(CICLO), 10.9)

    def test_fase_unica_e_a_propria_corrente(self):
        self.assertAlmostEqual(m.corrente_media_ma([m.Fase("x", 42.0, 7.0)]), 42.0)

    def test_ciclo_vazio_ou_sem_duracao(self):
        for fases in ([], [m.Fase("x", 5.0, 0.0)]):
            with self.subTest(fases=fases), self.assertRaises(ValueError):
                m.corrente_media_ma(fases)


class TestAutonomia(unittest.TestCase):
    def test_autonomia_basica(self):
        # 1000 mAh / 10,9 mA = 91,74 h (aproveitamento 100 %)
        self.assertAlmostEqual(m.autonomia_horas(1000, CICLO, aproveitamento=1.0), 1000 / 10.9)

    def test_aproveitamento_reduz_a_autonomia_proporcionalmente(self):
        cheia = m.autonomia_horas(1000, CICLO, aproveitamento=1.0)
        self.assertAlmostEqual(m.autonomia_horas(1000, CICLO, aproveitamento=0.8), cheia * 0.8)

    def test_autodescarga_equivalente(self):
        # 3 % ao mês numa célula de 1000 mAh: 1000 * 0,03 / 720 = 0,041667 mA
        self.assertAlmostEqual(m.autodescarga_ma(1000, 3.0), 1000 * 0.03 / 720)

    def test_autodescarga_reduz_a_autonomia(self):
        sem = m.autonomia_horas(1000, CICLO, 1.0, 0.0)
        com = m.autonomia_horas(1000, CICLO, 1.0, 3.0)
        self.assertLess(com, sem)
        self.assertAlmostEqual(com, 1000 / (10.9 + 1000 * 0.03 / 720))

    def test_duty_cycle_menor_estende_a_autonomia(self):
        raro = [m.Fase("ativo", 100.0, 10.0), m.Fase("sleep", 1.0, 590.0)]
        self.assertGreater(m.autonomia_horas(1000, raro), m.autonomia_horas(1000, CICLO))

    def test_entradas_invalidas(self):
        with self.assertRaises(ValueError):
            m.autonomia_horas(0, CICLO)
        for aproveitamento in (0, -0.1, 1.5):
            with self.subTest(aproveitamento=aproveitamento), self.assertRaises(ValueError):
                m.autonomia_horas(1000, CICLO, aproveitamento)
        with self.assertRaises(ValueError):
            m.autonomia_horas(1000, [m.Fase("x", 0.0, 10.0)])  # corrente zero: autonomia infinita


class TestParticipacao(unittest.TestCase):
    def test_soma_um_e_aponta_o_dominante(self):
        partes = m.participacao_por_fase(CICLO)
        self.assertAlmostEqual(sum(partes.values()), 1.0)
        self.assertAlmostEqual(partes["ativo"], 1000 / 1090)
        self.assertGreater(partes["ativo"], partes["sleep"])


class TestParseFase(unittest.TestCase):
    def test_valida(self):
        self.assertEqual(m.parse_fase("tx:120:8"), m.Fase("tx", 120.0, 8.0))
        self.assertEqual(m.parse_fase("sleep:0.05:580"), m.Fase("sleep", 0.05, 580.0))

    def test_invalidas(self):
        for texto in ("tx:120", "tx:abc:8", ":120:8", "tx:-1:8", "tx:1:2:3"):
            with self.subTest(texto=texto), self.assertRaises(argparse.ArgumentTypeError):
                m.parse_fase(texto)


class TestCLI(unittest.TestCase):
    def test_saida_do_cli(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = m.main(["--capacidade", "1000", "--aproveitamento", "1",
                             "--fase", "ativo:100:10", "--fase", "sleep:1:90"])
        self.assertEqual(codigo, 0)
        texto = saida.getvalue()
        self.assertIn("10.9 mA", texto)
        self.assertIn("91.7 h", texto)
        self.assertLess(texto.index("ativo"), texto.index("sleep"))  # maior consumo primeiro

    def test_erro_de_dados(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.main(["--capacidade", "1000", "--fase", "x:0:10"]), 2)


if __name__ == "__main__":
    unittest.main()
