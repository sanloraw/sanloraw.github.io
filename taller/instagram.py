#!/usr/bin/env python3
"""El brazo de Instagram del taller de Sanlo.raw.

Mismo ritmo que la web: sueltas los originales en una carpeta, esto los
monta, tú escribes una línea y se publica. Lo que no está en ninguna parte
—esa línea— es lo único que pregunta.

  instagram/
    _originales/         sueltas aquí las fotos      (fuera del repositorio)
    <nombre>_ig.jpg      el montaje 1080 × 1350      (SÍ va al repositorio)
    posts.json           la ficha de cada publicación — ESCRIBE SÓLO EL TALLER
    publicados/          un archivo por publicación  — ESCRIBE QUIEN PUBLICA
    .credenciales.json   el token de Meta            (fuera del repositorio)

Por qué dos sitios y no uno: la cola la edita el taller en casa y la
publica GitHub Actions en la nube, a la vez y sin avisarse. Si los dos
escribiesen posts.json, al juntarse chocarían; y si la Action no pudiera
dejar dicho que ya publicó, la siguiente pasada publicaría otra vez. Así
cada archivo tiene un solo dueño y git nunca tiene nada que mezclar.

El montaje se hace con ImageMagick, igual que la conversión a WebP: el
taller ya depende de él y así no aparece ninguna dependencia nueva de
Python. La tipografía viaja en taller/fuentes/ para que el resultado sea
el mismo en cualquier máquina.

    python taller/instagram.py estado
    python taller/instagram.py importar
    python taller/instagram.py publicar <montaje>
    python taller/instagram.py cola [--ensayo]      lo que corre la Action
    python taller/instagram.py caducidad            cuánto le queda al token

Nada de esto se ejecuta solo salvo `cola`, y `cola` sólo publica lo que tú
marcaste como listo y con fecha.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import taller                                    # noqa: E402  (convertir, exif, …)

RAIZ = taller.RAIZ
ENTRADA = os.path.join(RAIZ, 'instagram', '_originales')
MONTAJES = os.path.join(RAIZ, 'instagram')
POSTS = os.path.join(MONTAJES, 'posts.json')
PUBLICADOS = os.path.join(MONTAJES, 'publicados')
CREDENCIALES = os.path.join(MONTAJES, '.credenciales.json')

RAMA = 'main'                                    # la que sirve GitHub Pages

# Cuánto se espera a una reserva antes de darla por abandonada. Una
# publicación normal tarda segundos; si pasado esto sigue "publicando", es
# que quien la reservó se cayó a medias y hay que mirar en Instagram.
RESERVA_CADUCA = timedelta(minutes=20)
FUENTE = os.path.join(taller.TALLER, 'fuentes', 'Karla.ttf')

SITIO = 'https://sanloraw.github.io'             # de dónde las lee Instagram

# ─────────────────────────────────────────────────────────────────────
#  El marco. Estos números están decididos: no se tocan por capricho.
# ─────────────────────────────────────────────────────────────────────

ANCHO, ALTO = 1080, 1350          # 4:5, el único formato que la miniatura
                                  # del perfil no llega a recortar
PAPEL = 'white'
MARGEN = {'horizontal': 40,       # 40 es el suelo: la miniatura 3:4 se come
          'vertical': 8}          # 33,75 px por lado y hay que sobrevivirlos
BANDA = 80                        # aire arriba y abajo cuando hay pie
FILETE = '#DFDFDE'                # 1 px, para que un cielo claro no se derrame
TINTA = '#8A8683'                 # sumi al 62 % sobre blanco
CUERPO = 15
INTERLETRA = 2.8
ALTURA_PIE = 18                   # del borde inferior, con gravedad sur


def _magick():
    if not taller.MAGICK:
        raise RuntimeError('No encuentro ImageMagick. Es el mismo que usa '
                           'el taller para convertir a WebP.')
    return taller.MAGICK


def montar(origen, destino, pie, orientacion):
    """Original → montaje 1080 × 1350 con la foto entera y centrada.

    El '>' de -resize sólo encoge: una foto pequeña nunca se estira. El
    -border pone el filete y el -extent centra sobre el papel. El pie va
    después, para que no lo toque el escalado.
    """
    m = MARGEN[orientacion]
    caja = f'{ANCHO - 2*m}x{ALTO - 2*BANDA}>'
    orden = [_magick(), origen, '-auto-orient', '-resize', caja,
             '-bordercolor', FILETE, '-border', '1',
             '-background', PAPEL, '-gravity', 'center',
             '-extent', f'{ANCHO}x{ALTO}']
    if pie:
        orden += ['-font', FUENTE, '-pointsize', str(CUERPO),
                  '-kerning', str(INTERLETRA), '-fill', TINTA,
                  '-gravity', 'south', '-annotate', f'+0+{ALTURA_PIE}', pie]
    orden += ['-quality', '93', '-sampling-factor', '1x1', destino]
    subprocess.run(orden, check=True, capture_output=True)


def medidas(ruta):
    """Ancho y alto YA girados. Muchas cámaras guardan la vertical tumbada
    con una etiqueta que dice cuánto rotarla: preguntando después del
    -auto-orient, una vertical se reconoce como vertical."""
    salida = subprocess.run(
        [_magick(), ruta, '-auto-orient', '-format', '%w %h', 'info:'],
        check=True, capture_output=True, text=True).stdout.split()
    return int(salida[0]), int(salida[1])


def orientacion_de(ruta):
    ancho, alto = medidas(ruta)
    return 'horizontal' if ancho >= alto else 'vertical'


# ─────────────────────────────────────────────────────────────────────
#  El texto: pie grabado, hashtags, alternativo
# ─────────────────────────────────────────────────────────────────────

def pie_grabado(ficha):
    """Lo que va escrito dentro de la imagen. Ciudad y año en los dos
    formatos: la cuadrícula se lee mejor si todas dicen lo mismo."""
    ciudad = (ficha.get('city') or '').strip()
    anio = (ficha.get('year') or '').strip()
    if not ciudad:
        return ''
    return (f'{ciudad} · {anio}' if anio else ciudad).upper()


def _etiqueta(texto):
    """Rastro → #rastro. Sin tildes, sin espacios, sin signos."""
    plano = unicodedata.normalize('NFD', texto)
    plano = ''.join(c for c in plano if unicodedata.category(c) != 'Mn')
    return '#' + re.sub(r'[^a-z0-9]', '', plano.lower())


