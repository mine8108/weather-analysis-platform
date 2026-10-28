"""Create a reproducible, synthetic Plotly chart; capture it in the local browser for UI QA."""
from pathlib import Path
import numpy as np
import plotly.graph_objects as go
root = Path(__file__).resolve().parents[1]
target = root / "docs/design/workbench-20261026/evidence/fixtures"
target.mkdir(parents=True, exist_ok=True)
x, y = np.linspace(-5, 5, 220), np.linspace(-4, 4, 180)
xx, yy = np.meshgrid(x, y)
p = 1018 - 26*np.exp(-((xx+1.7)**2/4+(yy-.3)**2/5)) + 14*np.exp(-((xx-3)**2/5+(yy-1)**2/7))
fig = go.Figure(go.Contour(x=x,y=y,z=p,colorscale="RdBu_r",reversescale=False,
    contours=dict(start=992,end=1036,size=4,showlabels=True,labelfont=dict(size=13,color="#264766")),
    line=dict(color="#3b526c",width=1),colorbar=dict(title="hPa")))
fig.add_annotation(x=-1.7,y=.3,text="L",showarrow=False,font=dict(size=40,color="#1454bd"))
fig.add_annotation(x=3,y=1,text="H",showarrow=False,font=dict(size=38,color="#c3382d"))
fig.update_layout(width=900,height=660,margin=dict(l=55,r=80,t=60,b=65),paper_bgcolor="white",
    title="SYNTHETIC PRESSURE FIELD / hPa",xaxis_title="Illustrative x coordinate",yaxis_title="Illustrative y coordinate",
    annotations=list(fig.layout.annotations)+[dict(x=.5,y=-.13,xref="paper",yref="paper",showarrow=False,
        text="UI TEST FIXTURE - NOT OBSERVATIONS OR A WEATHER FORECAST",font=dict(size=11,color="#405a76"))])
fig.write_html(target / "synthetic-pressure.html",include_plotlyjs=True,config={"displayModeBar":False})
