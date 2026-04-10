"""
Function Tools - Herramientas invocables por la IA en tiempo real
=================================================================
Este módulo contiene las funciones que FRANK puede ejecutar cuando
necesita información del mundo real (hora, ubicación, cálculos, etc.)

Uso con OpenAI Realtime API:
1. Las tools se definen en session.update
2. Cuando la API necesita datos, envía function_call_arguments.done
3. execute_tool() ejecuta la función correspondiente
4. El resultado se envía de vuelta a la API
"""

import json
import os
import subprocess
import math
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from pathlib import Path

# Logger del proyecto
try:
    from utils.logger import get_logger
    log = get_logger('tools')
except ImportError:
    import logging
    log = logging.getLogger('tools')
    log.setLevel(logging.INFO)
    if not log.handlers:
        log.addHandler(logging.StreamHandler())


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

# Directorio para archivos de datos (notas, etc.)
DATA_DIR = Path(__file__).parent.parent / "data"
NOTES_FILE = DATA_DIR / "notes.json"


# ══════════════════════════════════════════════════════════════════════════════
# DEFINICIONES DE TOOLS PARA LA API
# ══════════════════════════════════════════════════════════════════════════════

TOOLS_DEFINITIONS = [
    {
        "type": "function",
        "name": "get_current_datetime",
        "description": "Obtiene la fecha y hora actual del sistema. Usar cuando el usuario pregunte qué hora es, qué día es, qué fecha es, o cualquier información temporal.",
        "parameters": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["full", "time_only", "date_only", "day_of_week"],
                    "description": "Formato de respuesta: 'full' para fecha y hora completa, 'time_only' solo hora, 'date_only' solo fecha, 'day_of_week' para el día de la semana"
                },
                "include_seconds": {
                    "type": "boolean",
                    "description": "Si incluir segundos en la hora (default: false)"
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "calculate",
        "description": "Realiza cálculos matemáticos. Usar para operaciones aritméticas, porcentajes, raíces, potencias, trigonometría, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Expresión matemática a evaluar. Ejemplos: '15 * 340 / 100' para porcentajes, 'sqrt(144)', '2**10', 'sin(45)'"
                },
                "precision": {
                    "type": "integer",
                    "description": "Número de decimales en el resultado (default: 2)"
                }
            },
            "required": ["expression"]
        }
    },
    {
        "type": "function",
        "name": "get_location_info",
        "description": "Obtiene información de ubicación aproximada basada en la IP pública. Incluye ciudad, país, zona horaria y coordenadas aproximadas.",
        "parameters": {
            "type": "object",
            "properties": {
                "include_coordinates": {
                    "type": "boolean",
                    "description": "Si incluir coordenadas geográficas (default: false)"
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "control_volume",
        "description": "Controla el volumen del sistema (subir, bajar, silenciar, establecer nivel específico). Usar cuando el usuario pida cambiar el volumen.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "up", "down", "mute", "unmute", "toggle_mute"],
                    "description": "Acción a realizar: 'get' obtener nivel actual, 'set' establecer nivel, 'up'/'down' subir/bajar, 'mute'/'unmute' silenciar"
                },
                "level": {
                    "type": "integer",
                    "description": "Nivel de volumen (0-100). Solo requerido para action='set'"
                },
                "step": {
                    "type": "integer",
                    "description": "Cantidad a subir/bajar (default: 10). Solo para action='up' o 'down'"
                }
            },
            "required": ["action"]
        }
    },
    {
        "type": "function",
        "name": "manage_notes",
        "description": "Gestiona notas y recordatorios. Permite crear, listar, buscar y eliminar notas. Usar cuando el usuario quiera anotar algo, ver sus notas o borrar una nota.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "search", "delete", "clear"],
                    "description": "Acción: 'add' crear nota, 'list' ver todas, 'search' buscar, 'delete' eliminar por ID, 'clear' borrar todas"
                },
                "content": {
                    "type": "string",
                    "description": "Contenido de la nota (para 'add') o término de búsqueda (para 'search')"
                },
                "note_id": {
                    "type": "integer",
                    "description": "ID de la nota a eliminar (para 'delete')"
                }
            },
            "required": ["action"]
        }
    },
    {
        "type": "function",
        "name": "get_weather",
        "description": "Obtiene el clima actual y pronóstico. Usar cuando el usuario pregunte por temperatura, clima, si va a llover, humedad, viento, etc. Por defecto usa la ubicación detectada por IP.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "Ciudad para consultar el clima. Si no se especifica, usa la ubicación actual detectada por IP."
                },
                "units": {
                    "type": "string",
                    "enum": ["metric", "imperial"],
                    "description": "Unidades: 'metric' para Celsius (default), 'imperial' para Fahrenheit"
                },
                "include_forecast": {
                    "type": "boolean",
                    "description": "Si incluir pronóstico de las próximas horas (default: false)"
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "web_search",
        "description": "Busca información en internet usando DuckDuckGo. Usar cuando el usuario pregunte por información actual, noticias, datos que no conoces, o cualquier cosa que requiera búsqueda web. Ejemplos: '¿Qué pasó hoy en las noticias?', '¿Cuál es el precio del dólar?', 'Buscá info sobre X'.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Término de búsqueda. Sé específico para mejores resultados."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo de resultados a devolver (default: 5, max: 10)"
                }
            },
            "required": ["query"]
        }
    }
]


