# 🎧 Sistema de Auto-Detección de Dispositivos de Audio

## 📋 Cambios Implementados

### 1. **AudioDeviceManager Mejorado**

#### Nuevas Funcionalidades:
- **Clasificación inteligente de dispositivos** (`_classify_device_type`)
  - USB → Prioridad 1 (dispositivos físicos por cable/auxiliar)
  - Bluetooth → Prioridad 2 (dispositivos inalámbricos)
  - Internal → Prioridad 3 (micrófono/altavoz integrado)
  - Unknown → Prioridad 4
  - HDMI → Prioridad 5 (baja para conversación)
  - Virtual → Prioridad 6 (default, pipewire, pulse)

- **Auto-detección automática** (`auto_detect_best_devices`)
  - Busca automáticamente el mejor micrófono y altavoz disponible
  - Prioriza dispositivos físicos (USB/Bluetooth) sobre virtuales
  - Evita HDMI salvo que no haya alternativa
  - Imprime en consola qué dispositivos detectó

- **Ordenamiento de dispositivos**
  - Los dispositivos se muestran ordenados por prioridad
  - Los dispositivos físicos (USB/Bluetooth) aparecen primero

#### Mejoras en get_device_names():
- **Emojis descriptivos:**
  - 🔌 = USB
  - 📶 = Bluetooth
  - 🎙️ = Interno
  - 📺 = HDMI
  - ⚙️ = Virtual (default, pipewire)
  - ❓ = Desconocido

- **Etiquetas claras:**
  - Dispositivos físicos (USB/Bluetooth) marcados con ⭐ [USB] o [BLUETOOTH]
  - Dispositivos sistema marcados con (Sistema)
  - Trunca nombres largos (>40 chars) para mejor lectura

### 2. **GUI Mejorado (05_gui_chat.py)**

#### Auto-detección al Iniciar:
```python
# Si no hay preferencias guardadas:
1. Ejecuta auto_detect_best_devices()
2. Configura automáticamente micrófono y altavoz
3. Guarda la configuración en .audio_config
4. Muestra en consola qué dispositivos detectó
```

#### Ventana de Configuración Mejorada:
- **Panel de Estado Actual (verde)**
  - Muestra dispositivos actualmente en uso con tipo
  - Ejemplo: "MS210x [USB]", "USB Audio Device [USB]"

- **Listas desplegables mejoradas**
  - Dispositivos ordenados por prioridad
  - ⭐ destacan dispositivos físicos recomendados
  - Emojis indican tipo de dispositivo
  - Width aumentado (55 chars) para nombres completos

- **Botón Auto-Detectar (amarillo)**
  - Ejecuta detección manual en tiempo real
  - Actualiza los dropdowns automáticamente
  - Útil si conectas/desconectas dispositivos mientras la app está abierta

- **Leyenda clara**
  - Explica emojis y etiquetas
  - Indica que ⭐ son recomendados

---

## 🔧 Funcionamiento

### Primera Ejecución (sin .audio_config):
1. Inicia la app
2. Auto-detecta dispositivos físicos
3. Selecciona:
   - Micrófono: MS210x USB (card 0)
   - Altavoz: USB Audio Device (card 3)
4. Guarda en `.audio_config`
5. Muestra en consola los dispositivos seleccionados

### Ejecuciones Posteriores:
1. Carga configuración desde `.audio_config`
2. Usa los dispositivos guardados
3. Muestra en consola qué está usando

### Cambiar Dispositivos Manualmente:
1. Click en botón "🎧 Audio"
2. Ver estado actual (panel verde)
3. Opción A: Click "🤖 Auto-Detectar" → Busca automáticamente
4. Opción B: Seleccionar manualmente desde dropdown
5. Click "🎤 Probar" para verificar que funciona
6. Click "💾 Guardar y Aplicar"
7. Si está grabando, detener y reiniciar para aplicar cambios

---

## 🎯 Ejemplo de Detección en tu Caso

**Dispositivos Detectados:**
```
INPUT:
[0] MS210x: USB Audio (hw:0,0) → USB ⭐
[2] USB Audio Device: - (hw:3,0) → USB ⭐
[6] default → Virtual

OUTPUT:
[2] USB Audio Device: - (hw:3,0) → USB ⭐
[1] vc4-hdmi-1: MAI PCM (hw:2,0) → HDMI
[6] default → Virtual
```

