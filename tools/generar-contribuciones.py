#!/usr/bin/env python3
"""Graficos de actividad del perfil y cifras del README.

Todo se calcula con la API de GitHub: el calendario de contribuciones por dia,
la racha actual y la mas larga, el total del ultimo ano, los commits publicos y
los repositorios abiertos. No depende de servicios de terceros (readme-stats,
streak-stats), que responden 200 con un SVG de error y dejan el perfil roto.

Fuentes, en orden:
    1. GraphQL con token (contribuciones exactas por dia, incluidas las privadas).
    2. REST con token (repositorios y commits publicos).
    3. Calendario publico anonimo, si no hay token.

Salidas:
    assets/contribuciones.svg   Calendario anual con la paleta de marca
    assets/resumen.svg          Racha actual, racha maxima y totales
    README.md                   Seccion de actividad y bloque de cifras

Uso:
    python3 tools/generar-contribuciones.py
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --- Identidad de marca ----------------------------------------------------
TEAL = "#03A8FA"
VIOLET = "#9800E9"
FONDO = "#0C1226"
PANEL = "#111833"
TEXTO = "#8FA3C4"
CLARO = "#E6EDF7"

NIVELES = {0: PANEL, 1: "#0B3A5C", 2: "#0E6FA8", 3: TEAL, 4: VIOLET}

CELDA = 11
HUECO = 3
RETROCESO = 3

LOGIN = "Chencho2323"
ORIGEN = Path(__file__).resolve().parent.parent
ASSETS = ORIGEN / "assets"
SVG_CALENDARIO = ASSETS / "contribuciones.svg"
SVG_RESUMEN = ASSETS / "resumen.svg"
README = ORIGEN / "README.md"

API = "https://api.github.com"
CALENDARIO_PUBLICO = f"https://github.com/users/{LOGIN}/contributions"
PERFILES_GH = Path.home() / ".openclaw" / "credentials" / "github" / "personal"

INICIO_MARCADOR = "<!-- ACTIVIDAD:INICIO -->"
FIN_MARCADOR = "<!-- ACTIVIDAD:FIN -->"

MESES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre",
    12: "diciembre",
}
MES_CORTO = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
             "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


# --- Credencial ------------------------------------------------------------


def token_github() -> str:
    """Token para consultar la API, sin escribirlo en ningun archivo."""
    for variable in ("GITHUB_TOKEN", "GH_TOKEN"):
        valor = os.environ.get(variable, "").strip()
        if valor:
            return valor
    if not PERFILES_GH.is_dir():
        return ""
    candidatos = []
    for directorio in PERFILES_GH.iterdir():
        hosts = directorio / "hosts.yml"
        if not hosts.is_file():
            continue
        try:
            texto = hosts.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"oauth_token:\s*(\S+)", texto)
            if m:
                candidatos.append((hosts.stat().st_mtime, m.group(1)))
        except OSError:
            continue
    if not candidatos:
        return ""
    candidatos.sort(reverse=True)
    return candidatos[0][1]


def _peticion(url: str, token: str, datos: dict | None = None) -> dict:
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    cabeceras = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{LOGIN}-profile",
    }
    if token:
        cabeceras["Authorization"] = f"token {token}"
    peticion = urllib.request.Request(url, data=cuerpo, headers=cabeceras)
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def graphql(token: str, consulta: str) -> dict:
    return _peticion(f"{API}/graphql", token, {"query": consulta})


# --- Datos -----------------------------------------------------------------


def dias_por_graphql(token: str) -> list[dict] | None:
    consulta = (
        "{ user(login: \"%s\") { contributionsCollection {"
        " contributionCalendar { totalContributions"
        " weeks { contributionDays { date contributionCount contributionLevel } }"
        " } } } }" % LOGIN
    )
    try:
        datos = graphql(token, consulta)
        coleccion = datos["data"]["user"]["contributionsCollection"]
        calendario = coleccion["contributionCalendar"]
    except (urllib.error.URLError, KeyError, TypeError, json.JSONDecodeError):
        return None
    niveles = {
        "NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
        "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4,
    }
    dias = []
    for semana in calendario["weeks"]:
        for dia in semana["contributionDays"]:
            conteo = int(dia["contributionCount"])
            dias.append({
                "fecha": dia["date"],
                "conteo": conteo,
                "activo": conteo > 0,
                "nivel": niveles.get(dia["contributionLevel"], 0),
            })
    return dias or None


def dias_por_calendario_publico() -> list[dict] | None:
    """Sin token: el mismo calendario que ve un visitante anonimo."""
    peticion = urllib.request.Request(
        CALENDARIO_PUBLICO, headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            html = respuesta.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError):
        return None

    celdas = re.findall(
        r'data-date="(\d{4}-\d{2}-\d{2})"[^>]*?data-level="(\d)"', html
    )
    if not celdas:
        return None
    return [
        {"fecha": fecha, "conteo": None, "activo": int(nivel) > 0, "nivel": int(nivel)}
        for fecha, nivel in celdas
    ]


def total_anual_publico() -> int | None:
    """Cifra anual que muestra la pagina publica de contribuciones."""
    peticion = urllib.request.Request(
        CALENDARIO_PUBLICO, headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            html = respuesta.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError):
        return None
    m = re.search(r"([\d,]+)\s+contributions?\s+in the last year", html)
    return int(m.group(1).replace(",", "")) if m else None


def repositorios_publicos(token: str) -> int | None:
    try:
        return int(_peticion(f"{API}/users/{LOGIN}", token).get("public_repos", 0))
    except (urllib.error.URLError, ValueError, TypeError):
        return None


def commits_publicos(token: str) -> int | None:
    try:
        datos = _peticion(
            f"{API}/search/commits?q=author%3A{LOGIN}&per_page=1", token
        )
        return int(datos.get("total_count", 0))
    except (urllib.error.URLError, ValueError, TypeError):
        return None


def cuenta_desde(token: str) -> str | None:
    try:
        creada = _peticion(f"{API}/users/{LOGIN}", token).get("created_at", "")
        anio, mes = creada[:4], int(creada[5:7])
        return f"{MESES[mes]} de {anio}"
    except (urllib.error.URLError, ValueError, KeyError, TypeError):
        return None


# --- Metricas --------------------------------------------------------------


def rachas(dias: list[dict], hoy: date) -> tuple[int, int]:
    """Racha actual (hasta hoy o ayer) y racha mas larga, en dias."""
    activos = {d["fecha"] for d in dias if d.get("activo")}
    if not activos:
        return 0, 0

    actual = 0
    cursor = hoy if hoy.isoformat() in activos else hoy - timedelta(days=1)
    while cursor.isoformat() in activos:
        actual += 1
        cursor -= timedelta(days=1)

    maxima = 0
    corrida = 0
    anterior = None
    for fecha in sorted(activos):
        dia = date.fromisoformat(fecha)
        if anterior and (dia - anterior).days == 1:
            corrida += 1
        else:
            corrida = 1
        maxima = max(maxima, corrida)
        anterior = dia
    return actual, max(maxima, actual)


def construir_semanas(dias: list[dict]) -> list[list[dict]]:
    """Agrupa por semana con domingo como primer dia, como GitHub."""
    semanas: list[list[dict]] = []
    actual: list[dict] = []
    for dia in sorted(dias, key=lambda d: d["fecha"]):
        fecha = date.fromisoformat(dia["fecha"])
        if fecha.weekday() == 6 and actual:
            semanas.append(actual)
            actual = []
        actual.append({**dia, "dia": fecha})
    if actual:
        semanas.append(actual)
    return semanas


# --- SVG: calendario -------------------------------------------------------


def svg_calendario(dias: list[dict], total: int, activos: int) -> str:
    semanas = construir_semanas(dias)
    columnas = len(semanas)
    ancho = RETROCESO + columnas * (CELDA + HUECO)
    alto = 7 * (CELDA + HUECO) + 34

    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="{alto}" '
        f'viewBox="0 0 {ancho} {alto}" role="img" '
        f'aria-label="Actividad en GitHub: {total} contribuciones en el ultimo ano">',
        f"<title>Actividad en GitHub: {total} contribuciones en el último año</title>",
        "<style>"
        ".celda{transition:opacity .2s ease}"
        ".activa{animation:latido 3.2s ease-in-out infinite}"
        "@keyframes latido{0%,100%{opacity:1}50%{opacity:.45}}"
        "@media (prefers-reduced-motion: reduce){.activa{animation:none;opacity:1}}"
        "</style>",
        f'<rect width="{ancho}" height="{alto}" rx="10" fill="{FONDO}"/>',
    ]

    mes_previo = None
    for indice, semana in enumerate(semanas):
        primer_dia = semana[0]["dia"]
        if primer_dia.month != mes_previo:
            mes_previo = primer_dia.month
            x = RETROCESO + indice * (CELDA + HUECO)
            partes.append(
                f'<text x="{x}" y="11" fill="{TEXTO}" '
                f'font-family="Inter,Segoe UI,sans-serif" font-size="9">{MES_CORTO[mes_previo - 1]}</text>'
            )

    contador = 0
    for columna, semana in enumerate(semanas):
        for dia in semana:
            x = RETROCESO + columna * (CELDA + HUECO)
            y = 18 + ((dia["dia"].weekday() + 1) % 7) * (CELDA + HUECO)
            nivel = dia["nivel"] if dia.get("activo") else 0
            color = NIVELES.get(nivel, PANEL)
            clase = "celda activa" if nivel > 0 else "celda"
            estilo = ""
            if nivel > 0:
                estilo = f' style="animation-delay:{(contador % 7) * 0.16:.2f}s"'
                contador += 1
            partes.append(
                f'<rect class="{clase}" x="{x}" y="{y}" width="{CELDA}" '
                f'height="{CELDA}" rx="2.5" fill="{color}"{estilo}>'
                f"<title>{dia['fecha']}: {dia['conteo'] or 1} contribuciones</title></rect>"
            )

    partes.append(
        f'<text x="{RETROCESO}" y="{alto - 9}" fill="{TEXTO}" '
        f'font-family="Inter,Segoe UI,sans-serif" font-size="9">'
        f"{total} contribuciones · {activos} días con actividad · "
        f"actualizado {date.today().isoformat()}</text>"
    )
    partes.append("</svg>")
    return "\n".join(partes)


# --- SVG: resumen ----------------------------------------------------------


def svg_resumen(
    total: int,
    activos: int,
    racha: int,
    maxima: int,
    commits: int | None,
    repos: int | None,
) -> str:
    ancho, alto = 495, 195
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="{alto}" '
        f'viewBox="0 0 {ancho} {alto}" role="img" '
        f'aria-label="Resumen de actividad en GitHub">',
        "<title>Resumen de actividad en GitHub</title>",
        f'<rect width="{ancho}" height="{alto}" rx="12" fill="{FONDO}"/>',
        f'<text x="24" y="34" fill="{CLARO}" font-family="Inter,Segoe UI,sans-serif" '
        f'font-size="15" font-weight="600">Actividad en GitHub</text>',
        f'<text x="24" y="52" fill="{TEXTO}" font-family="Inter,Segoe UI,sans-serif" '
        f'font-size="10">ultimo año · {date.today().isoformat()}</text>',
    ]

    # Bloque principal: contribuciones del ultimo ano.
    partes.append(
        f'<text x="24" y="112" fill="{TEAL}" font-family="Inter,Segoe UI,sans-serif" '
        f'font-size="40" font-weight="700">{total}</text>'
    )
    partes.append(
        f'<text x="24" y="132" fill="{TEXTO}" font-family="Inter,Segoe UI,sans-serif" '
        f'font-size="10">contribuciones en el ultimo año</text>'
    )

    columnas = [
        ("Racha actual", f"{racha} días"),
        ("Racha máxima", f"{maxima} días"),
        ("Días activos", f"{activos}"),
        ("Commits públicos", f"{commits}" if commits is not None else "—"),
        ("Repositorios", f"{repos}" if repos is not None else "—"),
    ]
    y = 70
    for etiqueta, valor in columnas:
        partes.append(
            f'<text x="255" y="{y}" fill="{TEXTO}" font-family="Inter,Segoe UI,sans-serif" '
            f'font-size="10">{etiqueta}</text>'
        )
        partes.append(
            f'<text x="470" y="{y}" fill="{CLARO}" text-anchor="end" '
            f'font-family="Inter,Segoe UI,sans-serif" font-size="11" '
            f'font-weight="600">{valor}</text>'
        )
        y += 22

    partes.append(
        f'<text x="24" y="168" fill="{TEXTO}" font-family="Inter,Segoe UI,sans-serif" '
        f'font-size="9">Datos del calendario público de GitHub.</text>'
    )
    partes.append("</svg>")
    return "\n".join(partes)


# --- README ----------------------------------------------------------------


def seccion_actividad(total: int) -> str:
    """Los dos graficos, sin texto alrededor: las cifras ya estan en el SVG."""
    return "\n".join([
        INICIO_MARCADOR,
        '<a href="https://github.com/' + LOGIN + '">',
        f'  <img src="https://raw.githubusercontent.com/{LOGIN}/{LOGIN}/main/'
        f'assets/contribuciones.svg" alt="Actividad en GitHub: {total} contribuciones '
        f'en el último año" width="100%" />',
        "</a>",
        "",
        f'<img src="https://raw.githubusercontent.com/{LOGIN}/{LOGIN}/main/'
        f'assets/resumen.svg" alt="Resumen de actividad en GitHub: racha, días activos, '
        f'commits y repositorios" width="100%" />',
        FIN_MARCADOR,
    ])


def actualizar_readme(total: int) -> bool:
    if not README.exists():
        return False
    texto = README.read_text(encoding="utf-8")
    if INICIO_MARCADOR not in texto or FIN_MARCADOR not in texto:
        print("    AVISO: el README no tiene los marcadores ACTIVIDAD. No se modifica.")
        return False
    inicio = texto.index(INICIO_MARCADOR)
    fin = texto.index(FIN_MARCADOR) + len(FIN_MARCADOR)
    nuevo = texto[:inicio] + seccion_actividad(total) + texto[fin:]
    if nuevo == texto:
        return False
    README.write_text(nuevo, encoding="utf-8")
    return True


# --- Principal -------------------------------------------------------------


def main() -> None:
    token = token_github()
    dias = dias_por_graphql(token) if token else None
    fuente = "graphql"
    if dias is None:
        dias = dias_por_calendario_publico()
        fuente = "calendario publico"
    if not dias:
        raise SystemExit("No se pudo leer el calendario de contribuciones de GitHub.")

    if fuente == "graphql":
        total = sum(d["conteo"] for d in dias)
    else:
        total = total_anual_publico() or sum(1 for d in dias if d["activo"])
    activos = sum(1 for d in dias if d["activo"])
    hoy = date.today()
    racha, maxima = rachas(dias, hoy)

    ASSETS.mkdir(parents=True, exist_ok=True)
    SVG_CALENDARIO.write_text(svg_calendario(dias, total, activos), encoding="utf-8")

    commits = commits_publicos(token) if token else None
    repos = repositorios_publicos(token) if token else None
    SVG_RESUMEN.write_text(
        svg_resumen(total, activos, racha, maxima, commits, repos), encoding="utf-8"
    )

    cambio = actualizar_readme(total)

    print(f"fuente: {fuente} · {total} contrib. · {activos} dias · racha {racha}/{maxima}")
    print(f"commits publicos: {commits} · repos publicos: {repos}")
    print(f"README: {'actualizado' if cambio else 'sin cambios'}")


if __name__ == "__main__":
    main()
