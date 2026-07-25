# Cómo añadir fotos

No hace falta tocar el HTML ni saber programar. Solo dos pasos:

## 1. Coloca el archivo en la carpeta correcta

```
fotos/<ciudad>/<formato>/<color>/archivo.jpg
```

- `ciudad`: el nombre que quieras (madrid, lisboa, tanger, roma...). Si es una
  ciudad nueva que no está en `NOMBRES_CIUDAD` dentro de `index.html`, se
  mostrará igual en el filtro, con la primera letra en mayúscula.
- `formato`: `digital` o `analogico`
- `color`: `bn` (blanco y negro) o `color`

Ejemplo:

```
fotos/madrid/analogico/bn/lavapies.jpg
fotos/lisboa/digital/color/alfama.jpg
```

## 2. Añade una línea en `manifest.json`

Cada foto es un objeto con la ruta (sin el "fotos/" delante) y el texto que
quieres que aparezca sobre la imagen:

```json
[
  { "ruta": "madrid/analogico/bn/lavapies.jpg", "lugar": "Lavapiés" },
  { "ruta": "lisboa/digital/color/alfama.jpg",  "lugar": "Alfama" }
]
```

El orden de la lista es el orden en que aparecen en la galería. Cuidado con
las comas: cada objeto va separado por coma, excepto el último.

## Ciudad, formato y tratamiento se deducen solos

El filtro "Ciudad" de la barra lateral, y los contadores de cada opción, se
generan automáticamente a partir de las fotos que haya en el manifiesto — no
hay que editar el HTML para añadir una ciudad nueva.

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
No aparecen en la web hasta que las muevas a su carpeta de ciudad/formato/
color y las incluyas en `manifest.json`.
