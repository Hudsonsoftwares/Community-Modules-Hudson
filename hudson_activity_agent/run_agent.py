"""Entry point used by PyInstaller and for running from source: python run_agent.py"""
from agent.main import main

if __name__ == "__main__":
    raise SystemExit(main())
