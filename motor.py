import csv
import datetime
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
import requests

# ==========================================
# CONFIGURACIÓN AUTOMÁTICA (CERO MANTENIMIENTO)
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "").strip()

# En el Bloque 3 pondremos aquí tu enlace de afiliado / Gumroad.
# Por ahora redirige a tu propio canal para viralizar cuando reenvíen tus mensajes.
CANAL_LIMPIO = TELEGRAM_CHANNEL.replace("@", "")
ENLACE_MONETIZACION = "https://marcosboullos.gumroad.com/l/vfqcj"
TEXTO_GANCHO = "📊 Accede aquí al Buscador Excel Auto-Actualizable con TODAS las ayudas y subastas activas"

PALABRAS_CLAVE = [
    "subvenci",
    "ayuda",
    "beca",
    "subasta",
    "bono",
    "vivienda",
    "autónomo",
    "autonomo",
    "pyme",
    "solar",
    "eléctric",
    "energia",
    "energía",
    "rehabilitación",
    "rehabilitacion",
    "kit digital",
    "alquiler",
    "empleo",
    "emprend",
    "financiación",
    "licitaci",
]

CARPETA_DATOS = "datos"
ARCHIVO_HISTORIAL = os.path.join(CARPETA_DATOS, "historial_ids.txt")
ARCHIVO_CSV = os.path.join(CARPETA_DATOS, "dataset_ayudas_boe.csv")
ARCHIVO_JSON = os.path.join(CARPETA_DATOS, "dataset_ayudas_boe.json")


def limpiar_rgpd(texto):
  """Elimina DNIs y NIEs automáticamente para cumplir 100% con el RGPD."""
  if not texto:
    return ""
  texto = re.sub(r"\b[0-9]{8}[A-Za-z]\b", "[DATO_PROTEGIDO]", texto)
  texto = re.sub(r"\b[XYZxyz][0-9]{7}[A-Za-z]\b", "[DATO_PROTEGIDO]", texto)
  return texto


def cargar_historial():
  os.makedirs(CARPETA_DATOS, exist_ok=True)
  if not os.path.exists(ARCHIVO_HISTORIAL):
    return set()
  with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
    return set(line.strip() for line in f if line.strip())


def guardar_en_historial(id_boe):
  with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
    f.write(f"{id_boe}\n")


def obtener_items_boe():
  """Busca en el BOE de hoy. Si es domingo/festivo o aún no hay datos, retrocede hasta 4 días."""
  headers = {
      "Accept": "application/xml",
      "User-Agent": "Mozilla/5.0 (compatible; OpenDataAudit/1.0)",
  }
  hoy = datetime.date.today()

  for dias_atras in range(0, 5):
    fecha_consulta = (hoy - datetime.timedelta(days=dias_atras)).strftime(
        "%Y%m%d"
    )
    url = f"https://www.boe.es/datosabiertos/api/boe/sumario/{fecha_consulta}"
    try:
      resp = requests.get(url, headers=headers, timeout=20)
      if resp.status_code != 200:
        continue

      root = ET.fromstring(resp.content)
      items_encontrados = []

      for item in root.findall(".//item"):
        id_elem = item.find("identificador")
        titulo_elem = item.find("titulo")
        url_pdf_elem = item.find("url_pdf")
        url_html_elem = item.find("url_html")

        if id_elem is None or titulo_elem is None:
          continue

        id_boe = id_elem.text.strip()
        titulo = limpiar_rgpd(titulo_elem.text.strip())
        enlace = (
            url_html_elem.text.strip()
            if (url_html_elem is not None and url_html_elem.text)
            else f"https://www.boe.es/diario_boe/txt.php?id={id_boe}"
        )

        titulo_lower = titulo.lower()
        if any(palabra in titulo_lower for palabra in PALABRAS_CLAVE):
          items_encontrados.append({
              "id": id_boe,
              "fecha": fecha_consulta,
              "titulo_original": titulo,
              "url_oficial": enlace,
          })

      if items_encontrados:
        print(
            f"[OK] Encontrados {len(items_encontrados)} anuncios relevantes en"
            f" fecha {fecha_consulta}."
        )
        return items_encontrados
    except Exception as e:
      print(f"[AVISO] Saltando fecha {fecha_consulta} por: {e}")
      continue

  return []


def resumir_con_ia(item):
  """Traduce el texto del BOE a lenguaje claro usando la capa gratuita de Google Gemini."""
  prompt = (
      "Eres un analista experto en subvenciones, licitaciones y subastas"
      " públicas de España. Resume este anuncio oficial del BOE en español"
      " claro y directo en 3 puntos breves:\n1) Qué es exactamente (ayuda,"
      " subvención, beca, subasta o licitación).\n2) A quién beneficia o quién"
      " puede solicitarlo (autónomos, particulares, empresas, estudiantes,"
      " etc.).\n3) Organismo o región que lo convoca.\nNo inventes datos ni"
      " uses formato markdown con asteriscos. Máximo 90 palabras en"
      f" total.\n\nTexto oficial: {item['titulo_original']}"
  )

  modelos = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-1.5-flash"]
  for modelo in modelos:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 250},
    }
    try:
      r = requests.post(url, json=payload, timeout=20)
      if r.status_code == 200:
        data = r.json()
        texto_ia = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return limpiar_rgpd(texto_ia.replace("*", ""))
    except Exception:
      continue

  # Fallback automático si la IA está saturada: devuelve el título limpio sin detener el sistema
  return item["titulo_original"]


