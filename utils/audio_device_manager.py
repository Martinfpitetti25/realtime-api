"""
Gestor de Dispositivos de Audio
Maneja detección, selección y guardado de preferencias de dispositivos de audio
"""
import json
import os
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
        
    def get_devices(self) -> Dict[str, List[Dict]]:
        """Obtiene lista de todos los dispositivos de entrada y salida"""
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
                        "is_pipewire": "pipewire" in device_name.lower() or "default" in device_name.lower()
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
        
        return devices
    
    def get_device_names(self) -> Tuple[List[str], List[str]]:
        """Obtiene nombres de dispositivos para mostrar en GUI"""
        devices = self.get_devices()
        
        input_names = []
        output_names = []
        
        # Dispositivos de entrada (micrófonos)
        for dev in devices["input"]:
            name = dev["name"]
            # Priorizar PipeWire/Default
            if dev["is_pipewire"]:
                name = f"🎤 {name} (PipeWire - Recomendado)"
            elif dev["is_default_input"]:
                name = f"🎤 {name} (Default)"
            else:
                name = f"   {name}"
            input_names.append(name)
        
        # Dispositivos de salida (altavoces)
        for dev in devices["output"]:
            name = dev["name"]
            # Priorizar PipeWire/Default
            if dev["is_pipewire"]:
                name = f"🔊 {name} (PipeWire - Recomendado)"
            elif dev["is_default_output"]:
                name = f"🔊 {name} (Default)"
            else:
                name = f"   {name}"
            output_names.append(name)
        
        # Si no hay dispositivos, agregar opción "ninguno"
        if not input_names:
            input_names = ["❌ Sin dispositivos de entrada"]
        if not output_names:
            output_names = ["❌ Sin dispositivos de salida"]
        
        return input_names, output_names
    
    def get_device_index_from_name(self, device_name: str, device_type: str = "input") -> Optional[int]:
        """Obtiene el índice de un dispositivo desde su nombre mostrado"""
        devices = self.get_devices()
        device_list = devices.get(device_type, [])
        
        # Limpiar el nombre (quitar emojis y "(Default)")
        clean_name = device_name.replace("🎤 ", "").replace("🔊 ", "").replace("   ", "").replace(" (Default)", "").strip()
        
        for dev in device_list:
            if dev["name"] == clean_name:
                return dev["index"]
        
        return None
    
    def get_preferred_devices(self) -> Dict[str, Optional[int]]:
        """Obtiene los dispositivos preferidos guardados"""
        return {
            "input": self.config.get("preferred_input_device"),
            "output": self.config.get("preferred_output_device")
        }
    
    def set_preferred_devices(self, input_index: Optional[int] = None, output_index: Optional[int] = None):
        """Guarda los dispositivos preferidos"""
        if input_index is not None:
            self.config["preferred_input_device"] = input_index
        if output_index is not None:
            self.config["preferred_output_device"] = output_index
        
        self.save_config()
    
    def get_preferred_device_names(self) -> Tuple[Optional[str], Optional[str]]:
        """Obtiene los nombres de los dispositivos preferidos"""
        devices = self.get_devices()
        prefs = self.get_preferred_devices()
        
        input_name = None
        output_name = None
        
        # Buscar nombre del dispositivo de entrada
        if prefs["input"] is not None:
            for dev in devices["input"]:
                if dev["index"] == prefs["input"]:
                    input_name = dev["name"]
                    break
        
        # Buscar nombre del dispositivo de salida
        if prefs["output"] is not None:
            for dev in devices["output"]:
                if dev["index"] == prefs["output"]:
                    output_name = dev["name"]
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
            "input_volume": 1.0,
            "output_volume": 1.0,
            "noise_reduction_enabled": True,
            "agc_enabled": True,
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
