# EduDev Comments

Fase 1: generar un comentario profesional para una publicación de LinkedIn con **Ollama** y **qwen3:1.7b**, en local.

La extensión sigue el mismo esquema que EduDevTranslate: el content script lee la publicación, el service worker llama a un servidor en `127.0.0.1` y ese servidor es quien habla con Ollama. Usa el puerto **8788** para poder convivir con el traductor, que escucha en el 8787.

## Arrancar

Con Ollama abierto y el modelo instalado (`ollama pull qwen3:1.7b`). Si el puerto 8788 ya está ocupado, detén ese proceso antes de arrancar:

```bash
python3 -m uvicorn server:app --host 127.0.0.1 --port 8788
```

Comprobar:

```bash
curl http://127.0.0.1:8788/health
```

## Extensión

```bash
cd extension
npm install
npm run build
```

En `chrome://extensions`, activa el modo de desarrollador, elige **Cargar descomprimida** y selecciona `extension/dist`.

La extensión queda fijada al origen `chrome-extension://jlinanjklmiikeepamkodmhmhnnngnlh`. Si ese origen no coincide, define `EXTENSION_ORIGIN` antes de arrancar el servidor.

En el feed o en el detalle de una publicación aparece **Generar comentario**. El resultado se puede copiar o regenerar. No se publica nada en LinkedIn.

El servidor no guarda el texto de la publicación. Cada regeneración vuelve a consultar el modelo.
