#!/usr/bin/env python3
"""El taller de Sanlo.raw.

Levanta el sitio en local y, en /taller/, una página para etiquetar las
fotografías viéndolas. Hace solo todo lo que se puede hacer solo:

  · convierte a WebP los originales que aún no lo estén (lado mayor 2000)
  · mide el archivo ya convertido y apunta width/height reales
  · lee del EXIF la cámara y la fecha del original
  · escribe la ficha en filtros.json
  · regenera los botones de Ciudad y Cámaras en index.html

Lo único que pregunta es lo que no está en ninguna parte: el lugar, el
tratamiento y, en los escaneos, con qué cámara se disparó de verdad.

    python taller/taller.py

Sin argumentos, sirve en el puerto 8123.
"""

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TALLER = os.path.join(RAIZ, 'taller')
ORIGINALES = os.path.join(RAIZ, 'fotos', '_originales')
WEBPS = os.path.join(RAIZ, 'fotos')
FILTROS = os.path.join(RAIZ, 'filtros.json')
INDEX = os.path.join(RAIZ, 'index.html')

LADO_MAYOR = 2000
CALIDAD = 82
EXTENSIONES = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.heic')

# Un solo escritor a la vez: la página puede disparar varias peticiones
# seguidas y filtros.json no admite que dos las escriban a la vez.
CERROJO = threading.Lock()


# ─────────────────────────────────────────────────────────────────────
#  ImageMagick
# ─────────────────────────────────────────────────────────────────────

def _magick():
    """En Windows 'convert' es otra cosa; se prefiere 'magick'."""
    for nombre in ('magick', 'convert'):
        if shutil.which(nombre):
            return nombre
    return None


MAGICK = _magick()


def convertir(origen, destino):
    """Original → WebP con el lado mayor a 2000. El '>' sólo encoge.

    -auto-orient no es opcional. Muchas cámaras guardan la foto siempre
    en horizontal y añaden una etiqueta EXIF diciendo cuánto hay que
    girarla; sin esto los pixeles salen tal cual y la vertical se publica
    tumbada. Va antes del -resize para que el lado mayor se mida sobre la
    imagen ya derecha.
    """
    if not MAGICK:
        raise RuntimeError(
            'No encuentro ImageMagick. Instálalo desde imagemagick.org '
            'y vuelve a abrir la terminal.')
    subprocess.run(
        [MAGICK, origen, '-auto-orient',
         '-resize', f'{LADO_MAYOR}x{LADO_MAYOR}>',
         '-quality', str(CALIDAD), destino],
        check=True, capture_output=True)


def medir(ruta):
    """(ancho, alto) del archivo ya convertido, leídos del propio archivo."""
    if MAGICK:
        try:
            salida = subprocess.run(
                [MAGICK, 'identify', '-format', '%w %h', ruta],
                check=True, capture_output=True, text=True).stdout.split()
            return int(salida[0]), int(salida[1])
        except Exception:
            pass
    return _medir_webp(ruta)


def _medir_webp(ruta):
    """Lector de cabeceras WebP, por si ImageMagick no estuviera."""
    with open(ruta, 'rb') as fh:
        d = fh.read(64)
    if d[12:16] == b'VP8X':
        return (1 + int.from_bytes(d[24:27], 'little'),
                1 + int.from_bytes(d[27:30], 'little'))
    if d[12:16] == b'VP8L':
        b = int.from_bytes(d[21:25], 'little')
        return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    if d[12:16] == b'VP8 ':
        return (struct.unpack('<H', d[26:28])[0] & 0x3FFF,
                struct.unpack('<H', d[28:30])[0] & 0x3FFF)
    raise ValueError(f'no sé leer las medidas de {ruta}')


# ─────────────────────────────────────────────────────────────────────
#  EXIF — sólo lo que hace falta, sin dependencias
# ─────────────────────────────────────────────────────────────────────

