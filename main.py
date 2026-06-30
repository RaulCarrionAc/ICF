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

import sys
from datetime import datetime
from pathlib import Path
import pandas as pd

from src.descubrir import listar_meses
from src.indicadores.icf import (
    calcular_psi,
    construir_resumenes_icf,
    crear_df_icf,
    exportar_resumenes_icf,
    tabla_periodo_vs_fecha,
    proyectar_simulado_estocastico,
    proyectar_ideal,
    crear_tabla_comparativa,
    exportar_reporte_proyeccion,
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

# Fuente (proveedor) del archivo de expediciones de cada empresa.
# "transidea": .xls/HTML (lider, toptur)
# "citymovil": .xlsx (tasacop)
FUENTE_POR_EMPRESA = {
    "lider": "transidea",
    "toptur": "transidea",
    "tasacop": "citymovil",
}


def procesar_mes(
    empresa: str, fuente: str, empresa_dir: Path, ruta_frecuencias: Path, 
    mes_info: dict, df_historico: pd.DataFrame
) -> pd.DataFrame:
    """Calcula y exporta el reporte de ICF para un mes específico. Retorna el df_icf calculado."""
    carpeta = mes_info["carpeta"]
    mes_nombre = mes_info["mes_nombre"]
    anio_str = mes_info["anio_str"]
    expediciones_path = mes_info["expediciones_path"]
    anio_num = mes_info["anio_num"]
    mes_num = mes_info["mes_num"]

    print(f"--- Procesando {empresa} - {mes_nombre}{anio_str} ({carpeta.name}) ---")

    carpeta_salida = SALIDAS / f"{empresa}-{mes_nombre}{anio_str}"
    carpeta_reportes = carpeta_salida / "reporte_servicio_sentido"
    carpeta_salida.mkdir(parents=True, exist_ok=True)
    carpeta_reportes.mkdir(parents=True, exist_ok=True)

    print(f"Leyendo expediciones: {expediciones_path.name}")
    df_conteo = leer_expediciones(expediciones_path, fuente = fuente)
    print(f"Expediciones validas leidas: {df_conteo['expediciones_observadas'].sum()}")

    # Mejora en el truncado del calendario
    hoy = datetime.now()
    es_mes_en_curso = (anio_num == hoy.year and mes_num == hoy.month)
    es_mes_futuro = (anio_num > hoy.year) or (anio_num == hoy.year and mes_num > hoy.month)

    if es_mes_en_curso:
        if df_conteo.empty:
            ultima_fecha = pd.Timestamp(hoy.date())
        else:
            ultima_fecha = df_conteo["Fecha"].max()
        print(f"  Mes en curso. Truncando calendario a la última fecha con datos: {ultima_fecha.strftime('%Y-%m-%d')}")
        calendario_mes = construir_calendario_mes(
            anio_num,
            mes_num,
            fecha_corte = ultima_fecha
        )
    elif es_mes_futuro:
        print(f"  Mes futuro. Truncando calendario a la fecha de hoy: {hoy.strftime('%Y-%m-%d')}")
        calendario_mes = construir_calendario_mes(
            anio_num,
            mes_num,
            fecha_corte = pd.Timestamp(hoy.date())
        )
    else:
        print("  Mes pasado completado. Evaluando mes calendario completo.")
        calendario_mes = construir_calendario_mes(
            anio_num,
            mes_num,
            fecha_corte = None
        )

    print(f"  Leyendo frecuencias fijas: {ruta_frecuencias.name}")
    df_base_exigida = leer_frecuencias(calendario_mes, ruta_frecuencias)

    # 2. Cálculo del ICF 
    df_icf = crear_df_icf(df_base_exigida, df_conteo)
    df_icf["psi"] = calcular_psi(df_icf, mas_de_24_meses=True)
    
    # Obtener el valor de psi del mes
    psi_vigente = 0.95
    if not df_icf.empty and "psi" in df_icf.columns:
        psi_vigente = float(df_icf["psi"].iloc[0])

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

    # Resumen mensual del ICF (Real Observado)
    tabla_por_tipo_demanda, icf_general, tabla_por_tipo_demanda_servicio, icf_pago = construir_resumenes_icf(
        df_icf,
        psi_valor=psi_vigente
    )

    ruta_salida_reporte = carpeta_salida / "reporte.xlsx"
    while True:
        try:
            exportar_resumenes_icf(
                tabla_por_tipo_demanda,
                icf_general,
                tabla_por_tipo_demanda_servicio,
                icf_pago,
                ruta_salida_reporte,
            )
            break
        except PermissionError:
            print(f"\n[ERROR] No se pudo escribir en '{ruta_salida_reporte}'. El archivo está abierto o bloqueado.")
            try:
                input("Por favor, cierre el archivo en Excel y presione ENTER para reintentar (o Ctrl+C para abortar)...")
            except (EOFError, KeyboardInterrupt):
                print("Abortando la escritura.")
                raise

    print(f"  ICF_general = {icf_general}")
    print(f"  ICF_pago = {icf_pago}")
    print(f"  Reporte exportado a {ruta_salida_reporte}")

    # 3. Lógica de Simulación (solo para el mes en curso)
    if es_mes_en_curso:
        print("\n  --- Iniciando Simulación y Proyección para fin de mes ---")
        
        # Obtener calendario completo del mes (sin truncar)
        calendario_completo = construir_calendario_mes(anio_num, mes_num, fecha_corte=None)
        df_base_completa = leer_frecuencias(calendario_completo, ruta_frecuencias)
        
        df_icf_completo = crear_df_icf(df_base_completa, df_conteo)
        df_icf_completo["psi"] = calcular_psi(df_icf_completo, mas_de_24_meses=True)
        
        # Escenario Simulado Estocástico (Opción B con histórico acumulado)
        df_sim = proyectar_simulado_estocastico(df_icf_completo, df_historico, ultima_fecha, seed=42)
        tabla_dem_sim, icf_gen_sim, tabla_serv_sim, icf_pag_sim = construir_resumenes_icf(df_sim, psi_vigente)
        
        # Escenario Ideal
        df_ideal = proyectar_ideal(df_icf_completo, ultima_fecha)
        tabla_dem_ideal, icf_gen_ideal, tabla_serv_ideal, icf_pag_ideal = construir_resumenes_icf(df_ideal, psi_vigente)
        
        # Crear tabla comparativa
        df_comparativa = crear_tabla_comparativa(
            tabla_por_tipo_demanda, icf_general, icf_pago,
            tabla_dem_sim, icf_gen_sim, icf_pag_sim,
            tabla_dem_ideal, icf_gen_ideal, icf_pag_ideal
        )
        
        # Exportar proyecciones
        ruta_salida_proyeccion = carpeta_salida / "reporte_proyeccion.xlsx"
        while True:
            try:
                exportar_reporte_proyeccion(
                    df_comparativa,
                    df_sim,
                    df_ideal,
                    tabla_dem_sim, icf_gen_sim, tabla_serv_sim, icf_pag_sim,
                    tabla_dem_ideal, icf_gen_ideal, tabla_serv_ideal, icf_pag_ideal,
                    ultima_fecha,
                    ruta_salida_proyeccion
                )
                break
            except PermissionError:
                print(f"\n[ERROR] No se pudo escribir en '{ruta_salida_proyeccion}'. El archivo está abierto o bloqueado.")
                try:
                    input("Por favor, cierre el archivo en Excel y presione ENTER para reintentar (o Ctrl+C para abortar)...")
                except (EOFError, KeyboardInterrupt):
                    print("Abortando la escritura.")
                    raise
        
        print("  Proyecciones guardadas en:", ruta_salida_proyeccion)
        print("\n  >>> COMPARATIVA DE PROYECCIONES (Fin de Mes) <<<")
        print(df_comparativa.to_string(index=False))
        print("  ================================================\n")

    return df_icf


def main() -> None:
    # Lista de empresas a procesar
    empresas_a_procesar = []
    
    if len(sys.argv) > 1:
        # Se especificó una empresa por consola
        empresa_solicitada = sys.argv[1].lower()
        if empresa_solicitada in FUENTE_POR_EMPRESA:
            empresas_a_procesar = [empresa_solicitada]
        else:
            print(f"Error: La empresa '{empresa_solicitada}' no está en la configuración.")
            print(f"Empresas válidas: {list(FUENTE_POR_EMPRESA.keys())}")
            sys.exit(1)
    else:
        # Modo por defecto: procesar todas las empresas configuradas cuyas carpetas existan en data/
        print("Ejecutando en modo por defecto (procesando todas las empresas configuradas)...")
        for emp in FUENTE_POR_EMPRESA.keys():
            if (DATA / emp).exists():
                empresas_a_procesar.append(emp)
        
        if not empresas_a_procesar:
            print(f"No se encontraron carpetas para ninguna de las empresas en {DATA}")
            return
            
    print(f"Empresas a procesar: {empresas_a_procesar}")
    print()

    # Estructura para acumular historial de datos observados por empresa
    historico_por_empresa = {}

    for empresa in empresas_a_procesar:
        fuente = FUENTE_POR_EMPRESA[empresa]
        empresa_dir = DATA / empresa
        
        print(f"============================================================")
        print(f"PROCESANDO EMPRESA: {empresa.upper()} (Fuente: {fuente})")
        print(f"============================================================")
        
        meses = listar_meses(empresa_dir)
        if not meses:
            print(f"No se encontraron carpetas de mes con datos en {empresa_dir}")
            continue

        # Inicializar el DataFrame de historial acumulado para esta empresa
        historico_por_empresa[empresa] = pd.DataFrame()

        try:
            ruta_frecuencias = buscar_frecuencias_fijas(empresa_dir)
            print(f"Frecuencias fijas encontradas: {ruta_frecuencias.name}")
            print()
            
            for mes_info in meses:
                try:
                    df_icf = procesar_mes(
                        empresa, fuente, empresa_dir, ruta_frecuencias, 
                        mes_info, df_historico=historico_por_empresa[empresa]
                    )
                    # Acumular el df_icf observado en el histórico cronológico
                    if df_icf is not None and not df_icf.empty:
                        historico_por_empresa[empresa] = pd.concat(
                            [historico_por_empresa[empresa], df_icf], 
                            ignore_index=True
                        )
                except Exception as e:
                    print(f"  ERROR procesando '{mes_info['carpeta'].name}': {e}")
                print()
        except Exception as e:
            print(f"ERROR al inicializar la empresa '{empresa}': {e}")
        print()


if __name__ == "__main__":
    main()