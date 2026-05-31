import os
from flask import Flask

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")


@app.route("/")
def home():
    return """
    <html>
      <head>
        <title>NEET Platform</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          body {
            margin: 0;
            font-family: Inter, Arial, sans-serif;
            background: linear-gradient(135deg, #0f172a, #1e293b);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
          }
          .card {
            background: rgba(255,255,255,0.08);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 24px;
            padding: 32px;
            max-width: 720px;
            width: calc(100% - 40px);
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
          }
          h1 { margin: 0 0 12px; font-size: 2rem; }
          p { margin: 0 0 12px; color: #dbeafe; line-height: 1.6; }
          .ok {
            display: inline-block;
            margin-top: 12px;
            padding: 10px 14px;
            border-radius: 999px;
            background: #16a34a;
            color: white;
            font-weight: 700;
          }
        </style>
      </head>
      <body>
        <div class="card">
          <h1>NEET Platform is live</h1>
          <p>This is the clean Render boot stage.</p>
          <p>Next step: attach PostgreSQL, authentication, question bank, and test engine.</p>
          <div class="ok">Render deploy successful</div>
        </div>
      </body>
    </html>
    """


@app.route("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
