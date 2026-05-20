# Frontend Analytics Notebook

This notebook provides the frontend visual analytics dashboard for the project.

The frontend retrieves processed analytical results from the backend REST API and generates interactive visualisations using Plotly.

## Requirements

- Python 3
- Jupyter Notebook
- pandas
- requests
- plotly

## How to Run

1. Expose the Fission router service:

```bash
kubectl port-forward service/router -n fission 8888:80
```

2. Start Jupyter Notebook:

```bash
jupyter notebook
```

3. Open:

```text
Frontend_Team36.ipynb
```

4. Run all notebook cells sequentially.

## Main Features

The notebook includes:

- Fuel price trend analysis
- Social media discussion analysis
- Sentiment comparison
- Platform comparison
- Correlation analysis