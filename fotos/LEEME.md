# Cómo añadir fotos

No hace falta tocar el HTML ni saber programar. Solo dos pasos.

(Los filtros de Formato/Ciudad/Tratamiento están en pausa por ahora — se
retomarán más adelante con un JSON propio. De momento las fotos solo se
agrupan por categoría/proyecto.)

## 1. Coloca el archivo en la carpeta de su categoría

```
fotos/<categoria>/archivo.jpg
```

`categoria` es el nombre del proyecto o serie al que pertenece la foto —
tú eliges el nombre de la carpeta (por ejemplo `retratos`, `madrid-2025`,
`analogico`...). Cada categoría se muestra seguida de un separador (un
haiku o un concepto japonés) antes de pasar a la siguiente.

Ejemplo:

```
fotos/retratos/lavapies.jpg
fotos/retratos/atocha.jpg
fotos/nocturnas/sol.jpg
```

## 2. Añade una línea en `manifest.json`

Cada foto es un objeto con la ruta (sin el "fotos/" delante) y el texto que
quieres que aparezca sobre la imagen:

```json
[
  { "ruta": "retratos/lavapies.jpg", "lugar": "Lavapiés" },
  { "ruta": "retratos/atocha.jpg",   "lugar": "Atocha" },
  { "ruta": "nocturnas/sol.jpg",     "lugar": "Sol, 19:40" }
]
```

El **orden de la lista** es el orden en que aparecen las categorías y sus
fotos en la galería: la primera vez que aparece una categoría nueva marca
dónde empieza ese grupo. Cuidado con las comas: cada objeto va separado por
coma, excepto el último.

## El separador entre categorías

Los haikus y conceptos japoneses ya están escritos en `index.html` (busca
`MIS_TEXTOS`). Se van asignando en ese mismo orden a cada cambio de
categoría — la primera categoría no lleva separador delante, solo se
inserta uno ENTRE una categoría y la siguiente. Si quieres cambiar el texto
de un separador concreto, edita ese array directamente.

## Previsualizar en local

El sitio carga `manifest.json` con `fetch()`, y los navegadores bloquean esa
petición si abres `index.html` con doble clic (protocolo `file://`). Para
verlo en tu ordenador antes de subirlo, usa un servidor local sencillo, por
ejemplo la extensión "Live Server" de VS Code, o:

```
npx serve .
```

En GitHub Pages funciona sin nada especial, porque se sirve por `https://`.

## Carpeta `_sin-clasificar/`

Ahí están las fotos que aún no se han organizado ni añadido al manifiesto.
No aparecen en la web hasta que las muevas a su carpeta de categoría y las
incluyas en `manifest.json`. Esta carpeta no se sube a GitHub (está en
`.gitignore`).
