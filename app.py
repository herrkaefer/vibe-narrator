import gradio as gr
import base64
import io
from pathlib import Path

def greet(name):
    return "Hello " + name + "!!"

# Load logo - try file first (for local dev), then base64 (for Space)
logo_path = Path(__file__).parent / "logo.png"
logo_data = None

if logo_path.exists():
    # Local development: use file
    logo_file = str(logo_path)
else:
    # Space: use base64 from logo_data.py
    try:
        from logo_data import LOGO_BASE64
        logo_bytes = base64.b64decode(LOGO_BASE64)
        logo_file = io.BytesIO(logo_bytes)
    except ImportError:
        logo_file = None

# Create interface with logo
with gr.Blocks(title="Vibe Narrator") as demo:
    if logo_file:
        gr.Image(logo_file, show_label=False, container=False, height=120, elem_id="logo")
    else:
        gr.Markdown("### Vibe Narrator")
    
    gr.Interface(fn=greet, inputs="text", outputs="text")

demo.launch()