# ══════════════════════════════════════════════════════════════════════════════
# IMPLEMENTACIÓN DE TOOLS
# ══════════════════════════════════════════════════════════════════════════════

def get_current_datetime(
    format: str = "full",
    include_seconds: bool = False
) -> Dict[str, Any]:
    """
    Obtiene la fecha y hora actual del sistema.
    
    Args:
        format: Formato de respuesta ('full', 'time_only', 'date_only', 'day_of_week')
        include_seconds: Si incluir segundos en la hora
        
    Returns:
        Dict con la información temporal solicitada
    """
    now = datetime.now()
    
    # Nombres en español
    days_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    months_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    
    day_name = days_es[now.weekday()]
    month_name = months_es[now.month - 1]
    
    # Formato de hora
    if include_seconds:
        time_str = now.strftime("%H:%M:%S")
        time_12h = now.strftime("%I:%M:%S %p").lower().replace("am", "a.m.").replace("pm", "p.m.")
    else:
        time_str = now.strftime("%H:%M")
        time_12h = now.strftime("%I:%M %p").lower().replace("am", "a.m.").replace("pm", "p.m.")
    
    # Formato de fecha
    date_str = f"{now.day} de {month_name} de {now.year}"
    
    result = {
        "success": True,
        "timestamp": now.isoformat(),
        "timezone": "America/Argentina/Buenos_Aires",  # Ajustar según ubicación
    }
    
    if format == "time_only":
        result["time_24h"] = time_str
        result["time_12h"] = time_12h
        result["message"] = f"Son las {time_str} ({time_12h})"
    elif format == "date_only":
        result["date"] = date_str
        result["day"] = now.day
        result["month"] = month_name
        result["year"] = now.year
        result["message"] = f"Hoy es {date_str}"
    elif format == "day_of_week":
        result["day_of_week"] = day_name
        result["date"] = date_str
        result["message"] = f"Hoy es {day_name}, {date_str}"
    else:  # full
        result["time_24h"] = time_str
        result["time_12h"] = time_12h
        result["date"] = date_str
        result["day_of_week"] = day_name
        result["message"] = f"Son las {time_str} del {day_name} {date_str}"
    
    log.info(f"🕐 get_current_datetime({format}): {result['message']}")
    return result


def calculate(
    expression: str,
    precision: int = 2
) -> Dict[str, Any]:
    """
    Evalúa una expresión matemática de forma segura.
    
    Args:
        expression: Expresión matemática a evaluar
        precision: Decimales en el resultado
        
    Returns:
        Dict con el resultado del cálculo
    """
    # Funciones matemáticas permitidas
    safe_functions = {
        'abs': abs,
        'round': round,
        'min': min,
        'max': max,
        'sum': sum,
        'pow': pow,
        # Funciones de math
        'sqrt': math.sqrt,
        'sin': lambda x: math.sin(math.radians(x)),  # Grados a radianes
        'cos': lambda x: math.cos(math.radians(x)),
        'tan': lambda x: math.tan(math.radians(x)),
        'asin': lambda x: math.degrees(math.asin(x)),
        'acos': lambda x: math.degrees(math.acos(x)),
        'atan': lambda x: math.degrees(math.atan(x)),
        'log': math.log,
        'log10': math.log10,
        'log2': math.log2,
        'exp': math.exp,
        'floor': math.floor,
        'ceil': math.ceil,
        'pi': math.pi,
        'e': math.e,
    }
    
    try:
        # Limpiar expresión
        expr_clean = expression.strip()
        
        # Reemplazar símbolos comunes
        expr_clean = expr_clean.replace('^', '**')  # Potencia
        expr_clean = expr_clean.replace('×', '*')   # Multiplicación
        expr_clean = expr_clean.replace('÷', '/')   # División
        expr_clean = expr_clean.replace(',', '.')   # Decimales
        
        # Evaluar de forma segura
        result = eval(expr_clean, {"__builtins__": {}}, safe_functions)
        
        # Formatear resultado
        if isinstance(result, float):
            if result == int(result):
                result_formatted = str(int(result))
            else:
                result_formatted = f"{result:.{precision}f}"
        else:
            result_formatted = str(result)
        
        log.info(f"🔢 calculate({expression}): {result_formatted}")
        
        return {
            "success": True,
            "expression": expression,
            "result": result,
            "result_formatted": result_formatted,
            "message": f"El resultado de {expression} es {result_formatted}"
        }
        
    except ZeroDivisionError:
        log.warning(f"🔢 calculate({expression}): División por cero")
        return {
            "success": False,
            "error": "division_by_zero",
            "message": "No se puede dividir por cero"
        }
    except Exception as e:
        log.error(f"🔢 calculate({expression}): Error - {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"No pude calcular eso: {str(e)}"
        }


