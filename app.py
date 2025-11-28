import gradio as gr

def greet(name):
    return "Hello " + name + "!!"

# Create interface with logo
with gr.Blocks(title="Vibe Narrator") as demo:
    gr.Image("logo.png", show_label=False, container=False, height=120)
    gr.Interface(fn=greet, inputs="text", outputs="text")

demo.launch()
