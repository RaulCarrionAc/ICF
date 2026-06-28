"""
Carga de las dos fuentes de datos del cálculo de ICF:

- Expediciones observadas (.xls, HTML exportado por el sistema): se
  cuenta cuántas expediciones válidas hubo por fecha/servicio/sentido/
  tipo_dia/periodo.
- Frecuencias fijas (A1, .xlsx): la exigencia de frecuencia (EE) por
  servicio/sentido/periodo/tipo_dia/tipo_demanda.
"""

from pathlib import Path
import re

import holidays
import numpy as np
import pandas as pd


def _calcular_tipo_dia(fechas: pd.Series) -> pd.Series:
    """
    Calcula tipo_dia (DL/DS/DF) a partir de una serie de fechas, usando la
    librería 'holidays' para festivos de Chile. Es la única fuente de
    verdad para tipo_dia en todo el pipeline: nunca se debe leer desde un
    archivo de expediciones, porque tipo_dia es un dato de calendario que
    existe independientemente de si hubo o no expediciones ese día.
    """
    anios = fechas.dt.year.unique().tolist()
    feriados_cl = holidays.Chile(years=anios)

    es_feriado = fechas.apply(lambda x: x in feriados_cl)
    es_domingo = fechas.dt.weekday == 6
    es_sabado = fechas.dt.weekday == 5

    condiciones = [es_feriado | es_domingo, es_sabado]
    valores = ["DF", "DS"]
    return pd.Series(np.select(condiciones, valores, default="DL"), index=fechas.index)


def construir_calendario_mes(anio: int, mes: int, fecha_corte=None) -> pd.DataFrame:
    """
    Construye el calendario completo (Fecha, tipo_dia) de TODOS los días
    de un mes, sin importar si hubo o no expediciones registradas ese día.
    
    Si se entrega una fecha_corte (ej. para meses en curso), el calendario
    se trunca hasta esa fecha para evitar rellenar días futuros con 0.
    """
    inicio_mes = pd.Timestamp(year=anio, month=mes, day=1)
    fin_mes = inicio_mes + pd.offsets.MonthEnd(0)
    
    #esto corta el mes para cuando querramos calcular en un mes que no ha terminado aun
    if fecha_corte is not None:
        fecha_corte = pd.Timestamp(fecha_corte)
        if fecha_corte < fin_mes:
            fin_mes = fecha_corte

    fechas = pd.Series(pd.date_range(start=inicio_mes, end=fin_mes, freq="D"))

    return pd.DataFrame({"Fecha": fechas, "tipo_dia": _calcular_tipo_dia(fechas)})


FUENTES_EXPEDICIONES = ("transidea", "citymovil")


def leer_expediciones(ruta_expediciones: Path, fuente: str = "transidea") -> pd.DataFrame:
    """
    Lee el archivo de expediciones y retorna el conteo de expediciones
    válidas por fecha/servicio/sentido/tipo_dia/periodo, sin importar la
    fuente (proveedor) de la que provenga.

    Parámetros
    ----------
    ruta_expediciones : Path
        Ruta al archivo de expediciones.
    fuente : str
        Proveedor del archivo: "transidea" (HTML disfrazado de .xls,
        usado por lider/toptur) o "citymovil" (.xlsx, usado por tasacop).
    """
    if fuente == "transidea":
        return _leer_expediciones_transidea(ruta_expediciones)
    elif fuente == "citymovil":
        return _leer_expediciones_citymovil(ruta_expediciones)
    else:
        raise ValueError(
            f"Fuente de expediciones desconocida: '{fuente}'. "
            f"Opciones válidas: {FUENTES_EXPEDICIONES}"
        )


