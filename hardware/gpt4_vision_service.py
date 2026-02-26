"""
GPT-4 Vision Service - Para análisis detallado de imágenes
Usa la API de OpenAI para descripciones precisas bajo demanda
"""
import os
import base64
import requests
from typing import Dict, Optional
import cv2
import numpy as np
from dotenv import load_dotenv

load_dotenv()

class GPT4VisionService:
    """Servicio para análisis de imágenes con GPT-4 Vision"""
    
    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.api_url = "https://api.openai.com/v1/chat/completions"
        self.model = "gpt-4o"  # Modelo con visión
        
    def encode_frame(self, frame: np.ndarray, quality: int = 85) -> str:
        """
        Codifica un frame de OpenCV a base64
        
        Args:
            frame: Frame de OpenCV (BGR)
            quality: Calidad JPEG (1-100)
            
        Returns:
            String en base64
        """
        # Redimensionar si es muy grande (para ahorrar costos)
        height, width = frame.shape[:2]
        max_size = 512
        
        if max(height, width) > max_size:
            scale = max_size / max(height, width)
            new_width = int(width * scale)
            new_height = int(height * scale)
            frame = cv2.resize(frame, (new_width, new_height))
        
        # Convertir a JPEG
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        _, buffer = cv2.imencode('.jpg', frame, encode_param)
        
        # Convertir a base64
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        return jpg_as_text
    
    def analyze_image(
        self, 
        frame: np.ndarray,
        prompt: str = "Describe esta imagen en detalle. Menciona objetos, personas, colores, posiciones y cualquier texto visible.",
        max_tokens: int = 300
    ) -> Dict:
        """
        Analiza una imagen con GPT-4 Vision
        
        Args:
            frame: Frame de OpenCV (BGR)
            prompt: Pregunta o instrucción para GPT-4V
            max_tokens: Máximo de tokens en la respuesta
            
        Returns:
            Dict con 'description' (str), 'success' (bool), 'error' (str optional)
        """
        if not self.api_key:
            return {
                'success': False,
                'error': 'API key no configurada',
                'description': ''
            }
        
        try:
            # Codificar imagen
            base64_image = self.encode_frame(frame)
            
            # Construir request
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "low"  # "low" es más barato
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7
            }
            
            # Hacer request
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                description = result['choices'][0]['message']['content']
                
                # Calcular costo aproximado
                usage = result.get('usage', {})
                input_tokens = usage.get('prompt_tokens', 0)
                output_tokens = usage.get('completion_tokens', 0)
                
                # Precios aproximados (pueden variar)
                cost = (input_tokens * 0.01 + output_tokens * 0.03) / 1000
                
                return {
                    'success': True,
                    'description': description,
                    'usage': usage,
                    'cost': cost,
                    'error': None
                }
            else:
                error_msg = f"API error {response.status_code}: {response.text}"
                return {
                    'success': False,
                    'error': error_msg,
                    'description': ''
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'description': ''
            }
    
    def quick_description(self, frame: np.ndarray) -> str:
        """
        Obtiene una descripción rápida de la imagen
        
        Args:
            frame: Frame de OpenCV
            
        Returns:
            String con descripción o mensaje de error
        """
        result = self.analyze_image(
            frame,
            prompt="Describe brevemente lo que ves en esta imagen en español.",
            max_tokens=150
        )
        
        if result['success']:
            return result['description']
        else:
            return f"Error: {result['error']}"
    
    def answer_question(self, frame: np.ndarray, question: str) -> str:
        """
        Responde una pregunta específica sobre la imagen
        
        Args:
            frame: Frame de OpenCV
            question: Pregunta del usuario
            
        Returns:
            String con respuesta o mensaje de error
        """
        prompt = f"Responde esta pregunta sobre la imagen en español: {question}"
        
        result = self.analyze_image(frame, prompt=prompt, max_tokens=200)
        
        if result['success']:
            return result['description']
        else:
            return f"Error: {result['error']}"
