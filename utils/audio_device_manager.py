"""
Gestor de Dispositivos de Audio
Maneja detección, selección y guardado de preferencias de dispositivos de audio
"""
import json
import os
import re
import subprocess
from typing import Optional, Dict, List, Tuple

try:
    import pyaudio
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False


class AudioDeviceManager:
    """Gestiona dispositivos de audio y preferencias"""
    
    CONFIG_FILE = ".audio_config"
    
    def __init__(self):
        self.audio = pyaudio.PyAudio() if AUDIO_AVAILABLE else None
        self.config = self.load_config()
        
    def _classify_device_type(self, device_name: str) -> str:
        """Clasifica el tipo de dispositivo basado en su nombre"""
        name_lower = device_name.lower()
        
        # Dispositivos virtuales/sistema (baja prioridad)
        if any(x in name_lower for x in ['default', 'pipewire', 'pulse', 'sysdefault', 'dmix', 'null']):
            return 'virtual'
        
        # Dispositivos USB físicos (ALTA PRIORIDAD)
        if 'usb' in name_lower:
            return 'usb'
        
        # Dispositivos Bluetooth (ALTA PRIORIDAD)
        if any(x in name_lower for x in ['bluetooth', 'bluez', 'bt']):
            return 'bluetooth'
        
        # Dispositivos HDMI (baja prioridad para audio conversacional)
        if 'hdmi' in name_lower:
            return 'hdmi'
        
        # Dispositivos internos (media prioridad)
        if any(x in name_lower for x in ['built-in', 'internal', 'analog']):
            return 'internal'
        
        return 'unknown'
    
    def get_devices(self) -> Dict[str, List[Dict]]:
        """Obtiene lista de todos los dispositivos de entrada y salida con clasificación"""
        if not self.audio:
            return {"input": [], "output": []}
        
        devices = {"input": [], "output": []}
        
        try:
            device_count = self.audio.get_device_count()
            
            for i in range(device_count):
                try:
                    info = self.audio.get_device_info_by_index(i)
                    device_name = info.get("name", f"Device {i}")
                    
                    device_info = {
                        "index": i,
                        "name": device_name,
                        "max_input_channels": info.get("maxInputChannels", 0),
                        "max_output_channels": info.get("maxOutputChannels", 0),
                        "default_sample_rate": info.get("defaultSampleRate", 0),
                        "is_default_input": i == self.audio.get_default_input_device_info()["index"],
                        "is_default_output": i == self.audio.get_default_output_device_info()["index"],
                        "is_pipewire": "pipewire" in device_name.lower() or "default" in device_name.lower(),
                        "device_type": self._classify_device_type(device_name)  # Nuevo campo
                    }
                    
                    # Agregar a la lista correspondiente
                    if device_info["max_input_channels"] > 0:
                        devices["input"].append(device_info)
                    
                    if device_info["max_output_channels"] > 0:
                        devices["output"].append(device_info)
                        
                except Exception as e:
                    print(f"[WARNING] Error obteniendo info del dispositivo {i}: {e}")
                    continue
                    
        except Exception as e:
            print(f"[ERROR] Error obteniendo dispositivos: {e}")
        
        # Inyectar dispositivos PipeWire (Bluetooth, etc.) no visibles via ALSA puro
        self._inject_pipewire_devices(devices)

        # PRIORIZAR dispositivos físicos (USB, Bluetooth) sobre virtuales
        priority_order = {'usb': 1, 'bluetooth': 2, 'internal': 3, 'unknown': 4, 'hdmi': 5, 'virtual': 6}
        devices["input"].sort(key=lambda d: (priority_order.get(d['device_type'], 999), d['index']))
        devices["output"].sort(key=lambda d: (priority_order.get(d['device_type'], 999), d['index']))

        return devices

    def get_pipewire_sinks_sources(self) -> Dict[str, List[Dict]]:
        """Consulta wpctl para obtener todos los sinks y sources de PipeWire (incluyendo Bluetooth)"""
        result: Dict[str, List[Dict]] = {"sinks": [], "sources": [], "bt_device_names": set()}

        try:
            out = subprocess.check_output(
                ['wpctl', 'status'], text=True, timeout=3, stderr=subprocess.DEVNULL
            )
        except Exception:
            return result

        # Primera pasada: encontrar nombres de dispositivos Bluetooth en la sección Devices
        in_audio = False
        in_devices = False
        for line in out.splitlines():
            stripped = line.strip()
            if stripped == 'Audio':
                in_audio = True
                in_devices = False
            elif stripped == 'Video':
                in_audio = False
            elif in_audio and '─ Devices:' in stripped:
                in_devices = True
            elif in_devices and '─ ' in stripped and 'Devices:' not in stripped:
                in_devices = False
            elif in_devices and '[bluez5]' in stripped:
                m = re.search(r'\d+\.\s+(.+?)\s+\[bluez5\]', stripped)
                if m:
                    result["bt_device_names"].add(m.group(1).strip())

        # Segunda pasada: parsear Sinks y Sources
        current_section = None
        in_audio = False
        for line in out.splitlines():
            stripped = line.strip()
            if stripped == 'Audio':
                in_audio = True
            elif stripped == 'Video':
                in_audio = False
            if not in_audio:
                continue
            if '─ Sinks:' in stripped:
                current_section = 'sinks'
            elif '─ Sources:' in stripped:
                current_section = 'sources'
            elif any(x in stripped for x in ['─ Filters:', '─ Streams:', '─ Devices:']):
                current_section = None
            elif current_section:
                m = re.match(r'[│\s]*([\*\s])\s*(\d+)\.\s+(.+?)(?:\s+\[vol.*)?$', line)
                if m and m.group(3).strip():
                    name = m.group(3).strip()
                    result[current_section].append({
                        "id": int(m.group(2)),
                        "name": name,
                        "is_default": m.group(1).strip() == '*',
                        "is_bluetooth": name in result["bt_device_names"]
                    })

        return result

    def _inject_pipewire_devices(self, devices: Dict[str, List[Dict]]):
        """Inyecta dispositivos Bluetooth de PipeWire que no son visibles via ALSA directamente"""
        # Encontrar el índice ALSA del bridge 'pipewire' o 'default' para usarlo como túnel
        pipewire_out_index = None
        pipewire_in_index = None

        for dev in devices["output"]:
            name_l = dev['name'].lower()
            if 'pipewire' in name_l and pipewire_out_index is None:
                pipewire_out_index = dev['index']
            elif 'default' in name_l and pipewire_out_index is None:
                pipewire_out_index = dev['index']

        for dev in devices["input"]:
            name_l = dev['name'].lower()
            if 'pipewire' in name_l and pipewire_in_index is None:
                pipewire_in_index = dev['index']
            elif 'default' in name_l and pipewire_in_index is None:
                pipewire_in_index = dev['index']

        pw = self.get_pipewire_sinks_sources()

        # Inyectar sinks Bluetooth (outputs)
        for sink in pw.get("sinks", []):
            if not sink.get("is_bluetooth"):
                continue  # Solo BT — USB/HDMI ya están en ALSA
            name = sink["name"]
            already = any(
                d["name"] == name
                for d in devices["output"]
                if not d.get("via_pipewire")
            )
            if not already and pipewire_out_index is not None:
                devices["output"].append({
                    "index": pipewire_out_index,
                    "name": name,
                    "max_input_channels": 0,
                    "max_output_channels": 2,
                    "default_sample_rate": 48000.0,
                    "is_default_input": False,
                    "is_default_output": sink.get("is_default", False),
                    "is_pipewire": True,
                    "device_type": "bluetooth",
                    "pipewire_id": sink["id"],
                    "via_pipewire": True
                })

        # Inyectar sources Bluetooth (inputs) — útil para mics BT
        for source in pw.get("sources", []):
            if not source.get("is_bluetooth"):
                continue
            name = source["name"]
            already = any(
                d["name"] == name
                for d in devices["input"]
                if not d.get("via_pipewire")
            )
            if not already and pipewire_in_index is not None:
                devices["input"].append({
                    "index": pipewire_in_index,
                    "name": name,
                    "max_input_channels": 2,
                    "max_output_channels": 0,
                    "default_sample_rate": 48000.0,
                    "is_default_input": source.get("is_default", False),
                    "is_default_output": False,
                    "is_pipewire": True,
                    "device_type": "bluetooth",
                    "pipewire_id": source["id"],
                    "via_pipewire": True
                })

    def set_pipewire_default(self, node_id: int) -> bool:
        """Establece un nodo PipeWire como el sink/source por defecto usando wpctl"""
        try:
            subprocess.run(
                ['wpctl', 'set-default', str(node_id)],
                check=True, timeout=3,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print(f"[PIPEWIRE] Nodo {node_id} establecido como predeterminado")
            return True
        except Exception as e:
            print(f"[ERROR] No se pudo cambiar el sink/source predeterminado: {e}")
            return False
    
    def get_device_names(self) -> Tuple[List[str], List[str]]:
        """Obtiene nombres de dispositivos para mostrar en GUI con tipo y estado"""
        devices = self.get_devices()
        
        input_names = []
        output_names = []
        
        # Emojis por tipo de dispositivo
        type_emoji = {
            'usb': '🔌',
            'bluetooth': '📶',
            'internal': '🎙️',
            'hdmi': '📺',
            'virtual': '⚙️',
            'unknown': '❓'
        }
        
        # Dispositivos de entrada (micrófonos)
        for dev in devices["input"]:
            emoji = type_emoji.get(dev["device_type"], '🎤')
            base_name = self.get_device_alias(dev["name"]) or dev["name"]

            # Truncar nombres muy largos
            if len(base_name) > 40:
                base_name = base_name[:37] + "..."
            
            # Formato según prioridad
            if dev["device_type"] in ['usb', 'bluetooth']:
                # Dispositivos físicos DESTACADOS
                type_label = dev["device_type"].upper()
                name = f"{emoji} {base_name} [{type_label}] ⭐"
            elif dev["is_default_input"]:
                name = f"{emoji} {base_name} (Sistema)"
            else:
                name = f"{emoji} {base_name}"
            
            input_names.append(name)
        
        # Dispositivos de salida (altavoces)
        for dev in devices["output"]:
            emoji = type_emoji.get(dev["device_type"], '🔊')
            base_name = self.get_device_alias(dev["name"]) or dev["name"]

            # Truncar nombres muy largos
            if len(base_name) > 40:
                base_name = base_name[:37] + "..."
            
            # Formato según prioridad
            if dev["device_type"] in ['usb', 'bluetooth']:
                # Dispositivos físicos DESTACADOS
                type_label = dev["device_type"].upper()
                name = f"{emoji} {base_name} [{type_label}] ⭐"
            elif dev["is_default_output"]:
                name = f"{emoji} {base_name} (Sistema)"
            else:
                name = f"{emoji} {base_name}"
            
            output_names.append(name)
        
        # Si no hay dispositivos, agregar opción "ninguno"
        if not input_names:
            input_names = ["❌ Sin dispositivos de entrada"]
        if not output_names:
            output_names = ["❌ Sin dispositivos de salida"]
        
        return input_names, output_names
    
    def get_device_index_from_name(self, device_name: str, device_type: str = "input") -> Optional[int]:
        """Obtiene el índice PyAudio de un dispositivo desde su nombre mostrado (maneja aliases)"""
        info = self.get_device_full_info_from_name(device_name, device_type)
        return info["index"] if info else None

    def get_device_full_info_from_name(self, device_name: str, device_type: str = "input") -> Optional[Dict]:
        """Obtiene el dict completo de un dispositivo desde su nombre mostrado (maneja aliases)"""
        devices = self.get_devices()
        device_list = devices.get(device_type, [])

        # Limpiar nombre mostrado: quitar emoji/símbolos iniciales y etiquetas de la GUI
        # 1. Quitar emoji/símbolo inicial no-ASCII (🔌 📶 etc.)
        clean_name = re.sub(r'^[^\x00-\x7E]+\s*', '', device_name)
        # 2. Quitar etiquetas de tipo: [USB], [BLUETOOTH], etc.
        clean_name = re.sub(r'\s*\[.*?\]', '', clean_name)
        # 3. Quitar etiquetas de estado de la GUI (no quitar "(hw:X,X)" de ALSA)
        clean_name = re.sub(r'\s+\(Sistema\)', '', clean_name)
        clean_name = re.sub(r'\s+\(Default\)', '', clean_name)
        # 4. Quitar símbolos no-ASCII al final (⭐ etc.)
        clean_name = re.sub(r'[^\x00-\x7E]+$', '', clean_name).strip()

        for dev in device_list:
            dev_name = dev["name"].strip()
            dev_alias = self.get_device_alias(dev_name) or ""
            if dev_name == clean_name or dev_alias == clean_name:
                return dev

        return None
    
    def auto_detect_best_devices(self) -> Tuple[Optional[int], Optional[int]]:
        """Auto-detecta los mejores dispositivos físicos disponibles"""
        devices = self.get_devices()
        
        best_input = None
        best_output = None
        
        # Prioridad: USB > Bluetooth > Internal > Default
        priority = ['usb', 'bluetooth', 'internal', 'unknown', 'virtual']
        
        # Buscar mejor input
        for device_type in priority:
            for dev in devices["input"]:
                if dev["device_type"] == device_type:
                    best_input = dev["index"]
                    print(f"[AUTO-DETECT] Input: [{dev['index']}] {dev['name']} ({device_type})")
                    break
            if best_input is not None:
                break
        
        # Buscar mejor output (evitar HDMI si hay alternativas)
        for device_type in priority:
            if device_type == 'hdmi':  # Skip HDMI en primera pasada
                continue
            for dev in devices["output"]:
                if dev["device_type"] == device_type:
                    best_output = dev["index"]
                    print(f"[AUTO-DETECT] Output: [{dev['index']}] {dev['name']} ({device_type})")
                    break
            if best_output is not None:
                break
        
        # Si no encontró nada, aceptar HDMI como último recurso
        if best_output is None:
            for dev in devices["output"]:
                if dev["device_type"] == 'hdmi':
                    best_output = dev["index"]
                    print(f"[AUTO-DETECT] Output (fallback HDMI): [{dev['index']}] {dev['name']}")
                    break
        
        return best_input, best_output
    
    def get_preferred_devices(self) -> Dict:
        """Obtiene los dispositivos preferidos guardados (incluye pipewire_id para BT)"""
        return {
            "input": self.config.get("preferred_input_device"),
            "output": self.config.get("preferred_output_device"),
            "input_pipewire_id": self.config.get("preferred_input_pipewire_id"),
            "output_pipewire_id": self.config.get("preferred_output_pipewire_id")
        }
    
    def set_preferred_devices(self, input_index: Optional[int] = None, output_index: Optional[int] = None,
                               input_pipewire_id: Optional[int] = None, output_pipewire_id: Optional[int] = None):
        """Guarda los dispositivos preferidos (incluye pipewire_id para dispositivos BT)"""
        if input_index is not None:
            self.config["preferred_input_device"] = input_index
        if output_index is not None:
            self.config["preferred_output_device"] = output_index
        if input_pipewire_id is not None:
            self.config["preferred_input_pipewire_id"] = input_pipewire_id
        elif input_index is not None:
            self.config["preferred_input_pipewire_id"] = None  # Reset si no es BT
        if output_pipewire_id is not None:
            self.config["preferred_output_pipewire_id"] = output_pipewire_id
        elif output_index is not None:
            self.config["preferred_output_pipewire_id"] = None  # Reset si no es BT

        self.save_config()

    def set_device_alias(self, device_name: str, alias: str):
        """Guarda un nombre amigable para un dispositivo (alias visible en la GUI)"""
        if 'device_aliases' not in self.config:
            self.config['device_aliases'] = {}
        if alias.strip():
            self.config['device_aliases'][device_name] = alias.strip()
        elif device_name in self.config.get('device_aliases', {}):
            del self.config['device_aliases'][device_name]
        self.save_config()

    def get_device_alias(self, device_name: str) -> Optional[str]:
        """Obtiene el alias de un dispositivo si existe, o None"""
        return self.config.get('device_aliases', {}).get(device_name)
    
    def get_preferred_device_names(self) -> Tuple[Optional[str], Optional[str]]:
        """Obtiene los nombres de los dispositivos preferidos con tipo"""
        devices = self.get_devices()
        prefs = self.get_preferred_devices()
        
        input_name = None
        output_name = None
        
        # Buscar nombre del dispositivo de entrada
        if prefs["input"] is not None:
            for dev in devices["input"]:
                if dev["index"] == prefs["input"]:
                    display = self.get_device_alias(dev['name']) or dev['name']
                    type_label = dev["device_type"].upper()
                    input_name = f"{display} [{type_label}]"
                    break

        # Buscar nombre del dispositivo de salida
        if prefs["output"] is not None:
            for dev in devices["output"]:
                if dev["index"] == prefs["output"]:
                    display = self.get_device_alias(dev['name']) or dev['name']
                    type_label = dev["device_type"].upper()
                    output_name = f"{display} [{type_label}]"
                    break
        
        return input_name, output_name
    
    def test_device(self, device_index: int, device_type: str = "input", duration: float = 1.0) -> bool:
        """Prueba si un dispositivo funciona correctamente"""
        if not self.audio:
            return False
        
        try:
            if device_type == "input":
                # Probar grabación
                stream = self.audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=24000,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=1024
                )
                # Leer un poco de audio
                stream.read(int(24000 * duration), exception_on_overflow=False)
                stream.stop_stream()
                stream.close()
                return True
            else:
                # Probar reproducción (silencio)
                stream = self.audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=24000,
                    output=True,
                    output_device_index=device_index,
                    frames_per_buffer=1024
                )
                # Reproducir silencio
                silence = b'\x00' * int(24000 * 2 * duration)  # 2 bytes por muestra
                stream.write(silence)
                stream.stop_stream()
                stream.close()
                return True
                
        except Exception as e:
            print(f"[ERROR] Test de dispositivo falló: {e}")
            return False
    
    def load_config(self) -> Dict:
        """Carga configuración guardada"""
        default_config = {
            "preferred_input_device": None,
            "preferred_output_device": None,
            "preferred_input_pipewire_id": None,
            "preferred_output_pipewire_id": None,
            "device_aliases": {},
            "input_volume": 1.0,
            "output_volume": 1.0,
            "noise_reduction_enabled": True,
            "agc_enabled": True,
            "calibrated_noise_floor": None,
            "last_used": None
        }
        
        if not os.path.exists(self.CONFIG_FILE):
            return default_config
        
        try:
            with open(self.CONFIG_FILE, 'r') as f:
                loaded_config = json.load(f)
                # Merge con defaults
                default_config.update(loaded_config)
                return default_config
        except Exception as e:
            print(f"[WARNING] Error cargando config de audio: {e}")
            return default_config
    
    def save_config(self):
        """Guarda configuración"""
        try:
            import datetime
            self.config["last_used"] = datetime.datetime.now().isoformat()
            
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
            
            print(f"[CONFIG] Preferencias de audio guardadas en {self.CONFIG_FILE}")
        except Exception as e:
            print(f"[ERROR] Error guardando config de audio: {e}")
    
    def get_supported_rates(self, device_index: int, device_type: str = "input") -> List[int]:
        """Obtiene las sample rates soportadas por un dispositivo"""
        if not self.audio:
            return []
        
        common_rates = [8000, 16000, 22050, 24000, 32000, 44100, 48000, 96000]
        supported = []
        
        for rate in common_rates:
            try:
                if device_type == "input":
                    if self.audio.is_format_supported(
                        rate,
                        input_device=device_index,
                        input_channels=1,
                        input_format=pyaudio.paInt16
                    ):
                        supported.append(rate)
                else:
                    if self.audio.is_format_supported(
                        rate,
                        output_device=device_index,
                        output_channels=1,
                        output_format=pyaudio.paInt16
                    ):
                        supported.append(rate)
            except:
                continue
        
        return supported
    
    def get_noise_floor(self) -> Optional[float]:
        """Obtiene el noise floor calibrado persistido de la sesión anterior"""
        value = self.config.get("calibrated_noise_floor")
        return float(value) if value is not None else None

    def save_noise_floor(self, noise_floor: float):
        """Persiste el noise floor calibrado para la próxima sesión (calibración instantánea)"""
        self.config["calibrated_noise_floor"] = round(noise_floor, 2)
        self.save_config()

    def cleanup(self):
        """Limpia recursos"""
        if self.audio:
            self.audio.terminate()


