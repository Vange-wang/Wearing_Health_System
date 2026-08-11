"""启动入口（uvicorn，Spec §4/§10）：venv\\Scripts\\python run.py"""
import uvicorn

from app.config import load_config

if __name__ == "__main__":
    cfg = load_config()
    uvicorn.run("app.main:app", host=cfg.server_host, port=cfg.server_port, log_level=cfg.log_level.lower())
