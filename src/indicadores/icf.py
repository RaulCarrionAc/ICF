import pandas as pd
import numpy as np
import holidays
from pathlib import Path

def crear_df_icf(df_a1:pd.DataFrame, df_conteo:pd.DataFrame)->pd.DataFrame:
    df_icf = pd.merge(
        df_a1,
        df_conteo,
        on = ["Fecha","servicio","sentido","tipo_dia","periodo"],
        how="left",
    )

    df_icf = df_icf.rename(columns = {"expediciones_observadas": "EO"})
    df_icf["EO"] = df_icf["EO"].fillna(0)
    df_icf['ICF'] = np.floor(np.minimum(df_icf['EE'], df_icf['EO']) / df_icf['EE'] * 100 + 0.5) / 100
    return df_icf

def calcular_psi(df,fecha_columna="Fecha",fecha_inicio_operacion=None,mas_de_24_meses=None):
    """
    Calcula el parámetro psi (ψ) según la antigüedad de la operación,
    de acuerdo a lo indicado en la Res. 49/2024 (pág. 41):
        - Hasta el mes 24 de operación: psi = 0,90
        - Desde el mes 25 en adelante:  psi = 0,95

    Parámetros
    ----------
    df : DataFrame
        DataFrame que contiene la columna de fecha sobre la que se calculará psi.
    fecha_columna : str
        Nombre de la columna de fecha en df (default 'Fecha').
    fecha_inicio_operacion : str o Timestamp, opcional
        Fecha de inicio de operación del Perímetro de Exclusión. Si se entrega,
        psi se calcula automáticamente fila por fila según la antigüedad real
        a la fecha de cada registro.
    mas_de_24_meses : bool, opcional
        Si no quieres calcular la antigüedad real (por ejemplo, para otros
        servicios donde solo sabes "ya superó los 24 meses" o no), puedes
        forzar el valor directamente: True -> psi=0.95 para todo el df,
        False -> psi=0.90 para todo el df.

    Debes entregar UNO de los dos parámetros: fecha_inicio_operacion o mas_de_24_meses.

    Retorna
    -------
    Series con el valor de psi para cada fila de df.
    """
    if fecha_inicio_operacion is None and mas_de_24_meses is None:
        raise ValueError(
            "Debes especificar 'fecha_inicio_operacion' o 'mas_de_24_meses'."
        )

    if mas_de_24_meses is not None:
        # Modo simple: se fuerza el mismo psi para todo el dataframe
        return pd.Series(0.95 if mas_de_24_meses else 0.90, index=df.index)

    # Modo automático: calcular antigüedad real fila por fila
    fecha_inicio_operacion = pd.Timestamp(fecha_inicio_operacion)

    def mes_operacion(fecha):
        return (fecha.year - fecha_inicio_operacion.year) * 12 + (fecha.month - fecha_inicio_operacion.month) + 1

    meses_operacion = df[fecha_columna].apply(mes_operacion)
    return np.where(meses_operacion <= 24, 0.90, 0.95)

def tabla_periodo_vs_fecha(df_icf, servicio, sentido):
    """
    Reproduce la tabla 'periodo x fecha' (con promedio final) usando la
    razón cruda EO/EE (SIN aplicar el min/cap del ICF normativo) — esto
    es lo que muestra el reporte de referencia, no el ICF oficial.
    """
    df_filtro = df_icf[
        (df_icf['servicio'] == servicio) &
        (df_icf['sentido'] == sentido)
    ].copy()

    # Razón cruda, sin el cap de min(EE,EO)
    df_filtro['ratio_crudo'] = df_filtro['EO'] / df_filtro['EE']

    tabla = df_filtro.pivot_table(
        index='periodo',
        columns='Fecha',
        values='ratio_crudo',
        aggfunc='mean'   # por si hay más de una fila por periodo-fecha (no debería)
    )

    # Formatear columnas de fecha igual al reporte (YYYY-MM-DD)
    tabla.columns = [c.strftime('%Y-%m-%d') for c in tabla.columns]

    # Agregar columna de promedio simple por periodo (a través de todas las fechas)
    tabla['Promedio'] = tabla.mean(axis=1).round(2)

    return tabla

def aplicar_regla_pago(icf, psi=0.95):
    if icf < 0.50:
        return 0.50
    elif icf > psi:
        return 1.00
    else:
        return icf


def construir_resumenes_icf(df_icf: pd.DataFrame):
    """
    Construye los 3 resúmenes del ICF a nivel mensual:

    1. tabla_por_tipo_demanda: ICF promedio por tipo de demanda
       (df_icf.groupby("tipo_demanda")["ICF"].mean().round(2))
    2. icf_general: promedio simple de los promedios anteriores
       (tabla_por_tipo_demanda.mean().round(3))
    3. tabla_por_tipo_demanda_servicio: ICF promedio por tipo de demanda
       y servicio
       (df_icf.groupby(["tipo_demanda","servicio"])["ICF"].mean().round(2))

    Retorna (tabla_por_tipo_demanda, icf_general, tabla_por_tipo_demanda_servicio)
    """
    tabla_por_tipo_demanda = df_icf.groupby("tipo_demanda")["ICF"].mean().round(2)
    icf_general = round(tabla_por_tipo_demanda.mean(), 3)
    tabla_por_tipo_demanda_servicio = (
        df_icf.groupby(["tipo_demanda", "servicio"])["ICF"].mean().round(2)
    )

    return tabla_por_tipo_demanda, icf_general, tabla_por_tipo_demanda_servicio


def exportar_resumenes_icf(
    tabla_por_tipo_demanda: pd.Series,
    icf_general: float,
    tabla_por_tipo_demanda_servicio: pd.Series,
    ruta_archivo: Path
) -> None:
    """
    Exporta los 3 resúmenes del ICF a un único Excel, cada uno en su
    propia hoja.
    """
    df_tipo_demanda = tabla_por_tipo_demanda.reset_index().rename(
        columns={"ICF": "ICF_promedio"}
    )
    df_general = pd.DataFrame({"ICF_general": [icf_general]})
    df_tipo_demanda_servicio = tabla_por_tipo_demanda_servicio.reset_index().rename(
        columns={"ICF": "ICF_promedio"}
    )

    with pd.ExcelWriter(ruta_archivo, engine="openpyxl") as writer:
        df_tipo_demanda.to_excel(writer, sheet_name="Por_TipoDemanda", index=False)
        df_general.to_excel(writer, sheet_name="ICF_General", index=False)
        df_tipo_demanda_servicio.to_excel(
            writer, sheet_name="Por_TipoDemanda_Servicio", index=False
        )