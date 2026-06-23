"""
Utilidades para descubrir automáticamente, dentro de la carpeta de una
empresa (ej. data/toptur/), qué subcarpetas corresponden a meses con
datos de expediciones (Abril26, Mayo26, Junio26, ...).
"""

import re
from pathlib import Path

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def parsear_carpeta_mes(nombre_carpeta: str) -> tuple[str, int, str, int]:
    """
    Interpreta nombres de carpeta tipo "Abril26", "Mayo26", "Junio2026"
    y retorna (mes_nombre, mes_num, anio_str, anio_num).
    """
    match = re.match(r"([A-Za-zÁÉÍÓÚáéíóúñÑ]+)(\d+)", nombre_carpeta)
    if not match:
        raise ValueError(f"No se pudo interpretar el nombre de carpeta: '{nombre_carpeta}'")

    mes_nombre, anio_str = match.group(1), match.group(2)
    mes_num = MESES.get(mes_nombre.lower())
    if mes_num is None:
        raise ValueError(f"Mes no reconocido en carpeta '{nombre_carpeta}': '{mes_nombre}'")

    anio_num = int(anio_str)
    if anio_num < 100:  # "26" -> 2026
        anio_num += 2000

    return mes_nombre, mes_num, anio_str, anio_num


def listar_meses(empresa_dir: Path) -> list[dict]:
    """
    Recorre las subcarpetas directas de empresa_dir. Cada subcarpeta que
    contenga al menos un archivo .xls/.xlsx se interpreta como un mes con
    datos de expediciones.

    Retorna una lista de dicts, ordenada cronológicamente, con las claves:
        carpeta, mes_nombre, mes_num, anio_str, anio_num, expediciones_path

    Si el nombre de una carpeta no se logra interpretar (o no contiene
    ningún .xls/.xlsx), esa carpeta se omite con un aviso por consola,
    sin detener la ejecución del resto.
    """
    meses = []

    for carpeta in sorted(p for p in empresa_dir.iterdir() if p.is_dir()):
        candidatos = sorted(carpeta.glob("*.xls")) + sorted(carpeta.glob("*.xlsx"))
        if not candidatos:
            continue

        try:
            mes_nombre, mes_num, anio_str, anio_num = parsear_carpeta_mes(carpeta.name)
        except ValueError as e:
            print(f"  Saltando carpeta '{carpeta.name}': {e}")
            continue

        meses.append(
            {
                "carpeta": carpeta,
                "mes_nombre": mes_nombre,
                "mes_num": mes_num,
                "anio_str": anio_str,
                "anio_num": anio_num,
                "expediciones_path": candidatos[0],
            }
        )

    meses.sort(key=lambda m: (m["anio_num"], m["mes_num"]))
    return meses
