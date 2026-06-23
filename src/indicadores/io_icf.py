"""
Carga de las dos fuentes de datos del cálculo de ICF:

- Expediciones observadas (.xls, HTML exportado por el sistema): se
  cuenta cuántas expediciones válidas hubo por fecha/servicio/sentido/
  tipo_dia/periodo.
- Frecuencias fijas (A1, .xlsx): la exigencia de frecuencia (EE) por
  servicio/sentido/periodo/tipo_dia/tipo_demanda.
"""

from pathlib import Path

import holidays
import numpy as np
import pandas as pd


def leer_expediciones(ruta_expediciones: Path) -> pd.DataFrame:
    """
    Lee el archivo de expediciones (.xls, en realidad HTML) y retorna el
    conteo de expediciones válidas por fecha/servicio/sentido/tipo_dia/periodo.
    """
    df_exp = pd.read_html(ruta_expediciones, flavor="lxml")[0]
    df_exp["Fecha"] = pd.to_datetime(df_exp["Fecha"])

    anios = df_exp["Fecha"].dt.year.unique().tolist()
    feriados_cl = holidays.Chile(years=anios)

    es_feriado = df_exp["Fecha"].apply(lambda x: x in feriados_cl)
    es_domingo = df_exp["Fecha"].dt.weekday == 6
    es_sabado = df_exp["Fecha"].dt.weekday == 5

    condiciones = [es_feriado | es_domingo, es_sabado]
    valores = ["DF", "DS"]
    df_exp["tipo_dia"] = np.select(condiciones, valores, default="DL")

    df_exp["sentido_str"] = df_exp["Sentido"].astype(str).str.strip().str.upper().str[0]
    df_exp["servicio_str"] = df_exp["Servicio"].astype(str).str.strip()
    df_exp["periodo_num"] = pd.to_numeric(df_exp["Periodo"], errors="coerce").astype("Int64")
    filtro_valida = df_exp["Estado"].astype(str).str.strip() == "Valida"
    df_exp_validas = df_exp[filtro_valida].copy()

    df_conteo = (
        df_exp_validas.groupby(["Fecha", "servicio_str", "sentido_str", "tipo_dia", "periodo_num"])
        .size()
        .reset_index(name="expediciones_observadas")
    )

    df_conteo.rename(
        columns={
            "servicio_str": "servicio",
            "sentido_str": "sentido",
            "periodo_num": "periodo",
        },
        inplace=True,
    )
    return df_conteo


def buscar_frecuencias_fijas(empresa_dir: Path) -> Path:
    """
    Busca el archivo de frecuencias fijas (A1, .xlsx) ubicado directamente
    en empresa_dir (sin entrar a las subcarpetas de mes). Se asume que
    cada empresa tiene un único A1 vigente para todos sus meses.

    Si hay más de uno, se usa el primero (ordenado alfabéticamente) y se
    avisa por consola.
    """
    candidatos = sorted(empresa_dir.glob("*.xlsx"))
    if not candidatos:
        raise FileNotFoundError(
            f"No se encontró ningún archivo de frecuencias fijas (.xlsx) en {empresa_dir}"
        )
    if len(candidatos) > 1:
        print(
            f"  Aviso: hay {len(candidatos)} archivos .xlsx en {empresa_dir}, "
            f"se usará '{candidatos[0].name}'"
        )
    return candidatos[0]


def leer_frecuencias(df_conteo: pd.DataFrame, ruta_frecuencias: Path) -> pd.DataFrame:
    """
    Lee el archivo de frecuencias fijas (A1) y retorna la exigencia (EE)
    cruzada contra el calendario real de fechas/tipo_dia de df_conteo.
    """
    excel_completo = pd.ExcelFile(ruta_frecuencias)

    hojas_servicios = [hoja for hoja in excel_completo.sheet_names if "-" in hoja]

    lista_dataframes = []

    for hoja in hojas_servicios:
        # Extraemos el código del servicio y el sentido desde el nombre de la pestaña
        # Ej: '701-I' -> servicio='701', sentido='I'
        servicio, sentido = hoja.split("-")

        df_frec = pd.read_excel(excel_completo, sheet_name=hoja, skiprows=10, header=[0, 1])
        df_frec = df_frec.dropna(axis=1, how="all")
        df_frec = df_frec[df_frec.iloc[:, 0].astype(str).str.strip().str.lower() != "total"]

        if df_frec.empty:
            continue

        # Asignar las columnas aplanadas
        df_frec.columns = [
            "periodo",
            "horario",
            "demanda_DL",
            "frecuencia_DL",
            "demanda_DS",
            "frecuencia_DS",
            "demanda_DF",
            "frecuencia_DF",
        ]

        # Separar y etiquetar por tipo de día
        df_dl = df_frec[["periodo", "demanda_DL", "frecuencia_DL"]].copy()
        df_dl["tipo_dia"] = "DL"
        df_dl.rename(columns={"demanda_DL": "tipo_demanda", "frecuencia_DL": "frecuencia"}, inplace=True)

        df_ds = df_frec[["periodo", "demanda_DS", "frecuencia_DS"]].copy()
        df_ds["tipo_dia"] = "DS"
        df_ds.rename(columns={"demanda_DS": "tipo_demanda", "frecuencia_DS": "frecuencia"}, inplace=True)

        df_df = df_frec[["periodo", "demanda_DF", "frecuencia_DF"]].copy()
        df_df["tipo_dia"] = "DF"
        df_df.rename(columns={"demanda_DF": "tipo_demanda", "frecuencia_DF": "frecuencia"}, inplace=True)

        df_hoja_normalizado = pd.concat([df_dl, df_ds, df_df], ignore_index=True)
        df_hoja_normalizado["servicio"] = servicio
        df_hoja_normalizado["sentido"] = sentido

        lista_dataframes.append(df_hoja_normalizado)

    df_master_frecuencias = pd.concat(lista_dataframes, ignore_index=True)
    df_master_frecuencias = df_master_frecuencias[
        ["servicio", "sentido", "periodo", "tipo_dia", "tipo_demanda", "frecuencia"]
    ]

    df_master_frecuencias["periodo"] = pd.to_numeric(
        df_master_frecuencias["periodo"], errors="coerce"
    ).astype("Int64")

    df_a1 = df_master_frecuencias[df_master_frecuencias["tipo_demanda"].notna()].copy()
    df_a1 = df_a1.rename(columns={"frecuencia": "EE"})

    calendario = df_conteo[["Fecha", "tipo_dia"]].drop_duplicates()
    df_base_exigida = pd.merge(calendario, df_a1, on="tipo_dia", how="left")
    return df_base_exigida
