from __future__ import annotations

import subprocess
import sys


def choose_folder_dialog(prompt: str) -> str:
    """
    Best-effort folder chooser.

    Returns the selected folder path as a string, or "" if cancelled/unsupported.
    """
    if sys.platform == "darwin":
        try:
            safe_prompt = (prompt or "").replace('"', '\\"')
            script = f'POSIX path of (choose folder with prompt "{safe_prompt}")'
            proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120, check=False)
            folder = (proc.stdout or "").strip()
            return folder if proc.returncode == 0 else ""
        except Exception:
            return ""

    if sys.platform.startswith("win"):
        try:
            safe_prompt = (prompt or "").replace("'", "''")
            script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
                f"$dialog.Description = '{safe_prompt}'; "
                "$dialog.ShowNewFolderButton = $true; "
                "$result = $dialog.ShowDialog(); "
                "if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.SelectedPath) { "
                "Write-Output $dialog.SelectedPath }"
            )
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", script],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            folder = (proc.stdout or "").strip()
            return folder if proc.returncode == 0 else ""
        except Exception:
            return ""

    return ""

