# 🤖 Sistema Híbrido Inteligente GPT-4V

## Descripción

Sistema de visión dual que combina **YOLO (gratuito)** para detección continua y **GPT-4 Vision API (preciso)** para análisis detallado automático.

## ✨ Características

### 1. Detección de Cambios Inteligente
- **Tracking de objetos**: Compara objetos detectados entre frames
- **Umbral configurable**: Define qué porcentaje de cambio activa GPT-4V
- **Posicionamiento**: Identifica objetos nuevos o que desaparecen

### 2. Refresh Periódico Opcional
- **Intervalo configurable**: 0-180 segundos (0 = desactivado)
- **Balance costo/precisión**: Refresh cada 60s recomendado
- **Estimación de costos**: Muestra costo por hora en configuración

### 3. Triple Activación GPT-4V
1. **Automático por cambios**: Cuando la escena cambia significativamente
2. **Automático periódico**: Cada X segundos (opcional)
3. **Manual**: Botón o keywords en el chat

## 🎮 Controles en la Ventana de Cámara

```
┌─────────────────────────────────┐
│  📹 Webcam Feed                 │
├─────────────────────────────────┤
│                                 │
│      [Video en vivo]            │
│                                 │
├─────────────────────────────────┤
│ 👁️ Detecciones YOLO            │
├─────────────────────────────────┤
│ [🔍 Manual] [🤖 Auto: ON] [⚙️] │
└─────────────────────────────────┘
```

### Botones
- **🔍 Análisis Manual**: Activa GPT-4V inmediatamente
- **🤖 Auto: ON/OFF**: Toggle del sistema automático
- **⚙️**: Configuración avanzada

## ⚙️ Configuración Avanzada

### Umbral de Cambio (Change Threshold)
- **Rango**: 0.1 - 1.0 (10% - 100%)
- **Recomendado**: 0.3 (30%)
- **Sensible**: 0.2 - 0.3 (detecta cambios pequeños)
- **Conservador**: 0.5 - 0.8 (solo cambios grandes)

### Refresh Automático
- **Rango**: 0 - 180 segundos
- **0**: Desactivado (solo por cambios + keywords)
- **30s**: Muy activo ($1.20/hora)
- **60s**: Balanceado ($0.60/hora) ⭐ Recomendado
- **120s**: Económico ($0.30/hora)

### Keywords que Activan GPT-4V
Estas palabras en el chat activan GPT-4V automáticamente:
- `detalle` / `describe`
- `texto` / `lee`
- `color` / `colores`
- `exactamente` / `preciso`

## 💰 Costos

### YOLO (Siempre Activo)
- **Costo**: $0.00 (gratis)
- **Frecuencia**: Cada 2 segundos
- **Uso**: Detección básica continua

### GPT-4V (Bajo Demanda)
- **Costo por análisis**: ~$0.01 USD
- **Solo se activa cuando**:
  1. Cambio significativo detectado
  2. Refresh periódico (si habilitado)
  3. Keyword en mensaje
  4. Botón manual

### Ejemplo de Costo Real
**Configuración recomendada** (Umbral=30%, Refresh=60s):
- Escena estática: ~$0.60/hora (solo refresh)
- Escena dinámica: ~$1-2/hora (cambios + refresh)
- Sin refresh: Variable según actividad

## 🔧 Uso

### 1. Iniciar Cámara
```bash
python 05_gui_chat.py
```
1. Click en **📹 Cámara**
2. Se abre ventana de video

### 2. Activar Visión YOLO
1. Click en **👁️ Visión** en el GUI principal
2. Detecciones continuas cada 2s

### 3. Configurar Sistema Híbrido
1. Click en **⚙️** en ventana de cámara
2. Ajustar:
   - Umbral de cambio: 30% (sensible)
   - Refresh: 60s (balanceado)
3. Click **💾 Guardar**

### 4. Toggle Automático
- Click en **🤖 Auto: ON** para activar/desactivar
- Verde = activo, Gris = desactivado

## 📊 Logs de Depuración

El sistema imprime información útil en la consola:

```
🔄 Cambio significativo: 45.0% (umbral: 30%)
🤖 [AUTO] Cambio detectado, activando GPT-4V...
✅ GPT-4V automático completado ($0.0105)

⏰ Refresh automático (60s transcurridos)
🤖 [AUTO] Cambio detectado, activando GPT-4V...
✅ GPT-4V automático completado ($0.0098)
```

## 🎯 Escenarios de Uso

### 1. Vigilancia de Espacio
**Config**: Umbral=40%, Refresh=120s
- Detecta cuando alguien entra/sale
- Bajo costo (~$0.30/hora)

### 2. Asistente Interactivo
**Config**: Umbral=30%, Refresh=60s
- Responde rápido a cambios
- Balance costo/precisión (~$0.60/hora)

### 3. Análisis Detallado
**Config**: Umbral=20%, Refresh=30s
- Máxima precisión
- Mayor costo (~$1.20/hora)

### 4. Solo Preguntas
**Config**: Umbral=30%, Refresh=0
- GPT-4V solo con keywords o manual
- Costo mínimo (variable)

## 🚀 Ventajas del Sistema Híbrido

✅ **Económico**: YOLO gratis + GPT-4V solo cuando necesario
✅ **Inteligente**: Detecta cambios automáticamente
✅ **Flexible**: 3 formas de activación (auto/periódico/manual)
✅ **Configurable**: Ajusta según tus necesidades
✅ **Transparente**: Muestra costos en tiempo real

## 📝 Notas Técnicas

### Detección de Cambios
```python
# Cada objeto se identifica por: clase + zona espacial
obj_id = f"{clase}_{x//100}_{y//100}"

# Se compara set actual vs anterior
cambios = (nuevos + eliminados) / max(actual, anterior)

# Si cambios >= umbral → Activa GPT-4V
```

### Threading
- YOLO: Thread separado cada 2s
- GPT-4V: Thread bajo demanda
- Flag `gpt4v_analyzing` previene análisis simultáneos

### Contexto Visual
```python
{
    'vision_summary': 'Detecciones YOLO básicas',
    'raw_detections': [...],
    'gpt4v_description': 'Análisis detallado GPT-4V',  # Solo si se activó
    'gpt4v_cost': 0.0105
}
```

## 🐛 Troubleshooting

### GPT-4V no se activa automáticamente
1. Verificar `🤖 Auto: ON` (verde)
2. Revisar umbral (30% recomendado)
3. Verificar que la escena cambie significativamente

### Demasiados análisis GPT-4V
1. Aumentar umbral a 50-80%
2. Desactivar refresh (0s)
3. Desactivar auto temporalmente

### Costo muy alto
1. Desactivar refresh periódico
2. Aumentar umbral a 60%+
3. Usar solo keywords/manual

## 📚 Referencias

- **YOLO**: hardware/camera_service.py
- **GPT-4V**: hardware/gpt4_vision_service.py
- **Sistema Híbrido**: 05_gui_chat.py (líneas 82-91, 1048-1144)
- **Keywords**: `['detalle', 'describe', 'texto', 'lee', 'color', 'exactamente', 'preciso']`

---

**Versión**: 1.0
**Fecha**: 2026-02-10
**Estado**: ✅ Implementado y funcional