def get_location_info(
    include_coordinates: bool = False
) -> Dict[str, Any]:
    """
    Obtiene información de ubicación basada en IP pública.
    Usa el servicio gratuito ip-api.com (no requiere API key).
    
    Args:
        include_coordinates: Si incluir lat/lon
        
    Returns:
        Dict con información de ubicación
    """
    try:
        import urllib.request
        import json as json_module
        
        # Consultar API gratuita
        url = "http://ip-api.com/json/?lang=es&fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,query"
        
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json_module.loads(response.read().decode())
        
        if data.get("status") != "success":
            raise Exception(data.get("message", "Error desconocido"))
        
        result = {
            "success": True,
            "city": data.get("city", "Desconocida"),
            "region": data.get("regionName", ""),
            "country": data.get("country", "Desconocido"),
            "timezone": data.get("timezone", ""),
            "ip": data.get("query", ""),
            "isp": data.get("isp", ""),
        }
        
        if include_coordinates:
            result["latitude"] = data.get("lat")
            result["longitude"] = data.get("lon")
        
        location_str = f"{result['city']}, {result['region']}, {result['country']}"
        result["message"] = f"Tu ubicación aproximada es {location_str} (zona horaria: {result['timezone']})"
        
        log.info(f"📍 get_location_info(): {location_str}")
        return result
        
    except Exception as e:
        log.error(f"📍 get_location_info(): Error - {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"No pude obtener la ubicación: {str(e)}"
        }


