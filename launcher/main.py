import sys
from aero.app import main, cli

if __name__ == "__main__":
    cli() if "--cli" in sys.argv else main()
