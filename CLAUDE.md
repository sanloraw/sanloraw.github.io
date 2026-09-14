# Sanlo.raw

Sitio de fotografía de calle de Daniel San Lorenzo, servido por GitHub Pages
desde `sanloraw/sanloraw.github.io`. Sitio estático: HTML, CSS y JavaScript a
pelo, sin compilación ni dependencias de Node.

## Cómo está montado

| | |
|---|---|
| `index.html` | La web entera. Las fotos salen de `filtros.json`. |
| `filtros.json` | Ficha de cada fotografía: lugar, cámara, datos de disparo. |
| `fotos/` | Los WebP que publica la web (lado mayor 2000, calidad 82). |
| `fotos/_originales/` | Los JPEG a resolución completa. **Fuera del repositorio.** |
| `taller/taller.py` | Servidor local en :8123 que sirve el sitio y el taller. |
| `taller/taller.html` | La página del taller: etiquetar, cuadrícula, Instagram. |
| `taller/instagram.py` | El brazo de Instagram (ver abajo). |
| `instagram/` | Los montajes 1080 × 1350 y la cola de publicaciones. |
| `instagram/publicados/` | Un registro por publicación. Lo escribe quien publica. |
| `.github/workflows/instagram.yml` | La Action que publica la cola por fecha. |

El taller se abre con `Abrir taller.bat` o `python taller/taller.py`. Depende de
**ImageMagick** para todo lo que sea tocar imágenes; en Python no usa ninguna
librería externa, y conviene que siga siendo así.

El botón *Publicar* del taller hace `git add/commit/push` de `PUBLICABLE`
—`filtros.json`, `index.html`, `fotos`, `instagram`— y nada más. El código del
sitio y del taller se queda fuera a propósito: ese botón publica contenido.

## Instagram

Decidido en septiembre de 2026 tras un estudio de maquetación con la cuenta
delante. Estos números no son preferencias: cada uno responde a algo.

**La regla que no se negocia: la fotografía nunca se recorta.** Se escala y se
centra sobre el papel. No hay `object-fit`, ni recorte cuadrado, ni en la
miniatura del perfil.

| | |
|---|---|
| Lienzo | 1080 × 1350 (4:5) |
| Papel | Blanco `#FFFFFF` |
| Margen horizontales | 40 px |
| Margen verticales | 8 px |
| Banda con pie | 80 px arriba y abajo |
| Pie | `CIUDAD · AÑO`, Karla 500, 15 px, interletra 2,8, a 18 px del borde sur |
| Filete | 1 px `#DFDFDE` rodeando la foto |

Por qué 4:5 y por qué 40: desde enero de 2025 la cuadrícula del perfil recorta
todas las miniaturas a **3:4**, y sobre un 4:5 eso se lleva 33,75 px por lado.
Un lienzo cuadrado se llevaría 135 y se comería la foto. Un margen menor de 34
también. De ahí el suelo de 40, que deja 6 px de holgura. **Si Instagram vuelve
a cambiar la proporción de la cuadrícula, hay que recalcular ese margen.**

En verticales el margen lateral real lo impone la altura (acaba en 122-143 px),
así que el filo de 8 px sólo gobierna arriba y abajo. La banda de 80 existe
porque con menos el pie se pega al borde de la foto en las verticales.

### El flujo

1. Sueltas originales en `instagram/_originales/` (fuera del repositorio).
2. Pestaña **Instagram** del taller → *Montar*. Hereda ciudad, zona y año de
   `filtros.json` si la foto ya está en la web, emparejando por nombre base.
3. Escribes tu línea. Hashtags, texto alternativo y pie vienen propuestos.
4. *Publicar* (el botón de la cabecera) sube los montajes al repositorio.
   **Este paso es obligatorio**: la API de Instagram no acepta archivos, sólo
   una URL pública, y la de cada montaje es
   `https://sanloraw.github.io/instagram/<nombre>_ig.jpg`.
5. Una de dos:
   - *Publicar ahora*: sale en el momento.
   - *Listo para publicar* con fecha, y *Publicar* otra vez: la saca la
     Action a su hora, aunque el ordenador esté apagado.

Cambiar ciudad o año rehace el montaje, porque el pie va grabado dentro del
JPEG y no en el texto del post.

### La cola y quién escribe qué

La cola la edita el taller en casa y la publica la Action en la nube, a la
vez y sin avisarse. Para que no choquen, **cada archivo tiene un solo
dueño**:

| | Lo escribe | Qué guarda |
|---|---|---|
| `instagram/posts.json` | sólo el taller | lo editorial, y el estado `borrador` o `listo` |
| `instagram/publicados/<montaje>.json` | quien publica | `publicando`, `publicado` o `error` |