**Auto-Detección Selecciona:**
- ✅ Input: `[0] MS210x` (primer USB encontrado)
- ✅ Output: `[2] USB Audio Device` (primer USB no-HDMI encontrado)

**Razón:** USB tiene prioridad sobre virtual y HDMI. Los dispositivos auxiliares conectados por USB se detectan automáticamente.

---

## 📱 Interfaz Mejorada

### Panel de Estado (Verde):
```
🟢 Estado Actual
🎤 Micrófono: MS210x: USB Audio (hw:0,0) [USB]
🔊 Altavoz: USB Audio Device: - (hw:3,0) [USB]
```

### Dropdown de Entrada:
```
🔌 MS210x: USB Audio (hw:0,0) [USB] ⭐
🔌 USB Audio Device: - (hw:3,0) [USB] ⭐
⚙️ pipewire (Sistema)
⚙️ default (Sistema)
❓ spdif
```

### Dropdown de Salida:
```
🔌 USB Audio Device: - (hw:3,0) [USB] ⭐
⚙️ pipewire (Sistema)
⚙️ default (Sistema)
📺 vc4-hdmi-1: MAI PCM (hw:2,0)
```

---

## 🚀 Ventajas del Nuevo Sistema

1. **No más "default" genérico** - Sabes exactamente qué dispositivo estás usando
2. **Auto-detección inteligente** - Prioriza USB/Auxiliar sobre virtuales
3. **Identificación clara** - Emojis y etiquetas muestran tipo de dispositivo
4. **Botón de auto-detección manual** - Si conectas/desconectas algo durante el uso
5. **Estado visible** - Siempre ves qué dispositivos están activos
6. **Priorización correcta** - USB > Bluetooth > Interno > HDMI > Virtual

---

## 🔍 Testing

Para probar que funciona correctamente:

```bash
# 1. Eliminar config anterior (forzar auto-detección)
rm -f .audio_config

# 2. Iniciar aplicación
python3 05_gui_chat.py

# 3. Verificar en consola que muestra:
#    "🔍 Auto-detectando dispositivos físicos..."
#    "✅ Micrófono auto-detectado y guardado"
#    "✅ Altavoz auto-detectado y guardado"
#    "🎧 Dispositivos de audio configurados:"
#    "  🎤 Input: MS210x... [USB]"
#    "  🔊 Output: USB Audio Device... [USB]"

# 4. Abrir ventana de configuración (botón "🎧 Audio")
#    - Ver estado actual en panel verde
#    - Ver ⭐ junto a dispositivos USB
#    - Probar botón "🤖 Auto-Detectar"

# 5. Probar dispositivos con botones "🎤 Probar" y "🔊 Probar"
```

---

## 📝 Notas Técnicas

### Priorización de Dispositivos:
- **USB/Auxiliar:** Máxima prioridad - son dispositivos físicos confiables
- **Bluetooth:** Alta prioridad - dispositivos inalámbricos de calidad
- **Internal:** Media prioridad - micrófono/altavoz integrado (laptop)
- **HDMI:** Baja prioridad - típicamente solo para video, no óptimo para conversación
- **Virtual (default/pipewire):** Mínima prioridad - abstracciones del sistema

### Clasificación:
El sistema detecta tipo de dispositivo buscando keywords en el nombre:
- `usb` en nombre → USB
- `bluetooth`, `bluez`, `bt` → Bluetooth
- `hdmi` → HDMI
- `default`, `pipewire`, `pulse` → Virtual

### Guardado:
El archivo `.audio_config` guarda:
```json
{
  "preferred_input_device": 0,
  "preferred_output_device": 2,
  "last_used": "2026-03-26T..."
}
```

---

## ✅ Problema Resuelto

**Antes:**
- No quedaba claro qué dispositivo estaba usando
- Seleccionaba "default" genérico sin especificar hardware
- Difícil saber si era USB, Bluetooth o HDMI

**Ahora:**
- Detecta automáticamente dispositivos físicos (USB/Auxiliar)
- Muestra tipo de dispositivo con emoji y etiqueta
- Prioriza hardware real sobre abstracciones
- Panel de estado muestra exactamente qué está usando
- Botón de auto-detección para reconectar dispositivos
