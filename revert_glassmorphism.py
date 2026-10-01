import glob
import re

original_root = """:root {
            --bg-color: #f8fafc;
            --panel-bg: #ffffff;
            --text-primary: #0f172a;
            --text-secondary: #64748b;
            --accent-red: #ef4444;
            --accent-green: #22c55e;
            --accent-orange: #f97316;
            --border-color: #e2e8f0;
        }"""

original_body = """body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);"""

toast_dark = """            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);"""
            
toast_light = """            background: rgba(255, 255, 255, 0.85);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.5);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);"""

for filepath in glob.glob("templates/*.html"):
    with open(filepath, "r") as f:
        content = f.read()
    
    # Replace :root block completely
    content = re.sub(r':root\s*\{[^}]*\}', original_root, content, count=1)
    
    # Revert body style
    content = re.sub(r'body\s*\{\s*font-family:[^}]*color: var\(--text-primary\);', original_body, content, count=1)
    
    # Revert backdrop filters for panel backgrounds
    content = content.replace("background: var(--panel-bg);\n            backdrop-filter: var(--glass-blur);\n            -webkit-backdrop-filter: var(--glass-blur);", "background: var(--panel-bg);")
    
    # Revert glass-toast
    content = content.replace(toast_dark, toast_light)
    
    with open(filepath, "w") as f:
        f.write(content)
print("Glassmorphism reverted.")