def actualizar_datasets(nuevos_registros):
  """Actualiza los archivos CSV y JSON listos para vender en Gumroad / RapidAPI y alimentar la Web."""
  archivo_existe = os.path.exists(ARCHIVO_CSV)
  with open(ARCHIVO_CSV, "a", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "id",
            "fecha",
            "titulo_original",
            "resumen_ia",
            "url_oficial",
        ],
    )
    if not archivo_existe:
      writer.writeheader()
    for reg in nuevos_registros:
      writer.writerow(reg)

  datos_json = []
  if os.path.exists(ARCHIVO_JSON):
    try:
      with open(ARCHIVO_JSON, "r", encoding="utf-8") as f:
        datos_json = json.load(f)
    except Exception:
      datos_json = []

  datos_json = nuevos_registros + datos_json
  datos_json = datos_json[
      :1000
  ]  # Mantiene las últimas 1.000 ayudas optimizadas
  with open(ARCHIVO_JSON, "w", encoding="utf-8") as f:
    json.dump(datos_json, f, ensure_ascii=False, indent=2)


def enviar_a_telegram(registro):
  """Publica el aviso formateado en el canal de Telegram."""
  if not TELEGRAM_TOKEN or not TELEGRAM_CHANNEL:
    print("[AVISO] Faltan credenciales de Telegram en GitHub Secrets.")
    return False

  resumen_seguro = html.escape(registro["resumen_ia"])
  url_segura = html.escape(registro["url_oficial"])
  id_seguro = html.escape(registro["id"])

  mensaje = (
      f"🚨 <b>NUEVA CONVOCATORIA / SUBASTA BOE ({id_seguro})</b>\n\n"
      f"{resumen_seguro}\n\n"
      f"📄 <a href='{url_segura}'>Ver documento oficial en el BOE</a>\n"
      "💡 <a"
      f" href='{ENLACE_MONETIZACION}'><b>{html.escape(TEXTO_GANCHO)}</b></a>"
  )

  url_tg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  payload = {
      "chat_id": TELEGRAM_CHANNEL,
      "text": mensaje,
      "parse_mode": "HTML",
      "disable_web_page_preview": True,
  }
  try:
    r = requests.post(url_tg, json=payload, timeout=15)
    if r.status_code == 200:
      print(f"[OK] Publicado en Telegram: {registro['id']}")
      return True
    else:
      print(f"[ERROR TELEGRAM] {r.status_code}: {r.text}")
      return False
  except Exception as e:
    print(f"[ERROR CONEXIÓN TELEGRAM]: {e}")
    return False


def main():
  historial = cargar_historial()
  items = obtener_items_boe()

  pendientes = [item for item in items if item["id"] not in historial]
  if not pendientes:
    print("[OK] No hay convocatorias nuevas pendientes de publicar hoy.")
    return

  # Publicamos un máximo de 3 alertas por ejecución para no saturar el canal y cuidar la API gratuita
  lote_hoy = pendientes[:3]
  registros_procesados = []

  for item in lote_hoy:
    resumen = resumir_con_ia(item)
    item["resumen_ia"] = resumen
    exito = enviar_a_telegram(item)
    if exito:
      guardar_en_historial(item["id"])
      registros_procesados.append(item)
      time.sleep(3)

  if registros_procesados:
    actualizar_datasets(registros_procesados)
    print(
        f"[ÉXITO TOTAL] Se han procesado y guardado {len(registros_procesados)}"
        " registros."
    )
  # Añade esta línea al final de main(), justo antes de terminar la función:
  generar_sitemap_y_robots()
def generar_sitemap_y_robots():
  """Genera automáticamente sitemap.xml y robots.txt para indexar en Google."""
  hoy_str = datetime.date.today().strftime("%Y-%m-%d")
  usuario = os.environ.get("GITHUB_REPOSITORY_OWNER", "usuario")
  url_base = f"https://{usuario}.github.io/motor-ayudas-espana/"

  # 1. Crear sitemap.xml
  contenido_sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{url_base}</loc>
    <lastmod>{hoy_str}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>"""

  with open("sitemap.xml", "w", encoding="utf-8") as f:
    f.write(contenido_sitemap.strip())

  # 2. Crear robots.txt
  contenido_robots = f"""User-agent: *
Allow: /

Sitemap: {url_base}sitemap.xml"""

  with open("robots.txt", "w", encoding="utf-8") as f:
    f.write(contenido_robots.strip())

  print("[OK] sitemap.xml y robots.txt generados correctamente para Google.")
if __name__ == "__main__":
  main()