def control_volume(
    action: str,
    level: Optional[int] = None,
    step: int = 10
) -> Dict[str, Any]:
    """
    Controla el volumen del sistema usando PipeWire/PulseAudio.
    
    Args:
        action: 'get', 'set', 'up', 'down', 'mute', 'unmute', 'toggle_mute'
        level: Nivel de volumen (0-100) para action='set'
        step: Cantidad a subir/bajar para 'up'/'down'
        
    Returns:
        Dict con el resultado de la operación
    """
    try:
        # Detectar qué comando usar (wpctl para PipeWire, pactl para PulseAudio)
        use_wpctl = True
        try:
            subprocess.run(['wpctl', '--version'], capture_output=True, timeout=2)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            use_wpctl = False
        
        if action == "get":
            # Obtener volumen actual
            if use_wpctl:
                result = subprocess.run(
                    ['wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@'],
                    capture_output=True, text=True, timeout=5
                )
                # Formato: "Volume: 0.75" o "Volume: 0.75 [MUTED]"
                output = result.stdout.strip()
                is_muted = "[MUTED]" in output
                vol_str = output.replace("Volume:", "").replace("[MUTED]", "").strip()
                current_vol = int(float(vol_str) * 100)
            else:
                result = subprocess.run(
                    ['pactl', 'get-sink-volume', '@DEFAULT_SINK@'],
                    capture_output=True, text=True, timeout=5
                )
                # Extraer porcentaje
                import re
                match = re.search(r'(\d+)%', result.stdout)
                current_vol = int(match.group(1)) if match else 0
                
                mute_result = subprocess.run(
                    ['pactl', 'get-sink-mute', '@DEFAULT_SINK@'],
                    capture_output=True, text=True, timeout=5
                )
                is_muted = "yes" in mute_result.stdout.lower()
            
            return {
                "success": True,
                "volume": current_vol,
                "muted": is_muted,
                "message": f"El volumen está al {current_vol}%" + (" (silenciado)" if is_muted else "")
            }
        
        elif action == "set":
            if level is None:
                return {"success": False, "error": "Se requiere nivel para 'set'", "message": "No especificaste el nivel de volumen"}
            
            level = max(0, min(100, level))  # Limitar 0-100
            
            if use_wpctl:
                subprocess.run(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', f'{level}%'], timeout=5)
            else:
                subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{level}%'], timeout=5)
            
            log.info(f"🔊 control_volume(set): {level}%")
            return {
                "success": True,
                "volume": level,
                "message": f"Volumen establecido al {level}%"
            }
        
        elif action in ["up", "down"]:
            sign = "+" if action == "up" else "-"
            
            if use_wpctl:
                subprocess.run(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', f'{step}%{sign}'], timeout=5)
            else:
                subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{sign}{step}%'], timeout=5)
            
            # Obtener nuevo nivel
            new_status = control_volume("get")
            new_vol = new_status.get("volume", "?")
            
            action_text = "subido" if action == "up" else "bajado"
            log.info(f"🔊 control_volume({action}): {new_vol}%")
            return {
                "success": True,
                "volume": new_vol,
                "message": f"Volumen {action_text} al {new_vol}%"
            }
        
        elif action in ["mute", "unmute", "toggle_mute"]:
            if action == "toggle_mute":
                mute_arg = "toggle"
            else:
                mute_arg = "1" if action == "mute" else "0"
            
            if use_wpctl:
                subprocess.run(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', mute_arg], timeout=5)
            else:
                subprocess.run(['pactl', 'set-sink-mute', '@DEFAULT_SINK@', mute_arg], timeout=5)
            
            if action == "mute":
                msg = "Volumen silenciado"
            elif action == "unmute":
                msg = "Volumen restaurado"
            else:
                # Obtener estado actual
                status = control_volume("get")
                msg = "Volumen silenciado" if status.get("muted") else "Volumen restaurado"
            
            log.info(f"🔊 control_volume({action})")
            return {
                "success": True,
                "message": msg
            }
        
        else:
            return {
                "success": False,
                "error": f"Acción desconocida: {action}",
                "message": f"No entiendo la acción '{action}'"
            }
            
    except Exception as e:
        log.error(f"🔊 control_volume({action}): Error - {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Error controlando volumen: {str(e)}"
        }


def manage_notes(
    action: str,
    content: Optional[str] = None,
    note_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Gestiona notas persistentes en un archivo JSON.
    
    Args:
        action: 'add', 'list', 'search', 'delete', 'clear'
        content: Contenido de la nota o término de búsqueda
        note_id: ID de la nota a eliminar
        
    Returns:
        Dict con el resultado de la operación
    """
    # Asegurar que existe el directorio de datos
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    def load_notes() -> list:
        if NOTES_FILE.exists():
            try:
                with open(NOTES_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def save_notes(notes: list) -> None:
        with open(NOTES_FILE, 'w', encoding='utf-8') as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
    
    try:
        notes = load_notes()
        
        if action == "add":
            if not content:
                return {"success": False, "error": "Sin contenido", "message": "¿Qué querés que anote?"}
            
            # Generar nuevo ID
            new_id = max([n.get("id", 0) for n in notes], default=0) + 1
            
            new_note = {
                "id": new_id,
                "content": content,
                "created_at": datetime.now().isoformat(),
            }
            notes.append(new_note)
            save_notes(notes)
            
            log.info(f"📝 manage_notes(add): #{new_id} - {content[:50]}...")
            return {
                "success": True,
                "note_id": new_id,
                "message": f"Anotado: '{content}' (nota #{new_id})"
            }
        
        elif action == "list":
            if not notes:
                return {
                    "success": True,
                    "notes": [],
                    "count": 0,
                    "message": "No tenés notas guardadas"
                }
            
            notes_summary = []
            for n in notes[-10:]:  # Últimas 10
                preview = n["content"][:50] + "..." if len(n["content"]) > 50 else n["content"]
                notes_summary.append(f"#{n['id']}: {preview}")
            
            log.info(f"📝 manage_notes(list): {len(notes)} notas")
            return {
                "success": True,
                "notes": notes,
                "count": len(notes),
                "message": f"Tenés {len(notes)} notas:\n" + "\n".join(notes_summary)
            }
        
        elif action == "search":
            if not content:
                return {"success": False, "error": "Sin término", "message": "¿Qué querés buscar?"}
            
            matches = [n for n in notes if content.lower() in n["content"].lower()]
            
            if not matches:
                return {
                    "success": True,
                    "matches": [],
                    "count": 0,
                    "message": f"No encontré notas con '{content}'"
                }
            
            matches_summary = []
            for n in matches:
                preview = n["content"][:50] + "..." if len(n["content"]) > 50 else n["content"]
                matches_summary.append(f"#{n['id']}: {preview}")
            
            log.info(f"📝 manage_notes(search): {len(matches)} coincidencias para '{content}'")
            return {
                "success": True,
                "matches": matches,
                "count": len(matches),
                "message": f"Encontré {len(matches)} notas con '{content}':\n" + "\n".join(matches_summary)
            }
        
        elif action == "delete":
            if note_id is None:
                return {"success": False, "error": "Sin ID", "message": "¿Qué nota querés borrar? Dame el número"}
            
            original_len = len(notes)
            notes = [n for n in notes if n.get("id") != note_id]
            
            if len(notes) == original_len:
                return {
                    "success": False,
                    "error": "not_found",
                    "message": f"No encontré la nota #{note_id}"
                }
            
            save_notes(notes)
            log.info(f"📝 manage_notes(delete): #{note_id}")
            return {
                "success": True,
                "message": f"Nota #{note_id} eliminada"
            }
        
        elif action == "clear":
            count = len(notes)
            save_notes([])
            log.info(f"📝 manage_notes(clear): {count} notas eliminadas")
            return {
                "success": True,
                "deleted_count": count,
                "message": f"Eliminé todas las notas ({count} en total)"
            }
        
        else:
            return {
                "success": False,
                "error": f"Acción desconocida: {action}",
                "message": f"No entiendo la acción '{action}'"
            }
            
    except Exception as e:
        log.error(f"📝 manage_notes({action}): Error - {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Error con las notas: {str(e)}"
        }


def _get_weather_wttr(city: str, units: str = "metric", include_forecast: bool = False) -> Dict[str, Any]:
    """
    Obtiene el clima usando wttr.in (fallback gratuito sin API key).
    
    Args:
        city: Ciudad para consultar
        units: 'metric' (Celsius) o 'imperial' (Fahrenheit)
        include_forecast: Si incluir pronóstico
        
    Returns:
        Dict con información del clima
    """
    import urllib.request
    import json as json_module
    
    try:
        # wttr.in usa 'm' para métrico y 'u' para imperial
        unit_param = "m" if units == "metric" else "u"
        city_encoded = urllib.parse.quote(city)
        
        # Formato JSON de wttr.in
        url = f"https://wttr.in/{city_encoded}?format=j1&lang=es"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json_module.loads(response.read().decode())
        
        # Extraer datos del clima actual
        current = data["current_condition"][0]
        location = data["nearest_area"][0]
        
        # Temperatura según unidades
        if units == "metric":
            temp = float(current["temp_C"])
            feels_like = float(current["FeelsLikeC"])
            wind_speed = float(current["windspeedKmph"]) / 3.6  # Convertir a m/s
            temp_unit = "°C"
            wind_unit = "m/s"
        else:
            temp = float(current["temp_F"])
            feels_like = float(current["FeelsLikeF"])
            wind_speed = float(current["windspeedMiles"])
            temp_unit = "°F"
            wind_unit = "mph"
        
        humidity = int(current["humidity"])
        
        # Descripción en español (wttr.in lo soporta)
        description = current.get("lang_es", [{}])
        if description and len(description) > 0:
            description = description[0].get("value", current["weatherDesc"][0]["value"])
        else:
            description = current["weatherDesc"][0]["value"]
        
        city_name = location["areaName"][0]["value"]
        country = location["country"][0]["value"]
        
        result = {
            "success": True,
            "city": city_name,
            "country": country,
            "temperature": round(temp, 1),
            "feels_like": round(feels_like, 1),
            "humidity": humidity,
            "description": description.lower(),
            "wind_speed": round(wind_speed, 1),
            "units": units,
            "source": "wttr.in"
        }
        
        # Mensaje natural
        message_parts = [
            f"En {city_name} ({country}) hay {round(temp)}{temp_unit}",
            f"con {description.lower()}."
        ]
        
        if abs(temp - feels_like) > 2:
            message_parts.append(f"La sensación térmica es de {round(feels_like)}{temp_unit}.")
        
        message_parts.append(f"Humedad: {humidity}%. Viento: {round(wind_speed)} {wind_unit}.")
        
        result["message"] = " ".join(message_parts)
        
        # Agregar pronóstico si se solicita
        if include_forecast and "weather" in data:
            forecast_list = []
            # wttr.in da pronóstico por día con horarios
            for day in data["weather"][:2]:  # Hoy y mañana
                for hour in day.get("hourly", [])[:4]:
                    hour_time = hour.get("time", "0").zfill(4)
                    hour_formatted = f"{hour_time[:2]}:{hour_time[2:]}"
                    
                    if units == "metric":
                        hour_temp = int(hour.get("tempC", 0))
                    else:
                        hour_temp = int(hour.get("tempF", 0))
                    
                    hour_desc = hour.get("lang_es", [{}])
                    if hour_desc and len(hour_desc) > 0:
                        hour_desc = hour_desc[0].get("value", hour["weatherDesc"][0]["value"])
                    else:
                        hour_desc = hour["weatherDesc"][0]["value"]
                    
                    forecast_list.append({
                        "time": hour_formatted,
                        "temp": hour_temp,
                        "description": hour_desc.lower()
                    })
                    
                    if len(forecast_list) >= 4:
                        break
                if len(forecast_list) >= 4:
                    break
            
            if forecast_list:
                result["forecast"] = forecast_list
                forecast_msg = " Pronóstico: "
                for f in forecast_list:
                    forecast_msg += f"{f['time']}→{f['temp']}{temp_unit} ({f['description']}), "
                result["message"] += forecast_msg.rstrip(", ") + "."
        
        log.info(f"🌡️ get_weather[wttr.in]({city}): {round(temp)}{temp_unit}, {description}")
        return result
        
    except Exception as e:
        log.error(f"🌡️ get_weather[wttr.in]({city}): Error - {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"No pude obtener el clima: {str(e)}"
        }


def get_weather(
    city: Optional[str] = None,
    units: str = "metric",
    include_forecast: bool = False
) -> Dict[str, Any]:
    """
    Obtiene el clima actual usando OpenWeatherMap API con fallback a wttr.in.
    
    Args:
        city: Ciudad para consultar (si no se especifica, usa ubicación por IP)
        units: 'metric' (Celsius) o 'imperial' (Fahrenheit)
        include_forecast: Si incluir pronóstico de las próximas horas
        
    Returns:
        Dict con información del clima
    """
    import urllib.request
    import json as json_module
    
    # Si no se especifica ciudad, obtener ubicación por IP
    original_city = city
    if not city:
        location = get_location_info(include_coordinates=True)
        if location.get("success"):
            city = location.get("city", "La Rioja")
            log.debug(f"Usando ubicación detectada: {city}")
        else:
            city = "La Rioja, AR"  # Default fallback
    
    # Intentar primero con OpenWeatherMap
    api_key = os.getenv('OPENWEATHERMAP_API_KEY')
    
    if api_key:
        try:
            # Construir URL para clima actual
            base_url = "https://api.openweathermap.org/data/2.5/weather"
            city_encoded = urllib.parse.quote(city)
            params = f"q={city_encoded}&appid={api_key}&units={units}&lang=es"
            url = f"{base_url}?{params}"
            
            log.debug(f"Consultando OpenWeatherMap: {url.replace(api_key, '***')}")
            
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json_module.loads(response.read().decode())
            
            # Extraer datos relevantes
            temp = data["main"]["temp"]
            feels_like = data["main"]["feels_like"]
            humidity = data["main"]["humidity"]
            description = data["weather"][0]["description"]
            wind_speed = data["wind"]["speed"]
            city_name = data["name"]
            country = data["sys"]["country"]
            
            # Unidad de temperatura
            temp_unit = "°C" if units == "metric" else "°F"
            wind_unit = "m/s" if units == "metric" else "mph"
            
            result = {
                "success": True,
                "city": city_name,
                "country": country,
                "temperature": round(temp, 1),
                "feels_like": round(feels_like, 1),
                "humidity": humidity,
                "description": description,
                "wind_speed": round(wind_speed, 1),
                "units": units,
                "source": "openweathermap"
            }
            
            # Mensaje natural
            message_parts = [
                f"En {city_name} ({country}) hay {round(temp)}{temp_unit}",
                f"con {description}."
            ]
            
            if abs(temp - feels_like) > 2:
                message_parts.append(f"La sensación térmica es de {round(feels_like)}{temp_unit}.")
            
            message_parts.append(f"Humedad: {humidity}%. Viento: {round(wind_speed)} {wind_unit}.")
            
            result["message"] = " ".join(message_parts)
            
            # Agregar pronóstico si se solicita
            if include_forecast:
                forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?q={city_encoded}&appid={api_key}&units={units}&lang=es&cnt=8"
                
                try:
                    with urllib.request.urlopen(forecast_url, timeout=10) as response:
                        forecast_data = json_module.loads(response.read().decode())
                    
                    forecast_list = []
                    for item in forecast_data["list"][:4]:
                        dt = datetime.fromtimestamp(item["dt"])
                        forecast_list.append({
                            "time": dt.strftime("%H:%M"),
                            "temp": round(item["main"]["temp"]),
                            "description": item["weather"][0]["description"]
                        })
                    
                    result["forecast"] = forecast_list
                    
                    forecast_msg = " Pronóstico: "
                    for f in forecast_list:
                        forecast_msg += f"{f['time']}→{f['temp']}{temp_unit} ({f['description']}), "
                    result["message"] += forecast_msg.rstrip(", ") + "."
                    
                except Exception as e:
                    log.warning(f"Error obteniendo pronóstico: {e}")
            
            log.info(f"🌡️ get_weather[OWM]({city}): {round(temp)}{temp_unit}, {description}")
            return result
            
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning(f"🌡️ get_weather[OWM]({city}): Ciudad no encontrada, probando wttr.in")
            else:
                log.warning(f"🌡️ get_weather[OWM]({city}): HTTP {e.code}, usando fallback wttr.in")
            # Continuar al fallback
            
        except Exception as e:
            log.warning(f"🌡️ get_weather[OWM]({city}): Error ({e}), usando fallback wttr.in")
            # Continuar al fallback
    else:
        log.debug("OpenWeatherMap API key no configurada, usando wttr.in")
    
    # Fallback a wttr.in
    return _get_weather_wttr(city, units, include_forecast)


def web_search(
    query: str,
    max_results: int = 5
) -> Dict[str, Any]:
    """
    Busca información en internet usando DuckDuckGo.
    No requiere API key.
    
    Args:
        query: Término de búsqueda
        max_results: Número máximo de resultados (1-10)
        
    Returns:
        Dict con resultados de búsqueda
    """
    import urllib.request
    import urllib.parse
    import json as json_module
    import re
    
    try:
        # Limitar resultados
        max_results = min(max(1, max_results), 10)
        
        # Usar DuckDuckGo HTML lite (más confiable que la API)
        query_encoded = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={query_encoded}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es-AR,es;q=0.9,en;q=0.8',
        }
        
        req = urllib.request.Request(url, headers=headers)
        
        log.debug(f"🔍 web_search: Buscando '{query}'...")
        
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8', errors='ignore')
        
        # Parsear resultados del HTML
        results = []
        
        # Buscar bloques de resultados
        # DuckDuckGo HTML tiene estructura: <a class="result__a" href="...">título</a>
        # y <a class="result__snippet">descripción</a>
        
        # Patrón para extraer resultados
        result_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>([^<]*)</a>',
            re.DOTALL | re.IGNORECASE
        )
        
        # También intentar patrón alternativo
        alt_pattern = re.compile(
            r'<a[^>]*rel="nofollow"[^>]*class="result__url"[^>]*href="([^"]*)"[^>]*>.*?</a>.*?'
            r'<a[^>]*class="result__a"[^>]*>([^<]*)</a>.*?'
            r'class="result__snippet"[^>]*>([^<]*)<',
            re.DOTALL | re.IGNORECASE
        )
        
        # Patrón más simple y robusto
        simple_pattern = re.compile(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]+)</a>',
            re.IGNORECASE
        )
        snippet_pattern = re.compile(
            r'class="result__snippet"[^>]*>([^<]+)',
            re.IGNORECASE
        )
        
        # Extraer URLs y títulos
        matches = simple_pattern.findall(html)
        snippets = snippet_pattern.findall(html)
        
        for i, (url_match, title) in enumerate(matches[:max_results]):
            # Limpiar URL (DuckDuckGo usa redirects)
            if 'uddg=' in url_match:
                # Extraer URL real del parámetro uddg
                try:
                    real_url = urllib.parse.unquote(url_match.split('uddg=')[1].split('&')[0])
                except:
                    real_url = url_match
            else:
                real_url = url_match
            
            # Limpiar título
            title = title.strip()
            title = re.sub(r'\s+', ' ', title)
            
            # Obtener snippet si existe
            snippet = ""
            if i < len(snippets):
                snippet = snippets[i].strip()
                snippet = re.sub(r'\s+', ' ', snippet)
                # Decodificar entidades HTML básicas
                snippet = snippet.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
            
            if title and real_url and not real_url.startswith('//duckduckgo'):
                results.append({
                    "title": title[:200],  # Limitar longitud
                    "url": real_url,
                    "snippet": snippet[:300] if snippet else ""
                })
        
        if not results:
            # Intentar con DuckDuckGo Instant Answer API como fallback
            api_url = f"https://api.duckduckgo.com/?q={query_encoded}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(api_url, headers={'User-Agent': 'FRANK/1.0'})
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json_module.loads(response.read().decode())
            
            # Respuesta instantánea
            if data.get('AbstractText'):
                results.append({
                    "title": data.get('Heading', query),
                    "url": data.get('AbstractURL', ''),
                    "snippet": data.get('AbstractText', '')[:300]
                })
            
            # Resultados relacionados
            for topic in data.get('RelatedTopics', [])[:max_results-len(results)]:
                if isinstance(topic, dict) and topic.get('Text'):
                    results.append({
                        "title": topic.get('Text', '')[:100].split(' - ')[0],
                        "url": topic.get('FirstURL', ''),
                        "snippet": topic.get('Text', '')[:300]
                    })
        
        if not results:
            log.warning(f"🔍 web_search({query}): Sin resultados")
            return {
                "success": False,
                "error": "no_results",
                "message": f"No encontré resultados para '{query}'. Intentá con otros términos."
            }
        
        # Construir mensaje natural
        message_parts = [f"Encontré {len(results)} resultados para '{query}':\n"]
        for i, r in enumerate(results, 1):
            message_parts.append(f"{i}. **{r['title']}**")
            if r['snippet']:
                message_parts.append(f"   {r['snippet']}")
        
        log.info(f"🔍 web_search({query}): {len(results)} resultados")
        
        return {
            "success": True,
            "query": query,
            "results": results,
            "count": len(results),
            "message": "\n".join(message_parts)
        }
        
    except urllib.error.URLError as e:
        log.error(f"🔍 web_search({query}): Error de red - {e}")
        return {
            "success": False,
            "error": "network_error",
            "message": f"No pude conectarme a internet para buscar: {str(e)}"
        }
    except Exception as e:
        log.error(f"🔍 web_search({query}): Error - {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Error buscando información: {str(e)}"
        }


# ══════════════════════════════════════════════════════════════════════════════
# EJECUTOR DE TOOLS
# ══════════════════════════════════════════════════════════════════════════════

# Mapeo de nombres de funciones a implementaciones
TOOLS_MAP = {
    "get_current_datetime": get_current_datetime,
    "calculate": calculate,
    "get_location_info": get_location_info,
    "control_volume": control_volume,
    "manage_notes": manage_notes,
    "get_weather": get_weather,
    "web_search": web_search,
}


def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """
    Ejecuta una tool por nombre con los argumentos dados.
    
    Args:
        name: Nombre de la función a ejecutar
        arguments: Diccionario con los argumentos
        
    Returns:
        String JSON con el resultado (para enviar a la API)
    """
    if name not in TOOLS_MAP:
        log.error(f"❌ Tool desconocida: {name}")
        return json.dumps({
            "success": False,
            "error": f"Tool '{name}' no existe",
            "message": f"No conozco esa función"
        })
    
    try:
        log.info(f"🔧 Ejecutando tool: {name}({arguments})")
        func = TOOLS_MAP[name]
        result = func(**arguments)
        return json.dumps(result, ensure_ascii=False)
        
    except TypeError as e:
        log.error(f"❌ Error de argumentos en {name}: {e}")
        return json.dumps({
            "success": False,
            "error": f"Argumentos inválidos: {str(e)}",
            "message": "Hubo un problema con los parámetros"
        })
    except Exception as e:
        log.error(f"❌ Error ejecutando {name}: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": f"Error ejecutando la función: {str(e)}"
        })


def get_tools_definitions() -> list:
    """
    Retorna las definiciones de tools para enviar a la API.
    """
    return TOOLS_DEFINITIONS
