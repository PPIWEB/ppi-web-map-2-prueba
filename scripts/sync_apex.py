import csv
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ================= CONFIGURACIÓN =================
APEX_BASE_URL = "https://g7291f4e4aa4c82-agentech.adb.sa-saopaulo-1.oraclecloudapps.com/ords/"
APEX_LOGIN_URL = APEX_BASE_URL + "f?p=152:553"

APEX_USER = os.environ.get("APEX_USER", "")
APEX_PASS = os.environ.get("APEX_PASS", "")

GEO_JS_PATH = Path("layers/COMBINADO_3.js")
CSV_OUT_PATH = Path("layers/PPI_TABLA.csv")
COMMIT_MSG_PATH = Path(".commit_msg.txt")
DEBUG_IMG_PATH = Path("debug_apex.png")

# Por ahora vacío para usar los estados TAL CUAL vienen del sistema.
# Luego puedes llenar equivalencias aquí, ej: {"LIBRE": "Libre", "VENDIDO": "Vendido", "P": "Cancelado"}
MAPA_ESTADOS = {}

# Fracción 3 en APEX usa Manzanas 1..4 pero en COMBINADO_3.js usa A..D
MAPA_MANZANA_FRAC3 = {"1": "A", "2": "B", "3": "C", "4": "D"}

# Descuento por defecto si un polígono nuevo no tiene el campo "Descuento"
DESCUENTO_DEFAULT = 0.50
CUOTAS_TOTAL = 130
# =================================================


