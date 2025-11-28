import gradio as gr
from pathlib import Path

def greet(name):
    return "Hello " + name + "!!"

# Get absolute path to logo
logo_path = Path(__file__).parent / "logo.png"

# Create interface with logo
with gr.Blocks(title="Vibe Narrator") as demo:
    # Use Image component with absolute path for local, relative path for Space
    if logo_path.exists():
        gr.Image(str(logo_path), show_label=False, container=False, height=120, elem_id="logo")
    else:
        # Fallback: try relative path (for Space)
        gr.Image("logo.png", show_label=False, container=False, height=120, elem_id="logo")

    gr.Interface(fn=greet, inputs="text", outputs="text")

demo.launch()