def _leer_expediciones_transidea(ruta_expediciones: Path) -> pd.DataFrame:
    """
    Lee el archivo de expediciones de Transidea (.xls, en realidad HTML) y
    retorna el conteo de expediciones válidas por
    fecha/servicio/sentido/tipo_dia/periodo.
    """
    df_exp = pd.read_html(ruta_expediciones, flavor="lxml")[0]
    df_exp["Fecha"] = pd.to_datetime(df_exp["Fecha"])
    df_exp["tipo_dia"] = _calcular_tipo_dia(df_exp["Fecha"])

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


# Mapeos de los códigos de Citymovil hacia los códigos internos usados en
# el resto del pipeline (los mismos que produce Transidea).
_TIPO_DIA_CITYMOVIL = {
    "DLN": "DL",  # Día Laboral Normal
    "SAB": "DS",  # Sábado
    "DOM": "DF",  # Domingo/Feriado
}
_SENTIDO_CITYMOVIL = {
    "IDA": "I",
    "REG": "R",
}


def _leer_expediciones_citymovil(ruta_expediciones: Path) -> pd.DataFrame:
    """
    Lee el archivo de expediciones de Citymovil (.xlsx, usado por tasacop)
    y retorna el conteo de expediciones válidas por
    fecha/servicio/sentido/tipo_dia/periodo.

    Particularidades del formato Citymovil vs Transidea:
      - El servicio y el sentido vienen mezclados en la columna 'Variante'
        (ej. 'R792', 'R792V', 'R790V_R', 'R793_I'); el sufijo '_I'/'_R' es
        inconsistente (a veces está, a veces no, y no siempre coincide con
        la dirección real), así que se descarta y el sentido real se toma
        de la columna 'Dirección' ('Ida'/'Reg').
      - 'Estado' usa tildes ('Válida'/'Inválida') en vez de 'Valida'.
      - La columna de periodo se llama 'Período' (con tilde).
      - Citymovil entrega su propia columna 'Tipo de Día' (DLN/SAB/DOM),
        pero NO se usa directamente: tipo_dia es un dato de calendario
        puro (festivo/sábado/laboral) que no depende de si hubo o no
        expediciones ese día, así que tomarlo de una fila del archivo
        omitiría aquellos días en que el servicio no circuló (no existe
        fila → no hay de dónde leerlo). Por eso se calcula igual que en
        Transidea, con la librería 'holidays', a partir de 'Fecha'. La
        columna del proveedor solo se usa para validar que no haya
        discrepancias (típicamente por feriados no actualizados).
    """
    df_exp = pd.read_excel(ruta_expediciones, sheet_name="Datos")
    df_exp["Fecha"] = pd.to_datetime(df_exp["Fecha"])

    # tipo_dia: calculado a partir de la fecha, no leído del archivo
    df_exp["tipo_dia"] = _calcular_tipo_dia(df_exp["Fecha"])

    # Validación cruzada (no bloqueante) contra la columna del proveedor
    if "Tipo de Día" in df_exp.columns:
        tipo_dia_proveedor = (
            df_exp["Tipo de Día"].astype(str).str.strip().str.upper().map(_TIPO_DIA_CITYMOVIL)
        )
        discrepancias = df_exp.loc[
            tipo_dia_proveedor.notna() & (tipo_dia_proveedor != df_exp["tipo_dia"]),
            "Fecha",
        ].unique()
        if len(discrepancias) > 0:
            print(
                f"  Aviso: 'Tipo de Día' de Citymovil no coincide con el calculado "
                f"(holidays) para las fechas: {sorted(pd.to_datetime(discrepancias).date.tolist())}"
            )

    # Servicio: la 'Variante' sin el sufijo de sentido redundante (_I/_R)
    df_exp["servicio_str"] = (
        df_exp["Variante"].astype(str).str.strip().str.replace(r"_(I|R)$", "", regex=True)
    )

    # Sentido: tomado de 'Dirección', no del sufijo de 'Variante'
    sentido_normalizado = df_exp["Dirección"].astype(str).str.strip().str.upper()
    df_exp["sentido_str"] = sentido_normalizado.map(_SENTIDO_CITYMOVIL)
    sentidos_no_mapeados = sentido_normalizado[df_exp["sentido_str"].isna()].unique()
    if len(sentidos_no_mapeados) > 0:
        raise ValueError(
            f"Valores de 'Dirección' no reconocidos en archivo Citymovil: "
            f"{list(sentidos_no_mapeados)}"
        )

    df_exp["periodo_num"] = pd.to_numeric(df_exp["Período"], errors="coerce").astype("Int64")

    filtro_valida = df_exp["Estado"].astype(str).str.strip().str.upper() == "VÁLIDA"
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
    Busca el archivo de frecuencias fijas (anexo A1, .xlsx) ubicado
    directamente en empresa_dir (sin entrar a las subcarpetas de mes).
    Se asume que cada empresa tiene un único A1 vigente para todos sus
    meses.

    El ICF solo se calcula con el anexo A1. Otros anexos que puedan
    convivir en la misma carpeta (ej. A5, usado para otra métrica) se
    ignoran explícitamente: no se "prefieren" sobre ellos, se descartan
    por completo, para no depender del orden alfabético ni arrastrar por
    error un archivo que no corresponde.
    """
    candidatos = sorted(empresa_dir.glob("*.xlsx"))
    if not candidatos:
        raise FileNotFoundError(
            f"No se encontró ningún archivo de frecuencias fijas (.xlsx) en {empresa_dir}"
        )

    patron_a1 = re.compile(r"(?<![A-Za-z0-9])A1(?![A-Za-z0-9])")
    candidatos_a1 = [c for c in candidatos if patron_a1.search(c.stem)]
    descartados = [c for c in candidatos if c not in candidatos_a1]

    if not candidatos_a1:
        raise FileNotFoundError(
            f"No se encontró ningún archivo con 'A1' en el nombre en {empresa_dir} "
            f"(el ICF solo se calcula con el anexo A1). Archivos .xlsx presentes: "
            f"{[c.name for c in candidatos]}"
        )

    if descartados:
        print(
            f"  Aviso: se ignoran {len(descartados)} archivo(s) .xlsx sin 'A1' en "
            f"{empresa_dir} (no corresponden al cálculo del ICF): "
            f"{[c.name for c in descartados]}"
        )

    if len(candidatos_a1) > 1:
        print(
            f"  Aviso: hay {len(candidatos_a1)} archivos .xlsx con 'A1' en {empresa_dir}, "
            f"se usará '{candidatos_a1[0].name}'"
        )

    return candidatos_a1[0]


def leer_frecuencias(calendario: pd.DataFrame, ruta_frecuencias: Path) -> pd.DataFrame:
    """
    Lee el archivo de frecuencias fijas (A1) y retorna la exigencia (EE)
    cruzada contra el calendario completo del mes (Fecha, tipo_dia).
    Utiliza busqueda dinamica de encabezados MultiIndex para tolerar 
    ausencia de bloques de días (ej. servicios que no operan sábados).
    """
    excel_completo = pd.ExcelFile(ruta_frecuencias)
    hojas_servicios = [hoja for hoja in excel_completo.sheet_names if "-" in hoja]
    lista_dataframes = []

    for hoja in hojas_servicios:
        # Extraemos el código del servicio y el sentido desde el nombre de la pestaña
        servicio, sentido = hoja.split("-")

        # Leer con MultiIndex (Nivel 0: Tipo de día, Nivel 1: Periodo/Demanda/Frecuencia)
        df_frec = pd.read_excel(excel_completo, sheet_name=hoja, skiprows=10, header=[0, 1])
        df_frec = df_frec.dropna(axis=1, how="all")

        if df_frec.empty:
            continue

        # 1. Identificar la columna 'Periodo' dinámicamente
        col_periodo = None
        for col in df_frec.columns:
            # Buscamos en el segundo nivel del MultiIndex
            if "periodo" in str(col[1]).lower() or "período" in str(col[1]).lower():
                col_periodo = col
                break
        
        # Fallback a la primera columna si no se llama estrictamente 'periodo'
        if not col_periodo:
            col_periodo = df_frec.columns[0] 

        lista_df_dias = []
        
        # 2. Iterar sobre los encabezados de nivel superior ("Día Laboral", "Sábado", etc.)
        niveles_superiores = df_frec.columns.get_level_values(0).unique()

        for lvl0 in niveles_superiores:
            lvl0_str = str(lvl0).lower()
            tipo_dia = None

            # Clasificar el bloque de columnas actual
            if "laboral" in lvl0_str:
                tipo_dia = "DL"
            elif "sabado" in lvl0_str or "sábado" in lvl0_str or "sáb" in lvl0_str:
                tipo_dia = "DS"
            elif "domingo" in lvl0_str or "festivo" in lvl0_str or "dom" in lvl0_str:
                tipo_dia = "DF"

            if tipo_dia:
                # Filtrar solo las columnas que pertenecen a este tipo de día
                cols_lvl0 = [c for c in df_frec.columns if c[0] == lvl0]
                col_demanda, col_frec = None, None

                # 3. Buscar las subcolumnas exactas de Demanda y Frecuencia
                for c in cols_lvl0:
                    c1_str = str(c[1]).lower()
                    if "demanda" in c1_str:
                        col_demanda = c
                    elif "frecuencia" in c1_str:
                        col_frec = c

                # Si el bloque está completo, construimos el sub-dataframe
                if col_demanda and col_frec:
                    df_dia = pd.DataFrame({
                        "periodo": df_frec[col_periodo],
                        "tipo_demanda": df_frec[col_demanda],
                        "frecuencia": df_frec[col_frec],
                        "tipo_dia": tipo_dia
                    })
                    lista_df_dias.append(df_dia)

        if not lista_df_dias:
            continue

        # 4. Consolidar los bloques encontrados para esta hoja
        df_hoja_normalizado = pd.concat(lista_df_dias, ignore_index=True)

        # 5. Limpieza final de filas inútiles (ej. la fila 'Total' o nulos)
        filtro_nulos = df_hoja_normalizado["periodo"].notna()
        filtro_total = df_hoja_normalizado["periodo"].astype(str).str.strip().str.lower() != "total"
        df_hoja_normalizado = df_hoja_normalizado[filtro_nulos & filtro_total].copy()

        # Agregar metadatos de la hoja
        df_hoja_normalizado["servicio"] = servicio
        df_hoja_normalizado["sentido"] = sentido

        lista_dataframes.append(df_hoja_normalizado)

    # Si por alguna razón ningún Excel tenía datos procesables
    if not lista_dataframes:
        return pd.DataFrame(columns=["Fecha", "tipo_dia", "servicio", "sentido", "periodo", "tipo_demanda", "EE"])

    # 6. Unir todas las hojas procesadas
    df_master_frecuencias = pd.concat(lista_dataframes, ignore_index=True)
    
    # Ordenar las columnas al formato esperado por el resto del pipeline
    df_master_frecuencias = df_master_frecuencias[
        ["servicio", "sentido", "periodo", "tipo_dia", "tipo_demanda", "frecuencia"]
    ]

    df_master_frecuencias["periodo"] = pd.to_numeric(
        df_master_frecuencias["periodo"], errors="coerce"
    ).astype("Int64")

    # Filtrar solo filas con tipo de demanda válida y renombrar 'frecuencia' a 'EE'
    df_a1 = df_master_frecuencias[df_master_frecuencias["tipo_demanda"].notna()].copy()
    df_a1 = df_a1.rename(columns={"frecuencia": "EE"})

    # Cruzar contra el calendario
    calendario = calendario[["Fecha", "tipo_dia"]].drop_duplicates()
    df_base_exigida = pd.merge(calendario, df_a1, on="tipo_dia", how="left")
    
    return df_base_exigida