def descargar_csv_apex(destino_csv: Path) -> Path:
    if not APEX_USER or not APEX_PASS:
        raise RuntimeError("Faltan las variables de entorno APEX_USER y/o APEX_PASS.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, viewport={"width": 1600, "height": 900})
        page = context.new_page()

        try:
            print("1) Abriendo Oracle APEX...")
            page.goto(APEX_LOGIN_URL, wait_until="networkidle", timeout=60000)

            # Login en Oracle APEX
            user_input = page.locator(
                'input[name="P9999_USERNAME"], input[name="P101_USERNAME"], input[type="text"]'
            ).first
            pass_input = page.locator(
                'input[name="P9999_PASSWORD"], input[name="P101_PASSWORD"], input[type="password"]'
            ).first

            user_input.wait_for(state="visible", timeout=30000)
            user_input.fill(APEX_USER)
            pass_input.fill(APEX_PASS)
            pass_input.press("Enter")

            # Esperar a entrar al sistema
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            # Si APEX redirigió al Home (página 1) en vez de la 553 (Lotes), saltar directo conservando la sesión
            url_actual = page.url
            print(f"2) Sesión iniciada. URL actual: {url_actual}")
            m_sess = re.search(r"f\?p=152:(\d+):(\d+)", url_actual)
            session_id = m_sess.group(2) if m_sess else None

            if ":553:" not in url_actual and session_id:
                url_lotes = f"{APEX_BASE_URL}f?p=152:553:{session_id}:::::"
                print(f"   Navegando directo a Lotes (553): {url_lotes}")
                page.goto(url_lotes, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2000)

            # Verificar que estamos en la grilla de Lotes
            btn_acciones = page.locator('button:has-text("Acciones")').first
            btn_acciones.wait_for(state="visible", timeout=30000)

            print("3) Descargando CSV desde Acciones -> Descargar...")
            # Intento 1: Descarga directa vía URL estándar de Oracle APEX Interactive Report (más rápida)
            if session_id:
                try:
                    with page.expect_download(timeout=20000) as download_info:
                        page.goto(f"{APEX_BASE_URL}f?p=152:553:{session_id}:CSV::::")
                    download = download_info.value
                    download.save_as(str(destino_csv))
                    print(f"   CSV descargado vía URL directa: {destino_csv}")
                    return destino_csv
                except Exception:
                    # Volver a la página 553 y usar los clics de la interfaz
                    page.goto(f"{APEX_BASE_URL}f?p=152:553:{session_id}:::::", wait_until="networkidle")
                    btn_acciones.wait_for(state="visible", timeout=30000)

            # Intento 2: Clic en Acciones -> Descargar -> CSV
            btn_acciones.click()
            page.locator('button:has-text("Descargar"), a:has-text("Descargar"), span:has-text("Descargar")').first.click()
            page.wait_for_timeout(1500)

            with page.expect_download(timeout=60000) as download_info:
                # En APEX 24/26 puede ser un botón/tile CSV directo o seleccionar CSV + botón Descargar
                csv_opt = page.locator(
                    'a[id$="_download_CSV"], button:has-text("CSV"), li[data-format="CSV"], label:has-text("CSV")'
                ).first
                csv_opt.click()
                # Si el modal tiene un botón de confirmación "Descargar"
                modal_btn = page.locator('.ui-dialog button:has-text("Descargar")')
                if modal_btn.count() > 0 and modal_btn.first.is_visible():
                    modal_btn.first.click()

            download = download_info.value
            download.save_as(str(destino_csv))
            print(f"   CSV descargado vía interfaz: {destino_csv}")
            return destino_csv

        except Exception as e:
            page.screenshot(path=str(DEBUG_IMG_PATH), full_page=True)
            print(f"ERROR durante la descarga de APEX. Captura guardada en {DEBUG_IMG_PATH}: {e}")
            raise
        finally:
            browser.close()


def limpiar_entero(valor: str) -> int:
    s = str(valor or "").strip()
    if not s or s.lower() == "nan":
        return 0
    # Quitar puntos de miles y decimales si hubiera
    s = s.split(",")[0]
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


def formato_miles(numero: int) -> str:
    if not numero:
        return ""
    return f"{numero:,}".replace(",", ".")


def limpiar_superficie(valor: str) -> str:
    s = str(valor or "").strip()
    if not s or s.lower() == "nan":
        return ""
    # "4.825,95" -> "4825.95" | "734,25" -> "734.25"
    s = s.replace(".", "").replace(",", ".")
    return s


def parsear_descuento(desc_str: str) -> float:
    s = str(desc_str or "").strip().replace("%", "")
    if not s:
        return DESCUENTO_DEFAULT
    try:
        val = float(s)
        return val / 100.0 if val > 1 else val
    except ValueError:
        return DESCUENTO_DEFAULT


def construir_id(fraccion: str, manzana: str, lote: str) -> str:
    m = re.match(r"^0*(\d+)", str(fraccion).strip())
    frac_num = m.group(1) if m else str(fraccion).strip()
    mz = str(manzana).strip()
    lt = str(lote).strip()
    if mz.isdigit():
        mz = str(int(mz))
    if lt.isdigit():
        lt = str(int(lt))
    if frac_num == "3" and mz in MAPA_MANZANA_FRAC3:
        mz = MAPA_MANZANA_FRAC3[mz]
    return f"{frac_num}-{mz}-{lt}"


def cargar_datos_apex(csv_path: Path) -> dict:
    try:
        df = pd.read_csv(csv_path, sep=";", encoding="utf-8", dtype=str).fillna("")
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, sep=";", encoding="latin1", dtype=str).fillna("")

    df["ID_CALC"] = df.apply(lambda r: construir_id(r["Fraccion"], r["Manzana"], r["Lote"]), axis=1)
    # Conservar la última fila en caso de duplicados en APEX
    df = df.drop_duplicates(subset=["ID_CALC"], keep="last")

    registros = {}
    for _, row in df.iterrows():
        estado_raw = str(row.get("Estado", "")).strip()
        estado_final = MAPA_ESTADOS.get(estado_raw, estado_raw)
        registros[row["ID_CALC"]] = {
            "Estado": estado_final,
            "Cuota_int": limpiar_entero(row.get("Cuota", "")),
            "Contado_int": limpiar_entero(row.get("Contado", "")),
            "Superficie": limpiar_superficie(row.get("Superficie", "")),
        }
    return registros


