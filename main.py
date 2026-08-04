#!/usr/bin/env python3
"""
Realtime-IA Humanoid Assistant — Main Application Entry Point
==============================================================
Launches the Realtime OpenAI Assistant GUI with computer vision,
wake-word detection, and hardware servo control.
"""

import sys
import os
import subprocess
from pathlib import Path

# Add project root directory to Python path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

def check_environment():
    """Verify environment setup and .env file presence."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        print("⚠️ Warning: .env file not found. Copying from .env.example...")
        env_example = PROJECT_ROOT / ".env.example"
        if env_example.exists():
            import shutil
            shutil.copy(env_example, env_file)
            print("✅ Created .env from .env.example. Please configure your OPENAI_API_KEY.")
        else:
            print("❌ Error: .env.example not found.")

def main():
    """Main execution function."""
    print("=========================================================")
    print(" 🤖 Realtime-IA Humanoid Assistant — Starting System")
    print("=========================================================")
    
    check_environment()
    
    gui_script = PROJECT_ROOT / "05_gui_chat.py"
    if not gui_script.exists():
        print(f"❌ Error: Main GUI script not found at {gui_script}")
        sys.exit(1)
        
    print(f"🚀 Launching GUI interface ({gui_script.name})...\n")
    
    # Execute GUI script
    try:
        subprocess.run([sys.executable, str(gui_script)], check=True)
    except KeyboardInterrupt:
        print("\n👋 System shut down by user.")
    except Exception as e:
        print(f"\n❌ Application error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
