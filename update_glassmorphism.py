import os
import glob
import re

css_root = """:root {
            --bg-color: #0f172a;
            --panel-bg: rgba(255, 255, 255, 0.05);
            --text-primary: #f8fafc;
            --text-secondary: #cbd5e1;
            --accent-red: #ef4444;
            --accent-blue: #3b82f6;
            --accent-green: #22c55e;
            --accent-orange: #f97316;
            --border-color: rgba(255, 255, 255, 0.1);
            --glass-blur: blur(12px);
        }"""

for filepath in glob.glob("templates/*.html"):
    with open(filepath, "r") as f:
        content = f.read()
    
    # Replace :root block completely
    content = re.sub(r':root\s*\{[^}]*\}', css_root, content, count=1)
    
    # Add beautiful gradient to body if not already there
    body_gradient = """body {
            font-family: 'Inter', sans-serif;
            background: radial-gradient(circle at top left, #1e1b4b, #0f172a 70%);
            background-attachment: fixed;
            color: var(--text-primary);"""
    content = re.sub(r'body\s*\{\s*font-family:[^}]*color: var\(--text-primary\);', body_gradient, content, count=1)
    
    # Add backdrop filter to panel elements
    # For .topbar, .sidebar, .log-container, .upload-card, .face-card, .glass-toast
    content = content.replace("background: var(--panel-bg);", "background: var(--panel-bg);\n            backdrop-filter: var(--glass-blur);\n            -webkit-backdrop-filter: var(--glass-blur);")
    
    with open(filepath, "w") as f:
        f.write(content)
print("Glassmorphism applied.")