El estado que se ve es el del registro si lo hay. Los registros se nombran
por el montaje y no por el número de la cola, para que un número reutilizado
no herede la publicación de otra foto.

**Git hace de cerrojo.** Antes de llamar a Meta, quien publica trae lo de
GitHub, escribe «publicando» y lo sube. Si otro se adelantó, el push falla,
la reserva se deshace y no se publica nada. Es lo que impide que el taller y
la Action, o dos pasadas de la Action, saquen la misma foto dos veces.
Probado con dos clones y un remoto local: choque simultáneo, push rechazado
deshecho sin restos, y trabajo a medias intacto gracias a `--autostash`.

Por eso el botón *Publicar* hace `pull --rebase --autostash` antes del push:
GitHub tiene commits que no salen de casa. Nunca choca con la Action porque
la Action sólo escribe en `publicados/`.

### La Action

`.github/workflows/instagram.yml`, a los minutos 7 y 37 de cada hora (no en
punto: GitHub va cargado y se retrasa).

- **Una por pasada.** Si se acumulan, salen con media hora de aire.
- **No reintenta.** Con registro de error o reserva a medias, no la toca:
  se ve en el taller y se reintenta con *Publicar ahora*. Una reserva de más
  de 20 minutos se da por abandonada; hay que mirar en Instagram si salió.
- **Sin línea no publica**: apunta el error una vez y no insiste.
- **Sin secretos no hace nada** y termina en verde. Un fallo manda un correo,
  y fallar cada media hora por no estar configurada sería un correo cada
  media hora.
- **Revisión diaria del token** (10:17 en Madrid): falla a propósito si le
  queda una semana o menos. Una vez al día, no cada pasada.
- Lanzada a mano desde GitHub, es un **ensayo** por defecto: dice qué
  publicaría sin publicar.
- Antes de pedirle la imagen a Meta, espera a que Pages la sirva; y entre
  crear el contenedor y publicarlo, espera a que Meta la procese.

`posts.json` está en un repositorio público: las líneas programadas se ven
antes de salir.

### Hashtags

Pocas y precisas, de 4 a 6. Mosseri dijo en julio de 2026 que los hashtags
nunca han sido una buena forma de aumentar el alcance: sirven como etiqueta de
contexto. El alcance se juega en las palabras del pie, la ubicación y el texto
alternativo, que Instagram sí indexa. No conviene volver a la red de pesca de
treinta etiquetas.

### Credenciales

`instagram/.credenciales.json`, fuera del repositorio, con `token` e
`ig_user_id` (y opcionalmente `host`, `version`, `caduca`). La cuenta es
profesional y la app de Meta está en modo desarrollo con el propio usuario como
administrador, que es lo que evita la revisión de Meta. El token de larga
duración caduca a los 60 días; el taller muestra los días restantes y tiene un
botón para renovarlo.

**El token no pasa por ningún chat, ni por el repositorio, ni por ningún
registro.** Sale de esta máquina en un solo caso: si se conecta la cola
automática, el taller manda una copia a los secretos cifrados de GitHub, que
es lo único que la Action puede leer. Lo hace `gh` (la herramienta oficial de
GitHub) con el token por la entrada estándar, nunca en los argumentos. En el
archivo de credenciales queda `sincronizado`, una huella de 12 caracteres para
saber si GitHub tiene el token de ahora sin guardarlo en otro sitio. Nadie
más que Sanlo pulsa ese botón.

| En GitHub | Tipo | |
|---|---|---|
| `IG_TOKEN`, `IG_USER_ID` | secreto | lo que la Action necesita para publicar |
| `IG_TOKEN_CADUCA` | variable | para la revisión diaria; no es secreta |
| `IG_HOST`, `IG_VERSION` | variable | sólo si no son los de por defecto |

**Se renueva en casa, no en la Action.** Para que la Action se renovara sola
tendría que poder reescribir sus propios secretos, y eso exige guardar en
GitHub otra llave con permiso para tocarlos: más peligrosa que el problema.
Renovar en el taller manda la copia nueva a GitHub en el mismo gesto.

`gh` hay que instalarlo una vez: `winget install --id GitHub.cli` y después
`gh auth login`.

## Lo que falta

- **Geoetiqueta**: la API admite `location_id`, pero conseguirlo exige buscar
  la página de Facebook del lugar y permisos adicionales. De momento se añade
  a mano editando la publicación, que sí está permitido.

## Cómo trabaja Sanlo

Valida lo visual y lo conceptual; la implementación la delega. Todo lo que vaya
a manejar él solo necesita estar explicado en lenguaje llano. Prefiere quitar
antes que añadir, tanto en diseño como en alcance. El español es el idioma del
proyecto: interfaz, comentarios del código y nombres de funciones.
