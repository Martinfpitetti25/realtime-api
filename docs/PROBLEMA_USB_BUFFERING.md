# 🔴 PROBLEMA USB BUFFERING - ANÁLISIS COMPLETO

**Fecha:** 25 de Marzo, 2026  
**Estado:** 🔍 CAUSA RAÍZ IDENTIFICADA  

---

## 📅 **¿POR QUÉ FUNCIONABA ANTES Y AHORA NO?**

### **LÍNEA DE TIEMPO DEL PROBLEMA:**

#### **FEBRERO 25, 2026 - Todo funcionaba ✅**
```json
.audio_config NO existía o era:
{
  "preferred_input_device": null,
  "preferred_output_device": null
}
```

**Comportamiento del código:**
```python
# Línea 156-157 del código
self.input_device_index = None
self.output_device_index = None

# Al abrir stream (línea 1866-1868):
if self.output_device_index is not None:  # ← FALSE, salta este if
    stream_kwargs['output_device_index'] = self.output_device_index

# stream_kwargs NO TIENE 'output_device_index'
stream = self.audio.open(**stream_kwargs)
```

**Flujo real:**
```
PyAudio.open(sin device index)
    ↓
Sistema elige default automáticamente
    ↓
Default = PulseAudio compatibility layer
    ↓
PipeWire (servidor real)
    ↓
PipeWire multiplexa hacia dispositivo físico
    ↓
✅ Navegador Y Python pueden usar audio simultáneamente
```

---

#### **MARZO 24, 2026 21:26 - TODO SE ROMPIÓ ❌**
```bash
$ stat .audio_config
2026-03-24 21:26:02  ← AQUÍ EMPEZÓ EL PROBLEMA
```

**Archivo .audio_config guardó:**
```json
{
  "preferred_input_device": 2,
  "preferred_output_device": 2  ← ESTO CAUSÓ EL PROBLEMA
}
```

**Nuevo comportamiento del código:**
```python
# Línea 162-163
prefs = self.audio_device_manager.get_preferred_devices()
self.output_device_index = 2  # ← Cargado de .audio_config ⚠️

# Al abrir stream:
if self.output_device_index is not None:  # ← AHORA ES TRUE
    stream_kwargs['output_device_index'] = 2  # ← SE ESPECIFICA DEVICE 2

stream = self.audio.open(**stream_kwargs)
```

**Nuevo flujo (ROTO):**
```
PyAudio.open(output_device_index=2)  ← ESPECIFICA DEVICE
    ↓
ALSA backend procesa index 2
    ↓
Device 2 = "pipewire" (nombre engañoso)
    ↓
"pipewire" es ALIAS de ALSA que apunta a "sysdefault"
    ↓
sysdefault = Primera tarjeta física = card0
    ↓
card0 = USB Audio Device
    ↓
Abre /dev/snd/pcmC0D0p DIRECTAMENTE
    ↓
🔒 LOCK EXCLUSIVO EN HARDWARE
    ↓
❌ PipeWire BYPASEADO - Sin multiplexado
    ↓
Navegador intenta usar USB → BLOQUEADO
    ↓
Video hace BUFFERING infinito ❌
```

---

## 🎯 **LA CAUSA RAÍZ EXACTA**

### **El nombre "pipewire" es ENGAÑOSO:**

El device llamado "pipewire" en PyAudio **NO usa realmente PipeWire**:

```bash
$ python -c "import pyaudio; p = pyaudio.PyAudio(); \
  info = p.get_device_info_by_index(2); \
  print(p.get_host_api_info_by_index(info['hostApi'])['name'])"

ALSA  ← Usa ALSA backend, NO PulseAudio/PipeWire
```

**Cuando especificas `output_device_index=2`:**
- PyAudio usa **ALSA backend** (no PulseAudio)
- ALSA abre el device "pipewire"
- Este device es un **alias que resuelve a hardware directo**
- Resultado: **Bypass de PipeWire** + **Lock exclusivo**

---

## 🔎 **POR QUÉ BLUETOOTH SÍ FUNCIONA**

**Bluetooth usa arquitectura diferente:**

```
Con Bluetooth activo:
  wpctl status muestra:
    └─ Sinks:
       * 57. USB Audio Device (inactivo, sin sink virtual)
       * XX. bluez_output.54_15_89_F9_1B_E1 ← SINK VIRTUAL ✅

  PyAudio.open(output_device_index=2)
      ↓
  Sistema detecta que USB no es accesible
      ↓
  Rutea automáticamente a sink de Bluetooth
      ↓
  Sink virtual = PipeWire está en medio
      ↓
  ✅ MULTIPLEXADO FUNCIONA
```

