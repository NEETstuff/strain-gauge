"""Plotly sparklines."""
import plotly.graph_objects as go


def spark(values, title):
    fig = go.Figure(go.Scatter(y=values, mode="lines", line=dict(width=2)))
    fig.update_layout(
        title=title, height=180, margin=dict(l=10, r=10, t=30, b=10),
        template="plotly_dark", xaxis=dict(showticklabels=False),
        yaxis=dict(showgrid=False),
    )
    return fig