def proponer_hashtags(ficha):
    """Pocas y precisas.

    Mosseri lo dijo en julio de 2026: los hashtags funcionan, pero nunca
    han sido una buena forma de aumentar el alcance. Sirven para decir de
    qué va esto y a qué pertenece. Así que aquí no hay red de pesca: una
    de serie, dos de género, el lugar, y una condicional según el archivo.
    El alcance se juega en el pie, la ubicación y el texto alternativo.
    """
    etiquetas = ['#sanloraw', '#fotografiacallejera', '#streetphotography']
    ciudad = (ficha.get('city') or '').strip()
    zona = (ficha.get('zone') or '').strip()
    if ciudad:
        etiquetas.append(_etiqueta(ciudad))
    if zona and zona.lower() != ciudad.lower() and len(zona) > 3:
        etiquetas.append(_etiqueta(zona))
    if (ficha.get('color_mode') or '') == 'bn':
        etiquetas.append('#blancoynegro')
    if (ficha.get('capture_type') or '') == 'analogico':
        etiquetas.append('#fotografiaanalogica')
    # Sin repetidas y sin vacías, respetando el orden.
    vistas, limpias = set(), []
    for e in etiquetas:
        if len(e) > 1 and e not in vistas:
            vistas.add(e)
            limpias.append(e)
    return limpias[:6]


def texto_alternativo(ficha):
    """Lo que Instagram sí indexa y casi nadie rellena."""
    sitio = ', '.join([v for v in [ficha.get('zone'), ficha.get('city')] if v])
    anio = (ficha.get('year') or '').strip()
    trozos = ['Fotografía de calle']
    if sitio:
        trozos.append(f'en {sitio}')
    if anio:
        trozos.append(f'({anio})')
    frase = ' '.join(trozos) + '.'
    escena = (ficha.get('alt_escena') or '').strip()
    return (frase + ' ' + escena).strip() if escena else frase


def caption(post):
    """Tu línea arriba, las etiquetas al final, separadas por aire."""
    partes = [(post.get('linea') or '').strip()]
    etiquetas = ' '.join(post.get('hashtags') or [])
    if etiquetas:
        partes.append(etiquetas)
    return '\n\n'.join(p for p in partes if p)


# ─────────────────────────────────────────────────────────────────────
#  La cola
# ─────────────────────────────────────────────────────────────────────

def leer_posts():
    if not os.path.exists(POSTS):
        return []
    with open(POSTS, encoding='utf-8') as fh:
        return json.load(fh).get('posts', [])