def exif(ruta):
    """Lo que el original sepa contar de su propio disparo. Nunca falla:
    lo que no esté, no sale.

    Devuelve camara, fecha, anio, apertura, velocidad, iso, focal (la real,
    en mm) y objetivo.
    """
    try:
        with open(ruta, 'rb') as fh:
            d = fh.read(400000)
        i = d.find(b'Exif\x00\x00')
        if i < 0:
            return {}
        t = d[i + 6:]
        en = '<' if t[:2] == b'II' else '>'
        raiz = struct.unpack(en + 'I', t[4:8])[0]

        def entradas(desplazamiento):
            n = struct.unpack(en + 'H', t[desplazamiento:desplazamiento + 2])[0]
            campos = {}
            for k in range(n):
                e = desplazamiento + 2 + k * 12
                etiqueta, tipo, cuenta = struct.unpack(en + 'HHI', t[e:e + 8])
                campos[etiqueta] = (tipo, cuenta, t[e + 8:e + 12])
            return campos

        def texto(etiqueta, campos):
            if etiqueta not in campos:
                return None
            _tipo, cuenta, valor = campos[etiqueta]
            if cuenta > 4:
                p = struct.unpack(en + 'I', valor)[0]
                bruto = t[p:p + cuenta - 1]
            else:
                bruto = valor[:max(cuenta - 1, 0)]
            return bruto.decode('latin1', 'ignore').strip('\x00 ').strip()

        def racional(etiqueta, campos):
            """Devuelve (numerador, denominador) o None."""
            if etiqueta not in campos:
                return None
            _tipo, _cuenta, valor = campos[etiqueta]
            p = struct.unpack(en + 'I', valor)[0]
            a, b = struct.unpack(en + 'II', t[p:p + 8])
            return (a, b) if b else None

        def entero(etiqueta, campos):
            if etiqueta not in campos:
                return None
            tipo, _cuenta, valor = campos[etiqueta]
            if tipo == 3:
                return struct.unpack(en + 'H', valor[:2])[0]
            if tipo == 4:
                return struct.unpack(en + 'I', valor)[0]
            return None

        principal = entradas(raiz)
        datos = {}
        modelo = texto(0x0110, principal)
        marca = texto(0x010F, principal)
        if modelo:
            # "Canon EOS 750D" → "Canon 750D"; "DSC-W730" → "Sony DSC-W730"
            modelo = modelo.replace('EOS ', '')
            if marca and not modelo.lower().startswith(marca.split()[0].lower()):
                modelo = f'{marca.split()[0].title()} {modelo}'
            datos['camara'] = modelo

        if 0x8769 in principal:
            p = struct.unpack(en + 'I', principal[0x8769][2])[0]
            sub = entradas(p)

            fecha = texto(0x9003, sub)
            if fecha and len(fecha) >= 10:
                datos['fecha'] = fecha[:10].replace(':', '-')
                datos['anio'] = fecha[:4]

            f = racional(0x829D, sub)          # FNumber
            if f:
                v = f[0] / f[1]
                # f/5.6 y no f/5.60; f/8 y no f/8.0
                datos['apertura'] = 'f/' + (f'{v:.1f}'.rstrip('0').rstrip('.'))

            v = racional(0x829A, sub)          # ExposureTime
            if v:
                num, den = v
                if num and den / num >= 1:
                    datos['velocidad'] = f'1/{round(den / num)} s'
                elif num:
                    datos['velocidad'] = (f'{num / den:g} s')

            iso = entero(0x8827, sub)
            if iso:
                datos['iso'] = iso

            fl = racional(0x920A, sub)         # FocalLength, la real
            if fl:
                datos['focal'] = fl[0] / fl[1]

            obj = texto(0xA434, sub)           # LensModel
            if obj:
                datos['objetivo'] = obj

        return datos
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────
#  Focal equivalente a 35 mm
# ─────────────────────────────────────────────────────────────────────

# Cuánto hay que multiplicar la focal real de cada cámara para saber qué
# encuadre da. Sin esto los números no se pueden comparar entre cámaras:
# 8 mm en la compacta es un angular corriente y en la réflex un ojo de pez.
# Las de carrete de 35 mm van a 1: ahí la focal ya es la equivalente.
FACTOR_RECORTE = {
    'Canon 750D': 1.6,          # APS-C
    'Sony DSC-W730': 5.62,      # sensor 1/2.3"
    'FED-2': 1.0,               # 35 mm
    'Zorki-6': 1.0,
    'Smena-2': 1.0,
    'Olympus Superzoom 70S': 1.0,
}


