# 🎙️ Wake Word Detection - Guía de Configuración

## ¿Qué es Wake Word?

Wake Word permite activar el asistente por voz diciendo una palabra clave como "Jarvis", "Computer" o "Alexa", similar a cómo funciona Alexa, Siri o Google Assistant.

## 🎯 Funcionamiento

1. **Activas Modo Voz** → El sistema espera escuchar la wake word en silencio
2. **Dices "Jarvis"** (u otra wake word) → Sistema detecta la palabra
3. **Asistente responde: "Estoy aquí"** → Confirmación de que te escuchó
4. **Hablas tu pregunta** → El asistente te escucha y responde
5. **Termina de responder** → Vuelve a esperar la wake word

**🔑 Diferencia clave:** En modo texto, el wake word NO se activa. Solo funciona en **Modo Voz**.

## 📦 Instalación

### 1. Instalar Porcupine

Ya está instalado con:
```bash
pip install pvporcupine
```

### 2. Obtener Access Key GRATIS

1. Ve a: https://console.picovoice.ai/
2. Crea una cuenta gratuita
3. Ve a "Access Keys" en el menú
4. Copia tu Access Key

**Plan Gratuito incluye:**
- ✅ 3 wake words simultáneas
- ✅ 3,000 detecciones/mes (suficiente para uso personal)
- ✅ Uso ilimitado en desarrollo

### 3. Configurar .env

Edita tu archivo `.env` y agrega:

```env
OPENAI_API_KEY=tu_api_key_de_openai
PORCUPINE_ACCESS_KEY=tu_access_key_de_porcupine
```

## 🎤 Wake Words Disponibles (Gratis)

Puedes cambiar la wake word en el código (`05_gui_chat.py`):

```python
DEFAULT_WAKE_WORD = 'jarvis'  # Cambiar a la que prefieras
```

**Wake words disponibles:**
- `jarvis` - ⭐ Recomendado, estilo Iron Man
- `alexa` - Como Amazon Alexa
- `computer` - Estilo Star Trek
- `hey google` - Similar a Google Assistant
- `hey siri` - Estilo Apple
- `ok google` - Variante de Google
- `picovoice` - Marca de Porcupine
- `porcupine` - Nombre del producto
- `bumblebee` - Transformers
- `terminator` - Terminator

## ⚙️ Personalizar Frase de Confirmación

Por defecto el asistente responde **"Estoy aquí"** cuando detecta la wake word.

Puedes cambiarla en el código:

```python
WAKE_WORD_CONFIRMATION = "Estoy aquí"  # Cambiar a lo que prefieras
```

**Ejemplos:**
- "Sí, dime"
- "Te escucho"
- "A la orden"
- "¿Qué necesitas?"
- "Presente"

## 🚀 Uso

1. **Inicia la aplicación:**
   ```bash
   python 05_gui_chat.py
   ```

2. **Activa Modo Voz** (botón "🎤 Modo Voz")

3. **Espera el mensaje:** "👂 Esperando wake word: 'jarvis'"

4. **Di la wake word:** "Jarvis"

5. **Escucha la confirmación:** "Estoy aquí"

6. **Habla tu pregunta:** "¿Qué hora es?"

7. **El asistente responde** y vuelve a esperar la wake word

## ❓ Solución de Problemas

### "Wake word requiere PORCUPINE_ACCESS_KEY en .env"

**Solución:** Configura tu Access Key en el archivo `.env`

### "Porcupine no disponible - wake word desactivado"

**Solución:** Instala pvporcupine:
```bash
pip install pvporcupine
```

### Wake word no se detecta

**Problema:** Baja sensibilidad del micrófono o ruido ambiente

**Soluciones:**
1. Habla más cerca del micrófono
2. Di la wake word más claro y despacio
3. Reduce el ruido ambiente
4. Prueba con otra wake word más corta como "alexa"

### Sin wake word (modo normal)

Si **NO** configuras `PORCUPINE_ACCESS_KEY`, el sistema funciona normalmente:
- Modo Voz inicia grabación inmediatamente (sin wake word)
- Modo Texto funciona igual

## 🎛️ Configuración Avanzada

### Cambiar Wake Word en Runtime (Futuro)

Actualmente la wake word está hardcodeada. Se puede agregar un selector en la GUI.

### Múltiples Wake Words

Puedes usar hasta 3 wake words simultáneas (plan gratuito):

```python
self.porcupine = pvporcupine.create(
    access_key=PORCUPINE_ACCESS_KEY,
    keywords=['jarvis', 'alexa', 'computer']  # Hasta 3
)
```

### Sensibilidad

Ajustar sensibilidad de detección:

```python
self.porcupine = pvporcupine.create(
    access_key=PORCUPINE_ACCESS_KEY,
    keywords=['jarvis'],
    sensitivities=[0.5]  # 0.0 (menos sensible) a 1.0 (más sensible)
)
```

## 📊 Rendimiento

- **Latencia detección:** ~50-80ms (imperceptible)
- **Uso de CPU:** ~2-5% en idle
- **Memoria:** ~5 MB
- **Precisión:** 98-99%
- **Funciona Offline:** ✅ Sí

## 🔗 Recursos

- **Documentación Porcupine:** https://picovoice.ai/docs/porcupine/
- **Console (Access Keys):** https://console.picovoice.ai/
- **Wake Words Personalizadas:** https://picovoice.ai/platform/porcupine/

## 🆘 Soporte

Si tienes problemas, revisa:
1. Archivo `.env` configurado correctamente
2. Access Key válida y no expirada
3. Micrófono funcionando correctamente
4. PyAudio instalado y funcionando

---

**¡Disfruta tu asistente con wake word detection! 🎙️✨**
