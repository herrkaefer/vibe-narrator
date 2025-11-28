import gradio as gr

def greet(name, age, city):
    return f"Hello {name}! You are {age} years old and from {city}!!"

def button_click():
    return "Button was clicked! 🎉"

# Create interface with logo and multiple inputs
with gr.Blocks(title="Vibe Narrator - Test Version") as demo:
    gr.Markdown("# 🎨 Vibe Narrator - UI Test")
    gr.Image("logo.png", show_label=False, container=False, height=120)
    
    with gr.Row():
        with gr.Column():
            gr.Markdown("## Input Section")
            name_input = gr.Textbox(label="Your Name", placeholder="Enter your name")
            age_input = gr.Number(label="Your Age", value=25)
            city_input = gr.Textbox(label="Your City", placeholder="Enter your city")
            
            with gr.Row():
                submit_btn = gr.Button("Submit", variant="primary")
                test_btn = gr.Button("Test Button", variant="secondary")
                clear_btn = gr.Button("Clear", variant="stop")
        
        with gr.Column():
            gr.Markdown("## Output Section")
            output_text = gr.Textbox(label="Result", lines=5)
            button_output = gr.Textbox(label="Button Result", lines=2)
    
    # Connect events
    submit_btn.click(fn=greet, inputs=[name_input, age_input, city_input], outputs=output_text)
    test_btn.click(fn=button_click, inputs=None, outputs=button_output)
    clear_btn.click(fn=lambda: ("", ""), inputs=None, outputs=[output_text, button_output])

demo.launch()
