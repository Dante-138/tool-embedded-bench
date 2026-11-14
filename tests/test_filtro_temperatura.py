import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from dados import filtro_temperatura as m


class TestMediaAparada(unittest.TestCase):
    def test_serie_simples(self):
        # 20 amostras, corte de 5 de cada lado: média de 6..15 = 10,5
        self.assertAlmostEqual(m.media_aparada(list(range(1, 21))), 10.5)

    def test_extremos_absurdos_sao_descartados(self):
        amostras = list(range(1, 19)) + [1000, -1000]
        self.assertAlmostEqual(m.media_aparada(amostras), 9.5)  # média de 5..14

    def test_ordem_das_amostras_nao_importa(self):
        amostras = [3, 9, 1, 7, 5, 100, -50, 4]
        self.assertAlmostEqual(m.media_aparada(amostras), m.media_aparada(sorted(amostras)))

    def test_corte_usa_divisao_inteira_como_o_firmware(self):
        # 5 amostras: 5*25//100 = 1 de cada lado, sobra 3.
        self.assertAlmostEqual(m.media_aparada([1, 2, 3, 4, 100]), 3.0)

    def test_sem_nada_sobrando(self):
        with self.assertRaises(ValueError):
            m.media_aparada([1.0, 2.0], trim_pct=50)


class TestEMA(unittest.TestCase):
    def test_primeira_leitura_inicializa_o_filtro(self):
        self.assertEqual(m.ema([0.0, 10.0]), [0.0, 3.0])

    def test_sequencia_de_referencia(self):
        e = m.ema([10, 20, 30], alpha=0.3)
        self.assertAlmostEqual(e[0], 10.0)
        self.assertAlmostEqual(e[1], 13.0)
        self.assertAlmostEqual(e[2], 18.1)

    def test_serie_constante_nao_muda(self):
        self.assertEqual(m.ema([21.5] * 6), [21.5] * 6)

    def test_alpha_um_repete_a_entrada(self):
        serie = [1.0, 5.0, 2.0]
        self.assertEqual(m.ema(serie, alpha=1.0), serie)

    def test_serie_vazia_e_alpha_invalido(self):
        self.assertEqual(m.ema([]), [])
        for alpha in (0, -0.1, 1.5):
            with self.subTest(alpha=alpha), self.assertRaises(ValueError):
                m.ema([1.0], alpha)


class TestOutliers(unittest.TestCase):
    def test_serie_com_um_pico(self):
        serie = [20.0, 21.0, 19.0, 20.5, 19.5, 20.2, 60.0]
        self.assertEqual(m.marcar_outliers(serie), [False] * 6 + [True])

    def test_mad_zero_usa_o_desvio_medio(self):
        self.assertEqual(m.marcar_outliers([20, 20, 20, 20, 35]), [False] * 4 + [True])

    def test_serie_constante_nao_tem_outlier(self):
        self.assertEqual(m.marcar_outliers([20.0] * 8), [False] * 8)

    def test_serie_curta_demais(self):
        self.assertEqual(m.marcar_outliers([1.0, 100.0]), [False, False])

    def test_variacao_normal_nao_e_marcada(self):
        serie = [20.0 + 0.5 * (i % 5) for i in range(30)]
        self.assertFalse(any(m.marcar_outliers(serie)))


CSV_EXEMPLO = """hora;temperatura;bateria
10:00;20,0;4,10
10:01;20,5;4,10
10:02;19,5;4,09
10:03;20,2;4,09
10:04;n/d;4,09
10:05;19,8;4,08
10:06;90,0;4,08
10:07;20,1;4,08
"""


class TestProcessarCSV(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.entrada = self.dir / "leituras.csv"
        self.entrada.write_text(CSV_EXEMPLO, encoding="utf-8")

    def processar(self, **kw):
        return m.processar(self.entrada, "temperatura", sep=";", decimal=",", **kw)

    def test_acrescenta_colunas_e_marca_o_pico(self):
        df = self.processar()
        self.assertIn("temperatura_ema", df.columns)
        self.assertIn("temperatura_outlier", df.columns)
        self.assertEqual(df.loc[df["temperatura_outlier"].fillna(False).astype(bool), "hora"].tolist(), ["10:06"])

    def test_linha_sem_valor_numerico_fica_vazia_e_nao_vira_falso(self):
        df = self.processar()
        linha = df[df["hora"] == "10:04"].iloc[0]
        self.assertTrue(pd.isna(linha["temperatura_ema"]))
        self.assertTrue(pd.isna(linha["temperatura_outlier"]))

    def test_descartar_outliers_tira_o_pico_do_ema(self):
        com = self.processar()
        sem = self.processar(descartar_outliers=True)
        self.assertGreater(com.loc[7, "temperatura_ema"], 25)
        self.assertLess(sem.loc[7, "temperatura_ema"], 21)
        self.assertTrue(pd.isna(sem.loc[6, "temperatura_ema"]))

    def test_grava_csv_e_grafico(self):
        saida, grafico = self.dir / "s" / "filtrado.csv", self.dir / "g" / "temp.png"
        self.processar(saida=saida, grafico=grafico)
        relido = pd.read_csv(saida, sep=";", decimal=",")
        self.assertIn("temperatura_ema", relido.columns)
        self.assertEqual(len(relido), 8)
        self.assertEqual(grafico.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_colunas_originais_voltam_identicas_no_csv_de_saida(self):
        saida = self.dir / "filtrado.csv"
        self.processar(saida=saida)
        linhas = saida.read_text(encoding="utf-8").splitlines()
        self.assertEqual(linhas[0], "hora;temperatura;bateria;temperatura_ema;temperatura_outlier")
        self.assertTrue(linhas[1].startswith("10:00;20,0;4,10;20,0;False"))
        self.assertEqual(linhas[5], "10:04;n/d;4,09;;")  # célula não numérica intacta, sem EMA

    def test_decimal_errado_gera_erro_com_dica_das_opcoes(self):
        with self.assertRaises(ValueError) as ctx:
            m.processar(self.entrada, "temperatura", sep=";", decimal=".")  # arquivo usa vírgula
        self.assertIn("--decimal", str(ctx.exception))

    def test_coluna_inexistente_lista_as_colunas_do_arquivo(self):
        with self.assertRaises(ValueError) as ctx:
            m.processar(self.entrada, "temp", sep=";", decimal=",")
        self.assertIn("temperatura", str(ctx.exception))

    def test_coluna_sem_numeros(self):
        with self.assertRaises(ValueError):
            m.processar(self.entrada, "hora", sep=";", decimal=",")

    def test_cli(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = m.main([str(self.entrada), "--coluna", "temperatura", "--sep", ";", "--decimal", ","])
        self.assertEqual(codigo, 0)
        self.assertIn("8 linhas | 1 outlier(s)", saida.getvalue())

    def test_cli_arquivo_inexistente(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.main([str(self.dir / "nao_existe.csv"), "--coluna", "x"]), 2)


if __name__ == "__main__":
    unittest.main()
