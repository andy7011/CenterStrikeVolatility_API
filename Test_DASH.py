import dash
from dash import dcc, Input, Output, callback, dash_table
from dash import html
import dash_table
import pandas as pd

app = dash.Dash(__name__)

df = pd.read_csv('https://raw.githubusercontent.com/plotly/datasets/master/solar.csv')

app.layout = html.Div([
      html.H4('Dashboard'),
      dcc.Interval('graph-update', interval = 10000, n_intervals = 0),
      dash_table.DataTable(
          id = 'table',
          data = df.to_dict('records'),
          columns=[{"name": i, "id": i} for i in df.columns])])

@app.callback(
        dash.dependencies.Output('table','data'),
        [dash.dependencies.Input('graph-update', 'n_intervals')])
def updateTable(n):
    df = pd.read_csv('https://raw.githubusercontent.com/plotly/datasets/master/solar.csv')
    return df.to_dict('records')

if __name__ == '__main__':
     app.run_server(debug=True, port=10451)