def escribir_posts(posts):
    os.makedirs(MONTAJES, exist_ok=True)
    tmp = POSTS + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump({'posts': posts}, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
    os.replace(tmp, POSTS)


# ── La hora ──────────────────────────────────────────────────────────
# La fecha de programación se guarda en UTC y con su desfase escrito. La
# Action corre en UTC y el taller en hora de Madrid: guardarla "a secas"
# haría que cada uno la leyera distinto, y en el cambio de horario se
# publicaría una hora antes o después.

def ahora():
    return datetime.now(timezone.utc)


def instante(texto):
    """Texto ISO → fecha con zona. None si no hay o no se entiende.
    Acepta la 'Z' final, que Python 3.10 todavía no sabe leer solo."""
    if not texto:
        return None
    try:
        d = datetime.fromisoformat(str(texto).strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def a_utc(texto):
    """Normaliza una fecha a UTC con minutos: '2026-09-18T17:00+00:00'."""
    d = instante(texto)
    return d.astimezone(timezone.utc).isoformat(timespec='minutes') if d else ''


# ── Los registros de publicación ─────────────────────────────────────
# Uno por foto, en instagram/publicados/<montaje sin .jpg>.json. Se nombran
# por el montaje y no por el número de la cola: si quitas una publicación y
# el número se reutiliza, su registro no se le pega a la nueva.

def _nombre_registro(post):
    return os.path.splitext(post['montaje'])[0] + '.json'


def _ruta_registro(post):
    return os.path.join(PUBLICADOS, _nombre_registro(post))


def _rel_registro(post):
    """La ruta tal y como la entiende git: relativa y con barras."""
    return 'instagram/publicados/' + _nombre_registro(post)


def leer_registro(post):
    try:
        with open(_ruta_registro(post), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def escribir_registro(post, datos):
    os.makedirs(PUBLICADOS, exist_ok=True)
    ruta = _ruta_registro(post)
    tmp = ruta + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
    os.replace(tmp, ruta)


def _registros_locales():
    salida = {}
    if os.path.isdir(PUBLICADOS):
        for n in os.listdir(PUBLICADOS):
            if not n.endswith('.json'):
                continue
            try:
                with open(os.path.join(PUBLICADOS, n), encoding='utf-8') as fh:
                    r = json.load(fh)
                salida[r['montaje']] = r
            except (OSError, ValueError, KeyError):
                pass
    return salida


_ultimo_fetch = [0.0]


def _registros_de_github(montajes):
    """Lo que la Action ha dejado en GitHub y aún no está en tu disco.

    Se lee sin tocar tu carpeta: fetch y `git show` de la rama remota. Así
    el taller enseña lo que de verdad pasó sin traerse nada a la fuerza.
    Sólo mira las fotos que pregunta, que son pocas, y hace un fetch como
    mucho una vez por minuto. Sin conexión, se queda con lo local."""
    if not montajes:
        return {}
    if time.time() - _ultimo_fetch[0] > 60:
        try:
            taller._git('fetch', '--quiet', 'origin', RAMA, timeout=20)
        except Exception:
            pass
        _ultimo_fetch[0] = time.time()
    salida = {}
    for m in montajes:
        rel = 'instagram/publicados/' + os.path.splitext(m)[0] + '.json'
        try:
            r = taller._git('show', f'origin/{RAMA}:{rel}', timeout=15)
        except Exception:
            continue
        if r.returncode == 0:
            try:
                salida[m] = json.loads(r.stdout)
            except ValueError:
                pass
    return salida


def _mas_reciente(a, b):
    if not a or not b:
        return a or b
    fa, fb = instante(a.get('fecha')), instante(b.get('fecha'))
    return a if (fa or ahora()) >= (fb or ahora()) else b


def con_estado(posts, remoto=False):
    """Las publicaciones con su estado real encima.

    En posts.json sólo hay borrador o listo, que es lo que decides tú. Lo
    demás —publicando, publicado, error— sale de los registros, que es
    donde lo apunta quien publica."""
    regs = _registros_locales()
    if remoto:
        pendientes = [p['montaje'] for p in posts
                      if p.get('estado') == 'listo'
                      and (regs.get(p['montaje']) or {}).get('estado') != 'publicado']
        for m, r in _registros_de_github(pendientes).items():
            regs[m] = _mas_reciente(regs.get(m), r)
    salida = []
    for p in posts:
        r = regs.get(p['montaje'])
        p = dict(p)
        if r:
            p['estado'] = r.get('estado', p.get('estado'))
            p['publicado'] = {'fecha': r.get('fecha'), 'media_id': r.get('media_id'),
                              'quien': r.get('quien')}
            if r.get('error'):
                p['error'] = r['error']
        salida.append(p)
    return salida


def reserva_viva(registro):
    """¿Hay alguien publicando esto ahora mismo?"""
    if not registro or registro.get('estado') != 'publicando':
        return False
    f = instante(registro.get('fecha'))
    return bool(f and ahora() - f < RESERVA_CADUCA)


# ── Git como cerrojo ────────────────────────────────────────────────
# Antes de llamar a Meta, quien publica sube a GitHub un registro que dice
# "estoy en ello". Si otro se le adelantó, GitHub rechaza el push y aquí
# no se publica nada. Es lo que impide que el taller y la Action, o dos
# pasadas de la Action, saquen la misma foto dos veces.

class Ocupada(RuntimeError):
    """Otro ya la tiene o ya la sacó. No es un fallo: es el cerrojo."""


def _git_ok(*args, timeout=90):
    r = taller._git(*args, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f'git {args[0]}: ' + (r.stderr or r.stdout).strip()[:300])
    return r


def _integrar():
    """Trae lo que haya en GitHub sin perder lo que tengas a medias.

    --autostash aparta tus cambios sin subir (posts.json, montajes nuevos),
    trae lo de fuera y los vuelve a poner. No choca nunca con lo de la
    Action porque la Action sólo escribe en publicados/, y eso no lo
    escribe nadie más que quien publica."""
    r = taller._git('pull', '--rebase', '--autostash', 'origin', RAMA, timeout=120)
    if r.returncode:
        taller._git('rebase', '--abort')
        raise RuntimeError('No he podido traer lo que hay en GitHub: '
                           + (r.stderr or r.stdout).strip()[:300])


def _subir_registro(post, mensaje):
    """Commit sólo de ese registro y push. Devuelve True si llegó."""
    rel = _rel_registro(post)
    _git_ok('add', '--', rel)
    # --only: aunque tengas otras cosas preparadas, este commit lleva sólo
    # el registro. Lo tuyo a medias sigue a medias.
    _git_ok('commit', '--only', '-m', mensaje, '--', rel)
    return taller._git('push', 'origin', f'HEAD:{RAMA}', timeout=120).returncode == 0


def reservar(post, quien):
    """Cierra el cerrojo sobre esa foto o lanza Ocupada."""
    _integrar()
    antes = leer_registro(post)
    if antes and antes.get('estado') == 'publicado':
        raise Ocupada(f"Ya se publicó el {(antes.get('fecha') or '')[:10]}.")
    if reserva_viva(antes):
        raise Ocupada('Ahora mismo la está publicando '
                      + ('GitHub' if antes.get('quien') == 'github' else 'el taller')
                      + '. Espera un par de minutos.')

    escribir_registro(post, {'montaje': post['montaje'], 'id': post.get('id'),
                             'estado': 'publicando', 'quien': quien,
                             'fecha': ahora().isoformat(timespec='seconds')})
    if _subir_registro(post, f"Reserva {post['montaje']} para Instagram"):
        return

    # GitHub cambió entre que traje y que subí: alguien se ha movido a la
    # vez. Se deshace la reserva sin tocar nada más y no se publica.
    taller._git('reset', '--soft', 'HEAD~1')
    taller._git('reset', '-q', '--', _rel_registro(post))
    if antes:
        escribir_registro(post, antes)
    elif os.path.exists(_ruta_registro(post)):
        os.remove(_ruta_registro(post))
    raise Ocupada('GitHub ha cambiado mientras la reservaba. No he publicado '
                  'nada: vuelve a intentarlo en un minuto.')


def cerrar(post, estado, **extra):
    """Deja apuntado cómo acabó y lo sube. Reintenta si GitHub se movió.

    Devuelve True si llegó a GitHub. Si no llega, el commit queda en tu
    disco y lo subirá el siguiente Publicar: la foto no se repite porque la
    reserva sí llegó."""
    datos = {'montaje': post['montaje'], 'id': post.get('id'), 'estado': estado,
             'quien': (leer_registro(post) or {}).get('quien'),
             'fecha': ahora().isoformat(timespec='seconds')}
    datos.update(extra)
    escribir_registro(post, datos)
    mensaje = (f"Publica en Instagram: {post['montaje']}" if estado == 'publicado'
               else f"No se pudo publicar {post['montaje']}")
    _integrar()
    if _subir_registro(post, mensaje):
        return True
    for _ in range(3):
        try:
            _integrar()
        except RuntimeError:
            return False
        if taller._git('push', 'origin', f'HEAD:{RAMA}', timeout=120).returncode == 0:
            return True
        time.sleep(5)
    return False


def ficha_heredada(nombre):
    """Lo que la web ya sabe de esa foto, si la conoce. Se busca por nombre
    base, que es como el taller relaciona original y WebP."""
    raiz = taller.base(nombre)
    for f in taller.leer_fichas():
        if taller.base(f['filename']) == raiz:
            return dict(f)
    return {}


def _desde_exif(ruta):
    e = taller.exif(ruta)
    return {'year': e.get('anio', ''), 'camera': e.get('camara', '')}


def importar():
    """Monta los originales que aún no tengan montaje. No publica nada."""
    montados, fallos = [], []
    if not os.path.isdir(ENTRADA):
        os.makedirs(ENTRADA, exist_ok=True)
        return montados, fallos

    posts = leer_posts()
    ya = {p['origen'] for p in posts}
    siguiente = max([p['id'] for p in posts], default=0) + 1

    for nombre in sorted(os.listdir(ENTRADA)):
        if not nombre.lower().endswith(taller.EXTENSIONES) or nombre in ya:
            continue
        origen = os.path.join(ENTRADA, nombre)
        destino_nombre = taller.base(nombre) + '_ig.jpg'
        destino = os.path.join(MONTAJES, destino_nombre)
        try:
            ficha = ficha_heredada(nombre) or _desde_exif(origen)
            orient = orientacion_de(origen)
            montar(origen, destino, pie_grabado(ficha), orient)
            posts.append({
                'id': siguiente,
                'origen': nombre,
                'montaje': destino_nombre,
                'city': ficha.get('city', ''),
                'zone': ficha.get('zone', ''),
                'year': ficha.get('year', ''),
                'orientacion': orient,
                'linea': '',
                'hashtags': proponer_hashtags(ficha),
                'alt': texto_alternativo(ficha),
                'estado': 'borrador',
                'programado': '',
                'publicado': None,
            })
            siguiente += 1
            montados.append(destino_nombre)
        except Exception as e:
            if os.path.exists(destino):
                os.remove(destino)
            fallos.append({'archivo': nombre, 'motivo': str(e)[:200]})

    escribir_posts(posts)
    return montados, fallos


def sin_subir():
    """Montajes que todavía no están en la web. Instagram lee la imagen por
    su dirección pública, así que publicar antes al repositorio no es un
    paso opcional: sin eso, la API no encuentra nada que publicar."""
    try:
        r = taller._git('status', '--porcelain', '--', 'instagram')
    except Exception:
        return set()
    sueltos = set()
    for linea in r.stdout.splitlines():
        ruta = linea[3:].strip().strip('"').replace('\\', '/')
        # los originales no suben nunca: mirarlos aquí daría un falso aviso
        if not ruta.startswith('instagram/') or ruta.startswith('instagram/_'):
            continue
        nombre = os.path.basename(ruta)
        if nombre.lower().endswith('.jpg'):
            sueltos.add(nombre)
    return sueltos


def buscar(id_post):
    posts = leer_posts()
    post = next((p for p in posts if p['id'] == id_post), None)
    if not post:
        raise RuntimeError(f'No encuentro la publicación {id_post}.')
    return posts, post


def actualizar(datos):
    """Guarda la ficha del post. Si cambian ciudad o año hay que rehacer el
    montaje: el pie va grabado dentro de la imagen, no en el texto."""
    posts, post = buscar(datos['id'])
    antes = pie_grabado(post)
    for campo in ('city', 'zone', 'year', 'linea', 'alt'):
        if campo in datos:
            post[campo] = datos[campo]
    # En posts.json el estado es sólo tuyo: borrador o listo. Publicando,
    # publicado y error los apunta quien publica, en su registro; si la
    # página los reenviara aquí, se colarían en el archivo equivocado.
    if datos.get('estado') in ('borrador', 'listo'):
        post['estado'] = datos['estado']
    if 'programado' in datos:
        post['programado'] = a_utc(datos['programado'])
    if 'hashtags' in datos:
        post['hashtags'] = [h if h.startswith('#') else '#' + h
                            for h in datos['hashtags'] if h.strip()]
    rehecho = False
    if pie_grabado(post) != antes:
        remontar(post)
        rehecho = True
    escribir_posts(posts)
    return {'rehecho': rehecho, 'post': post}


def borrar(id_post, borrar_montaje=True):
    """Saca la publicación de la cola. El original no se toca nunca."""
    posts, post = buscar(id_post)
    if borrar_montaje:
        ruta = os.path.join(MONTAJES, post['montaje'])
        if os.path.exists(ruta):
            os.remove(ruta)
    escribir_posts([p for p in posts if p['id'] != id_post])
    return post['montaje']


def publicar_post(id_post, quien='taller'):
    """Publicar ya. Lo usa el botón del taller y, a su hora, la Action.

    Reserva → espera a que la imagen esté en la web → Meta → apunta cómo
    acabó. Si falla después de reservar, queda apuntado el error en vez de
    quedarse colgado, y ni el taller ni la Action lo reintentan solos."""
    _, post = buscar(id_post)
    if not (post.get('linea') or '').strip():
        raise RuntimeError('Falta tu línea: es lo único que no puede '
                           'escribir nadie más.')
    if post['montaje'] in sin_subir():
        raise RuntimeError('El montaje todavía no está en la web. Publica '
                           'primero al repositorio: Instagram lee la imagen '
                           'por su dirección pública.')
    credenciales()                      # que falle antes de reservar nada

    reservar(post, quien)
    try:
        esperar_imagen(url_publica(post))
        media = publicar_en_instagram(post)
    except Exception as e:
        cerrar(post, 'error', error=str(e)[:400])
        raise
    subido = cerrar(post, 'publicado', media_id=media)
    resultado = con_estado([post])[0]
    resultado['avisoGit'] = None if subido else (
        'Publicada, pero no he podido apuntarlo en GitHub. Lo subirá el '
        'siguiente Publicar; mientras, la Action no la repite porque la '
        'reserva sí llegó.')
    return resultado


def remontar(post):
    """Rehace el montaje: hace falta cuando cambian ciudad o año, porque el
    pie va grabado dentro de la imagen y no en el texto del post."""
    origen = os.path.join(ENTRADA, post['origen'])
    if not os.path.exists(origen):
        raise RuntimeError(f"Ya no está el original ({post['origen']}). "
                           'Vuelve a dejarlo en instagram/_originales.')
    montar(origen, os.path.join(MONTAJES, post['montaje']),
           pie_grabado(post), post['orientacion'])


# ─────────────────────────────────────────────────────────────────────
#  Meta: dos llamadas y ya está
# ─────────────────────────────────────────────────────────────────────

def _credenciales_de_archivo():
    if not os.path.exists(CREDENCIALES):
        raise RuntimeError(
            'Falta instagram/.credenciales.json con el token y el id de la '
            'cuenta. Ese archivo no se sube al repositorio.')
    with open(CREDENCIALES, encoding='utf-8') as fh:
        return json.load(fh)


def credenciales():
    """El token y la cuenta.

    En la nube, la Action los recibe como secretos del repositorio en
    variables de entorno; en casa, se leen del archivo. Nunca se imprimen:
    ningún mensaje de este módulo incluye el token."""
    if os.environ.get('IG_TOKEN'):
        c = {'token': os.environ['IG_TOKEN'],
             'ig_user_id': os.environ.get('IG_USER_ID', ''),
             'host': os.environ.get('IG_HOST') or None,
             'version': os.environ.get('IG_VERSION') or None,
             'caduca': os.environ.get('IG_TOKEN_CADUCA') or None}
        c = {k: v for k, v in c.items() if v}
    else:
        c = _credenciales_de_archivo()
    for clave in ('token', 'ig_user_id'):
        if not c.get(clave):
            raise RuntimeError(f'A las credenciales les falta "{clave}".')
    c.setdefault('host', 'graph.instagram.com')
    c.setdefault('version', 'v26.0')
    return c


def _pedir(c, url, datos=None):
    """POST si hay datos, GET si no. El token viaja en el cuerpo o en la
    consulta, nunca en un mensaje de error: Meta no lo devuelve en los
    suyos y aquí sólo se reenvía lo que Meta dice."""
    try:
        if datos is None:
            peticion = urllib.request.Request(url)
        else:
            cuerpo = urllib.parse.urlencode(dict(datos, access_token=c['token']))
            peticion = urllib.request.Request(url, data=cuerpo.encode('utf-8'))
        with urllib.request.urlopen(peticion, timeout=120) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode('utf-8', 'replace')[:400]
        raise RuntimeError(f'Meta respondió {e.code}: {detalle}') from None


def _llamada(c, camino, datos):
    return _pedir(c, f"https://{c['host']}/{c['version']}/{camino}", datos)


def _consulta(c, camino, campos):
    q = urllib.parse.urlencode({'fields': campos, 'access_token': c['token']})
    return _pedir(c, f"https://{c['host']}/{c['version']}/{camino}?{q}")


def url_publica(post):
    return f"{SITIO}/instagram/{urllib.parse.quote(post['montaje'])}"


def esperar_imagen(url, plazo=240):
    """Espera a que GitHub Pages sirva el montaje.

    Instagram va a buscar la imagen a esa dirección. Justo después de un
    Publicar, Pages tarda uno o dos minutos en desplegar, y si Meta llega
    antes encuentra un 404 y la publicación falla sin decir por qué."""
    limite = time.time() + plazo
    while True:
        try:
            peticion = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(peticion, timeout=20) as r:
                if r.status == 200:
                    return
        except urllib.error.URLError:
            pass
        if time.time() > limite:
            raise RuntimeError(f'La imagen no aparece en la web ({url}). '
                               '¿Se subió el montaje con Publicar?')
        time.sleep(10)


def publicar_en_instagram(post):
    """Contenedor, esperar a que esté listo, y publicación.

    Entre crear el contenedor y publicarlo hay que dejar que Meta termine
    de procesar la imagen. Casi siempre es inmediato, pero publicar antes
    de tiempo da un error que en casa se reintenta a mano y en la nube,
    sin nadie delante, dejaría la foto sin salir."""
    c = credenciales()
    contenedor = _llamada(c, f"{c['ig_user_id']}/media", {
        'image_url': url_publica(post),
        'caption': caption(post),
        'alt_text': post.get('alt') or '',
    })
    if 'id' not in contenedor:
        raise RuntimeError(f'Meta no devolvió contenedor: {contenedor}')

    for _ in range(20):                         # hasta un minuto
        estado_c = _consulta(c, contenedor['id'], 'status_code').get('status_code')
        if estado_c == 'FINISHED':
            break
        if estado_c in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'Meta no pudo procesar la imagen ({estado_c}).')
        time.sleep(3)
    else:
        raise RuntimeError('Meta tarda demasiado en procesar la imagen.')

    publicado = _llamada(c, f"{c['ig_user_id']}/media_publish",
                         {'creation_id': contenedor['id']})
    if 'id' not in publicado:
        raise RuntimeError(f'Meta no publicó: {publicado}')
    return publicado['id']


def dias_de_token():
    """Cuánto le queda al token. Caduca a los 60 días y, si se pasa, la
    publicación deja de funcionar en silencio."""
    try:
        c = credenciales()
    except Exception:
        return None
    d = instante(c.get('caduca'))
    return (d - ahora()).days if d else None


def _guardar_credenciales(c):
    tmp = CREDENCIALES + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(c, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
    os.replace(tmp, CREDENCIALES)


def renovar_token():
    """Un token de larga duración se renueva por otro de 60 días, siempre
    que tenga más de 24 horas de vida.

    Se renueva en casa y no en la nube a propósito: para que la Action se
    renovara sola tendría que poder reescribir sus propios secretos, y eso
    exige guardar en GitHub otra llave con permiso para tocarlos. Es más
    peligrosa que el problema que resuelve. Así, renuevas aquí y el taller
    le manda la copia nueva a GitHub."""
    c = _credenciales_de_archivo()
    host = c.get('host') or 'graph.instagram.com'
    q = urllib.parse.urlencode({'grant_type': 'ig_refresh_token',
                                'access_token': c['token']})
    try:
        with urllib.request.urlopen(f'https://{host}/refresh_access_token?{q}',
                                    timeout=60) as r:
            d = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise RuntimeError('Meta no ha renovado el token: '
                           + e.read().decode('utf-8', 'replace')[:300]) from None
    if 'access_token' not in d:
        raise RuntimeError('Meta no ha devuelto un token nuevo.')
    c['token'] = d['access_token']
    segundos = int(d.get('expires_in', 60*24*3600))
    c['caduca'] = (ahora() + timedelta(seconds=segundos)).isoformat(timespec='seconds')
    _guardar_credenciales(c)
    return segundos // 86400


# ── La copia de GitHub ──────────────────────────────────────────────
# La Action necesita el token para publicar con el ordenador apagado, y lo
# único que puede leer es un secreto del repositorio. Se lo manda la
# herramienta oficial de GitHub, `gh`, que lo cifra antes de enviarlo: el
# token va de este archivo a GitHub por la entrada estándar, sin pasar por
# la línea de órdenes, ni por pantalla, ni por ningún registro.

def _gh():
    exe = shutil.which('gh')
    if exe:
        return exe
    for ruta in (os.path.join(os.environ.get('ProgramFiles', ''), 'GitHub CLI', 'gh.exe'),
                 os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs',
                              'GitHub CLI', 'gh.exe')):
        if os.path.isfile(ruta):
            return ruta
    return None


def _huella(token):
    """Doce caracteres para saber si GitHub tiene el token de ahora sin
    tener que guardar el token en ningún otro sitio."""
    import hashlib
    return hashlib.sha256(token.encode('utf-8')).hexdigest()[:12]


def github_al_dia():
    try:
        c = _credenciales_de_archivo()
    except Exception:
        return False
    return bool(c.get('token')) and c.get('sincronizado') == _huella(c['token'])


def sincronizar_github():
    """Manda a GitHub la copia del token y lo que la Action necesita."""
    exe = _gh()
    if not exe:
        raise RuntimeError(
            'Falta la herramienta de GitHub. Instálala una vez con '
            '«winget install --id GitHub.cli» y luego «gh auth login».')
    c = _credenciales_de_archivo()
    entorno = dict(os.environ, GH_PROMPT_DISABLED='1', NO_COLOR='1')

    def poner(tipo, nombre, valor):
        # el valor entra por stdin: nunca en los argumentos, que se ven en
        # la lista de procesos, ni en los mensajes de error
        r = subprocess.run([exe, tipo, 'set', nombre], input=str(valor),
                           cwd=RAIZ, env=entorno, capture_output=True,
                           text=True, encoding='utf-8', errors='replace',
                           timeout=60)
        if r.returncode:
            motivo = (r.stderr or r.stdout).strip()
            if 'auth login' in motivo or 'not logged' in motivo.lower():
                motivo = 'gh no tiene sesión abierta: ejecuta «gh auth login» una vez.'
            raise RuntimeError(f'GitHub no ha guardado {nombre}. {motivo[:300]}')

    poner('secret', 'IG_TOKEN', c['token'])
    poner('secret', 'IG_USER_ID', c['ig_user_id'])
    # la caducidad no es secreta: la Action la mira para avisarte a tiempo
    if c.get('caduca'):
        poner('variable', 'IG_TOKEN_CADUCA', c['caduca'])
    for clave, nombre in (('host', 'IG_HOST'), ('version', 'IG_VERSION')):
        if c.get(clave):
            poner('variable', nombre, c[clave])

    c['sincronizado'] = _huella(c['token'])
    _guardar_credenciales(c)
    return True


# ── Lo que corre la Action ───────────────────────────────────────────

def vencidas(momento=None):
    """Listas, con fecha ya pasada y sin registro, de la más antigua a la
    más nueva. Con registro ya no: si falló, se queda apuntado el error y
    la Action no insiste; lo reintentas tú desde el taller."""
    momento = momento or ahora()
    regs = _registros_locales()
    salida = [p for p in leer_posts()
              if p.get('estado') == 'listo'
              and instante(p.get('programado'))
              and instante(p['programado']) <= momento
              and p['montaje'] not in regs]
    return sorted(salida, key=lambda p: instante(p['programado']))


def _apuntar_error(post, motivo):
    """Para que un fallo que no se arregla solo no se repita cada media hora."""
    reservar(post, 'github')
    cerrar(post, 'error', error=motivo)


def cola(ensayo=False):
    """Una pasada: publica UNA vencida y termina.

    Una por pasada y no todas de golpe: si la Action estuvo parada y se
    acumulan tres, salen con media hora de aire entre ellas en vez de
    aparecer juntas en el perfil."""
    pendientes = vencidas()
    if not pendientes:
        print('  Nada que publicar ahora.')
        return 0
    post = pendientes[0]
    print(f"  Toca: {post['montaje']} · programada para {post['programado']}")
    if len(pendientes) > 1:
        print(f'  Hay {len(pendientes) - 1} más vencidas: saldrán en las '
              'próximas pasadas, una cada vez.')

    if ensayo:
        print('  Ensayo: no reservo ni publico nada. Saldría esto:\n')
        print('    ' + caption(post).replace('\n', '\n    '))
        print(f"\n  Imagen: {url_publica(post)}")
        return 0

    try:
        credenciales()
    except RuntimeError:
        # Sin secretos no hay nada que hacer, y fallar aquí mandaría un
        # correo cada media hora. Se avisa sin romper; el taller enseña la
        # publicación como vencida sin salir.
        print('::warning::Hay publicaciones vencidas pero GitHub no tiene el '
              'token. Conéctalo desde el taller.')
        return 0

    if not (post.get('linea') or '').strip():
        _apuntar_error(post, 'Falta tu línea: la Action no publica sin ella.')
        print(f"::error::{post['montaje']} no tiene línea. Apuntado como error.")
        return 1

    try:
        resultado = publicar_post(post['id'], quien='github')
    except Ocupada as e:
        print('  ' + str(e))
        return 0
    except Exception as e:
        print(f"::error::No se pudo publicar {post['montaje']}: {e}")
        return 1
    print(f"  Publicada: {post['montaje']} · {resultado['publicado']['media_id']}")
    if resultado.get('avisoGit'):
        print('::warning::' + resultado['avisoGit'])
    return 0


def caducidad():
    """La revisión diaria: si al token le queda una semana o menos, la
    pasada falla a propósito, y un fallo es lo que hace que GitHub te mande
    un correo. Una vez al día, no cada media hora."""
    fecha = os.environ.get('IG_TOKEN_CADUCA')
    if not fecha:
        try:
            fecha = _credenciales_de_archivo().get('caduca')
        except Exception:
            fecha = None
    d = instante(fecha)
    if not d:
        print('  No sé cuándo caduca el token: me salto la revisión.')
        return 0
    dias = (d - ahora()).days
    if dias < 0:
        print(f'::error::El token de Instagram caducó el {d.date()}. La cola '
              'está parada: abre el taller y renuévalo.')
        return 1
    if dias <= 7:
        print(f'::error::Al token de Instagram le quedan {dias} días. Abre '
              'el taller y pulsa Renovar: él mismo se lo manda a GitHub.')
        return 1
    print(f'  Al token le quedan {dias} días.')
    return 0


# ─────────────────────────────────────────────────────────────────────
#  Estado, para la página
# ─────────────────────────────────────────────────────────────────────

def estado():
    posts = leer_posts()
    ya = {p['origen'] for p in posts}
    sin_montar = []
    if os.path.isdir(ENTRADA):
        sin_montar = sorted(n for n in os.listdir(ENTRADA)
                            if n.lower().endswith(taller.EXTENSIONES)
                            and n not in ya)
    return {
        'posts': con_estado(posts, remoto=True),
        'sinMontar': sin_montar,
        'sinSubir': sorted(sin_subir()),
        'credenciales': os.path.exists(CREDENCIALES),
        'diasToken': dias_de_token(),
        'sitio': SITIO,
        'ahora': ahora().isoformat(timespec='seconds'),
        'reservaCaducaMin': int(RESERVA_CADUCA.total_seconds() // 60),
        'github': {'gh': bool(_gh()), 'alDia': github_al_dia()},
    }


# ─────────────────────────────────────────────────────────────────────
#  Línea de órdenes, para probar antes de que exista la pestaña
# ─────────────────────────────────────────────────────────────────────

def _cli():
    # Una consola de Windows que no admita tildes no debe tumbar la orden
    # por un «sí»: se cambia el carácter que no sepa pintar y se sigue.
    try:
        sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass
    orden = sys.argv[1] if len(sys.argv) > 1 else 'estado'

    if orden == 'importar':
        montados, fallos = importar()
        for m in montados:
            print('  montada  ', m)
        for f in fallos:
            print('  FALLO    ', f['archivo'], '·', f['motivo'])
        if not montados and not fallos:
            print('  No hay nada nuevo en instagram/_originales.')
        return

    if orden == 'estado':
        e = estado()
        print(f"  {len(e['posts'])} en la cola · "
              f"{len(e['sinMontar'])} sin montar · "
              f"credenciales: {'sí' if e['credenciales'] else 'no'}")
        for p in e['posts']:
            cuando = f" · {p['programado']}" if p.get('programado') else ''
            print(f"  [{p['estado']:>10}] {p['montaje']:<28} "
                  f"{p['city']} {p['year']}{cuando}")
        return 0

    if orden == 'publicar':
        if len(sys.argv) < 3:
            print('  Dime qué montaje publico.')
            return 1
        post = next((p for p in leer_posts() if p['montaje'] == sys.argv[2]), None)
        if not post:
            print('  No encuentro ese montaje en la cola.')
            return 1
        r = publicar_post(post['id'])
        print('  Publicada.', r['publicado']['media_id'])
        return 0

    if orden == 'cola':
        return cola(ensayo='--ensayo' in sys.argv)

    if orden == 'caducidad':
        return caducidad()

    print(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(_cli() or 0)