def actualizar_archivos(datos_apex: dict) -> list:
    raw_js = GEO_JS_PATH.read_text(encoding="utf-8").strip()
    m_prefix = re.match(r"^(var\s+\w+\s*=\s*)", raw_js)
    prefix = m_prefix.group(1) if m_prefix else "var json_COMBINADO_3 = "
    json_body = raw_js[len(prefix):].rstrip(";")
    geo = json.loads(json_body)

    cambios = []
    filas_csv = [["ID", "Manzana", "Lote", "Superficie", "Estado", "Cuota", "Total", "Descuento", "Contado"]]

    for feat in geo["features"]:
        props = feat["properties"]
        lote_id = str(props.get("ID", "")).strip()

        if lote_id in datos_apex:
            info = datos_apex[lote_id]

            estado_ant = str(props.get("Estado") or "").strip()
            cuota_ant = str(props.get("Cuota") or "").strip()
            sup_ant = str(props.get("Superficie") or "").strip()

            nuevo_estado = info["Estado"]
            cuota_int = info["Cuota_int"]
            nueva_cuota = formato_miles(cuota_int)
            nueva_sup = info["Superficie"] if info["Superficie"] else sup_ant

            total_int = cuota_int * CUOTAS_TOTAL if cuota_int > 0 else 0
            nuevo_total = formato_miles(total_int) if total_int > 0 else "0"

            desc_actual = str(props.get("Descuento") or "").strip()
            desc_float = parsear_descuento(desc_actual)
            if not desc_actual:
                desc_actual = f"{int(round(desc_float * 100))}%"

            if info["Contado_int"] > 0:
                contado_int = info["Contado_int"]
            elif total_int > 0:
                contado_int = int(round(total_int * (1.0 - desc_float)))
            else:
                contado_int = 0

            nuevo_contado = f"{formato_miles(contado_int)}Gs." if contado_int > 0 else "0Gs."

            if estado_ant != nuevo_estado or cuota_ant != nueva_cuota or sup_ant != nueva_sup:
                detalle = f"{lote_id}: {estado_ant}->{nuevo_estado}"
                if cuota_ant != nueva_cuota:
                    detalle += f" (Cuota {cuota_ant}->{nueva_cuota})"
                cambios.append(detalle)

                props["Estado"] = nuevo_estado
                props["Cuota"] = nueva_cuota
                props["Total"] = nuevo_total
                props["Descuento"] = desc_actual
                props["Contado"] = nuevo_contado
                props["Superficie"] = nueva_sup

        filas_csv.append([
            props.get("ID", ""),
            props.get("Manzana", ""),
            props.get("Lote", ""),
            props.get("Superficie", ""),
            props.get("Estado", ""),
            props.get("Cuota", ""),
            props.get("Total", ""),
            props.get("Descuento", ""),
            props.get("Contado", ""),
        ])

    if cambios:
        # Guardar COMBINADO_3.js actualizado
        GEO_JS_PATH.write_text(
            prefix + json.dumps(geo, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # Guardar layers/PPI_TABLA.csv sincronizado
        CSV_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CSV_OUT_PATH.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(filas_csv)

    return cambios


def main():
    # Permite probar localmente pasando un CSV: python scripts/sync_apex.py Lotes.csv
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        csv_path = Path(sys.argv[1])
        print(f"Modo prueba local con archivo: {csv_path}")
        datos = cargar_datos_apex(csv_path)
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "Lotes.csv"
            descargar_csv_apex(csv_path)
            datos = cargar_datos_apex(csv_path)

    print(f"Registros leídos de APEX: {len(datos)}")
    cambios = actualizar_archivos(datos)

    if not cambios:
        print("Sin cambios detectados respecto al mapa actual. No se hará commit.")
        if COMMIT_MSG_PATH.exists():
            COMMIT_MSG_PATH.unlink()
        return

    print(f"Se detectaron {len(cambios)} lote(s) con cambios:")
    for c in cambios[:20]:
        print("  -", c)
    if len(cambios) > 20:
        print(f"  ... y {len(cambios) - 20} más.")

    resumen = ", ".join(cambios[:5])
    if len(cambios) > 5:
        resumen += f" (+{len(cambios) - 5} más)"
    COMMIT_MSG_PATH.write_text(f"Sync APEX ({len(cambios)} cambios): {resumen}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
