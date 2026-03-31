# Uso de Docker para realtime-api

## 1. Variables de entorno
Copia `.env.example` a `.env` y coloca tu API key de OpenAI:

```
cp .env.example .env
# Edita .env y pon tu clave
```

## 2. Construir la imagen

```
docker-compose build
```

## 3. Ejecutar el contenedor

```
docker-compose up
```

- En PC: la GUI se abrirá si tienes entorno gráfico (X11).
- En Raspberry Pi: puedes usar scripts de texto/audio o acceder por VNC/SSH/X11 forwarding para GUI.

## 4. Notas para Raspberry Pi
- Usa una imagen base ARM64 si tu Pi es 64 bits: cambia `FROM python:3.11-slim` por `FROM python:3.11-slim-bullseye` o similar.
- Asegúrate de tener los dispositivos `/dev/snd` (audio) y `/dev/video0` (cámara) disponibles.
- Si usas modelos grandes (.pt), móntalos en `/app/models`.

## 5. Personalización
- Cambia el comando en el Dockerfile para otro script si no quieres la GUI por defecto.
- Puedes exponer otros puertos en `docker-compose.yml` si usas interfaces web.

---

¿Dudas? ¡Pregunta!