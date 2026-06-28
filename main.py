"""
Punto de entrada del cálculo del indice de Cumplimiento de Frecuencia (ICF).

Recorre automaticamente todas las carpetas de mes con datos dentro de
data/<EMPRESA>/ (ej. Abril26, Mayo26, Junio26, ...) y genera un reporte
por cada una.

Estructura de carpetas esperada:

    proyecto/
    ├── main.py
    ├── src/
    │   ├── descubrir.py
    │   └── indicadores/
    │       ├── io_icf.py
    │       └── icf.py
    └── data/
        └── toptur/
            ├── POT_..._A1_2.xlsx        (frecuencias fijas, único por empresa)
            ├── Abril26/
            │   └── expediciones_toptur_abril26.xls
            ├── Mayo26/
            │   └── expediciones.xls
            └── ...

"""

from pathlib import Path

from src.descubrir import listar_meses
from src.indicadores.icf import (
    calcular_psi,
    construir_resumenes_icf,
    crear_df_icf,
    exportar_resumenes_icf,
    tabla_periodo_vs_fecha,
)

from src.indicadores.io_icf import (
    buscar_frecuencias_fijas,
    construir_calendario_mes,
    leer_expediciones,
    leer_frecuencias,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SALIDAS = ROOT / "salidas"

# Nombre de la empresa = nombre de la carpeta dentro de data/
EMPRESA = "lider"
EMPRESA_DIR = DATA / EMPRESA

# Fuente (proveedor) del archivo de expediciones de cada empresa.
# "transidea": .xls/HTML (lider, toptur)
# "citymovil": .xlsx (tasacop)
FUENTE_POR_EMPRESA = {
    "lider": "transidea",
    "toptur": "transidea",
    "tasacop": "citymovil",
}
FUENTE = FUENTE_POR_EMPRESA[EMPRESA]


def procesar_mes(empresa_dir: Path, ruta_frecuencias: Path, mes_info: dict) -> None:
    """Calcula y exporta el reporte de ICF para un mes específico."""
    carpeta = mes_info["carpeta"]
    mes_nombre = mes_info["mes_nombre"]
    anio_str = mes_info["anio_str"]
    expediciones_path = mes_info["expediciones_path"]

    print(f"--- Procesando {EMPRESA} - {mes_nombre}{anio_str} ({carpeta.name}) ---")

    
    carpeta_salida = SALIDAS / f"{EMPRESA}-{mes_nombre}{anio_str}"
    carpeta_reportes = carpeta_salida / "reporte_servicio_sentido"
    carpeta_salida.mkdir(parents=True, exist_ok=True)
    carpeta_reportes.mkdir(parents=True, exist_ok=True)

    
    # print(f"  Leyendo expediciones: {expediciones_path.name}")
    # df_conteo = leer_expediciones(expediciones_path, fuente=FUENTE)
    # print(f"  Expediciones válidas leídas: {df_conteo['expediciones_observadas'].sum()}")

    # calendario_mes = construir_calendario_mes(mes_info["anio_num"], mes_info["mes_num"])

    print(f"Leyendo expediciones: {expediciones_path.name}")
    df_conteo = leer_expediciones(expediciones_path, fuente = FUENTE)
    print(f"Expediciones validas leidas: {df_conteo["expediciones_observadas"].sum()}")

    #Si cambio fecha_corte con un None realiza todo el mes
    ultima_fecha = df_conteo["Fecha"].max()
    calendario_mes = construir_calendario_mes(
        mes_info["anio_num"],
        mes_info["mes_num"],
        fecha_corte = ultima_fecha
    )

    print(f"  Leyendo frecuencias fijas: {ruta_frecuencias.name}")
    df_base_exigida = leer_frecuencias(calendario_mes, ruta_frecuencias)

    # 2. Cálculo del ICF 
    df_icf = crear_df_icf(df_base_exigida, df_conteo)
    df_icf["psi"] = calcular_psi(df_icf, mas_de_24_meses=True)

    combinaciones = (
        df_icf[["servicio", "sentido"]].drop_duplicates().sort_values(["servicio", "sentido"])
    )
    print(f"  Servicios/sentidos encontrados: {len(combinaciones)}")

    # Reporte periodo x fecha servicio/sentido 
    for _, row in combinaciones.iterrows():
        servicio = row["servicio"]
        sentido = row["sentido"]

        tabla = tabla_periodo_vs_fecha(df_icf, servicio=servicio, sentido=sentido)

        nombre_archivo = f"{servicio}_{sentido}.xlsx"
        tabla.to_excel(carpeta_reportes / nombre_archivo)
        print(f"    Guardado: reporte_servicio_sentido/{nombre_archivo}")

    # Resumen mensual del ICF 
    tabla_por_tipo_demanda, icf_general, tabla_por_tipo_demanda_servicio = construir_resumenes_icf(
        df_icf
    )

    exportar_resumenes_icf(
        tabla_por_tipo_demanda,
        icf_general,
        tabla_por_tipo_demanda_servicio,
        carpeta_salida / "reporte.xlsx",
    )

    print(f"  ICF_general = {icf_general}")
    print(f"  Reporte exportado a {carpeta_salida / 'reporte.xlsx'}")


def main() -> None:
    meses = listar_meses(EMPRESA_DIR)

    if not meses:
        print(f"No se encontraron carpetas de mes con datos en {EMPRESA_DIR}")
        return

    ruta_frecuencias = buscar_frecuencias_fijas(EMPRESA_DIR)
    print(f"Frecuencias fijas de '{EMPRESA}': {ruta_frecuencias.name}")
    print()

    for mes_info in meses:
        try:
            procesar_mes(EMPRESA_DIR, ruta_frecuencias, mes_info)
        except Exception as e:
            print(f"  ERROR procesando '{mes_info['carpeta'].name}': {e}")
        print()


if __name__ == "__main__":
    main()