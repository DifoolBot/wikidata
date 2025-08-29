import os
import subprocess
from pathlib import Path
import json

# --- Configuration ---
monorepo_root = Path(__file__).resolve().parent
projects_root = monorepo_root / "projects"
project_dirs = ["viaf", "wikipedia"]  # Subfolders inside 'projects'

# --- Script ---
for project in project_dirs:
    project_path = projects_root / project
    venv_path = project_path / ".venv"
    vscode_path = project_path / ".vscode"
    settings_file = vscode_path / "settings.json"

    print(f"🔧 Setting up virtual environment for: {project_path}")

    # Create virtual environment
    subprocess.run(["python", "-m", "venv", str(venv_path)], check=True)

    # Create .vscode/settings.json
    vscode_path.mkdir(exist_ok=True)
    interpreter_path = str(venv_path / "Scripts" / "python.exe")  # Windows-specific
    settings = {
        "python.pythonPath": interpreter_path,
        "python.terminal.activateEnvironment": True
    }

    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=4)

    print(f"✅ Virtual environment and VS Code config created for: {project}")

print("🎉 All environments set up successfully!")