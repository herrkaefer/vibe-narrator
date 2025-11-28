import gradio as gr

def greet(name):
    return "Hello " + name + "!!"

# Create interface with logo
with gr.Blocks(title="Vibe Narrator") as demo:
    # Use HTML to display logo (same way as in README.md, works reliably in Space)
    gr.HTML('<div style="text-align: center;"><img src="logo.png" alt="logo" style="max-height: 120px;"/></div>')
    gr.Interface(fn=greet, inputs="text", outputs="text")

demo.launch()
