"""Entry point: python -m academic_tools  or  fro-wang-academic-tools-mcp."""

from .server import mcp


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
