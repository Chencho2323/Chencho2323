#!/usr/bin/env python3
"""
Genera el grafico de actividad de contribuciones y sincroniza las cifras
publicas del README de perfil.

Datos: el calendario publico de GitHub (el mismo que ve cualquier visitante
sin token). No incluye repositorios privados ni nombres de ningun proyecto:
solo la fecha y el nivel de actividad de cada dia.

Salidas:
    assets/contribuciones.svg   Grafico animado con la paleta de marca
    README.md                    Bloque de cifras, delimitado por marcadores

Uso:
    python3 tools/generar-contribuciones.py
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import date, timedelta
from pathlib import Path

# --- Identidad de marca (mismos tokens que inheritdevs.com) ---------------
TEAL = "#03A8FA"
VIOLET = "#9800E9"
FONDO = "#0C1226"
VACIA = "#111833"
TEXTO = "#8FA3C4"

# Nivel de actividad -> color. El nivel maximo usa violeta para anclar el
# acento de marca y que el pico se lea de un vistazo.
NIVELES = {
    0: VACIA,
    1: "#0B3A5C",
    2: "#0E6FA8",
    3: TEAL,
    4: VIOLET,
}

CELDA = 11
HUECO = 3
RETROCESO = 3  # celdas de margen a la izquierda

ORIGEN = Path(__file__).resolve().parent.parent
DESTINO = ORIGEN / "assets" / "contribuciones.svg"
README = ORIGEN / "README.md"
CACHE = Path("/tmp/cal-contribuciones.json")

URL_CALENDARIO = "https://github.com/users/Chencho2323/contributions"
URL_STREAK = "https://github-readme-streak-stats.herokuapp.com/?user=Chencho2323&theme=dark"
URL_STATS = (
    "https://github-readme-stats.vercel.app/api"
    "?username=Chencho2323&include_all_commits=true"
)
URL_USUARIO = "https://api.github.com/users/Chencho2323"

INICIO_MARCADOR = "<!-- CONTRIBUCIONES:INICIO -->"
FIN_MARCADOR = "<!-- CONTRIBUCIONES:FIN -->"


def _descargar(url: str, timeout: int = 30) -> str:
    peticion = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(peticion, timeout=timeout).read().decode("utf-8", "ignore")


# --- Calendario ------------------------------------------------------------


def calendario() -> list[dict]:
    """Descarga (o reutiliza) el calendario publico de contribuciones."""
    if CACHE.exists():
        try:
            datos = json.loads(CACHE.read_text(encoding="utf-8"))
            if datos:
                return datos
        except (json.JSONDecodeError, OSError):
            pass

    html = _descargar(URL_CALENDARIO)
    patron = re.compile(r'data-date="(\d{4}-\d{2}-\d{2})"[^>]*?data-level="(\d)"')
    celdas = [{"fecha": d, "nivel": int(n)} for d, n in patron.findall(html)]
    if not celdas:
        raise RuntimeError("no se pudo leer el calendario publico de contribuciones")
    CACHE.write_text(json.dumps(celdas), encoding="utf-8")
    return celdas


def total_anio() -> int:
    """Contribuciones del ultimo ano, tal como las reporta GitHub."""
    html = _descargar(URL_CALENDARIO)
    coincidencia = re.search(
        r'id="js-contribution-activity-description"[^>]*>.*?([\d,]+)\s*contributions',
        html,
        re.S,
    )
    if not coincidencia:
        coincidencia = re.search(r">([\d,]+)\s*contributions", html)
    return int(coincidencia.group(1).replace(",", "")) if coincidencia else 0


# --- Cifras publicas -------------------------------------------------------


def _texto_svg(svg: str) -> list[str]:
    return [t.strip() for t in re.findall(r"<text[^>]*>([^<]*)</text>", svg) if t.strip()]


def total_contribuciones() -> int:
    """Total de contribuciones historicas (mismo origen que la tarjeta streak)."""
    textos = _texto_svg(_descargar(URL_STREAK))
    for i, t in enumerate(textos):
        if t == "Total Contributions" and i > 0:
            return int(textos[i - 1].replace(",", ""))
    return 0


def commits_publicos() -> int:
    """Commits publicos (mismo origen que la tarjeta de estadisticas)."""
    textos = _texto_svg(_descargar(URL_STATS))
    for i, t in enumerate(textos):
        if t.startswith("Total Commits"):
            for j in range(i + 1, min(i + 4, len(textos))):
                if textos[j].isdigit():
                    return int(textos[j])
    return 0


def repos_publicos() -> int:
    try:
        import json as _json

        datos = _json.loads(_descargar(URL_USUARIO))
        return int(datos.get("public_repos", 0))
    except Exception:  # noqa: BLE001
        return 0


# --- Generacion del SVG ----------------------------------------------------


def construir_rejilla(celdas: list[dict]) -> tuple[date, dict[tuple[int, int], int]]:
    """Ubica cada celda en (fila, columna). Filas = dias de la semana."""
    fechas = [date.fromisoformat(c["fecha"]) for c in celdas]
    base = min(fechas)
    rejilla: dict[tuple[int, int], int] = {}
    for c in celdas:
        d = date.fromisoformat(c["fecha"])
        columna = (d - base).days // 7
        # GitHub muestra domingo arriba: fila 0 = domingo.
        fila = (d.weekday() + 1) % 7
        rejilla[(fila, columna)] = c["nivel"]
    return base, rejilla


def svg_animado(
    base: date,
    rejilla: dict[tuple[int, int], int],
    total: int,
    dias_activos: int,
) -> str:
    columnas = max(c for _, c in rejilla) + 1
    ancho = columnas * (CELDA + HUECO) + RETROCESO
    alto = 7 * (CELDA + HUECO) + 34

    partes: list[str] = []
    partes.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="{alto}" '
        f'viewBox="0 0 {ancho} {alto}" role="img" '
        f'aria-label="Grafico de actividad en GitHub: {total} contribuciones en el ultimo ano">'
    )
    partes.append(f"<title>Actividad en GitHub: {total} contribuciones en el último año</title>")
    partes.append(
        "<style>"
        ".celda{transition:opacity .2s ease}"
        ".activa{animation:latido 3.2s ease-in-out infinite}"
        "@keyframes latido{0%,100%{opacity:1}50%{opacity:.45}}"
        "@media (prefers-reduced-motion: reduce){.activa{animation:none;opacity:1}}"
        "</style>"
    )
    partes.append(f'<rect width="{ancho}" height="{alto}" rx="10" fill="{FONDO}"/>')

    mes_actual = ""
    for columna in range(columnas):
        d = base + timedelta(days=7 * columna)
        etiqueta = d.strftime("%b")
        if etiqueta != mes_actual:
            mes_actual = etiqueta
            x = RETROCESO + columna * (CELDA + HUECO)
            partes.append(
                f'<text x="{x}" y="11" fill="{TEXTO}" font-family="Inter,Segoe UI,sans-serif" '
                f'font-size="9" text-anchor="middle">{etiqueta.upper()}</text>'
            )

    indice = 0
    activas: list[tuple[int, int, int]] = []
    for (fila, columna), nivel in sorted(rejilla.items()):
        x = RETROCESO + columna * (CELDA + HUECO)
        y = 18 + fila * (CELDA + HUECO)
        color = NIVELES.get(nivel, VACIA)
        if nivel > 0:
            activas.append((x, y, nivel))
            continue
        partes.append(
            f'<rect class="celda" x="{x}" y="{y}" width="{CELDA}" height="{CELDA}" '
            f'rx="2.5" fill="{color}"/>'
        )

    for x, y, nivel in activas:
        retardo = (indice % 7) * 0.16
        indice += 1
        partes.append(
            f'<rect class="celda activa" x="{x}" y="{y}" width="{CELDA}" height="{CELDA}" '
            f'rx="2.5" fill="{NIVELES[nivel]}" '
            f'style="animation-delay:{retardo:.2f}s">'
            f"<title>{nivel} contribución(es) ese día</title></rect>"
        )

    y_pie = alto - 9
    partes.append(
        f'<text x="{RETROCESO}" y="{y_pie}" fill="{TEXTO}" '
        f'font-family="Inter,Segoe UI,sans-serif" font-size="9">'
        f"{total} contribuciones · {dias_activos} días con actividad · "
        f"actualizado {date.today().isoformat()}</text>"
    )
    partes.append("</svg>")
    return "\n".join(partes)


# --- Sincronizacion del README --------------------------------------------


def actualizar_readme(
    total: int,
    commits: int,
    repos: int,
    dias_activos: int,
    desde: str,
    total_anual: int,
) -> bool:
    """Reemplaza el bloque de cifras entre los marcadores. Devuelve True si cambio."""
    if not README.exists():
        return False

    bloque = (
        f"{INICIO_MARCADOR}\n"
        f"**{total} contribuciones** en GitHub desde {desde} · "
        f"**{commits} commits** públicos · **{repos} repositorios** abiertos · "
        f"**{dias_activos} días con actividad** en el último año.\n"
        f"{FIN_MARCADOR}"
    )

    texto = README.read_text(encoding="utf-8")
    if INICIO_MARCADOR in texto and FIN_MARCADOR in texto:
        inicio = texto.index(INICIO_MARCADOR)
        fin = texto.index(FIN_MARCADOR) + len(FIN_MARCADOR)
        nuevo = texto[:inicio] + bloque + texto[fin:]
    else:
        # Primera ejecucion: se inserta despues de la linea de la tarjeta streak.
        ancla = "**204 contribuciones**"
        if ancla in texto:
            fin_linea = texto.index("\n", texto.index(ancla)) + 1
            nuevo = texto[:fin_linea] + "\n" + bloque + "\n" + texto[fin_linea:]
        else:
            return False

    # El texto alternativo del grafico lleva la cifra del ultimo ano: hay que
    # mantenerlo alineado con el dato real.
    nuevo = re.sub(
        r'alt="Actividad en GitHub: [\d.]+ contribuciones en el último año"',
        f'alt="Actividad en GitHub: {total_anual} contribuciones en el último año"',
        nuevo,
    )

    if nuevo == texto:
        return False
    README.write_text(nuevo, encoding="utf-8")
    return True


def fecha_inicio() -> str:
    """Mes y anio desde los que la cuenta acumula contribuciones."""
    textos = _texto_svg(_descargar(URL_STREAK))
    for i, t in enumerate(textos):
        if t == "Total Contributions" and i + 1 < len(textos):
            valor = textos[i + 1].split("-")[0].strip()
            mes, _, anio = valor.partition(",")
            meses = {
                "Jan": "enero", "Feb": "febrero", "Mar": "marzo", "Apr": "abril",
                "May": "mayo", "Jun": "junio", "Jul": "julio", "Aug": "agosto",
                "Sep": "septiembre", "Oct": "octubre", "Nov": "noviembre",
                "Dec": "diciembre",
            }
            clave = mes.strip()[:3]
            if clave in meses:
                return f"{meses[clave]} de {anio.strip()}"
    return "octubre de 2019"


def main() -> None:
    celdas = calendario()
    base, rejilla = construir_rejilla(celdas)
    dias_activos = sum(1 for c in celdas if c["nivel"] > 0)
    total_anual = total_anio()

    svg = svg_animado(base, rejilla, total_anual, dias_activos)
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(svg, encoding="utf-8")
    print(f"OK  {DESTINO}  ({len(svg)} bytes)")

    total = total_contribuciones()
    commits = commits_publicos()
    repos = repos_publicos()
    cambio = actualizar_readme(
        total, commits, repos, dias_activos, fecha_inicio(), total_anual
    )

    print(
        f"    {total_anual} contrib. (ultimo ano) · {total} historicas · "
        f"{commits} commits · {repos} repos · {dias_activos} dias activos"
    )
    print(f"    README: {'actualizado' if cambio else 'sin cambios'}")


if __name__ == "__main__":
    main()