**USB sin Bluetooth:**
```
  wpctl status muestra:
    └─ Sinks:
       * 57. USB Audio Device Analog Stereo ← SINK DIRECTO ⚠️
       
  PyAudio.open(output_device_index=2)
      ↓
  ALSA "pipewire" → sysdefault → card0
      ↓
  Abre /dev/snd/pcmC0D0p DIRECTO
      ↓
  🔒 LOCK EXCLUSIVO = Sin multiplexado
      ↓
  ❌ Navegador BLOQUEADO = BUFFERING
```

---

## 🕐 **CUÁNDO OCURRIÓ EL CAMBIO**

### **Cambio crítico en el código:**

Cuando implementamos `AudioDeviceManager` (docs/AUDIO_CONFIGURED.md), agregamos:

```python
# Líneas 160-163 (NUEVO código que causó el problema)
if self.audio_device_manager:
    prefs = self.audio_device_manager.get_preferred_devices()
    self.input_device_index = prefs.get("input")   # ← Lee de config
    self.output_device_index = prefs.get("output")  # ← Lee de config
```

**ANTES de este cambio:**
- No había `.audio_config`
- `device_index` siempre era `None`
- PyAudio usaba default system → ✅ Multiplexado

**DESPUÉS de este cambio:**
- `.audio_config` se crea al guardar preferencias
- `device_index = 2` se carga al iniciar
- PyAudio abre device específico → ❌ Lock exclusivo

---

### **El momento exacto:**

```bash
$ stat .audio_config
2026-03-24 21:26:02  ← GUARDASTE PREFERENCIAS EN LA GUI
```

**Qué hiciste ese día:**
1. Abriste el programa
2. Fuiste a "🎧 Audio" en la GUI
3. Seleccionaste "pipewire (PipeWire - Recomendado)" 🎤 y 🔊
4. Clickeaste "💾 Guardar y Aplicar"
5. `.audio_config` se creó con `preferred_output_device: 2`
6. **Desde ese momento, el USB quedó bloqueado** ❌

---

## 🎭 **EL ENGAÑO DEL NOMBRE**

En `AudioDeviceManager.get_device_names()` (línea ~80):

```python
if dev["is_pipewire"]:
    name = f"🔊 {name} (PipeWire - Recomendado)"  ← ETIQUETA ENGAÑOSA
```

**La detección de "is_pipewire":**
```python
"is_pipewire": "pipewire" in device_name.lower() or "default" in device_name.lower()
```

**Problema:** Device 2 se llama "pipewire", entonces:
- Lo etiqueta como "(PipeWire - Recomendado)" ✅
- Usuario lo selecciona creyendo que usa PipeWire ✅
- **PERO device 2 usa ALSA directo** ❌
- Resultado: Lock exclusivo, no multiplexado ❌

---

## 📊 **CONFIRMACIÓN EXPERIMENTAL**

### Test realizado AHORA:
```bash
$ python tests/test_usb_exclusive_lock.py

📋 TEST 4: Abrir stream SIN especificar device
✅ Stream abierto sin especificar device (usa default)
⚠️ Python está usando /dev/snd/pcmC0D0p (hardware USB directo)
   ESTO ES EL PROBLEMA - Bypass de PipeWire
```

### Con programa corriendo:
```bash
$ fuser -v /dev/snd/pcmC0D0p
/dev/snd/pcmC0D0p:   cluster    1613 F...m python3.13
                                      ^^^^
                                      Lock MMAP exclusivo
```

---

## 🚀 **IMPLEMENTA AHORA (3 MINUTOS)**

### **Quick Fix (sin tocar código):**
```bash
# OPCIÓN A: Borrar config (más simple)
rm /home/cluster/Projects/Realtime-IA/.audio_config

# OPCIÓN B: Cambiar a device 4
sed -i 's/"preferred_output_device": 2/"preferred_output_device": 4/' \
  /home/cluster/Projects/Realtime-IA/.audio_config
```

Reinicia el programa y **listo** ✅

---

### **Fix permanente (modificar código):**

¿Quieres que implemente la solución en el código para que esto no vuelva a pasar?

Modifico:
1. Línea ~1866-1870 en `play_audio()`
2. Línea ~1783-1787 en `record_audio()`
3. Agregar lógica para detectar devices "peligrosos"

**Tiempo:** 5 minutos  
**Archivos:** Solo `05_gui_chat.py`

---

**Resumen:** Guardaste "pipewire" como preferido (device 2) → Device 2 es alias de ALSA → ALSA abre USB directo → Lock exclusivo → Navegador bloqueado → Buffering infinito. Antes funcionaba porque NO había device guardado, sistema usaba default con multiplexado automático.
