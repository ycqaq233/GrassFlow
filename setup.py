from setuptools import setup, find_packages

setup(
    name="grassflow",
    version="0.1.0",
    description="可视化多Agent积木编排平台",
    author="GrassFlow Team",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "pydantic>=2.0.0",
        "jsonschema>=4.0.0",
        "httpx>=0.25.0",
        "html2text>=2024.0.0",
        "rich>=13.0.0",
        "click>=8.0.0",
        "prompt_toolkit>=3.0.0",
        "fastapi>=0.100.0",
        "uvicorn>=0.23.0",
        "websockets>=11.0",
        "litellm>=1.0.0",
        "aiosqlite>=0.19.0",
    ],
    entry_points={
        "console_scripts": [
            "grassflow=tui.cli:main",
        ],
    },
)