def focal_equivalente(focal_real, camara):
    """Focal en equivalente de 35 mm, redondeada. None si no sé el factor."""
    if not focal_real or not camara:
        return None
    factor = FACTOR_RECORTE.get(camara)
    if not factor:
        return None
    return round(focal_real * factor)


# ─────────────────────────────────────────────────────────────────────
#  filtros.json
# ─────────────────────────────────────────────────────────────────────

def leer_fichas():
    with open(FILTROS, encoding='utf-8') as fh:
        return json.load(fh).get('photos', [])


def escribir_fichas(fichas):
    """Mismo formato que tenía el archivo: 2 espacios, tildes sin escapar."""
    tmp = FILTROS + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump({'photos': fichas}, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
    os.replace(tmp, FILTROS)


# Primero lo que filtra y se ve en la portada; después la ficha técnica,
# que sólo asoma en el visor.
ORDEN = ['id', 'filename', 'width', 'height', 'place', 'city', 'zone',
         'camera', 'capture_type', 'color_mode',
         'lens', 'aperture', 'shutter', 'iso', 'focal_35',
         'film', 'developing', 'year']

# Los de la ficha técnica: no filtran, no salen en el mosaico.
TECNICOS = ['lens', 'aperture', 'shutter', 'iso', 'focal_35',
            'film', 'developing', 'year']


def ordenar(ficha):
    """Deja las claves siempre en el mismo orden, para que el diff se lea."""
    salida = {k: ficha[k] for k in ORDEN if k in ficha}
    for k, v in ficha.items():          # cualquier campo extra, al final
        if k not in salida:
            salida[k] = v
    return salida


# ─────────────────────────────────────────────────────────────────────
#  Botones de filtro en index.html
# ─────────────────────────────────────────────────────────────────────

def _escapar(v):
    return (v.replace('&', '&amp;').replace('"', '&quot;')
             .replace('<', '&lt;').replace('>', '&gt;'))


def _boton(eje, valor, sangria, clase='', extra='', oculto=False):
    v = _escapar(valor)
    codo = (f'\n{sangria}  <span class="opcion__codo" aria-hidden="true"></span>'
            if 'opcion--zona' in clase else '')
    return (
        f'{sangria}<button class="opcion{clase}" data-eje="{eje}" '
        f'data-valor="{v}"{extra} aria-pressed="false"'
        f'{" hidden" if oculto else ""}>{codo}\n'
        f'{sangria}  {v}\n'
        f'{sangria}  <span class="opcion__cuenta">0</span>\n'
        f'{sangria}</button>')


def _bloque_simple(eje, valores, sangria):
    return '\n'.join(_boton(eje, v, sangria) for v in valores)


def _bloque_ciudades(ciudades, zonas_de, sangria):
    """Cada ciudad y, sangradas debajo, sus zonas. Nacen ocultas: sólo
    asoman cuando su ciudad está marcada, y de eso se encarga el JS."""
    trozos = []
    for c in ciudades:
        trozos.append(_boton('ciudad', c, sangria))
        for z in zonas_de.get(c, []):
            trozos.append(_boton(
                'zona', z, sangria, clase=' opcion--zona',
                extra=f' data-ciudad="{_escapar(c)}"', oculto=True))
    return '\n'.join(trozos)


def html_regenerado(fichas):
    """Devuelve index.html con los botones al día, sin escribir nada.

    Se separa del guardado a propósito: si faltan las marcas, esto
    revienta antes de que se haya tocado ningún archivo. Antes se
    escribía filtros.json primero y el fallo llegaba después, así que la
    ficha quedaba guardada mientras la página anunciaba que no.
    """
    with open(INDEX, encoding='utf-8') as fh:
        html = fh.read()

    def unicos(campo):
        vistos = []
        for f in fichas:
            v = (f.get(campo) or '').strip()
            if v and v not in vistos:
                vistos.append(v)
        return vistos

    def zonas_por_ciudad():
        """Las zonas agrupadas bajo su ciudad, en el orden en que
        aparecen. Dos ciudades pueden tener un 'Centro' cada una y no se
        estorban, porque cada una cuelga de la suya."""
        salida = {}
        for f in fichas:
            z = (f.get('zone') or '').strip()
            c = (f.get('city') or '').strip()
            if z and c:
                salida.setdefault(c, [])
                if z not in salida[c]:
                    salida[c].append(z)
        return salida

    ciudades = unicos('city')
    zonas_de = zonas_por_ciudad()

    for marca in ('ciudades', 'camaras'):
        patron = re.compile(
            r'([ \t]*)(<!-- ' + marca + r':inicio -->)(.*?)([ \t]*<!-- '
            + marca + r':fin -->)', re.S)
        casacion = patron.search(html)
        if not casacion:
            raise RuntimeError(
                f'no encuentro las marcas «{marca}:inicio/fin» en index.html')
        sangria = casacion.group(1)
        nuevo = (_bloque_ciudades(ciudades, zonas_de, sangria)
                 if marca == 'ciudades'
                 else _bloque_simple('camara', unicos('camera'), sangria))
        html = (html[:casacion.start()] + sangria + casacion.group(2) + '\n'
                + nuevo + '\n' + casacion.group(4) + html[casacion.end():])

    return html


def escribir_index(html):
    tmp = INDEX + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(html)
    os.replace(tmp, INDEX)


def regenerar_botones(fichas):
    """Reescribe lo que hay entre las marcas. Fuera de ellas no toca nada."""
    escribir_index(html_regenerado(fichas))


# ─────────────────────────────────────────────────────────────────────
#  Estado: qué hay convertido, qué etiquetado, qué falta
# ─────────────────────────────────────────────────────────────────────

def base(nombre):
    return os.path.splitext(nombre)[0]


def estado():
    fichas = leer_fichas()
    con_ficha = {f['filename'] for f in fichas}

    webps = sorted(n for n in os.listdir(WEBPS)
                   if n.lower().endswith('.webp'))
    originales = []
    if os.path.isdir(ORIGINALES):
        originales = sorted(n for n in os.listdir(ORIGINALES)
                            if n.lower().endswith(EXTENSIONES))

    bases_webp = {base(n) for n in webps}
    sin_convertir = [n for n in originales if base(n) not in bases_webp]

    # sugerencias para las que aún no tienen ficha
    pendientes = []
    for n in webps:
        if n in con_ficha:
            continue
        original = next((o for o in originales if base(o) == base(n)), None)
        datos = exif(os.path.join(ORIGINALES, original)) if original else {}
        ancho, alto = medir(os.path.join(WEBPS, n))
        pendientes.append({
            'filename': n,
            'width': ancho,
            'height': alto,
            'sugerencia': {
                'camera': datos.get('camara', ''),
                'date': datos.get('fecha', ''),
            },
        })

    ciudades, camaras, formato_de = [], [], {}
    zonas_de = {}          # ciudad -> [zonas ya usadas en ella]
    for f in fichas:
        c = (f.get('city') or '').strip()
        if c and c not in ciudades:
            ciudades.append(c)
        m = (f.get('camera') or '').strip()
        if m and m not in camaras:
            camaras.append(m)
        if m and f.get('capture_type'):
            formato_de[m] = f['capture_type']
        z = (f.get('zone') or '').strip()
        if c and z:
            zonas_de.setdefault(c, [])
            if z not in zonas_de[c]:
                zonas_de[c].append(z)

    return {
        'pendientes': pendientes,
        'sinConvertir': sin_convertir,
        'etiquetadas': [ordenar(f) for f in fichas],
        'ciudades': ciudades,
        'camaras': camaras,
        'formatoDe': formato_de,
        'zonasDe': zonas_de,
        'peliculas': sorted({(f.get('film') or '').strip()
                             for f in fichas if f.get('film')}),
        'camarasConFactor': sorted(FACTOR_RECORTE),
        'tecnicos': TECNICOS,
        'magick': bool(MAGICK),
    }


def tecnica_de(nombre, camara):
    """Lo que el visor enseñaría de esa foto si la guardaras ahora mismo.
    La usa el taller para ir mostrando la lectura del original."""
    return datos_tecnicos(nombre, camara)


def importar():
    """Convierte los originales que aún no tengan WebP. Devuelve los nombres."""
    hechas, fallos = [], []
    if not os.path.isdir(ORIGINALES):
        return hechas, fallos
    bases_webp = {base(n) for n in os.listdir(WEBPS)
                  if n.lower().endswith('.webp')}
    for n in sorted(os.listdir(ORIGINALES)):
        if not n.lower().endswith(EXTENSIONES) or base(n) in bases_webp:
            continue
        destino = os.path.join(WEBPS, base(n) + '.webp')
        try:
            convertir(os.path.join(ORIGINALES, n), destino)
            hechas.append(os.path.basename(destino))
        except Exception as e:
            if os.path.exists(destino):
                os.remove(destino)
            fallos.append({'archivo': n, 'motivo': str(e)[:200]})
    return hechas, fallos


def datos_tecnicos(nombre_webp, camara):
    """Lo que el original cuenta de su disparo, listo para la ficha."""
    original = next((o for o in os.listdir(ORIGINALES)
                     if base(o) == base(nombre_webp)), None) \
        if os.path.isdir(ORIGINALES) else None
    if not original:
        return {}
    e = exif(os.path.join(ORIGINALES, original))
    salida = {}
    for clave, campo in (('apertura', 'aperture'), ('velocidad', 'shutter'),
                         ('iso', 'iso'), ('objetivo', 'lens'),
                         ('anio', 'year')):
        if e.get(clave):
            salida[campo] = e[clave]
    eq = focal_equivalente(e.get('focal'), camara)
    if eq:
        salida['focal_35'] = eq
    return salida


def _ficha_tecnica(ficha, entrada, nombre):
    """Rellena los campos que sólo se ven en el visor.

    En digital manda el original: se releen del EXIF en cada guardado, así
    que se corrigen solos si cambia la cámara —y con ella el factor de
    recorte—. En analógico no hay EXIF que valga, porque el del escaneo es
    del escáner, así que manda lo que escribas.
    """
    digital = ficha.get('capture_type') == 'digital'
    leidos = datos_tecnicos(nombre, ficha.get('camera')) if digital else {}

    for campo in TECNICOS:
        # Película y revelado son cosa del carrete: en digital no existen
        # por mucho que lleguen escritos.
        if digital and campo in ('film', 'developing'):
            ficha.pop(campo, None)
            continue

        escrito = entrada.get(campo)
        escrito = escrito.strip() if isinstance(escrito, str) else escrito
        valor = leidos.get(campo) if digital and leidos.get(campo) else escrito

        # ISO y focal son números aunque lleguen escritos a mano
        if campo in ('iso', 'focal_35') and isinstance(valor, str):
            valor = int(valor) if valor.strip().isdigit() else None

        if valor in (None, '', 0):
            ficha.pop(campo, None)
        else:
            ficha[campo] = valor


def guardar_ficha(entrada):
    """Añade o actualiza una ficha y deja index.html al día."""
    nombre = entrada.get('filename')
    if not nombre:
        raise ValueError('falta filename')
    ruta = os.path.join(WEBPS, nombre)
    if not os.path.isfile(ruta):
        raise ValueError(f'no existe fotos/{nombre}')

    ancho, alto = medir(ruta)          # siempre del archivo, nunca de fuera
    fichas = leer_fichas()
    existente = next((f for f in fichas if f['filename'] == nombre), None)

    ficha = dict(existente) if existente else {}
    ficha.update({
        'filename': nombre,
        'width': ancho,
        'height': alto,
        'place': (entrada.get('place') or '').strip(),
        'city': (entrada.get('city') or '').strip(),
        'camera': (entrada.get('camera') or '').strip(),
        'capture_type': entrada.get('capture_type') or 'digital',
        'color_mode': entrada.get('color_mode') or 'color',
    })
    # La zona es opcional: si no la hay, no se escribe el campo. Así
    # repasar la galería entera no deja 29 fichas con un "zone" vacío.
    zona = (entrada.get('zone') or '').strip()
    if zona:
        ficha['zone'] = zona
    else:
        ficha.pop('zone', None)

    _ficha_tecnica(ficha, entrada, nombre)

    if not existente:
        ficha['id'] = max([f.get('id', 0) for f in fichas], default=0) + 1
        fichas.append(ficha)
    else:
        fichas[fichas.index(existente)] = ficha

    fichas = [ordenar(f) for f in fichas]
    # Primero se prepara el HTML, que es lo único que puede fallar aquí;
    # sólo si sale bien se escribe. Al revés, un fallo dejaba la ficha ya
    # guardada mientras la página decía que no se había podido guardar.
    html = html_regenerado(fichas)
    escribir_fichas(fichas)
    escribir_index(html)
    return ficha


def borrar_ficha(nombre):
    fichas = [f for f in leer_fichas() if f['filename'] != nombre]
    fichas = [ordenar(f) for f in fichas]
    html = html_regenerado(fichas)
    escribir_fichas(fichas)
    escribir_index(html)


# ─────────────────────────────────────────────────────────────────────
#  Servidor
# ─────────────────────────────────────────────────────────────────────

class Manejador(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=RAIZ, **kw)

    def log_message(self, formato, *args):
        if '/taller' in (self.path or ''):
            sys.stderr.write('  %s\n' % (formato % args))

    def end_headers(self):
        """Nada de caché: aquí los archivos cambian mientras miras.
        Sin esto el navegador te enseña el index.html de hace dos
        guardados y parece que el taller no hace nada. Es el único sitio
        donde se pone la cabecera, así que nunca sale duplicada."""
        self.send_header('Cache-Control', 'no-store, must-revalidate')
        super().end_headers()

    # -- utilidades ---------------------------------------------------
    def _json(self, cuerpo, codigo=200):
        crudo = json.dumps(cuerpo, ensure_ascii=False).encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def _cuerpo(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n) or b'{}')

    # -- rutas --------------------------------------------------------
    def do_GET(self):
        ruta = self.path.split('?', 1)[0]

        if ruta.startswith('/taller/datos'):
            try:
                with CERROJO:
                    self._json(estado())
            except Exception as e:
                self._json({'error': str(e)}, 500)
            return

        # Qué diría el original de su disparo con la cámara que le pongas.
        # Va aparte de /datos porque cambia al tocar la cámara: el factor
        # de recorte depende de ella.
        if ruta.startswith('/taller/tecnica'):
            try:
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                self._json(tecnica_de(q.get('foto', [''])[0],
                                      q.get('camara', [''])[0]))
            except Exception as e:
                self._json({'error': str(e)}, 500)
            return

        # /taller → /taller/ ; /taller/ → la página. Ojo: comparar con
        # rstrip('/') casaba las dos y se redirigía a sí misma sin fin.
        if ruta == '/taller':
            self.send_response(302)
            self.send_header('Location', '/taller/')
            self.end_headers()
            return
        if ruta == '/taller/':
            self.path = '/taller/taller.html'

        return super().do_GET()

    def do_POST(self):
        try:
            if self.path.startswith('/taller/importar'):
                with CERROJO:
                    hechas, fallos = importar()
                self._json({'convertidas': hechas, 'fallos': fallos})
                return
            if self.path.startswith('/taller/guardar'):
                datos = self._cuerpo()
                with CERROJO:
                    ficha = guardar_ficha(datos)
                self._json({'ficha': ficha})
                return
            if self.path.startswith('/taller/borrar'):
                datos = self._cuerpo()
                with CERROJO:
                    borrar_ficha(datos.get('filename', ''))
                self._json({'ok': True})
                return
            self._json({'error': 'ruta desconocida'}, 404)
        except Exception as e:
            self._json({'error': str(e)}, 400)


def main():
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    if not MAGICK:
        print('  Aviso: no encuentro ImageMagick; no podré convertir '
              'originales.\n')
    servidor = ThreadingHTTPServer(('127.0.0.1', puerto), Manejador)
    print(f'  Sanlo.raw\n'
          f'  sitio   http://localhost:{puerto}\n'
          f'  taller  http://localhost:{puerto}/taller/\n\n'
          f'  Ctrl+C para parar.\n')
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print('\n  Hasta luego.')


if __name__ == '__main__':
    main()
