import gradio as gr

scores = []

def track_score(score):
    scores.append(score)
    return sorted(scores, reverse=True)[:3]

demo = gr.Interface(
    track_score, 
    gr.Number(label="Score"), 
    gr.JSON(label="Top Scores")
)
if __name__ == "__main__":
    demo.launch()