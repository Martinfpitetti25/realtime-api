# 🚀 Inicio Rápido

## Paso 1: Configura tu API Key

1. Abre el archivo `.env` en un editor de texto
2. Agrega tu API key de OpenAI:
   ```
   OPENAI_API_KEY=sk-tu-api-key-aqui
   ```
3. Guarda el archivo

## Paso 2: Prueba la conexión

Ejecuta el script de prueba:
```bash
python 00_test_connection.py
```

Si ves "✅ ¡CONEXIÓN EXITOSA!" entonces todo funciona.

## Paso 3: Prueba el chat de texto

```bash
python 02_text_chat.py
```

Escribe tus mensajes y el asistente te responderá.

## Paso 4: (Opcional) Prueba el chat de voz

```bash
python 03_audio_chat.py
```

Presiona ENTER, habla, y presiona ENTER de nuevo.

---

## ⚠️ Problemas comunes

### "No module named 'websocket'"
```bash
pip install websocket-client
```

### "No module named 'pyaudio'"
En Windows, puede ser complicado. Si falla:
```bash
pip install pipwin
pipwin install pyaudio
```

### Error de API Key
- Verifica que copiaste la key completa
- Asegúrate de que tu cuenta tiene acceso a la API Realtime
- Revisa tu saldo en https://platform.openai.com/usage

### Audio no funciona en Raspberry Pi
```bash
# Instala las dependencias del sistema
sudo apt-get update
sudo apt-get install portaudio19-dev python3-pyaudio

# Verifica el micrófono
arecord -l

# Verifica los altavoces
speaker-test -t wav -c 2
```

---

## 📊 Costos

**gpt-realtime-mini** (por millón de tokens):
- Entrada: $0.60
- Salida: $2.40

Para referencia:
- 1 minuto de audio ≈ 3,000-6,000 tokens
- Una conversación corta (2-3 min) ≈ $0.05-$0.15

---

## 🔗 Recursos útiles

- [Documentación Realtime API](https://platform.openai.com/docs/guides/realtime)
- [Modelos disponibles](https://platform.openai.com/docs/models)
- [Playground](https://platform.openai.com/playground)
- [Panel de uso](https://platform.openai.com/usage)