# Función helper para uso rápido
def get_audio_device_manager():
    """Obtiene instancia del gestor de dispositivos"""
    return AudioDeviceManager()


if __name__ == "__main__":
    # Test del módulo
    print("🎵 Audio Device Manager - Test\n")
    
    if not AUDIO_AVAILABLE:
        print("❌ PyAudio no disponible")
        exit(1)
    
    manager = AudioDeviceManager()
    
    # Listar dispositivos
    devices = manager.get_devices()
    
    print("📥 DISPOSITIVOS DE ENTRADA (Micrófonos):")
    for dev in devices["input"]:
        default = " [DEFAULT]" if dev["is_default_input"] else ""
        print(f"  [{dev['index']}] {dev['name']}{default}")
        print(f"      Canales: {dev['max_input_channels']}, Rate: {dev['default_sample_rate']} Hz")
    
    print("\n📤 DISPOSITIVOS DE SALIDA (Altavoces):")
    for dev in devices["output"]:
        default = " [DEFAULT]" if dev["is_default_output"] else ""
        print(f"  [{dev['index']}] {dev['name']}{default}")
        print(f"      Canales: {dev['max_output_channels']}, Rate: {dev['default_sample_rate']} Hz")
    
    # Mostrar preferencias guardadas
    print("\n⚙️ PREFERENCIAS GUARDADAS:")
    prefs = manager.get_preferred_devices()
    input_name, output_name = manager.get_preferred_device_names()
    print(f"  Input: {input_name if input_name else 'No configurado'}")
    print(f"  Output: {output_name if output_name else 'No configurado'}")
    
    manager.cleanup()
